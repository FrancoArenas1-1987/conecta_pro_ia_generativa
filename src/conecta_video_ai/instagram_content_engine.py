
from __future__ import annotations

import colorsys
import os
import json
import fnmatch
import hashlib
import random
import re
import shutil
import tempfile
import unicodedata
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import yaml
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps, ImageStat

from .assets import AssetLibrary
from .exceptions import GenerationError
from .meta_connector import MetaConnectorError, MetaCredentials, MetaGraphClient
from .models import BrandContext
from .music_engine import generate_instrumental_bed
from .providers import OllamaProvider, OpenAIImageProvider
from .settings import AppSettings
from .storage import create_run_dir, write_json
from .whatsapp_links import (
    DEFAULT_CLIENT_PHONE,
    DEFAULT_PROVIDER_PHONE,
    extract_whatsapp_phone,
    normalize_whatsapp_click_url,
)

_HASHTAG_RE = re.compile(r"#([A-Za-z0-9_]+)")
_WORD_RE = re.compile(r"[^a-z0-9]+")
_DIGITS_RE = re.compile(r"\d+")
_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
_VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}
_AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}


@dataclass
class DraftResult:
    draft_id: str
    draft_dir: Path
    payload: dict[str, Any]


class InstagramContentEngine:
    """Create Instagram-ready local drafts with category rotation and brand overlays."""

    def __init__(
        self,
        *,
        settings: AppSettings,
        context: BrandContext,
        provider: OllamaProvider,
        asset_library: AssetLibrary,
        openai_image_provider: OpenAIImageProvider | None,
    ) -> None:
        self.settings = settings
        self.context = context
        self.provider = provider
        self.asset_library = asset_library
        self.openai_image_provider = openai_image_provider

        self.drafts_root = settings.instagram_drafts_root
        self.catalog_path = settings.instagram_catalog_path
        self.plan_path = settings.instagram_plan_path
        self.state_path = settings.instagram_state_path
        self.publish_log_path = settings.output_root / "instagram" / "publish_log.jsonl"
        self.quality_reject_log_path = settings.output_root / "instagram" / "quality_reject_log.jsonl"
        self.quality_sweep_log_path = settings.output_root / "instagram" / "quality_sweep_log.jsonl"
        self.openai_budget_path = settings.instagram_openai_budget_path
        self.openai_budget_events_path = settings.output_root / "instagram" / "budget" / "openai_image_budget_events.jsonl"
        self.asset_catalog_path = settings.instagram_asset_catalog_path
        self.asset_overrides_path = settings.instagram_asset_overrides_path
        self.publish_assets_root = settings.instagram_publish_assets_root
        self.library_sync_state_path = settings.output_root / "instagram" / "catalog" / "library_sync_state.json"

        self.drafts_root.mkdir(parents=True, exist_ok=True)
        self.catalog_path.parent.mkdir(parents=True, exist_ok=True)
        self.plan_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.publish_log_path.parent.mkdir(parents=True, exist_ok=True)
        self.quality_reject_log_path.parent.mkdir(parents=True, exist_ok=True)
        self.quality_sweep_log_path.parent.mkdir(parents=True, exist_ok=True)
        self.openai_budget_path.parent.mkdir(parents=True, exist_ok=True)
        self.openai_budget_events_path.parent.mkdir(parents=True, exist_ok=True)
        self.asset_catalog_path.parent.mkdir(parents=True, exist_ok=True)
        self.publish_assets_root.mkdir(parents=True, exist_ok=True)
        self.library_sync_state_path.parent.mkdir(parents=True, exist_ok=True)
        self.descriptor_bootstrap_state_path = settings.output_root / "instagram" / "catalog" / "descriptor_bootstrap_state.json"
        self.descriptor_bootstrap_state_path.parent.mkdir(parents=True, exist_ok=True)
        self._normalize_publish_asset_layout()

        cfg = self._load_categories(settings.instagram_categories_path)
        self.defaults = cfg.get("defaults") if isinstance(cfg, dict) else {}
        if not isinstance(self.defaults, dict):
            self.defaults = {}
        yaml_categories = cfg.get("categories") if isinstance(cfg, dict) else []
        if not isinstance(yaml_categories, list):
            yaml_categories = []
        self._yaml_category_map: dict[str, dict[str, Any]] = {
            str(cat.get("id") or "").strip(): cat
            for cat in yaml_categories
            if isinstance(cat, dict) and str(cat.get("id") or "").strip()
        }
        desc_cfg = self._load_categories(settings.instagram_category_descriptors_path)
        self._descriptor_prompt_framework = self._load_descriptor_prompt_framework(desc_cfg)
        desc_categories = desc_cfg.get("categories") if isinstance(desc_cfg, dict) else []
        if not isinstance(desc_categories, list):
            desc_categories = []
        self._descriptor_category_map: dict[str, dict[str, Any]] = {
            str(cat.get("id") or "").strip(): cat
            for cat in desc_categories
            if isinstance(cat, dict) and str(cat.get("id") or "").strip()
        }
        self._auto_bootstrap_missing_descriptors()
        self.categories: list[dict[str, Any]] = []
        self.category_map: dict[str, dict[str, Any]] = {}
        self._refresh_runtime_categories()

        self._refresh_asset_library()
        try:
            self._sync_asset_catalog()
        except PermissionError:
            # OneDrive/ReparsePoint can temporarily lock catalog files.
            # Keep runtime operational and allow later explicit sync.
            pass
        except OSError:
            pass

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _norm(text: str) -> str:
        return " ".join(str(text or "").split()).strip()

    @staticmethod
    def _slug(text: str, fallback: str = "item") -> str:
        raw = _WORD_RE.sub("-", str(text or "").lower()).strip("-")
        return raw[:72] or fallback

    @staticmethod
    def _safe_read_json(path: Path, fallback: Any) -> Any:
        if not path.exists():
            return fallback
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return fallback

    @staticmethod
    def _safe_write_json(path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _refresh_asset_library(self) -> None:
        self.asset_library = AssetLibrary(self.publish_assets_root)

    def _asset_key(self, path: Path) -> str:
        try:
            return str(path.resolve()).lower()
        except Exception:
            return str(path).lower()

    def _asset_rel_path(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.publish_assets_root.resolve()).as_posix()
        except Exception:
            return path.name

    def _normalize_category_id(self, category_id: str) -> str:
        clean = str(category_id or "").strip()
        if clean in self.category_map:
            return clean
        if "general" in self.category_map:
            return "general"
        keys = sorted(k for k in self.category_map.keys() if str(k).strip())
        if keys:
            return keys[0]
        return clean or "general"

    @staticmethod
    def _is_image_path(path: Path) -> bool:
        return path.suffix.lower() in _IMAGE_EXTENSIONS

    @staticmethod
    def _is_video_path(path: Path) -> bool:
        return path.suffix.lower() in _VIDEO_EXTENSIONS

    @staticmethod
    def _is_audio_path(path: Path) -> bool:
        return path.suffix.lower() in _AUDIO_EXTENSIONS

    def _category_media_dirs(self, category_id: str) -> tuple[Path, Path, Path]:
        normalized = self._slug(str(category_id or ""), fallback="general").replace("-", "_")
        folder = self.publish_assets_root / normalized
        images_dir = folder / "images"
        videos_dir = folder / "videos"
        audios_dir = folder / "audios"
        return images_dir, videos_dir, audios_dir

    def _category_pool_dir(self, category_id: str, *, media_kind: str = "image") -> Path:
        images_dir, videos_dir, audios_dir = self._category_media_dirs(category_id)
        if media_kind == "video":
            target = videos_dir
        elif media_kind == "audio":
            target = audios_dir
        else:
            target = images_dir
        try:
            target.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        return target

    def _file_content_digest(self, source_path: Path) -> str:
        h = hashlib.sha1()
        try:
            with source_path.open("rb") as f:
                while True:
                    chunk = f.read(1024 * 1024)
                    if not chunk:
                        break
                    h.update(chunk)
            return h.hexdigest()[:12]
        except Exception:
            return hashlib.sha1(self._asset_key(source_path).encode("utf-8")).hexdigest()[:12]

    def _stable_asset_name(self, source_path: Path) -> str:
        ext = source_path.suffix.lower() or ".jpg"
        stem = self._slug(source_path.stem, fallback="asset")
        digest = self._file_content_digest(source_path)
        return f"{stem}_{digest}{ext}"

    def _upsert_pool_asset(self, *, source_path: Path, category_id: str, media_kind: str) -> tuple[Path, bool]:
        target_dir = self._category_pool_dir(category_id, media_kind=media_kind)
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            return source_path, False
        target = target_dir / self._stable_asset_name(source_path)
        if not target.exists():
            try:
                shutil.copy2(source_path, target)
                return target, True
            except Exception:
                return source_path, False

        try:
            src_stat = source_path.stat()
            dst_stat = target.stat()
            if int(src_stat.st_size) != int(dst_stat.st_size):
                suffix = hashlib.sha1(f"{target}_{self._now_iso()}".encode("utf-8")).hexdigest()[:6]
                target = target.with_name(f"{target.stem}_{suffix}{target.suffix}")
                try:
                    shutil.copy2(source_path, target)
                    return target, True
                except Exception:
                    return source_path, False
        except Exception:
            try:
                shutil.copy2(source_path, target)
                return target, True
            except Exception:
                return source_path, False
        return target, False

    def _new_generated_pool_path(self, *, category_id: str, prefix: str = "ai") -> Path:
        return self._new_generated_media_pool_path(
            category_id=category_id,
            prefix=prefix,
            media_kind="image",
            extension=".jpg",
        )

    def _new_generated_media_pool_path(
        self,
        *,
        category_id: str,
        prefix: str,
        media_kind: str,
        extension: str,
    ) -> Path:
        category = self._slug(str(category_id or ""), fallback="general").replace("-", "_")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        raw = f"{prefix}_{category}_{stamp}"
        base = self._slug(raw, fallback=f"{prefix}_{category}")
        ext = str(extension or "").strip().lower() or ".bin"
        if not ext.startswith("."):
            ext = f".{ext}"
        pool_dir = self._category_pool_dir(category, media_kind=media_kind)
        target = pool_dir / f"{base}{ext}"
        if target.exists():
            suffix = hashlib.sha1(f"{target}_{self._now_iso()}".encode("utf-8")).hexdigest()[:6]
            target = pool_dir / f"{base}_{suffix}{ext}"
        return target

    def _normalize_publish_asset_layout(self) -> dict[str, Any]:
        report = {"moved_images": 0, "moved_videos": 0, "moved_audios": 0, "categories": 0}
        if not self.publish_assets_root.exists():
            return report

        for category_dir in sorted([p for p in self.publish_assets_root.iterdir() if p.is_dir()], key=lambda p: p.name.lower()):
            images_dir, videos_dir, audios_dir = self._category_media_dirs(category_dir.name)
            report["categories"] = int(report.get("categories", 0)) + 1

            for file in [p for p in category_dir.iterdir() if p.is_file()]:
                target_base: Path | None = None
                if self._is_image_path(file):
                    target_base = images_dir
                    counter_key = "moved_images"
                elif self._is_video_path(file):
                    target_base = videos_dir
                    counter_key = "moved_videos"
                elif self._is_audio_path(file):
                    target_base = audios_dir
                    counter_key = "moved_audios"
                else:
                    continue

                try:
                    target_base.mkdir(parents=True, exist_ok=True)
                except Exception:
                    continue
                target = target_base / file.name
                if target.exists():
                    try:
                        src_stat = file.stat()
                        dst_stat = target.stat()
                        if int(src_stat.st_size) == int(dst_stat.st_size):
                            file.unlink(missing_ok=True)
                            continue
                    except Exception:
                        pass
                    target = target_base / self._stable_asset_name(file)
                shutil.move(str(file), str(target))
                report[counter_key] = int(report.get(counter_key, 0)) + 1
        return report

    def _load_library_sync_state(self) -> dict[str, Any]:
        fallback = {"updated_at": None, "drafts": {}}
        data = self._safe_read_json(self.library_sync_state_path, fallback)
        if not isinstance(data, dict):
            return fallback
        drafts = data.get("drafts")
        if not isinstance(drafts, dict):
            drafts = {}
        return {"updated_at": data.get("updated_at"), "drafts": drafts}

    def _save_library_sync_state(self, state: dict[str, Any]) -> None:
        payload = {
            "updated_at": self._now_iso(),
            "drafts": state.get("drafts") if isinstance(state.get("drafts"), dict) else {},
        }
        self._safe_write_json(self.library_sync_state_path, payload)

    def _draft_sync_signature(self, *, draft_path: Path, payload: dict[str, Any]) -> str:
        parts: list[str] = []
        try:
            parts.append(str(int(draft_path.stat().st_mtime_ns)))
        except Exception:
            parts.append("0")
        parts.append(str(payload.get("status") or ""))
        parts.append(str(payload.get("category_id") or ""))
        parts.append(str(payload.get("format_type") or ""))

        for key in ("image_path", "video_path"):
            text = str(payload.get(key) or "").strip()
            if not text:
                continue
            p = Path(text)
            if not p.exists():
                continue
            try:
                st = p.stat()
                parts.append(f"{key}:{int(st.st_size)}:{int(st.st_mtime_ns)}")
            except Exception:
                parts.append(f"{key}:exists")
        music_path = str(payload.get("video_music_path") or "").strip()
        if music_path:
            p = Path(music_path)
            if p.exists():
                try:
                    st = p.stat()
                    parts.append(f"video_music_path:{int(st.st_size)}:{int(st.st_mtime_ns)}")
                except Exception:
                    parts.append("video_music_path:exists")

        return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()

    def _library_category_from_draft(self, payload: dict[str, Any]) -> str:
        raw = str(payload.get("category_id") or "").strip()
        if not raw:
            raw = self._infer_category(str(payload.get("caption") or ""))
        normalized = self._slug(raw, fallback="general").replace("-", "_")
        return normalized or "general"

    def _ingest_draft_media_into_library(self, payload: dict[str, Any]) -> dict[str, Any]:
        category_id = self._library_category_from_draft(payload)
        copied_images = 0
        copied_videos = 0
        copied_audios = 0
        image_targets: list[str] = []
        video_targets: list[str] = []
        audio_targets: list[str] = []

        image_candidates: list[Path] = []
        base_image = str(payload.get("image_path") or "").strip()
        if base_image:
            image_candidates.append(Path(base_image))
        publish_media = payload.get("publish_media") if isinstance(payload.get("publish_media"), dict) else {}
        for key in ("post_image_path", "story_image_path"):
            candidate = str(publish_media.get(key) or "").strip()
            if candidate:
                image_candidates.append(Path(candidate))

        seen_images: set[str] = set()
        image_qc = payload.get("image_qc") if isinstance(payload.get("image_qc"), dict) else {}
        image_ok = bool(image_qc.get("passed", False))
        for source in image_candidates:
            key = self._asset_key(source)
            if key in seen_images:
                continue
            seen_images.add(key)
            if not source.exists() or not self._is_image_path(source):
                continue
            if not image_ok and source == Path(base_image):
                try:
                    report = self._validate_ig_image(
                        image_path=source,
                        image_source=str(payload.get("image_source") or "asset_library"),
                        format_type=str(payload.get("format_type") or "feed"),
                    )
                    image_ok = bool(report.get("passed", False))
                except Exception:
                    image_ok = False
            if not image_ok:
                continue
            target, created = self._upsert_pool_asset(source_path=source, category_id=category_id, media_kind="image")
            if created:
                copied_images += 1
            image_targets.append(str(target))

        video_path = str(payload.get("video_path") or "").strip()
        if video_path:
            source_video = Path(video_path)
            video_qc = payload.get("video_qc") if isinstance(payload.get("video_qc"), dict) else {}
            if source_video.exists() and self._is_video_path(source_video) and bool(video_qc.get("passed", False)):
                target, created = self._upsert_pool_asset(source_path=source_video, category_id=category_id, media_kind="video")
                if created:
                    copied_videos += 1
                video_targets.append(str(target))
        music_path = str(payload.get("video_music_path") or "").strip()
        if music_path:
            source_music = Path(music_path)
            if source_music.exists() and self._is_audio_path(source_music):
                target, created = self._upsert_pool_asset(source_path=source_music, category_id=category_id, media_kind="audio")
                if created:
                    copied_audios += 1
                audio_targets.append(str(target))

        return {
            "category_id": category_id,
            "copied_images": copied_images,
            "copied_videos": copied_videos,
            "copied_audios": copied_audios,
            "image_targets": image_targets,
            "video_targets": video_targets,
            "audio_targets": audio_targets,
            "primary_image_path": image_targets[0] if image_targets else "",
            "primary_video_path": video_targets[0] if video_targets else "",
            "primary_audio_path": audio_targets[0] if audio_targets else "",
        }

    def sync_library_from_drafts(self) -> dict[str, Any]:
        self._normalize_publish_asset_layout()
        state = self._load_library_sync_state()
        known = state.get("drafts") if isinstance(state.get("drafts"), dict) else {}
        if not isinstance(known, dict):
            known = {}

        report: dict[str, Any] = {
            "ok": True,
            "processed_drafts": 0,
            "updated_drafts": 0,
            "copied_images": 0,
            "copied_videos": 0,
            "copied_audios": 0,
            "by_category": {},
            "warnings": [],
        }
        by_category: dict[str, dict[str, int]] = {}

        for draft_dir in sorted([p for p in self.drafts_root.iterdir() if p.is_dir()], key=lambda p: p.name.lower()):
            draft_path = draft_dir / "draft.json"
            payload = self._safe_read_json(draft_path, None)
            if not isinstance(payload, dict):
                continue

            draft_id = str(payload.get("draft_id") or draft_dir.name).strip() or draft_dir.name
            sig = self._draft_sync_signature(draft_path=draft_path, payload=payload)
            report["processed_drafts"] = int(report["processed_drafts"]) + 1
            if str(known.get(draft_id) or "") == sig:
                continue

            result = self._ingest_draft_media_into_library(payload)
            known[draft_id] = sig
            report["updated_drafts"] = int(report["updated_drafts"]) + 1
            report["copied_images"] = int(report["copied_images"]) + int(result.get("copied_images", 0))
            report["copied_videos"] = int(report["copied_videos"]) + int(result.get("copied_videos", 0))
            report["copied_audios"] = int(report["copied_audios"]) + int(result.get("copied_audios", 0))

            category_id = str(result.get("category_id") or "general")
            cat_report = by_category.get(category_id) or {"images": 0, "videos": 0, "audios": 0}
            cat_report["images"] = int(cat_report["images"]) + int(result.get("copied_images", 0))
            cat_report["videos"] = int(cat_report["videos"]) + int(result.get("copied_videos", 0))
            cat_report["audios"] = int(cat_report["audios"]) + int(result.get("copied_audios", 0))
            by_category[category_id] = cat_report

        report["by_category"] = by_category
        try:
            self._save_library_sync_state({"drafts": known})
        except PermissionError as exc:
            report["warnings"].append(f"library_sync_state_write_permission_denied:{exc}")
        except OSError as exc:
            report["warnings"].append(f"library_sync_state_write_os_error:{exc}")
        self._refresh_runtime_categories()
        self._refresh_asset_library()
        try:
            self._sync_asset_catalog()
        except PermissionError as exc:
            report["warnings"].append(f"asset_catalog_write_permission_denied:{exc}")
        except OSError as exc:
            report["warnings"].append(f"asset_catalog_write_os_error:{exc}")
        return report

    def _discover_category_ids_from_folders(self) -> list[str]:
        if not self.publish_assets_root.exists():
            return []
        rows = [p.name.strip() for p in self.publish_assets_root.iterdir() if p.is_dir() and p.name.strip()]
        return sorted(set(rows))

    @staticmethod
    def _label_from_category_id(category_id: str) -> str:
        text = str(category_id or "").replace("_", " ").replace("-", " ").strip()
        return " ".join(part.capitalize() for part in text.split()) or "General"

    def _default_objective_for_category(self, category_id: str) -> str:
        low = str(category_id or "").lower()
        if any(tok in low for tok in ["proveedor", "profesional", "ofrece"]):
            return "captar_proveedores"
        if any(tok in low for tok in ["qr", "branding"]):
            return "branding"
        return "captar_clientes"

    @staticmethod
    def _norm_list(values: Any) -> list[str]:
        if values is None:
            return []
        if isinstance(values, str):
            values = [values]
        if not isinstance(values, list):
            return []
        out: list[str] = []
        for item in values:
            text = " ".join(str(item or "").split()).strip()
            if text:
                out.append(text)
        return out

    def _load_descriptor_prompt_framework(self, descriptor_cfg: dict[str, Any]) -> dict[str, Any]:
        raw = descriptor_cfg.get("prompt_framework") if isinstance(descriptor_cfg, dict) else {}
        if not isinstance(raw, dict):
            raw = {}

        return {
            "common_strengths": self._norm_list(raw.get("common_strengths")),
            "common_layout_rules": self._norm_list(raw.get("common_layout_rules")),
            "common_brand_rules": self._norm_list(raw.get("common_brand_rules")),
            "global_poster_structure": self._norm_list(raw.get("global_poster_structure")),
            "design_finish_rules": self._norm_list(raw.get("design_finish_rules")),
            "global_negative_rules": self._norm_list(raw.get("global_negative_rules")),
            "reference_policy": self._norm(raw.get("reference_policy") or ""),
        }

    def _build_creative_template(self, *, category_id: str, label: str, category_raw: dict[str, Any]) -> dict[str, Any]:
        raw = category_raw.get("creative_template") if isinstance(category_raw.get("creative_template"), dict) else {}
        framework = self._descriptor_prompt_framework or {}

        common_strengths = self._norm_list(framework.get("common_strengths")) + self._norm_list(raw.get("common_strengths"))
        composition_rules = self._norm_list(framework.get("common_layout_rules")) + self._norm_list(raw.get("composition_rules"))
        trust_cues = self._norm_list(framework.get("common_brand_rules")) + self._norm_list(raw.get("trust_cues"))
        poster_structure = self._norm_list(framework.get("global_poster_structure")) + self._norm_list(raw.get("poster_structure"))
        finish_rules = self._norm_list(framework.get("design_finish_rules")) + self._norm_list(raw.get("design_finish_rules"))
        negative_rules = self._norm_list(framework.get("global_negative_rules")) + self._norm_list(raw.get("avoid"))
        info_blocks = self._norm_list(raw.get("information_blocks"))
        text_hierarchy = self._norm_list(raw.get("text_hierarchy"))
        quality_checks = self._norm_list(raw.get("category_quality_checks"))
        try:
            min_info_elements = int(raw.get("min_info_elements") or 8)
        except Exception:
            min_info_elements = 8
        min_info_elements = max(6, min(18, min_info_elements))

        template = {
            "subject_profile": self._norm(raw.get("subject_profile") or ""),
            "scene_profile": self._norm(raw.get("scene_profile") or ""),
            "color_direction": self._norm(raw.get("color_direction") or ""),
            "lighting_direction": self._norm(raw.get("lighting_direction") or ""),
            "camera_direction": self._norm(raw.get("camera_direction") or ""),
            "copy_structure": self._norm(raw.get("copy_structure") or ""),
            "layout_density": self._norm(raw.get("layout_density") or ""),
            "tone_keywords": self._norm_list(raw.get("tone_keywords")),
            "differentiators": self._norm_list(raw.get("differentiators")),
            "scene_anchors": self._norm_list(raw.get("scene_anchors")),
            "signature_elements": self._norm_list(raw.get("signature_elements")),
            "information_blocks": info_blocks,
            "text_hierarchy": text_hierarchy,
            "category_quality_checks": quality_checks,
            "min_info_elements": min_info_elements,
            "composition_rules": composition_rules,
            "poster_structure": poster_structure,
            "design_finish_rules": finish_rules,
            "common_strengths": common_strengths,
            "trust_cues": trust_cues,
            "negative_rules": negative_rules,
            "reference_policy": self._norm(raw.get("reference_policy") or framework.get("reference_policy") or ""),
        }

        # Hard fallback to avoid generic/legacy drift when descriptor misses fields.
        if not template["subject_profile"]:
            template["subject_profile"] = f"Primary hero specialist for {label} with trustworthy expression."
        if not template["scene_profile"]:
            template["scene_profile"] = f"Commercial social ad scene for {label}, Chilean context."
        if not template["color_direction"]:
            template["color_direction"] = "Blue and teal base with one warm accent color."
        if not template["lighting_direction"]:
            template["lighting_direction"] = "Clean high-contrast studio-like key light with realistic shadows."
        if not template["camera_direction"]:
            template["camera_direction"] = "Mid shot, eye-level, sharp focus on hero subject."
        if not template["copy_structure"]:
            template["copy_structure"] = "Headline + supporting value blocks + clear CTA band with contact details."
        if not template["layout_density"]:
            template["layout_density"] = "information-rich but clean"
        if not template["information_blocks"]:
            template["information_blocks"] = [
                "Top block with compelling headline and service qualifier.",
                "Middle modules with explicit benefit bullets.",
                "Location or coverage chip with city names.",
                "Bottom CTA/contact strip with brand and WhatsApp details.",
            ]
        if not template["text_hierarchy"]:
            template["text_hierarchy"] = [
                "Headline should be the largest text element.",
                "Second level labels for specialty/service modules.",
                "Short bullets with high contrast and clear spacing.",
                "Final CTA and phone must remain highly legible.",
            ]
        if not template["category_quality_checks"]:
            template["category_quality_checks"] = [
                "No empty areas that make the ad look unfinished.",
                "Text blocks aligned and visually balanced with subject.",
                "Professional polish comparable to premium social ads.",
            ]
        if not template["composition_rules"]:
            template["composition_rules"] = [
                "Hero subject on right third.",
                "Readable negative space on left for future text blocks.",
                "Foreground, midground and background depth layers.",
            ]
        if not template["poster_structure"]:
            template["poster_structure"] = [
                "Top headline with 8% safe margin from top edge.",
                "Middle section with service value modules and bullets.",
                "Bottom CTA/contact band with logo, WhatsApp and website.",
            ]
        if not template["design_finish_rules"]:
            template["design_finish_rules"] = [
                "Use rounded capsules/chips for section labels.",
                "Use subtle iconography aligned to each benefit row.",
                "Use soft gradients and shape accents to avoid flat layout.",
                "Polished spacing and alignment with premium ad finish.",
            ]
        if not template["common_strengths"]:
            template["common_strengths"] = [
                "High trust visual language.",
                "Clear conversion intent.",
                "Professional service realism.",
            ]
        if not template["negative_rules"]:
            template["negative_rules"] = [
                "No distorted anatomy or hands.",
                "No unreadable typography blocks.",
                "No clutter that hides the CTA area.",
            ]
        return template

    def _load_descriptor_bootstrap_state(self) -> dict[str, Any]:
        fallback = {
            "updated_at": None,
            "folders_signature": "",
            "descriptor_mtime_ns": 0,
            "known_descriptor_ids": [],
            "generated": {},
            "skipped": {},
        }
        data = self._safe_read_json(self.descriptor_bootstrap_state_path, fallback)
        if not isinstance(data, dict):
            return fallback
        out = dict(fallback)
        out.update(data)
        if not isinstance(out.get("known_descriptor_ids"), list):
            out["known_descriptor_ids"] = []
        if not isinstance(out.get("generated"), dict):
            out["generated"] = {}
        if not isinstance(out.get("skipped"), dict):
            out["skipped"] = {}
        return out

    def _save_descriptor_bootstrap_state(self, state: dict[str, Any]) -> None:
        payload = dict(state or {})
        payload["updated_at"] = self._now_iso()
        try:
            self._safe_write_json(self.descriptor_bootstrap_state_path, payload)
        except OSError:
            # Descriptor bootstrap telemetry is best-effort and must not block publishing.
            return

    def _descriptor_folders_signature(self) -> str:
        if not self.publish_assets_root.exists():
            return ""
        rows: list[str] = []
        for folder in sorted([p for p in self.publish_assets_root.iterdir() if p.is_dir()], key=lambda p: p.name.lower()):
            latest = int(folder.stat().st_mtime_ns)
            count = 0
            for item in folder.rglob("*"):
                if item.is_file() and item.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
                    count += 1
                    try:
                        latest = max(latest, int(item.stat().st_mtime_ns))
                    except Exception:
                        pass
            rows.append(f"{folder.name.lower()}:{count}:{latest}")
        raw = "|".join(rows).encode("utf-8")
        return hashlib.sha1(raw).hexdigest()

    def _descriptor_base_from_existing(self, *, category_id: str) -> dict[str, Any]:
        target = self._tokens_from_text(category_id)
        if not target:
            target = {self._slug(category_id, fallback="general")}

        best_score = -1
        best: dict[str, Any] | None = None
        for row in self._descriptor_category_map.values():
            if not isinstance(row, dict):
                continue
            tokens: set[str] = set()
            tokens.update(self._tokens_from_text(str(row.get("id") or "")))
            tokens.update(self._tokens_from_text(str(row.get("label") or "")))
            for item in row.get("keywords") or []:
                tokens.update(self._tokens_from_text(str(item)))
            for item in row.get("services") or []:
                tokens.update(self._tokens_from_text(str(item)))
            if not tokens:
                continue
            overlap = len(target.intersection(tokens))
            if overlap > best_score:
                best_score = overlap
                best = row

        if best is None and self._descriptor_category_map:
            best = next(iter(self._descriptor_category_map.values()))
        return dict(best or {})

    def _pick_bootstrap_reference_image(self, *, category_id: str) -> Path | None:
        folder = self.publish_assets_root / category_id
        if not folder.exists() or not folder.is_dir():
            return None
        items = [p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}]
        if not items:
            return None

        def _rank(path: Path) -> tuple[int, int, str]:
            name = path.name.lower()
            generated_penalty = 1 if name.startswith(("openai_", "ai_", "generated_")) or "_openai_" in name else 0
            area = 0
            try:
                with Image.open(path) as img:
                    area = int(img.size[0] * img.size[1])
            except Exception:
                pass
            return (generated_penalty, -area, name)

        return sorted(items, key=_rank)[0]

    @staticmethod
    def _rgb_to_color_hint(r: int, g: int, b: int) -> str:
        if r >= g and r >= b:
            return "Warm red/orange dominant palette"
        if g >= r and g >= b:
            return "Green dominant palette with trust accents"
        return "Blue/cyan dominant palette with professional look"

    def _extract_ocr_text(self, path: Path) -> dict[str, Any]:
        result = {
            "engine": "none",
            "available": False,
            "lines": [],
            "tokens": [],
            "error": "no_ocr_engine",
        }

        try:
            import pytesseract  # type: ignore

            tesseract_candidates = [
                r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
                str(Path.home() / "AppData" / "Local" / "Programs" / "Tesseract-OCR" / "tesseract.exe"),
            ]
            for candidate in tesseract_candidates:
                if Path(candidate).exists():
                    try:
                        pytesseract.pytesseract.tesseract_cmd = candidate
                    except Exception:
                        pass
                    break

            lines: list[str] = []
            seen: set[str] = set()

            def _push_lines(raw_text: str) -> None:
                for raw in str(raw_text or "").splitlines():
                    clean = " ".join(str(raw or "").split()).strip().strip("-|")
                    clean = clean.replace("  ", " ")
                    if len(clean) < 3:
                        continue
                    if not any(ch.isalpha() for ch in clean):
                        continue
                    alpha_ratio = sum(1 for ch in clean if ch.isalpha()) / max(1, len(clean))
                    if alpha_ratio < 0.35:
                        continue
                    low = clean.lower()
                    if low in seen:
                        continue
                    seen.add(low)
                    lines.append(clean)
                    if len(lines) >= 32:
                        return

            with Image.open(path).convert("RGB") as src:
                gray = ImageOps.autocontrast(src.convert("L"))
                up = gray.resize((gray.width * 2, gray.height * 2), resample=Image.Resampling.LANCZOS)
                bw = up.point(lambda v: 255 if v > 165 else 0, mode="1").convert("L")
                variants = [src, gray.convert("RGB"), bw.convert("RGB")]
                configs = ["--oem 3 --psm 6", "--oem 3 --psm 11"]

                for image_variant in variants:
                    for cfg in configs:
                        try:
                            text = str(pytesseract.image_to_string(image_variant, lang="spa+eng", config=cfg) or "")
                            _push_lines(text)
                            if len(lines) >= 32:
                                break
                        except Exception:
                            continue
                    if len(lines) >= 32:
                        break

            tokens = sorted(self._tokens_from_text(" ".join(lines)))
            return {
                "engine": "pytesseract",
                "available": bool(lines),
                "lines": lines,
                "tokens": tokens[:32],
                "error": "" if lines else "ocr_no_text_detected",
            }
        except Exception as exc:  # noqa: BLE001
            result["error"] = f"ocr_unavailable:{type(exc).__name__}"
            return result

    @staticmethod
    def _zone_label(index: int) -> str:
        return ["left", "center", "right"][max(0, min(index, 2))]

    def _analyze_composition(self, path: Path) -> dict[str, Any]:
        try:
            with Image.open(path).convert("L") as img:
                w, h = img.size
                work = ImageOps.fit(img, (120, 120), method=Image.Resampling.LANCZOS)
                edges = work.filter(ImageFilter.FIND_EDGES)

                def _third_means(pil_img: Image.Image) -> list[float]:
                    ww, hh = pil_img.size
                    cuts = [0, ww // 3, (2 * ww) // 3, ww]
                    out: list[float] = []
                    for i in range(3):
                        box = pil_img.crop((cuts[i], 0, cuts[i + 1], hh))
                        out.append(float(ImageStat.Stat(box).mean[0]))
                    return out

                lum = _third_means(work)
                edge = _third_means(edges)
                edge_avg = float(sum(edge) / 3.0)
                edge_norm = [x / max(1.0, edge_avg) for x in edge]
                bright_avg = float(sum(lum) / 3.0)
                bright_norm = [x / max(1.0, bright_avg) for x in lum]
                safe_scores = [bright_norm[i] - (edge_norm[i] * 1.15) for i in range(3)]
                safe_zone_idx = max(range(3), key=lambda i: safe_scores[i])
                focal_zone_idx = max(range(3), key=lambda i: edge[i])

                hh = work.size[1]
                top = float(ImageStat.Stat(edges.crop((0, 0, 120, hh // 3))).mean[0])
                mid = float(ImageStat.Stat(edges.crop((0, hh // 3, 120, (2 * hh) // 3))).mean[0])
                bottom = float(ImageStat.Stat(edges.crop((0, (2 * hh) // 3, 120, hh))).mean[0])
                vertical_focus = max([("top", top), ("middle", mid), ("bottom", bottom)], key=lambda kv: kv[1])[0]

                density = "high" if edge_avg >= 26 else "medium" if edge_avg >= 15 else "low"
                edge_risk, edge_meta = self._edge_margin_risk(path)
                return {
                    "orientation": "vertical" if h >= w else "horizontal",
                    "safe_text_zone": self._zone_label(safe_zone_idx),
                    "focal_zone": self._zone_label(focal_zone_idx),
                    "vertical_focus": vertical_focus,
                    "content_density": density,
                    "edge_density": {
                        "left": round(edge[0], 2),
                        "center": round(edge[1], 2),
                        "right": round(edge[2], 2),
                    },
                    "luminance": {
                        "left": round(lum[0], 2),
                        "center": round(lum[1], 2),
                        "right": round(lum[2], 2),
                    },
                    "edge_margin_risk": bool(edge_risk),
                    "edge_meta": edge_meta,
                }
        except Exception:  # noqa: BLE001
            return {
                "orientation": "vertical",
                "safe_text_zone": "left",
                "focal_zone": "right",
                "vertical_focus": "middle",
                "content_density": "medium",
                "edge_density": {"left": 0.0, "center": 0.0, "right": 0.0},
                "luminance": {"left": 0.0, "center": 0.0, "right": 0.0},
                "edge_margin_risk": False,
                "edge_meta": {},
            }

    def _infer_semantic_tags(
        self,
        *,
        category_id: str,
        reference_image: Path,
        base_descriptor: dict[str, Any],
        ocr_tokens: list[str],
    ) -> list[str]:
        counter: Counter[str] = Counter()
        stop = {
            "conectaproia",
            "conecta",
            "pro",
            "ia",
            "png",
            "jpg",
            "jpeg",
            "webp",
            "openai",
            "image",
            "foto",
            "premium",
            "ad",
            "social",
            "chile",
            "chilean",
            "whatsapp",
        }

        def _add(tokens: set[str], weight: int) -> None:
            for tok in tokens:
                if not tok or tok in stop:
                    continue
                counter[tok] += weight

        _add(self._tokens_from_text(category_id), 4)
        _add(self._tokens_from_text(reference_image.stem), 3)
        _add(set(ocr_tokens or []), 2)

        for item in base_descriptor.get("keywords") or []:
            _add(self._tokens_from_text(str(item)), 2)
        for item in base_descriptor.get("services") or []:
            _add(self._tokens_from_text(str(item)), 2)
        for item in (base_descriptor.get("creative_template") or {}).get("tone_keywords") or []:
            _add(self._tokens_from_text(str(item)), 1)

        aliases = {
            "kinesiologia": ["rehabilitacion", "terapia", "bienestar"],
            "electricidad": ["electricista", "hogar", "seguridad"],
            "gasfiteria": ["gasfiter", "calefon", "fuga"],
            "legal": ["abogado", "contrato", "asesoria"],
            "proveedores": ["profesionales", "tecnicos", "especialistas"],
            "sincosto": ["gratis", "contacto", "beneficio"],
            "fonoaudiologia": ["voz", "lenguaje", "terapia"],
        }
        for key, rows in aliases.items():
            if key in counter:
                for value in rows:
                    counter[value] += 2

        ranked = [k for k, _ in counter.most_common(18)]
        return ranked

    def _analyze_reference_image(self, path: Path) -> dict[str, Any]:
        try:
            with Image.open(path).convert("RGB") as img:
                width, height = img.size
                thumb = ImageOps.fit(img, (96, 96), method=Image.Resampling.LANCZOS)
                pixels = list(thumb.getdata())
                r = int(sum(px[0] for px in pixels) / max(1, len(pixels)))
                g = int(sum(px[1] for px in pixels) / max(1, len(pixels)))
                b = int(sum(px[2] for px in pixels) / max(1, len(pixels)))
                sat = [
                    colorsys.rgb_to_hsv(px[0] / 255.0, px[1] / 255.0, px[2] / 255.0)[1]
                    for px in pixels
                ]
                sat_avg = float(sum(sat) / max(1, len(sat)))
                orientation = "vertical" if height >= width else "horizontal"
                brightness = (r + g + b) / 3.0
                mood = "bright" if brightness >= 150 else "balanced" if brightness >= 95 else "dramatic"
                sat_text = "high saturation" if sat_avg >= 0.55 else "medium saturation" if sat_avg >= 0.35 else "low saturation"
                composition = self._analyze_composition(path)
                ocr = self._extract_ocr_text(path)
                return {
                    "size": [int(width), int(height)],
                    "orientation": orientation,
                    "avg_rgb": [r, g, b],
                    "mood": mood,
                    "saturation": sat_text,
                    "color_hint": self._rgb_to_color_hint(r, g, b),
                    "composition": composition,
                    "ocr": ocr,
                }
        except Exception:
            return {
                "size": [1080, 1350],
                "orientation": "vertical",
                "avg_rgb": [120, 160, 190],
                "mood": "balanced",
                "saturation": "medium saturation",
                "color_hint": "Blue/cyan dominant palette with professional look",
                "composition": {
                    "orientation": "vertical",
                    "safe_text_zone": "left",
                    "focal_zone": "right",
                    "vertical_focus": "middle",
                    "content_density": "medium",
                    "edge_density": {"left": 0.0, "center": 0.0, "right": 0.0},
                    "luminance": {"left": 0.0, "center": 0.0, "right": 0.0},
                    "edge_margin_risk": False,
                    "edge_meta": {},
                },
                "ocr": {"engine": "none", "available": False, "lines": [], "tokens": [], "error": "analysis_failed"},
            }

    def _bootstrap_descriptor_entry(self, *, category_id: str, reference_image: Path) -> dict[str, Any]:
        label = self._label_from_category_id(category_id)
        objective = self._default_objective_for_category(category_id)
        base = self._descriptor_base_from_existing(category_id=category_id)
        analysis = self._analyze_reference_image(reference_image)
        composition = analysis.get("composition") if isinstance(analysis.get("composition"), dict) else {}
        ocr = analysis.get("ocr") if isinstance(analysis.get("ocr"), dict) else {}
        ocr_tokens = [str(x) for x in (ocr.get("tokens") or []) if str(x).strip()]
        semantic_tags = self._infer_semantic_tags(
            category_id=category_id,
            reference_image=reference_image,
            base_descriptor=base,
            ocr_tokens=ocr_tokens,
        )
        base_template = base.get("creative_template") if isinstance(base.get("creative_template"), dict) else {}

        keywords = semantic_tags[:8]
        if not keywords:
            tokens = sorted(self._tokens_from_text(category_id))
            keywords = tokens[:6]
        if not keywords:
            keywords = [self._slug(label, fallback="general").replace("-", " ")]

        services = [self._norm(x) for x in (base.get("services") or []) if self._norm(x)][:3]
        if not services:
            services = [str(tok).replace("-", " ") for tok in semantic_tags[:3] if str(tok).strip()]
        if not services:
            services = [label.lower()]

        objective_hint = {
            "captar_clientes": "Atraer clientes que necesitan ayuda inmediata y confiable.",
            "captar_proveedores": "Atraer profesionales que quieren recibir mas oportunidades reales.",
            "branding": "Refuerzo de marca y recordacion visual de ConectaProIA.",
        }[objective]

        safe_zone = str(composition.get("safe_text_zone") or "left")
        focal_zone = str(composition.get("focal_zone") or "right")
        density = str(composition.get("content_density") or "medium")
        ocr_preview = " | ".join([str(x) for x in (ocr.get("lines") or [])[:2]])
        visual_brief = (
            f"{analysis.get('mood')} mood, {analysis.get('saturation')}, {analysis.get('color_hint')}, "
            f"orientation {analysis.get('orientation')}, safe_text_zone={safe_zone}, focal_zone={focal_zone}, density={density}. "
            f"OCR cues: {ocr_preview or 'not detected'}."
        )

        hook = f"Necesitas {label.lower()} hoy?"
        value = f"ConectaProIA te ayuda a resolver {label.lower()} por WhatsApp con enfoque claro y rapido."
        proof = "Contenido diseñado para transmitir confianza, orden y accion inmediata."
        cta = "Escribenos ahora."
        if objective == "captar_proveedores":
            hook = f"Ofreces {label.lower()} y quieres mas clientes?"
            value = "ConectaProIA conecta profesionales con personas que si necesitan ayuda."
            proof = "Visibilidad, flujo y contacto directo por WhatsApp."
            cta = "Unete hoy."

        template = {
            "subject_profile": self._norm(base_template.get("subject_profile") or f"Primary specialist for {label} with confident and friendly expression."),
            "scene_profile": self._norm(
                base_template.get("scene_profile")
                or f"Commercial social ad context for {label} in Chilean environment, with focal emphasis on {focal_zone}."
            ),
            "color_direction": f"{analysis.get('color_hint')}. Avg RGB {analysis.get('avg_rgb')}.",
            "lighting_direction": self._norm(base_template.get("lighting_direction") or "Soft but clear commercial lighting with readable text-safe areas."),
            "camera_direction": self._norm(
                base_template.get("camera_direction")
                or f"Mid shot with clear subject prominence; preserve {safe_zone} zone for text modules."
            ),
            "copy_structure": self._norm(
                base_template.get("copy_structure")
                or f"Hook headline + value modules in {safe_zone} zone + trust bullets + CTA contact band."
            ),
            "layout_density": self._norm(base_template.get("layout_density") or f"{density} information density with clear segmentation"),
            "tone_keywords": self._norm_list(base_template.get("tone_keywords")) or ["confiable", "claro", "directo", "profesional", analysis.get("mood") or "balanced"],
            "differentiators": self._norm_list(base_template.get("differentiators")) or ["Category-specific visual language", "Fast-understanding CTA hierarchy", f"Composition tuned to {safe_zone} safe zone"],
            "scene_anchors": self._norm_list(base_template.get("scene_anchors")) or ["Hero specialist presence", f"Readable {safe_zone} information zone"],
            "trust_cues": self._norm_list(base_template.get("trust_cues")) or ["Natural expressions", "Realistic wardrobe and tools"],
            "composition_rules": self._norm_list(base_template.get("composition_rules")) or ["Hero on right or right-center", "Safe margins for top and bottom text"],
            "poster_structure": self._norm_list(base_template.get("poster_structure")) or ["Headline top block", "Middle value modules", "Bottom CTA contact strip"],
            "design_finish_rules": self._norm_list(base_template.get("design_finish_rules")) or ["Rounded modules", "Clean iconography", "Soft gradients and separators"],
            "category_quality_checks": self._norm_list(base_template.get("category_quality_checks")) or ["No clipping on top/bottom text", "Commercial-ready final polish"],
            "avoid": self._norm_list(base_template.get("negative_rules")) or ["No distorted anatomy", "No unreadable or clipped text"],
            "min_info_elements": int(base_template.get("min_info_elements") or 10),
        }

        entry = {
            "id": category_id,
            "label": label,
            "objective": objective,
            "category_context": objective_hint,
            "visual_brief": visual_brief,
            "keywords": keywords,
            "services": services,
            "reference_asset_patterns": [reference_image.name],
            "image_prompt_templates": [
                f"Vertical 9:16 premium social ad image for category '{label}' in Chile, photorealistic, polished, no clipping."
            ],
            "creative_template": template,
            "variants": [
                {
                    "hook": hook,
                    "value": value,
                    "proof": proof,
                    "cta": cta,
                    "short_text": self._clip(hook, 56),
                }
            ],
            "analysis": {
                "reference_file": reference_image.name,
                "reference_image": {
                    "size": analysis.get("size"),
                    "orientation": analysis.get("orientation"),
                    "avg_rgb": analysis.get("avg_rgb"),
                    "mood": analysis.get("mood"),
                    "saturation": analysis.get("saturation"),
                    "color_hint": analysis.get("color_hint"),
                },
                "composition": composition,
                "ocr": {
                    "engine": ocr.get("engine"),
                    "available": bool(ocr.get("available", False)),
                    "line_preview": [str(x) for x in (ocr.get("lines") or [])[:8]],
                    "tokens": [str(x) for x in (ocr.get("tokens") or [])[:20]],
                    "error": ocr.get("error"),
                },
                "semantic_tags": semantic_tags[:20],
            },
        }
        return entry

    @staticmethod
    def _validate_bootstrap_descriptor_entry(entry: dict[str, Any]) -> tuple[bool, str]:
        if not isinstance(entry, dict):
            return False, "descriptor_not_dict"
        cat_id = str(entry.get("id") or "").strip()
        if not cat_id:
            return False, "missing_id"
        objective = str(entry.get("objective") or "").strip().lower()
        if objective not in {"captar_clientes", "captar_proveedores", "branding"}:
            return False, "invalid_objective"
        if not isinstance(entry.get("services"), list) or not entry.get("services"):
            return False, "missing_services"
        if not isinstance(entry.get("image_prompt_templates"), list) or not entry.get("image_prompt_templates"):
            return False, "missing_prompt_templates"
        if not isinstance(entry.get("creative_template"), dict):
            return False, "missing_creative_template"
        return True, "ok"

    def _auto_bootstrap_missing_descriptors(self) -> None:
        desc_path = self.settings.instagram_category_descriptors_path
        if not desc_path.exists():
            try:
                desc_path.parent.mkdir(parents=True, exist_ok=True)
                desc_path.write_text("prompt_framework: {}\ncategories: []\n", encoding="utf-8")
            except OSError:
                # Descriptor bootstrap is best-effort. If the file is read-only, keep runtime
                # working with already loaded descriptor/legacy data and avoid crashing publish.
                return

        state = self._load_descriptor_bootstrap_state()
        folders_signature = self._descriptor_folders_signature()
        descriptor_mtime = int(desc_path.stat().st_mtime_ns) if desc_path.exists() else 0
        known_ids_now = sorted(self._descriptor_category_map.keys())
        if (
            str(state.get("folders_signature") or "") == folders_signature
            and int(state.get("descriptor_mtime_ns") or 0) == descriptor_mtime
            and list(state.get("known_descriptor_ids") or []) == known_ids_now
        ):
            return

        cfg = self._load_categories(desc_path)
        categories = cfg.get("categories") if isinstance(cfg.get("categories"), list) else []
        categories = [row for row in categories if isinstance(row, dict)]
        existing_ids = {str(row.get("id") or "").strip() for row in categories if str(row.get("id") or "").strip()}

        generated_map = dict(state.get("generated") or {})
        skipped_map = dict(state.get("skipped") or {})
        pending_generated: list[tuple[str, dict[str, Any], str]] = []

        folder_ids = self._discover_category_ids_from_folders()
        for cat_id in folder_ids:
            if cat_id in existing_ids:
                continue
            ref = self._pick_bootstrap_reference_image(category_id=cat_id)
            if ref is None:
                skipped_map[cat_id] = {"reason": "no_reference_image", "seen_at": self._now_iso()}
                continue

            entry = self._bootstrap_descriptor_entry(category_id=cat_id, reference_image=ref)
            ok, reason = self._validate_bootstrap_descriptor_entry(entry)
            if not ok:
                skipped_map[cat_id] = {"reason": reason, "seen_at": self._now_iso()}
                continue

            pending_generated.append((cat_id, entry, ref.name))

        wrote_descriptors = False
        if pending_generated:
            for cat_id, entry, _ref_name in pending_generated:
                categories.append(entry)
                existing_ids.add(cat_id)
            cfg["categories"] = categories
            try:
                desc_path.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
                wrote_descriptors = True
            except OSError:
                for cat_id, _entry, _ref_name in pending_generated:
                    skipped_map[cat_id] = {"reason": "descriptor_write_failed", "seen_at": self._now_iso()}
        else:
            cfg["categories"] = categories

        if wrote_descriptors:
            for cat_id, entry, ref_name in pending_generated:
                generated_map[cat_id] = {
                    "reference": ref_name,
                    "generated_at": self._now_iso(),
                    "objective": entry.get("objective"),
                }
                skipped_map.pop(cat_id, None)

            desc_cfg = self._load_categories(desc_path)
            self._descriptor_prompt_framework = self._load_descriptor_prompt_framework(desc_cfg)
            desc_categories = desc_cfg.get("categories") if isinstance(desc_cfg, dict) else []
            if not isinstance(desc_categories, list):
                desc_categories = []
            self._descriptor_category_map = {
                str(cat.get("id") or "").strip(): cat
                for cat in desc_categories
                if isinstance(cat, dict) and str(cat.get("id") or "").strip()
            }

        new_state = {
            "folders_signature": self._descriptor_folders_signature(),
            "descriptor_mtime_ns": int(desc_path.stat().st_mtime_ns) if desc_path.exists() else 0,
            "known_descriptor_ids": sorted(self._descriptor_category_map.keys()),
            "generated": generated_map,
            "skipped": skipped_map,
        }
        self._save_descriptor_bootstrap_state(new_state)

    def _build_runtime_category(self, category_id: str) -> dict[str, Any] | None:
        legacy = dict(self._yaml_category_map.get(category_id) or {})
        descriptor = dict(self._descriptor_category_map.get(category_id) or {})
        if not legacy and not descriptor:
            # Avoid using folder names directly as publication context.
            return None

        # Descriptor is the source of truth for creative direction.
        # Legacy YAML is only fallback if descriptor is missing.
        has_descriptor = bool(descriptor)
        creative_source = descriptor if has_descriptor else legacy
        merged = dict(legacy)
        merged.update(descriptor)

        label = self._norm(creative_source.get("label") or merged.get("label") or self._label_from_category_id(category_id))
        objective = str(
            creative_source.get("objective")
            or merged.get("objective")
            or self._default_objective_for_category(category_id)
        ).strip().lower()
        if objective not in {"captar_clientes", "captar_proveedores", "branding"}:
            objective = self._default_objective_for_category(category_id)

        keywords = [self._norm(x) for x in (creative_source.get("keywords") or []) if self._norm(x)]
        if not keywords:
            keywords = [self._norm(x) for x in (merged.get("keywords") or []) if self._norm(x)]
        if not keywords:
            keywords = [self._norm(category_id.replace("_", " "))]

        services = [self._norm(x) for x in (creative_source.get("services") or []) if self._norm(x)]
        if not services:
            services = [self._norm(x) for x in (merged.get("services") or []) if self._norm(x)]
        if not services:
            services = [label]

        templates = [self._norm(x) for x in (creative_source.get("image_prompt_templates") or []) if self._norm(x)]
        if not templates and not has_descriptor:
            templates = [self._norm(x) for x in (merged.get("image_prompt_templates") or []) if self._norm(x)]
        if not templates:
            templates = ["Vertical 9:16 photorealistic marketing ad image for ConectaProIA with integrated Spanish copy blocks."]

        variants = creative_source.get("variants") if isinstance(creative_source.get("variants"), list) else []
        if not variants:
            variants = merged.get("variants") if isinstance(merged.get("variants"), list) else []
        valid_variants = [v for v in variants if isinstance(v, dict)]
        if not valid_variants:
            valid_variants = [
                {
                    "hook": f"Necesitas {label.lower()} hoy?",
                    "value": f"ConectaProIA te conecta por WhatsApp con especialistas de {label.lower()}.",
                    "proof": "Respuesta rapida y contacto directo.",
                    "cta": "Escribenos ahora.",
                    "short_text": f"{label} por WhatsApp.",
                }
            ]

        category = {
            "id": category_id,
            "label": label,
            "objective": objective,
            "keywords": keywords,
            "services": services,
            "image_prompt_templates": templates,
            "creative_template": self._build_creative_template(category_id=category_id, label=label, category_raw=creative_source),
            "variants": valid_variants,
        }
        if self._norm(creative_source.get("category_context") or merged.get("category_context")):
            category["category_context"] = self._norm(creative_source.get("category_context") or merged.get("category_context"))
        if self._norm(creative_source.get("visual_brief") or merged.get("visual_brief")):
            category["visual_brief"] = self._norm(creative_source.get("visual_brief") or merged.get("visual_brief"))
        if bool(creative_source.get("force_qr", merged.get("force_qr", False))):
            category["force_qr"] = True
        if isinstance(creative_source.get("hashtags"), list):
            category["hashtags"] = [self._norm(x) for x in creative_source.get("hashtags") if self._norm(x)]
        elif isinstance(merged.get("hashtags"), list):
            category["hashtags"] = [self._norm(x) for x in merged.get("hashtags") if self._norm(x)]

        service_modules = self._norm_list(creative_source.get("service_modules"))
        if not service_modules:
            service_modules = self._norm_list(merged.get("service_modules"))
        if not service_modules:
            service_modules = services[:2]
        if service_modules:
            category["service_modules"] = service_modules

        reference_patterns = self._norm_list(creative_source.get("reference_asset_patterns"))
        if not reference_patterns:
            reference_patterns = self._norm_list(merged.get("reference_asset_patterns"))
        if reference_patterns:
            category["reference_asset_patterns"] = reference_patterns
        return category

    def _refresh_runtime_categories(self) -> None:
        self._auto_bootstrap_missing_descriptors()
        folder_ids = self._discover_category_ids_from_folders()
        if not folder_ids:
            folder_ids = sorted(set(list(self._descriptor_category_map.keys()) + list(self._yaml_category_map.keys())))

        built: list[dict[str, Any]] = []
        for cat_id in folder_ids:
            item = self._build_runtime_category(cat_id)
            if item is not None:
                built.append(item)

        self.categories = built
        self.category_map = {str(cat.get("id") or "").strip(): cat for cat in self.categories if str(cat.get("id") or "").strip()}

    @staticmethod
    def _tokens_from_text(text: str) -> set[str]:
        norm = re.sub(r"[^a-z0-9]+", " ", str(text or "").lower())
        stop = {"png", "jpg", "jpeg", "webp", "raw", "rrss", "franco", "conectapro", "biblioteca", "ia", "perfil", "portada", "facebook"}
        return {tok for tok in norm.split() if len(tok) >= 3 and tok not in stop}

    def _infer_asset_category(self, item: Any) -> tuple[str, int]:
        rel = self._asset_rel_path(item.path)
        folder_id = str(rel).split("/", 1)[0].strip()
        if folder_id in self.category_map:
            return folder_id, 100

        item_tags = self._tokens_from_text(" ".join(str(t) for t in (item.tags or [])))
        best_id = "general"
        best_score = 0

        for cat in self.categories:
            if bool(cat.get("force_qr", False)):
                continue

            cat_id = str(cat.get("id") or "general").strip() or "general"
            tokens: set[str] = set()
            tokens.update(self._tokens_from_text(cat_id))
            tokens.update(self._tokens_from_text(str(cat.get("label") or "")))

            for kw in cat.get("keywords") or []:
                tokens.update(self._tokens_from_text(str(kw)))
            for srv in cat.get("services") or []:
                tokens.update(self._tokens_from_text(str(srv)))

            if not tokens:
                continue

            overlap = len(item_tags.intersection(tokens))
            if cat_id in item_tags:
                overlap += 2

            if overlap > best_score:
                best_score = overlap
                best_id = cat_id

        confidence = min(100, best_score * 18) if best_score > 0 else 0
        return best_id, confidence

    def _sync_asset_catalog(self) -> dict[str, Any]:
        self._refresh_runtime_categories()
        self._refresh_asset_library()

        previous = self._safe_read_json(self.asset_catalog_path, {})
        prev_items_list = previous.get("items") if isinstance(previous, dict) else []
        prev_items: dict[str, dict[str, Any]] = {}
        for row in prev_items_list or []:
            if isinstance(row, dict) and str(row.get("path_key") or "").strip():
                prev_items[str(row.get("path_key"))] = row

        now_iso = self._now_iso()
        items: list[dict[str, Any]] = []
        counts_images: dict[str, int] = {}
        counts_videos: dict[str, int] = {}
        counts_audios: dict[str, int] = {}
        counts_images_quality_pass: dict[str, int] = {}

        def _ingest_items(rows: list[Any], media_type: str) -> None:
            for item in rows:
                path = item.path
                key = self._asset_key(path)
                rel = self._asset_rel_path(path)
                folder_id = str(rel).split("/", 1)[0].strip()
                if folder_id in self.category_map:
                    category_id, confidence = folder_id, 100
                    category_source = "folder"
                    excluded = False
                    override_flags: dict[str, Any] = {}
                else:
                    category_id, confidence = self._infer_asset_category(item)
                    category_id, confidence, category_source, excluded, override_flags = self._apply_asset_override(rel, category_id, confidence)
                inferred_flags = self._infer_asset_flags_from_path(rel, list(item.tags or []))
                merged_flags = dict(inferred_flags)
                for k, v in (override_flags or {}).items():
                    merged_flags[k] = v

                size_bytes = 0
                mtime_ns = 0
                try:
                    st = path.stat()
                    size_bytes = int(st.st_size)
                    mtime_ns = int(st.st_mtime_ns)
                except Exception:
                    pass

                prev = prev_items.get(key) or {}
                quality_score: int | None = None
                quality_passed: bool | None = None
                quality_issues: list[str] = []
                if media_type == "image":
                    prev_same_file = (
                        int(prev.get("size_bytes") or -1) == size_bytes
                        and int(prev.get("mtime_ns") or -1) == mtime_ns
                    )
                    if prev_same_file and isinstance(prev.get("quality_passed"), bool):
                        quality_score = int(prev.get("quality_score") or 0)
                        quality_passed = bool(prev.get("quality_passed"))
                        quality_issues = [str(x) for x in (prev.get("quality_issues") or []) if str(x).strip()][:4]
                    else:
                        q = self._validate_library_image_quality(path)
                        quality_score = int(q.get("score") or 0)
                        quality_passed = bool(quality_score >= int(self.settings.instagram_publish_quality_min_score))
                        quality_issues = [str(x) for x in (q.get("issues") or []) if str(x).strip()][:4]
                entry = {
                    "path_key": key,
                    "path": str(path),
                    "rel_path": rel,
                    "name": path.name,
                    "ext": path.suffix.lower(),
                    "media_type": media_type,
                    "size_bytes": size_bytes,
                    "mtime_ns": mtime_ns,
                    "tags": list(item.tags or []),
                    "category_id": category_id,
                    "category_confidence": confidence,
                    "category_source": category_source,
                    "flags": merged_flags,
                    "excluded": bool(excluded),
                    "first_seen_at": prev.get("first_seen_at") or now_iso,
                    "last_seen_at": now_iso,
                    "updated_at": now_iso,
                }
                if media_type == "image":
                    entry["quality_score"] = int(quality_score or 0)
                    entry["quality_passed"] = bool(quality_passed)
                    entry["quality_issues"] = quality_issues
                items.append(entry)
                if excluded:
                    continue
                if media_type == "video":
                    counts_videos[category_id] = int(counts_videos.get(category_id, 0)) + 1
                elif media_type == "audio":
                    counts_audios[category_id] = int(counts_audios.get(category_id, 0)) + 1
                else:
                    counts_images[category_id] = int(counts_images.get(category_id, 0)) + 1
                    if bool(quality_passed):
                        counts_images_quality_pass[category_id] = int(counts_images_quality_pass.get(category_id, 0)) + 1

        _ingest_items(self.asset_library.image_items, "image")
        _ingest_items(self.asset_library.video_items, "video")
        _ingest_items(self.asset_library.audio_items, "audio")

        items.sort(key=lambda x: (str(x.get("category_id") or ""), str(x.get("media_type") or ""), str(x.get("rel_path") or "")))
        payload = {
            "generated_at": now_iso,
            "assets_root": str(self.publish_assets_root),
            "total_images": len(self.asset_library.image_items),
            "total_videos": len(self.asset_library.video_items),
            "total_audios": len(self.asset_library.audio_items),
            "counts_by_category": counts_images,
            "counts_by_category_videos": counts_videos,
            "counts_by_category_audios": counts_audios,
            "counts_by_category_quality_pass": counts_images_quality_pass,
            "items": items,
        }
        try:
            self._safe_write_json(self.asset_catalog_path, payload)
        except PermissionError as exc:
            payload["write_warning"] = f"permission_denied:{exc}"
        except OSError as exc:
            payload["write_warning"] = f"os_error:{exc}"
        return payload

    def _asset_catalog_map(self) -> dict[str, dict[str, Any]]:
        data = self._safe_read_json(self.asset_catalog_path, {})
        out: dict[str, dict[str, Any]] = {}
        if not isinstance(data, dict):
            return out
        for row in data.get("items") or []:
            if isinstance(row, dict):
                key = str(row.get("path_key") or "").strip()
                if key:
                    out[key] = row
        return out

    @staticmethod
    def _catalog_image_quality_passed(meta: dict[str, Any]) -> bool:
        if not isinstance(meta, dict):
            return True
        if str(meta.get("media_type") or "").strip().lower() != "image":
            return True
        flag = meta.get("quality_passed")
        if isinstance(flag, bool):
            return flag
        return True

    def _resolve_preferred_assets(self, raw_list: list[Any]) -> list[Path]:
        results: list[Path] = []
        for raw in raw_list:
            if not raw:
                continue
            text = str(raw)
            if any(ch in text for ch in ["*", "?", "["]):
                try:
                    results.extend(self.publish_assets_root.glob(text))
                except Exception:
                    continue
            else:
                p = Path(text)
                if p.exists() and p.is_file():
                    try:
                        in_pool = p.resolve().is_relative_to(self.publish_assets_root.resolve())
                    except Exception:
                        in_pool = False
                    if in_pool:
                        results.append(p)
                    else:
                        results.extend(self.publish_assets_root.rglob(p.name))
                else:
                    candidate = self.publish_assets_root / text
                    if candidate.exists() and candidate.is_file():
                        results.append(candidate)
        dedup: list[Path] = []
        seen: set[str] = set()
        for p in results:
            key = self._asset_key(p)
            if key not in seen:
                seen.add(key)
                dedup.append(p)
        return dedup

    def _select_library_asset(self, *, query: str, category_id: str, state: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
        if self.settings.instagram_sequential_image_library:
            return self._next_sequential_image(state)

        catalog = self._asset_catalog_map()
        category_id = self._normalize_category_id(category_id)

        global_window = max(1, int(self.settings.instagram_asset_rotation_window))
        category_window = max(1, int(self.settings.instagram_asset_category_rotation_window))

        recent_global = list(state.get("recent_assets") or [])[-global_window:]
        recent_by_category = state.get("recent_assets_by_category") or {}
        if not isinstance(recent_by_category, dict):
            recent_by_category = {}
        recent_cat = list(recent_by_category.get(category_id) or [])[-category_window:]
        avoid_keys = set(str(x) for x in (recent_global + recent_cat) if str(x).strip())

        avoid_paths = {
            item.path
            for item in self.asset_library.image_items
            if self._asset_key(item.path) in avoid_keys
        }

        preferred_paths: list[Path] = []
        cat = self.category_map.get(category_id) or {}
        preferred_paths.extend(self._resolve_preferred_assets(cat.get("preferred_assets") or []))
        if not preferred_paths:
            preferred_paths.extend(self._resolve_preferred_assets(self.defaults.get("preferred_assets") or []))

        if preferred_paths:
            preferred_items = [
                item for item in self.asset_library.image_items if item.path in preferred_paths and item.path not in avoid_paths
            ]
            if not preferred_items:
                # Keep visual consistency: when style references are configured,
                # prefer them even if they were recently used.
                preferred_items = [item for item in self.asset_library.image_items if item.path in preferred_paths]
            preferred_items = [
                item
                for item in preferred_items
                if str((catalog.get(self._asset_key(item.path)) or {}).get("category_id") or "") == category_id
                and not bool((catalog.get(self._asset_key(item.path)) or {}).get("excluded"))
            ]
            preferred_items_quality = [
                item
                for item in preferred_items
                if self._catalog_image_quality_passed(catalog.get(self._asset_key(item.path)) or {})
            ]
            if preferred_items_quality:
                preferred_items = preferred_items_quality
            if preferred_items:
                pick_idx = int(state.get("counter", 0)) % max(1, len(preferred_items))
                chosen = preferred_items[pick_idx]
                key = self._asset_key(chosen.path)
                meta = catalog.get(key) or {}
                flags = meta.get("flags") if isinstance(meta.get("flags"), dict) else {}
                details = {
                    "asset_key": key,
                    "asset_rel_path": self._asset_rel_path(chosen.path),
                    "asset_category_id": str(meta.get("category_id") or "general"),
                    "asset_category_confidence": int(meta.get("category_confidence") or 0),
                    "asset_has_qr": bool(flags.get("has_qr")),
                    "asset_rotation_pool": len(preferred_items),
                    "asset_avoid_count": len(avoid_keys),
                }
                return chosen, details

        strict = [
            item
            for item in self.asset_library.top_images(query, limit=30)
            if str((catalog.get(self._asset_key(item.path)) or {}).get("category_id") or "") == category_id
            and not bool((catalog.get(self._asset_key(item.path)) or {}).get("excluded"))
        ]
        if not strict:
            strict = [
                item
                for item in self.asset_library.image_items
                if str((catalog.get(self._asset_key(item.path)) or {}).get("category_id") or "") == category_id
                and not bool((catalog.get(self._asset_key(item.path)) or {}).get("excluded"))
            ]
        strict_quality = [
            item
            for item in strict
            if self._catalog_image_quality_passed(catalog.get(self._asset_key(item.path)) or {})
        ]
        if strict_quality:
            strict = strict_quality
        strict_avoiding = [item for item in strict if item.path not in avoid_paths]

        pool = strict_avoiding or strict
        if not pool:
            raise GenerationError(
                f"No hay imagenes disponibles en el pool central para la categoria '{category_id}'."
            )
        rotate_span = min(6, len(pool))
        pick_idx = int(state.get("counter", 0)) % max(1, rotate_span)
        chosen = pool[pick_idx]
        key = self._asset_key(chosen.path)
        meta = catalog.get(key) or {}
        flags = meta.get("flags") if isinstance(meta.get("flags"), dict) else {}

        details = {
            "asset_key": key,
            "asset_rel_path": self._asset_rel_path(chosen.path),
            "asset_category_id": str(meta.get("category_id") or "general"),
            "asset_category_confidence": int(meta.get("category_confidence") or 0),
            "asset_has_qr": bool(flags.get("has_qr")),
            "asset_rotation_pool": len(pool),
            "asset_avoid_count": len(avoid_keys),
        }
        return chosen, details

    def _select_library_video(self, *, query: str, category_id: str, state: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
        catalog = self._asset_catalog_map()
        category_id = self._normalize_category_id(category_id)

        recent_videos = list(state.get("recent_videos") or [])
        avoid_keys = set(str(x) for x in recent_videos[-8:] if str(x).strip())
        avoid_paths = {
            item.path
            for item in self.asset_library.video_items
            if self._asset_key(item.path) in avoid_keys
        }

        strict = [
            item
            for item in self.asset_library.top_videos(query, limit=30)
            if str((catalog.get(self._asset_key(item.path)) or {}).get("category_id") or "") == category_id
            and not bool((catalog.get(self._asset_key(item.path)) or {}).get("excluded"))
        ]
        if not strict:
            strict = [
                item
                for item in self.asset_library.video_items
                if str((catalog.get(self._asset_key(item.path)) or {}).get("category_id") or "") == category_id
                and not bool((catalog.get(self._asset_key(item.path)) or {}).get("excluded"))
            ]
        strict_avoiding = [item for item in strict if item.path not in avoid_paths]
        pool = strict_avoiding or strict
        if not pool:
            raise GenerationError(f"No hay videos disponibles en la biblioteca para la categoria '{category_id}'.")

        rotate_span = min(6, len(pool))
        pick_idx = int(state.get("counter", 0)) % max(1, rotate_span)
        chosen = pool[pick_idx]
        key = self._asset_key(chosen.path)
        meta = catalog.get(key) or {}
        details = {
            "asset_key": key,
            "asset_rel_path": self._asset_rel_path(chosen.path),
            "asset_category_id": str(meta.get("category_id") or "general"),
            "asset_category_confidence": int(meta.get("category_confidence") or 0),
            "asset_rotation_pool": len(pool),
            "asset_avoid_count": len(avoid_keys),
        }
        return chosen, details

    def sync_asset_catalog(self) -> dict[str, Any]:
        if self.settings.instagram_library_sync_from_drafts:
            sync_report = self.sync_library_from_drafts()
        else:
            self._refresh_runtime_categories()
            self._refresh_asset_library()
            sync_report = {
                "ok": True,
                "skipped": True,
                "reason": "library_sync_from_drafts_disabled",
            }
            self._sync_asset_catalog()
        catalog = self._safe_read_json(self.asset_catalog_path, {})
        if not isinstance(catalog, dict):
            catalog = {}
        return {
            "ok": True,
            "library_sync": sync_report,
            "asset_catalog": catalog,
        }

    @staticmethod
    def _month_key(dt: datetime | None = None) -> str:
        now = dt or datetime.now(timezone.utc)
        return now.strftime("%Y-%m")

    def _load_openai_budget(self) -> dict[str, Any]:
        data = self._safe_read_json(self.openai_budget_path, {})
        if not isinstance(data, dict):
            data = {}

        month = self._month_key()
        state = {
            "month": str(data.get("month") or month),
            "images_generated": int(data.get("images_generated") or 0),
            "spent_estimated_usd": float(data.get("spent_estimated_usd") or 0.0),
        }
        if state["month"] != month:
            state = {"month": month, "images_generated": 0, "spent_estimated_usd": 0.0}
        return state

    def _append_openai_budget_event(self, payload: dict[str, Any]) -> None:
        row = dict(payload or {})
        row["ts"] = self._now_iso()
        try:
            with self.openai_budget_events_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        except Exception:
            pass

    @staticmethod
    def _read_last_jsonl_event(path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            with path.open("r", encoding="utf-8") as f:
                lines = f.readlines()
            if not lines:
                return {}
            row = json.loads(lines[-1])
            return row if isinstance(row, dict) else {}
        except Exception:
            return {}

    def _save_openai_budget(self, state: dict[str, Any]) -> None:
        payload = {
            "month": str(state.get("month") or self._month_key()),
            "images_generated": int(state.get("images_generated") or 0),
            "spent_estimated_usd": float(state.get("spent_estimated_usd") or 0.0),
            "updated_at": self._now_iso(),
            "monthly_budget_usd": float(self.settings.instagram_openai_monthly_budget_usd),
            "estimated_cost_per_image_usd": float(self.settings.instagram_openai_image_estimated_cost_usd),
        }
        self._safe_write_json(self.openai_budget_path, payload)

    def _openai_budget_allows_one_more(self) -> tuple[bool, dict[str, Any], str | None]:
        budget = float(self.settings.instagram_openai_monthly_budget_usd)
        cost = float(self.settings.instagram_openai_image_estimated_cost_usd)
        state = self._load_openai_budget()

        if budget <= 0:
            self._append_openai_budget_event(
                {
                    "event": "budget_check",
                    "allowed": False,
                    "reason": "budget_disabled",
                    "month": state.get("month"),
                    "images_generated": int(state.get("images_generated") or 0),
                    "spent_estimated_usd": float(state.get("spent_estimated_usd") or 0.0),
                    "estimated_cost_per_image_usd": cost,
                    "monthly_budget_usd": budget,
                }
            )
            return False, state, "budget_disabled"
        if cost <= 0:
            self._append_openai_budget_event(
                {
                    "event": "budget_check",
                    "allowed": False,
                    "reason": "invalid_cost",
                    "month": state.get("month"),
                    "images_generated": int(state.get("images_generated") or 0),
                    "spent_estimated_usd": float(state.get("spent_estimated_usd") or 0.0),
                    "estimated_cost_per_image_usd": cost,
                    "monthly_budget_usd": budget,
                }
            )
            return False, state, "invalid_cost"

        current = float(state.get("spent_estimated_usd") or 0.0)
        if current + cost > budget + 1e-9:
            self._append_openai_budget_event(
                {
                    "event": "budget_check",
                    "allowed": False,
                    "reason": "budget_cap_reached",
                    "month": state.get("month"),
                    "images_generated": int(state.get("images_generated") or 0),
                    "spent_estimated_usd": current,
                    "estimated_cost_per_image_usd": cost,
                    "monthly_budget_usd": budget,
                }
            )
            return False, state, "budget_cap_reached"
        self._append_openai_budget_event(
            {
                "event": "budget_check",
                "allowed": True,
                "reason": "ok",
                "month": state.get("month"),
                "images_generated": int(state.get("images_generated") or 0),
                "spent_estimated_usd": current,
                "estimated_cost_per_image_usd": cost,
                "monthly_budget_usd": budget,
            }
        )
        return True, state, None

    def _consume_openai_budget(self, state: dict[str, Any]) -> None:
        cost = float(self.settings.instagram_openai_image_estimated_cost_usd)
        state["images_generated"] = int(state.get("images_generated") or 0) + 1
        state["spent_estimated_usd"] = round(float(state.get("spent_estimated_usd") or 0.0) + cost, 4)
        self._save_openai_budget(state)
        self._append_openai_budget_event(
            {
                "event": "budget_consume",
                "month": state.get("month"),
                "images_generated": int(state.get("images_generated") or 0),
                "spent_estimated_usd": float(state.get("spent_estimated_usd") or 0.0),
                "estimated_cost_per_image_usd": cost,
                "monthly_budget_usd": float(self.settings.instagram_openai_monthly_budget_usd),
            }
        )

    def _should_use_openai_this_cycle(self, state: dict[str, Any]) -> bool:
        # Production default: use OpenAI whenever budget/config allows.
        # Optional interleaving can be re-enabled via INSTAGRAM_OPENAI_USE_INTERLEAVING=true.
        if not bool(self.settings.instagram_openai_use_interleaving):
            return True
        return int(state.get("counter", 0)) % 2 == 0

    @staticmethod
    def _load_categories(path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            content = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:
            return {}
        if not isinstance(content, dict):
            return {}
        return content


    def _load_asset_overrides(self) -> dict[str, Any]:
        if not self.asset_overrides_path.exists():
            return {"overrides": [], "exclude": [], "flags": []}
        try:
            payload = yaml.safe_load(self.asset_overrides_path.read_text(encoding="utf-8")) or {}
        except Exception:
            return {"overrides": [], "exclude": [], "flags": []}
        if not isinstance(payload, dict):
            return {"overrides": [], "exclude": [], "flags": []}

        rows = []
        for row in payload.get("overrides") or []:
            if not isinstance(row, dict):
                continue
            pattern = str(row.get("pattern") or "").strip()
            category_id = str(row.get("category_id") or "").strip()
            if not pattern or not category_id:
                continue
            flags = row.get("flags") if isinstance(row.get("flags"), dict) else {}
            rows.append({"pattern": pattern, "category_id": category_id, "flags": flags})

        exclude = [str(x).strip() for x in (payload.get("exclude") or []) if str(x).strip()]
        return {"overrides": rows, "exclude": exclude, "flags": rows}

    def _apply_asset_override(self, rel_path: str, inferred_category_id: str, inferred_confidence: int) -> tuple[str, int, str, bool, dict[str, Any]]:
        rel_norm = str(rel_path or "").replace('\\', '/').strip('/')
        rules = self._load_asset_overrides()

        for pattern in rules.get("exclude") or []:
            if fnmatch.fnmatch(rel_norm.lower(), pattern.lower()):
                return inferred_category_id, inferred_confidence, "excluded", True, {}

        for row in rules.get("overrides") or []:
            pattern = str(row.get("pattern") or "")
            category_id = str(row.get("category_id") or "")
            if not pattern or not category_id:
                continue
            if fnmatch.fnmatch(rel_norm.lower(), pattern.lower()):
                flags = row.get("flags") if isinstance(row.get("flags"), dict) else {}
                return category_id, 100, "override", False, flags

        return inferred_category_id, inferred_confidence, "inferred", False, {}

    @staticmethod
    def _infer_asset_flags_from_path(rel_path: str, tags: list[str]) -> dict[str, Any]:
        rel = str(rel_path or "").lower()
        tag_tokens = {str(t).lower() for t in (tags or [])}
        has_qr = ("qr" in rel) or ("whatsapp" in rel) or ("qr" in tag_tokens)
        return {"has_qr": bool(has_qr)}

    def _category_pool_items(self, category_id: str) -> list[Any]:
        category = self._normalize_category_id(category_id)
        catalog = self._asset_catalog_map()
        rows = [
            item
            for item in self.asset_library.image_items
            if str((catalog.get(self._asset_key(item.path)) or {}).get("category_id") or "") == category
            and not bool((catalog.get(self._asset_key(item.path)) or {}).get("excluded"))
        ]
        rows.sort(key=lambda x: x.path.name.lower())
        return rows

    def _select_category_reference_asset(self, *, category_id: str) -> tuple[Any | None, dict[str, Any]]:
        items = self._category_pool_items(category_id)
        if not items:
            return None, {}
        catalog = self._asset_catalog_map()
        passable_items = [
            item
            for item in items
            if self._catalog_image_quality_passed(catalog.get(self._asset_key(item.path)) or {})
        ]
        if passable_items:
            items = passable_items
        normalized = self._normalize_category_id(category_id)
        cat = self.category_map.get(normalized) or {}
        hints = [str(x).strip().lower() for x in (cat.get("reference_asset_patterns") or []) if str(x).strip()]

        def _is_generated_name(path: Path) -> bool:
            low = path.name.lower()
            return low.startswith(("openai_", "ai_", "generated_")) or "_openai_" in low or "_ai_" in low

        def _rank(item: Any) -> tuple[int, int, int, int, str]:
            rel = self._asset_rel_path(item.path).lower()
            name = item.path.name.lower()

            exact = 0
            wildcard = 0
            if hints:
                exact = 1
                wildcard = 1
                for pat in hints:
                    if pat == name or pat == rel:
                        exact = 0
                    if fnmatch.fnmatch(name, pat) or fnmatch.fnmatch(rel, pat):
                        wildcard = 0

            generated_penalty = 1 if _is_generated_name(item.path) else 0
            ext_penalty = 0 if item.path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"} else 1
            return (exact, wildcard, generated_penalty, ext_penalty, name)

        chosen = sorted(items, key=_rank)[0]
        key = self._asset_key(chosen.path)
        rel = self._asset_rel_path(chosen.path)
        return chosen, {
            "asset_key": key,
            "asset_rel_path": rel,
            "asset_category_id": self._normalize_category_id(category_id),
            "asset_category_confidence": 100,
            "asset_has_qr": bool("qr" in rel.lower() or "whatsapp" in rel.lower()),
            "asset_rotation_pool": len(items),
            "asset_avoid_count": 0,
        }

    @staticmethod
    def _describe_reference_image(path: Path) -> str:
        try:
            with Image.open(path).convert("RGB") as img:
                width, height = img.size
                thumb = img.resize((96, 96))
                pixels = list(thumb.getdata())
                if not pixels:
                    return "reference style image"

                r = int(sum(p[0] for p in pixels) / len(pixels))
                g = int(sum(p[1] for p in pixels) / len(pixels))
                b = int(sum(p[2] for p in pixels) / len(pixels))
                mood = "bright" if (r + g + b) / 3 > 145 else "balanced" if (r + g + b) / 3 > 95 else "dramatic"
                orientation = "vertical" if height >= width else "horizontal"

                sat_values = [colorsys.rgb_to_hsv(px[0] / 255.0, px[1] / 255.0, px[2] / 255.0)[1] for px in pixels]
                sat_avg = sum(sat_values) / max(1, len(sat_values))
                sat_level = "high saturation" if sat_avg >= 0.55 else "medium saturation" if sat_avg >= 0.35 else "low saturation"

                lum = [int((0.299 * px[0]) + (0.587 * px[1]) + (0.114 * px[2])) for px in pixels]
                w = 96
                left = [lum[i] for i in range(len(lum)) if (i % w) < 32]
                mid = [lum[i] for i in range(len(lum)) if 32 <= (i % w) < 64]
                right = [lum[i] for i in range(len(lum)) if (i % w) >= 64]
                left_avg = int(sum(left) / max(1, len(left)))
                mid_avg = int(sum(mid) / max(1, len(mid)))
                right_avg = int(sum(right) / max(1, len(right)))
                light_map = {"left": left_avg, "center": mid_avg, "right": right_avg}
                safest_zone = sorted(light_map.items(), key=lambda kv: kv[1], reverse=True)[0][0]
                return (
                    f"Reference image characteristics: {orientation} composition, {width}x{height}, "
                    f"average palette rgb({r},{g},{b}), {mood} tone, {sat_level}, "
                    f"light distribution left/center/right={left_avg}/{mid_avg}/{right_avg}, "
                    f"best clean zone for text-safe negative space: {safest_zone}."
                )
        except Exception:
            return "Reference style image with professional social media framing."

    @staticmethod
    def _edge_margin_risk(path: Path) -> tuple[bool, dict[str, float]]:
        """
        Heuristic to detect:
        1) clipping risk on top/bottom text bands, and
        2) inset-card risk (large outer margins with content trapped in center).
        """
        try:
            with Image.open(path).convert("L") as img:
                w, h = img.size
                if w < 32 or h < 32:
                    return False, {"top": 0.0, "bottom": 0.0, "left": 0.0, "right": 0.0, "center": 0.0}

                edge = img.filter(ImageFilter.FIND_EDGES)
                band = max(8, int(h * 0.08))
                thin = max(2, int(h * 0.02))
                side_band = max(8, int(w * 0.08))
                side_thin = max(2, int(w * 0.02))
                center_top = int(h * 0.42)
                center_bottom = int(h * 0.58)

                top_box = edge.crop((0, 0, w, band))
                bottom_box = edge.crop((0, h - band, w, h))
                center_box = edge.crop((0, center_top, w, center_bottom))
                left_box = edge.crop((0, 0, side_band, h))
                right_box = edge.crop((w - side_band, 0, w, h))
                top_thin_edge = edge.crop((0, 0, w, thin))
                bottom_thin_edge = edge.crop((0, h - thin, w, h))
                left_thin_gray = img.crop((0, 0, side_thin, h))
                right_thin_gray = img.crop((w - side_thin, 0, w, h))
                top_thin_gray = img.crop((0, 0, w, thin))
                bottom_thin_gray = img.crop((0, h - thin, w, h))

                top_v = float(ImageStat.Stat(top_box).mean[0])
                bottom_v = float(ImageStat.Stat(bottom_box).mean[0])
                center_v = max(1.0, float(ImageStat.Stat(center_box).mean[0]))
                left_v = float(ImageStat.Stat(left_box).mean[0])
                right_v = float(ImageStat.Stat(right_box).mean[0])
                top_thin_v = float(ImageStat.Stat(top_thin_edge).mean[0])
                bottom_thin_v = float(ImageStat.Stat(bottom_thin_edge).mean[0])

                top_pixels = list(top_thin_gray.getdata())
                bottom_pixels = list(bottom_thin_gray.getdata())
                left_pixels = list(left_thin_gray.getdata())
                right_pixels = list(right_thin_gray.getdata())
                top_dark_pct = (sum(1 for v in top_pixels if v < 96) * 100.0) / max(1, len(top_pixels))
                bottom_dark_pct = (sum(1 for v in bottom_pixels if v < 96) * 100.0) / max(1, len(bottom_pixels))
                left_dark_pct = (sum(1 for v in left_pixels if v < 96) * 100.0) / max(1, len(left_pixels))
                right_dark_pct = (sum(1 for v in right_pixels if v < 96) * 100.0) / max(1, len(right_pixels))
                top_std = float(ImageStat.Stat(top_thin_gray).stddev[0])
                bottom_std = float(ImageStat.Stat(bottom_thin_gray).stddev[0])

                ratio_top = top_v / center_v
                ratio_bottom = bottom_v / center_v
                ratio_left = left_v / center_v
                ratio_right = right_v / center_v
                clip_top = (
                    (top_dark_pct >= 85.0 and top_thin_v >= center_v * 1.15)
                    or (top_dark_pct >= 95.0 and ratio_top >= 1.60)
                )
                clip_bottom = (
                    (bottom_dark_pct >= 85.0 and bottom_thin_v >= center_v * 1.15)
                    or (bottom_dark_pct >= 95.0 and ratio_bottom >= 1.60)
                )
                # Detects visual elements touching the very edge even when the band is not dark.
                touch_top = top_thin_v >= center_v * 1.10 and top_std >= 22.0
                touch_bottom = bottom_thin_v >= center_v * 1.10 and bottom_std >= 22.0
                # Keep ratio checks only for extreme cases to avoid false positives.
                extreme_edge = (ratio_top >= 2.20) or (ratio_bottom >= 2.20)
                inset_card = (
                    (ratio_top <= 0.42 and ratio_bottom <= 0.42 and ratio_left <= 0.42 and ratio_right <= 0.42)
                    or (top_dark_pct >= 72.0 and bottom_dark_pct >= 72.0 and left_dark_pct >= 72.0 and right_dark_pct >= 72.0)
                )
                risk = clip_top or clip_bottom or touch_top or touch_bottom or extreme_edge or inset_card
                return risk, {
                    "top": ratio_top,
                    "bottom": ratio_bottom,
                    "left": ratio_left,
                    "right": ratio_right,
                    "center": center_v,
                    "top_dark_pct": top_dark_pct,
                    "bottom_dark_pct": bottom_dark_pct,
                    "left_dark_pct": left_dark_pct,
                    "right_dark_pct": right_dark_pct,
                    "top_std": top_std,
                    "bottom_std": bottom_std,
                    "touch_top": 1.0 if touch_top else 0.0,
                    "touch_bottom": 1.0 if touch_bottom else 0.0,
                    "inset_card": 1.0 if inset_card else 0.0,
                }
        except Exception:
            return False, {"top": 0.0, "bottom": 0.0, "left": 0.0, "right": 0.0, "center": 0.0}

    def _music_library_tracks(self) -> list[Path]:
        tracks: list[Path] = []
        seen: set[str] = set()

        library_roots = [
            self.publish_assets_root,
            self.settings.instagram_music_library_root,
        ]
        for root in library_roots:
            if not root.exists():
                continue
            for p in root.rglob("*"):
                if not p.is_file() or not self._is_audio_path(p):
                    continue
                # Prefer explicit audios folder inside unified media library.
                if root == self.publish_assets_root and "audios" not in [x.lower() for x in p.parts]:
                    continue
                key = self._asset_key(p)
                if key in seen:
                    continue
                seen.add(key)
                tracks.append(p)

        tracks.sort(key=lambda x: x.name.lower())
        return tracks

    def _pick_music_library_track(self, *, seed: int) -> Path | None:
        tracks = self._music_library_tracks()
        if not tracks:
            return None
        forced = self._norm(self.settings.instagram_music_force_track or "")
        if forced:
            low = forced.lower()
            exact = [p for p in tracks if p.name.lower() == low]
            if exact:
                return exact[0]
            partial = [p for p in tracks if low in p.name.lower()]
            if partial:
                return partial[0]
        rng = random.Random(seed)
        return tracks[rng.randrange(0, len(tracks))]

    def _style_profile_for_category(self, category_id: str) -> str:
        cat = self.category_map.get((category_id or "").strip()) or {}
        template = cat.get("creative_template") if isinstance(cat.get("creative_template"), dict) else {}
        tone = ", ".join([str(x).strip() for x in (template.get("tone_keywords") or []) if str(x).strip()])
        if tone:
            return tone
        return "professional service scene with trusted specialist, conversion-oriented commercial look"

    def _render_openai_prompt(
        self,
        *,
        base_prompt: str,
        category_id: str,
        service: str,
        locale: str,
        objective: str,
        category: dict[str, Any] | None = None,
    ) -> str:
        template = (category or {}).get("creative_template") if isinstance((category or {}).get("creative_template"), dict) else {}
        style_hint = self._norm((category or {}).get("visual_brief") or "") or self._style_profile_for_category(category_id)
        category_context = self._norm((category or {}).get("category_context") or "")
        objective_hint = {
            "captar_clientes": "problem-solution emotion, urgency and trust for immediate contact",
            "captar_proveedores": "opportunity and growth, professionals wanting more clients",
            "branding": "strong brand recall, premium polished visual identity",
        }.get((objective or "").strip().lower(), "clear conversion-focused commercial message")

        tone_keywords = ", ".join([self._norm(x) for x in (template.get("tone_keywords") or []) if self._norm(x)])
        common_strengths = "; ".join([self._norm(x) for x in (template.get("common_strengths") or []) if self._norm(x)])
        composition_rules = "; ".join([self._norm(x) for x in (template.get("composition_rules") or []) if self._norm(x)])
        trust_cues = "; ".join([self._norm(x) for x in (template.get("trust_cues") or []) if self._norm(x)])
        differentiators = "; ".join([self._norm(x) for x in (template.get("differentiators") or []) if self._norm(x)])
        scene_anchors = "; ".join([self._norm(x) for x in (template.get("scene_anchors") or []) if self._norm(x)])
        signature_elements = "; ".join([self._norm(x) for x in (template.get("signature_elements") or []) if self._norm(x)])
        information_blocks = "; ".join([self._norm(x) for x in (template.get("information_blocks") or []) if self._norm(x)])
        text_hierarchy = "; ".join([self._norm(x) for x in (template.get("text_hierarchy") or []) if self._norm(x)])
        quality_checks = "; ".join([self._norm(x) for x in (template.get("category_quality_checks") or []) if self._norm(x)])
        finish_rules = "; ".join([self._norm(x) for x in (template.get("design_finish_rules") or []) if self._norm(x)])
        negative_rules = "; ".join([self._norm(x) for x in (template.get("negative_rules") or []) if self._norm(x)])
        poster_structure = "; ".join([self._norm(x) for x in (template.get("poster_structure") or []) if self._norm(x)])
        service_modules = [self._norm(x) for x in ((category or {}).get("service_modules") or []) if self._norm(x)]
        modules_text = "; ".join(service_modules)
        min_info_elements = int(template.get("min_info_elements") or 8)
        reference_policy = self._norm(template.get("reference_policy") or "")
        subject_profile = self._norm(template.get("subject_profile") or "")
        scene_profile = self._norm(template.get("scene_profile") or "")
        color_direction = self._norm(template.get("color_direction") or "")
        lighting_direction = self._norm(template.get("lighting_direction") or "")
        camera_direction = self._norm(template.get("camera_direction") or "")
        copy_structure = self._norm(template.get("copy_structure") or "")
        layout_density = self._norm(template.get("layout_density") or "")
        brand_name = self._norm(self.context.company_name or "ConectaProIA")
        website = self._norm(self.context.website_url or "https://conectaproia.cl")
        whatsapp_phone = self._extract_phone_from_url(self._resolve_whatsapp_url(objective)) or "+56983434503"

        return (
            f"{base_prompt} Service focus: {service}. Locale: {locale}. "
            f"Brand website context: {website}. "
            f"Category context: {category_context or 'professional service conversion content'}. "
            f"Visual direction: {style_hint}. Objective direction: {objective_hint}. "
            f"Category template subject profile: {subject_profile}. "
            f"Category template scene profile: {scene_profile}. "
            f"Category template color direction: {color_direction}. "
            f"Category template lighting direction: {lighting_direction}. "
            f"Category template camera direction: {camera_direction}. "
            f"Category template copy structure: {copy_structure}. "
            f"Category template information density: {layout_density}. "
            f"Category template tone keywords: {tone_keywords}. "
            f"Shared strengths to preserve: {common_strengths}. "
            f"Shared trust cues to preserve: {trust_cues}. "
            f"Composition blueprint: {composition_rules}. "
            f"Poster structure blueprint: {poster_structure}. "
            f"Category differentiators: {differentiators}. "
            f"Scene anchors for this category: {scene_anchors}. "
            f"Category signature design elements: {signature_elements}. "
            f"Information architecture to include: {information_blocks}. "
            f"Text hierarchy requirements: {text_hierarchy}. "
            f"Category quality checks: {quality_checks}. "
            f"Design finish rules: {finish_rules}. "
            f"Mandatory service modules to include as visible labels: {modules_text}. "
            f"Reference policy: {reference_policy}. "
            "Create a premium vertical 9:16 social ad image for Chilean audience, highly realistic and polished. "
            "Keep the hero subject in right or right-center area and preserve clean left-side structure for information blocks. "
            "The artwork must be edge-to-edge with no thick outer borders or empty color margins. "
            "Do not design a minimal poster: it must be information-rich, detailed, and commercial-ready like a finished agency ad. "
            "Use a complete ad-poster layout with clear hierarchy: main headline, subheading, benefit bullets/modules, location chip, and CTA band. "
            f"Include at least {min_info_elements} visible text elements distributed in structured blocks (not a single text cluster). "
            "Include at least two explicit specialty/service modules with rounded capsule style labels, and each module should have concise supporting bullets. "
            "Keep all critical branding/contact text inside a central safe area (at least 12% padding from edges). "
            "Never crop or place headline touching the top frame. Keep top safety margin >=12% and bottom safety margin >=12%. "
            "All visible text must be in Spanish only. Do not output prompt-like/meta text. "
            f"Embed visible branding elements inside the image design: brand text '{brand_name}', "
            f"WhatsApp number '{whatsapp_phone}', and website '{website}'. "
            "Include a coherent ConectaProIA-style logo lockup in blue/cyan tones integrated in the design. "
            "Use natural human expressions, correct anatomy, correct hands and tools, and commercial ad clarity. "
            f"Avoid strictly: {negative_rules}. "
            "Deliver a fresh visual concept variant, not a duplicate."
        )

    def _meta_media(self, limit: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        creds_ok = bool((self.settings.meta_access_token or "").strip() and (self.settings.meta_page_id or "").strip())
        if not creds_ok:
            return [], {"ok": False, "reason": "missing_meta_credentials"}
        try:
            client = MetaGraphClient(
                MetaCredentials(
                    app_id=self.settings.meta_app_id or "",
                    app_secret=self.settings.meta_app_secret or "",
                    access_token=self.settings.meta_access_token or "",
                    page_id=self.settings.meta_page_id or "",
                    instagram_user_id=self.settings.meta_instagram_user_id,
                    graph_version=self.settings.meta_graph_version,
                )
            )
            report = client.inspect_account(media_limit=limit)
            media = report.get("recent_media") or []
            return media, {
                "ok": True,
                "instagram_connected": bool(report.get("instagram_connected")),
                "instagram": report.get("instagram"),
                "capabilities": report.get("capabilities") or {},
                "scopes": report.get("scopes") or [],
            }
        except MetaConnectorError as exc:
            return [], {"ok": False, "reason": str(exc)}

    @staticmethod
    def _normalize_match_text(text: str) -> str:
        raw = str(text or "").strip().lower()
        if not raw:
            return ""
        norm = unicodedata.normalize("NFKD", raw)
        ascii_text = "".join(ch for ch in norm if not unicodedata.combining(ch))
        ascii_text = re.sub(r"[^a-z0-9\s]+", " ", ascii_text)
        ascii_text = re.sub(r"\s+", " ", ascii_text).strip()
        return ascii_text

    @staticmethod
    def _last_distance(seq: list[str], value: str) -> int | None:
        target = str(value or "").strip()
        if not target:
            return None
        for idx, item in enumerate(reversed(seq), start=1):
            if str(item or "").strip() == target:
                return idx
        return None

    @staticmethod
    def _weighted_choice_index(weights: list[float], *, rng: random.Random) -> int:
        safe = [max(0.0, float(w)) for w in (weights or [])]
        total = float(sum(safe))
        if total <= 0.0:
            return 0
        needle = rng.random() * total
        acc = 0.0
        for idx, weight in enumerate(safe):
            acc += weight
            if needle <= acc:
                return idx
        return len(safe) - 1

    def _infer_category_scored(self, text: str) -> tuple[str, float]:
        normalized_text = self._normalize_match_text(text)
        if not normalized_text:
            return "general", 0.0

        tokens = self._tokens_from_text(normalized_text)
        generic_tokens = {
            "conectaproia",
            "contacta",
            "contacto",
            "profesional",
            "profesionales",
            "servicio",
            "servicios",
            "clientes",
            "whatsapp",
            "hoy",
            "ahora",
            "minutos",
            "rapido",
            "rapida",
            "confiable",
            "confiables",
            "ayuda",
            "solicita",
            "solicitud",
        }

        best_id = "general"
        best_score = -1.0

        for cat in self.categories:
            cat_id = str(cat.get("id") or "").strip() or "general"
            score = 0.0

            def _accumulate(value: str, *, token_weight: float, phrase_weight: float) -> None:
                nonlocal score
                norm = self._normalize_match_text(value)
                if not norm:
                    return
                phrase = norm.strip()
                if len(phrase) >= 6 and phrase in normalized_text:
                    score += phrase_weight
                for tok in self._tokens_from_text(norm):
                    if tok in generic_tokens:
                        continue
                    if tok in tokens:
                        score += token_weight

            _accumulate(cat_id.replace("_", " "), token_weight=2.2, phrase_weight=2.8)
            _accumulate(str(cat.get("label") or ""), token_weight=2.1, phrase_weight=2.6)
            for kw in cat.get("keywords") or []:
                _accumulate(str(kw), token_weight=2.0, phrase_weight=2.4)
            for srv in cat.get("services") or []:
                _accumulate(str(srv), token_weight=2.4, phrase_weight=3.2)

            variants = cat.get("variants") if isinstance(cat.get("variants"), list) else []
            for variant in variants:
                if not isinstance(variant, dict):
                    continue
                _accumulate(str(variant.get("hook") or ""), token_weight=1.2, phrase_weight=1.8)
                _accumulate(str(variant.get("value") or ""), token_weight=0.9, phrase_weight=1.4)
                _accumulate(str(variant.get("proof") or ""), token_weight=0.7, phrase_weight=1.1)
                _accumulate(str(variant.get("cta") or ""), token_weight=0.6, phrase_weight=1.0)

            # Slightly penalize overly generic categories when legal/technical cues exist.
            if cat_id == "contacta_profesional":
                if any(t in tokens for t in {"abogado", "legal", "contrato", "asesoria", "electricista", "calefon"}):
                    score -= 1.8

            if score > best_score:
                best_score = score
                best_id = cat_id

        if best_score < 1.6:
            return "general", float(best_score)
        return best_id, float(best_score)

    def _infer_category(self, text: str) -> str:
        cat_id, _score = self._infer_category_scored(text)
        return cat_id

    def _extract_meta_media_ocr(self, item: dict[str, Any]) -> dict[str, Any]:
        media_type = str(item.get("media_type") or "").strip().upper()
        if media_type not in {"IMAGE", "CAROUSEL_ALBUM", "VIDEO"}:
            return {"engine": "none", "available": False, "lines": [], "tokens": [], "error": "unsupported_media_type"}

        media_url = str(item.get("media_url") or item.get("thumbnail_url") or "").strip()
        if not media_url:
            return {"engine": "none", "available": False, "lines": [], "tokens": [], "error": "missing_media_url"}

        tmp_path: Path | None = None
        try:
            req = Request(
                url=media_url,
                method="GET",
                headers={
                    "User-Agent": "Mozilla/5.0",
                },
            )
            with urlopen(req, timeout=20) as resp:
                raw = resp.read()
            if not raw:
                return {"engine": "none", "available": False, "lines": [], "tokens": [], "error": "empty_media_body"}

            with tempfile.NamedTemporaryFile(prefix="ig_meta_ocr_", suffix=".jpg", delete=False) as tmp:
                tmp.write(raw)
                tmp_path = Path(tmp.name)

            return self._extract_ocr_text(tmp_path)
        except Exception as exc:  # noqa: BLE001
            return {
                "engine": "none",
                "available": False,
                "lines": [],
                "tokens": [],
                "error": f"meta_ocr_fetch_failed:{type(exc).__name__}",
            }
        finally:
            try:
                if tmp_path is not None and tmp_path.exists():
                    tmp_path.unlink()
            except Exception:
                pass

    def _extract_hashtags(self, caption: str) -> list[str]:
        out: list[str] = []
        for raw in _HASHTAG_RE.findall(caption or ""):
            tag = self._slug(raw, fallback="").replace("-", "")
            if tag:
                out.append(tag)
        return out

    def _detect_contact_type(self, caption: str) -> str:
        low = caption.lower()
        if any(k in low for k in ["proveedor", "profesional", "agenda", "sumate", "unete"]):
            return "proveedores"
        return "clientes"

    def _extract_phone_candidates(self, text: str) -> list[str]:
        candidates: list[str] = []
        for p in _DIGITS_RE.findall(self._norm(text)):
            if len(p) >= 8:
                candidates.append(p)
        return candidates

    def build_publication_catalog(self, *, use_meta_history: bool = True) -> dict[str, Any]:
        media_limit = max(5, int(self.settings.instagram_recent_media_limit))
        media: list[dict[str, Any]] = []
        meta_status: dict[str, Any] = {"ok": False, "reason": "meta_skipped"}
        if use_meta_history:
            media, meta_status = self._meta_media(media_limit)

        local_drafts = self.list_drafts(limit=500, include_payload=True)
        category_counts_meta: dict[str, int] = {k: 0 for k in self.category_map}
        category_counts_local: dict[str, int] = {k: 0 for k in self.category_map}
        category_counts_combined: dict[str, int] = {k: 0 for k in self.category_map}

        hashtag_counts: dict[str, int] = {}
        phones_seen: dict[str, int] = {}
        recent_media: list[dict[str, Any]] = []

        ocr_scan_limit = min(8, len(media))
        for idx, item in enumerate(media):
            caption = str(item.get("caption") or "")
            category_id_caption, caption_score = self._infer_category_scored(caption)

            ocr = {"engine": "none", "available": False, "lines": [], "tokens": [], "error": "not_requested"}
            category_id = category_id_caption
            classifier_source = "caption"
            if idx < ocr_scan_limit and (category_id_caption == "general" or caption_score < 4.2):
                ocr = self._extract_meta_media_ocr(item if isinstance(item, dict) else {})
                ocr_lines = [str(x).strip() for x in (ocr.get("lines") or []) if str(x).strip()]
                if ocr_lines:
                    merged = f"{caption}\n" + "\n".join(ocr_lines[:4])
                    category_id_combined, combined_score = self._infer_category_scored(merged)
                    category_id = category_id_combined
                    classifier_source = "ocr_required_applied"
                    if category_id_combined == "general":
                        classifier_source = "ocr_required_unresolved"
                else:
                    category_id = "general"
                    if str(ocr.get("error") or "").strip():
                        classifier_source = "ocr_required_unavailable"
                    else:
                        classifier_source = "ocr_required_no_text"

            category_counts_meta[category_id] = category_counts_meta.get(category_id, 0) + 1
            for tag in self._extract_hashtags(caption):
                hashtag_counts[tag] = hashtag_counts.get(tag, 0) + 1
            for ph in self._extract_phone_candidates(caption):
                phones_seen[ph] = phones_seen.get(ph, 0) + 1
            recent_media.append(
                {
                    "id": item.get("id"),
                    "timestamp": item.get("timestamp"),
                    "media_type": item.get("media_type"),
                    "permalink": item.get("permalink"),
                    "category_id": category_id,
                    "category_id_caption": category_id_caption,
                    "category_classifier_source": classifier_source,
                    "contact_type": self._detect_contact_type(caption),
                    "caption_preview": caption[:260],
                    "ocr_available": bool(ocr.get("available", False)),
                    "ocr_engine": str(ocr.get("engine") or ""),
                    "ocr_error": str(ocr.get("error") or ""),
                    "ocr_line_preview": [str(x).strip() for x in (ocr.get("lines") or []) if str(x).strip()][:2],
                }
            )

        for item in local_drafts:
            cat = str(item.get("category_id") or "general")
            category_counts_local[cat] = int(category_counts_local.get(cat, 0)) + 1

        for cat_id in set(list(category_counts_meta.keys()) + list(category_counts_local.keys())):
            category_counts_combined[cat_id] = int(category_counts_meta.get(cat_id, 0)) + int(category_counts_local.get(cat_id, 0))

        ranked_categories = sorted(
            [
                {
                    "id": cat_id,
                    "label": (self.category_map.get(cat_id) or {}).get("label", cat_id),
                    "meta_count": int(category_counts_meta.get(cat_id, 0)),
                    "local_count": int(category_counts_local.get(cat_id, 0)),
                    "combined_count": int(category_counts_combined.get(cat_id, 0)),
                }
                for cat_id in self.category_map.keys()
            ],
            key=lambda x: (x["combined_count"], x["id"]),
        )

        catalog = {
            "generated_at": self._now_iso(),
            "meta": meta_status,
            "counts": {
                "meta": category_counts_meta,
                "local": category_counts_local,
                "combined": category_counts_combined,
            },
            "ranked_categories": ranked_categories,
            "top_hashtags": [k for k, _ in sorted(hashtag_counts.items(), key=lambda kv: kv[1], reverse=True)[:10]],
            "detected_phone_numbers": [k for k, _ in sorted(phones_seen.items(), key=lambda kv: kv[1], reverse=True)[:5]],
            "recent_media": recent_media,
        }

        self._safe_write_json(self.catalog_path, catalog)
        self.build_publication_plan(catalog=catalog)
        return catalog

    def _load_state(self) -> dict[str, Any]:
        state = self._safe_read_json(self.state_path, {})
        if not isinstance(state, dict):
            state = {}
        state.setdefault("counter", 0)
        state.setdefault("recent_categories", [])
        state.setdefault("recent_formats", [])
        state.setdefault("recent_assets", [])
        state.setdefault("recent_assets_by_category", {})
        state.setdefault("last_quality_sweep_at", "")
        state.setdefault("image_sequence_index", 0)
        return state

    def _save_state(self, state: dict[str, Any]) -> None:
        self._safe_write_json(self.state_path, state)

    def _sequential_image_pool(self) -> list[Any]:
        catalog = self._asset_catalog_map()
        rows = [
            item
            for item in self.asset_library.image_items
            if not bool((catalog.get(self._asset_key(item.path)) or {}).get("excluded"))
        ]
        return sorted(rows, key=lambda item: self._asset_rel_path(item.path).lower())

    def _next_sequential_image(self, state: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
        pool = self._sequential_image_pool()
        if not pool:
            raise GenerationError(f"No hay imagenes disponibles en {self.publish_assets_root}.")
        pool_keys = [self._asset_key(item.path) for item in pool]
        last_published_key = str(state.get("last_sequence_published_asset_key") or "").strip().lower()
        if last_published_key and last_published_key in pool_keys:
            index = (pool_keys.index(last_published_key) + 1) % len(pool)
        elif last_published_key:
            # The curated folder changed and the previous file no longer exists.
            # Restart from the first current file instead of skipping one.
            index = 0
        else:
            index = max(0, int(state.get("image_sequence_index", 0))) % len(pool)
        chosen = pool[index]
        catalog = self._asset_catalog_map()
        key = self._asset_key(chosen.path)
        meta = catalog.get(key) or {}
        flags = meta.get("flags") if isinstance(meta.get("flags"), dict) else {}
        return chosen, {
            "asset_key": key,
            "asset_rel_path": self._asset_rel_path(chosen.path),
            "asset_category_id": str(meta.get("category_id") or "general"),
            "asset_category_confidence": int(meta.get("category_confidence") or 0),
            "asset_has_qr": bool(flags.get("has_qr")),
            "asset_rotation_pool": len(pool),
            "asset_avoid_count": 0,
            "asset_sequence_index": index,
        }

    def _pick_category(self, *, catalog: dict[str, Any], state: dict[str, Any], objective: str | None, force_category: str | None) -> dict[str, Any]:
        # In a manually curated sequential library, the selected image is the source
        # of truth. Its inferred category must drive the caption, even during retries
        # or diagnostic calls that provide a forced category.
        if self.settings.instagram_sequential_image_library:
            _item, image_meta = self._next_sequential_image(state)
            inferred_id = self._normalize_category_id(str(image_meta.get("asset_category_id") or "general"))
            inferred = self.category_map.get(inferred_id)
            if inferred is not None:
                return inferred

        if force_category:
            forced = self.category_map.get(force_category)
            if forced is not None:
                return forced

        candidates = [cat for cat in self.categories if (not objective or str(cat.get("objective") or "") == objective)]
        if not candidates:
            candidates = list(self.categories)

        asset_catalog = self._safe_read_json(self.asset_catalog_path, {})
        counts_by_category = (asset_catalog.get("counts_by_category") or {}) if isinstance(asset_catalog, dict) else {}
        counts_by_category_quality_pass = (
            (asset_catalog.get("counts_by_category_quality_pass") or {}) if isinstance(asset_catalog, dict) else {}
        )
        ai_possible = bool(self.settings.instagram_enable_openai_images and self.openai_image_provider is not None)
        available = [
            cat
            for cat in candidates
            if bool(cat.get("force_qr", False))
            or int(counts_by_category_quality_pass.get(str(cat.get("id") or ""), 0)) > 0
            or int(counts_by_category.get(str(cat.get("id") or ""), 0)) > 0
            or ai_possible
        ]
        if available:
            candidates = available
        if not candidates:
            raise GenerationError("No hay categorias disponibles basadas en carpetas de publish_assets.")

        combined_counts = (catalog.get("counts") or {}).get("combined") or {}
        recent = [str(x).strip() for x in (state.get("recent_categories") or []) if str(x).strip()]
        rotate_window = int(self.defaults.get("rotate_window", 3) or 3)
        generated_cooldown = max(2, rotate_window)
        generated_block = set(recent[-generated_cooldown:])

        recent_meta_rows = catalog.get("recent_media") if isinstance(catalog.get("recent_media"), list) else []
        recent_meta_categories = [
            str(row.get("category_id") or "").strip()
            for row in recent_meta_rows
            if isinstance(row, dict) and str(row.get("category_id") or "").strip()
        ]
        meta_cooldown = max(2, min(6, generated_cooldown * 2))
        meta_block = set(recent_meta_categories[:meta_cooldown])

        counter = int(state.get("counter", 0))
        rng = random.Random(f"ig_category_v2:{counter}:{len(recent)}:{len(recent_meta_categories)}")

        rows: list[dict[str, Any]] = []
        for cat in candidates:
            cat_id = str(cat.get("id") or "general")
            count = int(combined_counts.get(cat_id, 0))
            dist_generated = self._last_distance(recent, cat_id)
            dist_meta = self._last_distance(list(reversed(recent_meta_categories)), cat_id)

            # Base exploration: underused categories get more probability mass.
            weight = 1.0 / max(1.0, float(count + 1))

            if dist_generated is not None:
                if dist_generated <= 1:
                    weight *= 0.02
                elif dist_generated <= 2:
                    weight *= 0.12
                elif dist_generated <= 3:
                    weight *= 0.28
                elif dist_generated <= 5:
                    weight *= 0.55

            if dist_meta is not None:
                if dist_meta <= 1:
                    weight *= 0.10
                elif dist_meta <= 2:
                    weight *= 0.25
                elif dist_meta <= 4:
                    weight *= 0.55

            rows.append(
                {
                    "cat": cat,
                    "cat_id": cat_id,
                    "count": count,
                    "weight": max(0.0, float(weight)),
                    "blocked_generated": cat_id in generated_block,
                    "blocked_meta": cat_id in meta_block,
                }
            )

        # Strict diversity gate: avoid immediate repeats from both local run state and recent Meta posts.
        strict = [r for r in rows if not r["blocked_generated"] and not r["blocked_meta"]]
        if strict:
            rows = strict
        else:
            no_generated = [r for r in rows if not r["blocked_generated"]]
            if no_generated:
                rows = no_generated

        rows.sort(key=lambda r: (r["count"], r["cat_id"]))
        weights = [float(r["weight"]) for r in rows]
        pick_index = self._weighted_choice_index(weights, rng=rng)
        return rows[pick_index]["cat"]

    def _pick_format(self, state: dict[str, Any]) -> str:
        if self.settings.instagram_sequential_image_library:
            weekday_schedule = ["feed", "story", "feed", "story", "feed"]
            local_weekday = datetime.now().weekday()
            if 0 <= local_weekday < len(weekday_schedule):
                return weekday_schedule[local_weekday]
        cycle = [str(x).strip().lower() for x in (self.defaults.get("format_cycle") or ["reel", "story", "feed"]) if str(x).strip()]
        if not cycle:
            cycle = ["reel", "story", "feed"]
        return cycle[int(state.get("counter", 0)) % len(cycle)]

    def _pick_variant(self, category: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
        variants = category.get("variants") or []
        if not variants:
            raise GenerationError(f"Category has no variants: {category.get('id')}")
        idx = int(state.get("counter", 0)) % len(variants)
        chosen = variants[idx]
        if not isinstance(chosen, dict):
            raise GenerationError(f"Invalid variant config in category: {category.get('id')}")
        return chosen

    def _pick_service(self, category: dict[str, Any], state: dict[str, Any]) -> str:
        services = [self._norm(x) for x in (category.get("services") or []) if self._norm(x)]
        if not services:
            return str(category.get("label") or "servicio profesional")
        return services[int(state.get("counter", 0)) % len(services)]

    def _pick_locale(self, state: dict[str, Any]) -> str:
        locales = [self._norm(x) for x in (self.defaults.get("locale_cycle") or []) if self._norm(x)]
        if not locales:
            return "Chile"
        return locales[int(state.get("counter", 0)) % len(locales)]

    def _coverage_text(self) -> str:
        zones = [self._norm(x) for x in (self.defaults.get("coverage_zones") or []) if self._norm(x)]
        if not zones:
            zones = ["Concepción", "Talcahuano", "Hualpén"]
        if len(zones) == 1:
            return f"Cobertura: {zones[0]}"
        if len(zones) == 2:
            return f"Cobertura: {zones[0]} y {zones[1]}"
        head = ", ".join(zones[:-1])
        return f"Cobertura: {head} y {zones[-1]}"

    @staticmethod
    def _clip(text: str, max_chars: int) -> str:
        value = " ".join(str(text or "").split()).strip()
        if len(value) <= max_chars:
            return value
        out = value[: max_chars - 1].rstrip()
        if " " in out:
            out = out.rsplit(" ", 1)[0]
        return out + "..."

    def _resolve_whatsapp_url(self, objective: str) -> str:
        if objective == "captar_proveedores":
            return normalize_whatsapp_click_url(
                self.settings.instagram_whatsapp_provider_url
                or self.settings.instagram_whatsapp_client_url
                or self.context.whatsapp_url
                or "",
                fallback_phone=DEFAULT_PROVIDER_PHONE,
            )
        return normalize_whatsapp_click_url(
            self.settings.instagram_whatsapp_client_url
            or self.context.whatsapp_url
            or "",
            fallback_phone=DEFAULT_CLIENT_PHONE,
        )

    @staticmethod
    def _extract_phone_from_url(url: str) -> str:
        return extract_whatsapp_phone(url)

    def _safe_font(self, size: int) -> ImageFont.ImageFont:
        candidates = [
            r"C:\Windows\Fonts\segoeui.ttf",
            r"C:\Windows\Fonts\arial.ttf",
        ]
        for p in candidates:
            if Path(p).exists():
                try:
                    return ImageFont.truetype(p, size=size)
                except Exception:
                    continue
        return ImageFont.load_default()

    def _select_logo_path(self) -> Path | None:
        candidate_paths = [Path(candidate) for candidate in self.context.logo_candidates]
        assets_root = Path(os.getenv("ASSETS_ROOT", "assets"))
        candidate_paths.extend(
            [
                assets_root / "conectaprologo_512.png",
                assets_root / "conectaprologo.png",
                Path("assets/conectaprologo_512.png"),
                Path("/app/assets/conectaprologo_512.png"),
            ]
        )
        for p in candidate_paths:
            if p.exists() and p.is_file():
                return p
        # Fallback: auto-detect ConectaPro logos in default assets folder.
        fallback_dir = Path(r"C:\Franco\conectapro_rrss")
        if fallback_dir.exists():
            candidates = sorted(
                [
                    p
                    for p in fallback_dir.glob("conectaprologo*")
                    if p.is_file() and p.suffix.lower() in {".png", ".jpg", ".jpeg"}
                ],
                key=lambda p: (0 if p.suffix.lower() == ".png" else 1, 0 if "512" in p.name else 1, p.name.lower()),
            )
            if candidates:
                return candidates[0]
        return None

    def _resolve_qr_path(self, objective: str) -> Path | None:
        if objective == "captar_proveedores" and self.context.whatsapp_qr_provider_path:
            p = Path(self.context.whatsapp_qr_provider_path)
            if p.exists():
                return p
        if self.context.whatsapp_qr_path:
            p = Path(self.context.whatsapp_qr_path)
            if p.exists():
                return p
        return None

    @staticmethod
    def _paste_qr_badge(overlay: Image.Image, qr: Image.Image, x: int, y: int) -> None:
        pad = 14
        badge_w = qr.width + pad * 2
        badge_h = qr.height + pad * 2
        layer = Image.new("RGBA", overlay.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        # Soft shadow.
        draw.rounded_rectangle(
            [x + 4, y + 6, x + badge_w + 4, y + badge_h + 6],
            radius=22,
            fill=(0, 0, 0, 120),
        )
        # Clean badge container.
        draw.rounded_rectangle(
            [x, y, x + badge_w, y + badge_h],
            radius=22,
            fill=(255, 255, 255, 242),
            outline=(7, 32, 72, 210),
            width=2,
        )
        layer.alpha_composite(qr.convert("RGBA"), (x + pad, y + pad))
        merged = Image.alpha_composite(overlay, layer)
        overlay.paste(merged)

    @staticmethod
    def _target_dimensions(format_type: str) -> tuple[int, int]:
        if format_type == "feed":
            return 1080, 1350
        return 1080, 1920

    @staticmethod
    def _contain_with_soft_background(
        image: Image.Image,
        target_size: tuple[int, int],
        *,
        safe_scale: float = 1.0,
    ) -> Image.Image:
        """
        Preserve full source image (no crop) and fill remaining area with soft blurred background.
        Prevents clipping while avoiding hard bars and stretch artifacts.
        """
        width, height = target_size
        scale = min(1.0, max(0.85, float(safe_scale)))
        safe_width = max(1, int(width * scale))
        safe_height = max(1, int(height * scale))
        fg = ImageOps.contain(image, (safe_width, safe_height), method=Image.Resampling.LANCZOS)
        bg = ImageOps.fit(image, (width, height), method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))
        bg = bg.filter(ImageFilter.GaussianBlur(radius=30))
        canvas = bg.convert("RGB")

        x = (width - fg.width) // 2
        y = (height - fg.height) // 2
        canvas.paste(fg, (x, y))
        return canvas

    def _apply_branding_overlay(
        self,
        *,
        base_image: Path,
        output_path: Path,
        objective: str,
        format_type: str,
        overlay_text: str | None = None,
        asset_has_qr: bool = False,
        image_source: str = "",
    ) -> Path:
        width, height = self._target_dimensions(format_type)
        logo_path = self._select_logo_path()
        qr_overlay_enabled = bool(self.settings.instagram_qr_overlay_enabled)
        short_text_overlay_enabled = bool(self.settings.instagram_overlay_short_text_enabled)

        if self.settings.instagram_branding_required and not logo_path:
            raise GenerationError("No se encontro logo para branding de publicaciones IG")

        phone_label = "Clientes" if objective != "captar_proveedores" else "Proveedores"
        whatsapp_url = self._resolve_whatsapp_url(objective)
        phone = self._extract_phone_from_url(whatsapp_url)
        coverage_line = self._coverage_text()

        if self.settings.instagram_branding_required and not phone:
            raise GenerationError("No se pudo resolver numero de WhatsApp para branding IG")

        img = Image.open(base_image).convert("RGB")
        source_norm = str(image_source or "").strip().lower()
        ai_embedded_branding = source_norm == "openai_image"

        overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        title_font = self._safe_font(44)
        body_font = self._safe_font(34)
        small_font = self._safe_font(28)
        top_bar_h = int(height * 0.09)
        footer_h: int | None = None
        phone_line = phone or whatsapp_url
        website_line = self.context.website_url or "https://conectaproia.cl"

        if format_type == "story":
            if ai_embedded_branding:
                # Preserve complete generated ad (including logo/phone/footer copy)
                # to avoid clipping on left/right edges.
                canvas = self._contain_with_soft_background(img, (width, height))
            else:
                # Non-AI sources use full-bleed soft background to avoid inset-card quality penalties.
                canvas = self._contain_with_soft_background(img, (width, height))
        else:
            if ai_embedded_branding:
                canvas = self._contain_with_soft_background(img, (width, height))
            else:
                # Feed uses full-bleed soft background to reduce edge-risk false negatives.
                footer_padding_y = 18
                line_gap = 8
                phone_label_line = f"WhatsApp {phone_label}"

                lbl_h = draw.textbbox((0, 0), phone_label_line, font=small_font)[3]
                phone_h = draw.textbbox((0, 0), phone_line, font=body_font)[3]
                cov_h = draw.textbbox((0, 0), coverage_line, font=small_font)[3]
                web_h = draw.textbbox((0, 0), website_line, font=small_font)[3]

                qr_path = self._resolve_qr_path(objective)
                qr_size = int(width * 0.12) if qr_path and (not asset_has_qr) else 0
                text_block_h = lbl_h + phone_h + cov_h + web_h + line_gap * 3
                footer_h = max(int(height * 0.18), text_block_h + footer_padding_y * 2, qr_size + footer_padding_y * 2)
                canvas = self._contain_with_soft_background(img, (width, height))

        if format_type == "story":
            # Story mode: safe-area layout + minimal pop-up badge.
            # No text overlays in story to avoid covering base art.
            qr_path = self._resolve_qr_path(objective)
            if (
                qr_overlay_enabled
                and (not ai_embedded_branding)
                and qr_path
                and (not asset_has_qr)
                and ("qr" not in base_image.stem.lower())
            ):
                qr = Image.open(qr_path).convert("RGBA")
                qr_size = int(width * 0.25)
                qr = ImageOps.contain(qr, (qr_size, qr_size))
                qr_x = width - qr.width - 36
                qr_y = height - qr.height - 36
                self._paste_qr_badge(overlay, qr, qr_x, qr_y)
        else:
            # Feed: no extra text overlays (base art already includes WhatsApp/text).
            qr_path = self._resolve_qr_path(objective)
            if (
                qr_overlay_enabled
                and (not ai_embedded_branding)
                and qr_path
                and (not asset_has_qr)
                and ("qr" not in base_image.stem.lower())
            ):
                qr = Image.open(qr_path).convert("RGBA")
                qr_size = int(width * 0.25)
                qr = ImageOps.contain(qr, (qr_size, qr_size))
                qr_x = width - qr.width - 36
                qr_y = height - qr.height - 36
                self._paste_qr_badge(overlay, qr, qr_x, qr_y)

        overlay_line = (
            self._clip(self._norm(overlay_text or ""), 92)
            if ((not ai_embedded_branding) and short_text_overlay_enabled)
            else ""
        )
        if overlay_line:
            text_font = self._safe_font(40 if format_type == "story" else 30)
            text_bbox = draw.textbbox((0, 0), overlay_line, font=text_font)
            text_w = int(text_bbox[2] - text_bbox[0])
            text_h = int(text_bbox[3] - text_bbox[1])
            pad_x = 20
            pad_y = 14
            box_w = min(width - 40, text_w + pad_x * 2)
            x = (width - box_w) // 2
            y = int(height * (0.79 if format_type == "story" else 0.07))
            draw.rounded_rectangle(
                [x, y, x + box_w, y + text_h + pad_y * 2],
                radius=20,
                fill=(6, 18, 45, 190),
                outline=(91, 192, 190, 220),
                width=2,
            )
            tx = x + (box_w - text_w) // 2
            ty = y + pad_y
            draw.text((tx, ty), overlay_line, font=text_font, fill=(240, 249, 255, 255))

        merged = Image.alpha_composite(canvas.convert("RGBA"), overlay)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        merged.convert("RGB").save(output_path, format="JPEG", quality=94)
        return output_path
    def _build_qr_card(self, *, output_path: Path, objective: str, format_type: str) -> Path:
        qr_source = Path(self.context.whatsapp_qr_path) if self.context.whatsapp_qr_path else None
        if qr_source is None or not qr_source.exists():
            raise GenerationError("No existe QR configurado para tarjeta de cierre")

        width, height = self._target_dimensions(format_type)
        canvas = Image.new("RGB", (width, height), color=(11, 19, 43))
        draw = ImageDraw.Draw(canvas)

        logo_path = self._select_logo_path()
        if logo_path and logo_path.exists():
            logo = Image.open(logo_path).convert("RGBA")
            logo = ImageOps.contain(logo, (220, 220))
            canvas.paste(logo, (width // 2 - logo.width // 2, 80), logo)

        qr = Image.open(qr_source).convert("RGBA")
        qr = ImageOps.contain(qr, (int(width * 0.68), int(width * 0.68)))
        canvas.paste(qr, (width // 2 - qr.width // 2, height // 2 - qr.height // 2), qr)

        title_font = self._safe_font(66)
        body_font = self._safe_font(34)
        phone = self._extract_phone_from_url(self._resolve_whatsapp_url(objective))

        draw.text((width // 2, int(height * 0.72)), "Conecta YA", font=title_font, fill=(91, 192, 190), anchor="mm")
        draw.text((width // 2, int(height * 0.78)), "Escanea y habla por WhatsApp", font=body_font, fill=(240, 249, 255), anchor="mm")
        if phone:
            draw.text((width // 2, int(height * 0.83)), phone, font=body_font, fill=(240, 249, 255), anchor="mm")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        canvas.save(output_path, format="JPEG", quality=95)
        return output_path

    def _build_copy(self, *, category: dict[str, Any], variant: dict[str, Any], service: str, locale: str, format_type: str, objective: str, catalog: dict[str, Any]) -> dict[str, Any]:
        whatsapp_url = self._resolve_whatsapp_url(objective)
        whatsapp_phone = self._extract_phone_from_url(whatsapp_url)
        website = self.context.website_url or "https://conectaproia.cl"
        coverage_text = self._coverage_text()

        hook = self._norm(variant.get("hook") or "Necesitas ayuda profesional hoy?")
        value = self._norm(variant.get("value") or "ConectaProIA te conecta por WhatsApp con profesionales confiables.")
        proof = self._norm(variant.get("proof") or "Proceso claro, rapido y sin friccion.")
        cta = self._norm(variant.get("cta") or "Escribenos ahora.")
        short_text = self._norm(variant.get("short_text") or hook)

        if format_type == "story":
            short_text = self._clip(short_text, self.settings.instagram_short_text_max_chars)
        elif format_type == "reel":
            short_text = self._clip(short_text, max(36, self.settings.instagram_short_text_max_chars - 8))

        hashtags = [str(x).strip() for x in (self.defaults.get("hashtags_base") or []) if str(x).strip()]
        hashtags.extend([str(x).strip() for x in (category.get("hashtags") or []) if str(x).strip()])
        hashtags.extend([str(x).strip() for x in (catalog.get("top_hashtags") or []) if str(x).strip()][:3])

        clean_tags: list[str] = []
        seen: set[str] = set()
        for tag in hashtags:
            key = self._slug(tag, fallback="").replace("-", "")
            if key and key not in seen:
                seen.add(key)
                clean_tags.append(f"#{key}")

        caption = "\n".join(
            [
                hook,
                value,
                proof,
                cta,
                f"Servicio: {service} | Zona: {locale}",
                coverage_text,
                f"WhatsApp: {whatsapp_phone or whatsapp_url}",
                f"Link directo: {whatsapp_url}",
                f"Web: {website}",
                " ".join(clean_tags[:8]),
            ]
        ).strip()

        return {
            "hook": hook,
            "value": value,
            "proof": proof,
            "cta": cta,
            "short_text": short_text,
            "caption": caption,
            "hashtags": clean_tags[:12],
            "service": service,
            "locale": locale,
            "objective": objective,
            "whatsapp_url": whatsapp_url,
            "whatsapp_phone": whatsapp_phone,
        }

    def _generate_base_image(
        self,
        *,
        category: dict[str, Any],
        variant: dict[str, Any],
        service: str,
        locale: str,
        draft_dir: Path,
        state: dict[str, Any],
        objective: str,
        format_type: str,
    ) -> tuple[Path, str, str, dict[str, Any]]:
        category_id = str(category.get("id") or "general")
        if bool(category.get("force_qr", False)):
            out = draft_dir / "qr_card.jpg"
            self._build_qr_card(output_path=out, objective=objective, format_type="story")
            return out, "qr_card", "qr_generated", {
                "asset_key": "",
                "asset_rel_path": "",
                "asset_category_id": category_id,
                "asset_category_confidence": 100,
                "asset_rotation_pool": 1,
                "asset_avoid_count": 0,
            }

        # Folder-driven rule: each category uses its example image as visual reference.
        reference_asset, reference_meta = self._select_category_reference_asset(category_id=category_id)
        reference_prompt = ""
        if reference_asset is not None:
            reference_prompt = self._describe_reference_image(reference_asset.path)

        query = " ".join([
            str(category.get("label") or ""),
            service,
            locale,
            str(variant.get("hook") or ""),
            str(variant.get("value") or ""),
        ]).strip()

        prompt_templates = [self._norm(x) for x in (category.get("image_prompt_templates") or []) if self._norm(x)]
        if not prompt_templates:
            prompt_templates = ["Vertical 9:16 photorealistic marketing ad image for ConectaProIA with integrated Spanish copy blocks."]
        prompt = prompt_templates[int(state.get("counter", 0)) % len(prompt_templates)]

        if self.settings.instagram_enable_openai_images:
            allow_library_fallback = bool(self.settings.instagram_ai_library_fallback_enabled)
            if self.openai_image_provider is None:
                if self.settings.instagram_require_ai_image and not allow_library_fallback:
                    raise GenerationError("OPENAI_API_KEY requerida: modo IG exige imagen IA generada")
                prompt = f"{prompt} | openai_skipped=provider_unavailable"
            else:
                rendered_prompt = self._render_openai_prompt(
                    base_prompt=prompt,
                    category_id=category_id,
                    service=service,
                    locale=locale,
                    objective=objective,
                    category=category,
                )
                if reference_asset is not None:
                    rendered_prompt = (
                        f"{rendered_prompt} Create a NEW image inspired by category reference '{reference_meta.get('asset_rel_path')}'. "
                        f"{reference_prompt} Keep the same style direction but do not replicate the exact composition."
                    )

                use_openai_cycle = True if reference_asset is not None else self._should_use_openai_this_cycle(state)
                budget_ok, budget_state, budget_reason = self._openai_budget_allows_one_more()

                if use_openai_cycle and budget_ok:
                    prompt_attempt = rendered_prompt
                    attempts = max(1, min(3, int(self.settings.instagram_openai_max_generation_attempts or 1)))
                    for attempt in range(attempts):
                        if attempt > 0:
                            budget_ok_retry, budget_state, _ = self._openai_budget_allows_one_more()
                            if not budget_ok_retry:
                                break

                        out = self._new_generated_pool_path(category_id=category_id, prefix="openai")
                        try:
                            self.openai_image_provider.generate_image(prompt_attempt, out)
                            self._consume_openai_budget(budget_state)

                            quality_report = self._validate_ig_image(
                                image_path=out,
                                image_source="openai_image",
                                format_type=format_type,
                            )
                            quality_warning = ""
                            if int(quality_report.get("score") or 0) < int(self.settings.instagram_publish_quality_min_score):
                                if attempt < attempts - 1:
                                    prompt_attempt = (
                                        f"{rendered_prompt} Critical correction: keep all headline/footer blocks fully visible "
                                        "with generous top and bottom margins. No text touching edges. No clipping. "
                                        "Use full-bleed edge-to-edge composition, no inner framed card, no thick outer bars."
                                    )
                                    continue
                                quality_warning = "quality_warning_detected_after_retries"

                            key = self._asset_key(out)
                            rel = self._asset_rel_path(out)
                            return out, "openai_image", prompt_attempt, {
                                "asset_key": key,
                                "asset_rel_path": rel,
                                "asset_category_id": category_id,
                                "asset_category_confidence": 100,
                                "asset_rotation_pool": 1,
                                "asset_avoid_count": 0,
                                "asset_quality_warning": quality_warning,
                                "asset_quality_score": int(quality_report.get("score") or 0),
                            }
                        except Exception as exc:  # noqa: BLE001
                            if self.settings.instagram_require_ai_image and (not allow_library_fallback) and attempt == attempts - 1:
                                raise GenerationError(f"Generacion IA obligatoria fallo: {exc}") from exc
                elif use_openai_cycle and not budget_ok:
                    if self.settings.instagram_require_ai_image and not allow_library_fallback:
                        raise GenerationError(
                            f"Generacion IA obligatoria bloqueada por presupuesto/configuracion: {budget_reason}"
                        )
                    prompt = f"{prompt} | openai_skipped={budget_reason}"
                else:
                    prompt = f"{prompt} | openai_skipped=interleaved_local_cycle"

        # Local fallback should rotate through category pool first.
        # Use reference asset only as a last-resort backup if pool selection fails.
        try:
            selected_asset, asset_meta = self._select_library_asset(query=query, category_id=category_id, state=state)
            out = draft_dir / f"image_lib{selected_asset.path.suffix.lower() or '.jpg'}"
            shutil.copy2(selected_asset.path, out)
            return out, "asset_library", query, asset_meta
        except Exception:
            if reference_asset is not None:
                out = draft_dir / f"image_ref{reference_asset.path.suffix.lower() or '.jpg'}"
                shutil.copy2(reference_asset.path, out)
                return out, "category_template", f"category_template:{category_id}", reference_meta
            raise

    def _generate_image(
        self,
        *,
        category: dict[str, Any],
        variant: dict[str, Any],
        service: str,
        locale: str,
        draft_dir: Path,
        state: dict[str, Any],
        objective: str,
        format_type: str,
        ) -> tuple[Path, str, str, dict[str, Any]]:
        base, source, prompt, source_meta = self._generate_base_image(
            category=category,
            variant=variant,
            service=service,
            locale=locale,
            draft_dir=draft_dir,
            state=state,
            objective=objective,
            format_type=format_type,
        )
        branded = draft_dir / "image.jpg"
        source_meta = dict(source_meta or {})
        source_meta["base_image_path"] = str(base)
        self._apply_branding_overlay(
            base_image=base,
            output_path=branded,
            objective=objective,
            format_type=format_type,
            overlay_text=str(variant.get("short_text") or ""),
            asset_has_qr=bool(source_meta.get("asset_has_qr")),
            image_source=source,
        )
        return branded, source, prompt, source_meta

    def _objective_cycle(self) -> list[str]:
        cycle = [str(x).strip().lower() for x in (self.defaults.get("objective_cycle") or []) if str(x).strip()]
        valid = [x for x in cycle if x in {"captar_clientes", "captar_proveedores", "branding"}]
        if valid:
            return valid
        return ["captar_clientes", "captar_clientes", "captar_proveedores", "branding"]

    def build_publication_plan(self, *, catalog: dict[str, Any] | None = None, horizon_hours: int | None = None) -> dict[str, Any]:
        if catalog is None:
            catalog = self._safe_read_json(self.catalog_path, {})
            if not isinstance(catalog, dict):
                catalog = {}

        hours = int(horizon_hours or self.settings.instagram_plan_horizon_hours)
        interval = max(15, int(self.settings.instagram_post_interval_minutes))
        slots = max(1, int((hours * 60) / interval))

        state = self._load_state()
        base_counter = int(state.get("counter", 0))
        simulated_recent = list(state.get("recent_categories") or [])[-8:]
        objective_cycle = self._objective_cycle()
        now = datetime.now(timezone.utc)

        items: list[dict[str, Any]] = []
        for i in range(slots):
            c = base_counter + i
            objective = objective_cycle[c % len(objective_cycle)]
            category = self._pick_category(catalog=catalog, state={"counter": c, "recent_categories": simulated_recent}, objective=objective, force_category=None)
            variant = self._pick_variant(category, {"counter": c})
            service = self._pick_service(category, {"counter": c})
            locale = self._pick_locale({"counter": c})
            format_type = self._pick_format({"counter": c})
            items.append(
                {
                    "order": i + 1,
                    "scheduled_at": (now + timedelta(minutes=interval * i)).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                    "objective": objective,
                    "category_id": category.get("id"),
                    "category_label": category.get("label"),
                    "format_type": format_type,
                    "service": service,
                    "locale": locale,
                    "context": {
                        "hook": self._norm(variant.get("hook") or ""),
                        "value": self._norm(variant.get("value") or ""),
                        "proof": self._norm(variant.get("proof") or ""),
                        "cta": self._norm(variant.get("cta") or ""),
                    },
                    "whatsapp_url": self._resolve_whatsapp_url(objective),
                }
            )
            simulated_recent.append(str(category.get("id") or "general"))
            simulated_recent = simulated_recent[-12:]

        plan = {
            "generated_at": self._now_iso(),
            "interval_minutes": interval,
            "horizon_hours": hours,
            "slots": slots,
            "items": items,
        }
        self._safe_write_json(self.plan_path, plan)
        return plan

    def _to_generated_url(self, path: Path | None) -> str | None:
        if path is None:
            return None
        try:
            rel = path.resolve().relative_to(self.settings.output_root.resolve())
        except Exception:
            return None
        return f"/generated/{rel.as_posix()}"

    def _to_web_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        out = dict(payload)
        image_path = Path(str(payload.get("image_path") or "")) if payload.get("image_path") else None
        video_path = Path(str(payload.get("video_path") or "")) if payload.get("video_path") else None
        draft_dir = Path(str(payload.get("draft_dir") or "")) if payload.get("draft_dir") else None
        out["image_url"] = self._to_generated_url(image_path)
        out["video_url"] = self._to_generated_url(video_path)
        out["draft_dir_url"] = self._to_generated_url(draft_dir) if draft_dir else None
        out["caption_preview"] = self._clip(str(payload.get("caption") or ""), 240)
        out["short_text_preview"] = self._clip(str(payload.get("short_text") or ""), 120)
        return out

    def _render_publish_image_variant(
        self,
        *,
        source_path: Path,
        output_path: Path,
        target_size: tuple[int, int],
    ) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if output_path.exists():
            try:
                src_mtime = int(source_path.stat().st_mtime_ns)
                out_mtime = int(output_path.stat().st_mtime_ns)
                with Image.open(output_path) as existing:
                    if existing.size == target_size and out_mtime >= src_mtime:
                        return output_path
            except Exception:
                pass

        with Image.open(source_path).convert("RGB") as source:
            source_ratio = float(source.size[0]) / float(max(1, source.size[1]))
            target_ratio = float(target_size[0]) / float(max(1, target_size[1]))
            source_edge_risk, _edge_meta = self._edge_margin_risk(source_path)
            needs_safe_inset = bool(source_edge_risk and abs(source_ratio - target_ratio) <= 0.03)
            if source.size == target_size and not needs_safe_inset:
                shutil.copy2(source_path, output_path)
            else:
                rendered = self._contain_with_soft_background(
                    source,
                    target_size,
                    safe_scale=0.96 if needs_safe_inset else 1.0,
                )
                rendered.save(output_path, format="JPEG", quality=95)
        return output_path

    def ensure_publish_image_variants(self, *, draft: dict[str, Any]) -> dict[str, Any]:
        image_path = Path(str(draft.get("image_path") or "")).resolve()
        if not image_path.exists():
            raise GenerationError(f"Imagen base de draft no encontrada para variantes de publicacion: {image_path}")

        base_image_path_raw = str(draft.get("base_image_path") or "").strip()
        asset_key_raw = str(draft.get("asset_key") or "").strip()
        variant_source_path = image_path
        for candidate_raw in (base_image_path_raw, asset_key_raw):
            if not candidate_raw:
                continue
            candidate = Path(candidate_raw).resolve()
            if candidate.exists() and candidate.is_file() and self._is_image_path(candidate):
                variant_source_path = candidate
                break

        draft_dir_raw = str(draft.get("draft_dir") or "").strip()
        draft_dir = Path(draft_dir_raw).resolve() if draft_dir_raw else image_path.parent.resolve()
        if not draft_dir.exists():
            draft_dir = image_path.parent.resolve()

        publish_dir = draft_dir / "publish_variants"
        post_image_path = self._render_publish_image_variant(
            source_path=variant_source_path,
            output_path=publish_dir / "image_post_feed.jpg",
            target_size=(1080, 1350),
        )
        story_image_path = self._render_publish_image_variant(
            source_path=variant_source_path,
            output_path=publish_dir / "image_story.jpg",
            target_size=(1080, 1920),
        )

        image_source = str(draft.get("image_source") or "")
        post_qc = self._validate_ig_image(image_path=post_image_path, image_source=image_source, format_type="feed")
        story_qc = self._validate_ig_image(image_path=story_image_path, image_source=image_source, format_type="story")

        payload = {
            "generated_at": self._now_iso(),
            "source_image_path": str(image_path),
            "variant_source_path": str(variant_source_path),
            "post_image_path": str(post_image_path),
            "story_image_path": str(story_image_path),
            "post_image_qc": post_qc,
            "story_image_qc": story_qc,
        }

        draft_json_path = draft_dir / "draft.json"
        stored = self._safe_read_json(draft_json_path, {})
        if isinstance(stored, dict):
            stored["publish_media"] = payload
            self._safe_write_json(draft_json_path, stored)

        return payload

    def _render_video_from_image(
        self,
        *,
        category_id: str,
        image_path: Path,
        output_path: Path,
        duration_seconds: float,
        add_music: bool,
    ) -> tuple[Path, Path | None, str]:
        import tempfile

        from PIL import Image, ImageFilter, ImageOps
        from moviepy.editor import AudioFileClip, ImageClip

        duration = max(4.0, float(duration_seconds))
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Build a stable video directly from the generated image (single layer).
        # Preserve full artwork to avoid clipping text bands on generated posters.
        width, height = 1080, 1920
        with Image.open(image_path).convert("RGB") as src:
            canvas = self._contain_with_soft_background(src, (width, height))

            with tempfile.TemporaryDirectory(prefix="ig_video_card_") as td:
                frame_path = Path(td) / "frame.jpg"
                canvas.save(frame_path, format="JPEG", quality=95)
                clip = ImageClip(str(frame_path)).set_duration(duration)
                clip = clip.fadein(0.12).fadeout(0.12)
                audio_clip = None

                music_path: Path | None = None
                music_source = "none"
                if add_music:
                    # Vary seed per run so instrumental bed is not always identical.
                    run_seed = int(datetime.now(timezone.utc).timestamp()) % 100_000
                    library_track = self._pick_music_library_track(seed=run_seed) if self.settings.instagram_music_use_library_first else None
                    if library_track is not None:
                        music_path = self._new_generated_media_pool_path(
                            category_id=category_id,
                            prefix="musiclib",
                            media_kind="audio",
                            extension=library_track.suffix.lower() or ".mp3",
                        )
                        shutil.copy2(library_track, music_path)
                        music_source = "library"
                    else:
                        music_path = self._new_generated_media_pool_path(
                            category_id=category_id,
                            prefix="musicgen",
                            media_kind="audio",
                            extension=".wav",
                        )
                        generate_instrumental_bed(duration_seconds=duration, output_path=music_path, seed=run_seed)
                        music_source = "generated"

                    if music_path.exists():
                        audio_clip = AudioFileClip(str(music_path)).subclip(0, duration)
                        clip = clip.set_audio(audio_clip)

                clip.write_videofile(
                    str(output_path),
                    fps=30,
                    codec="libx264",
                    audio_codec="aac",
                    temp_audiofile=str(output_path.with_name(output_path.stem + "_temp_audio.m4a")),
                    remove_temp=True,
                    verbose=False,
                    logger=None,
                )
                try:
                    clip.close()
                except Exception:
                    pass
                if audio_clip is not None:
                    try:
                        audio_clip.close()
                    except Exception:
                        pass
                return output_path, music_path, music_source

    def _validate_ig_image(self, *, image_path: Path, image_source: str = "", format_type: str = "") -> dict[str, Any]:
        report: dict[str, Any] = {"passed": True, "score": 100, "issues": [], "checks": {}, "recommendations": []}
        if not image_path.exists() or image_path.stat().st_size == 0:
            report.update({"passed": False, "score": 0, "issues": ["Image missing"], "recommendations": ["Regenerar imagen"]})
            return report

        try:
            with Image.open(image_path).convert("RGB") as img:
                width, height = img.size
        except Exception as exc:  # noqa: BLE001
            report.update(
                {
                    "passed": False,
                    "score": 0,
                    "issues": [f"Image read failed: {exc}"],
                    "recommendations": ["Regenerar imagen"],
                }
            )
            return report

        ratio = float(width) / float(max(1, height))
        expected_story = 1080 / 1920
        expected_feed = 1080 / 1350
        ratio_delta = min(abs(ratio - expected_story), abs(ratio - expected_feed))

        edge_risk, edge_meta = self._edge_margin_risk(image_path)
        report["checks"] = {
            "size": [int(width), int(height)],
            "ratio": round(ratio, 4),
            "ratio_delta_to_targets": round(ratio_delta, 4),
            "edge_margin_risk": bool(edge_risk),
            "edge_meta": edge_meta,
        }

        if width < 1000 or height < 1200:
            report["score"] -= 12
            report["issues"].append("Resolucion baja para IG")
        if ratio_delta > 0.08:
            report["score"] -= 10
            report["issues"].append("Relacion de aspecto lejos de formatos IG esperados")
        if edge_risk:
            inset_card = bool((edge_meta or {}).get("inset_card"))
            touch_top = bool((edge_meta or {}).get("touch_top"))
            touch_bottom = bool((edge_meta or {}).get("touch_bottom"))
            if touch_top or touch_bottom:
                report["score"] -= 22
                where = "superior e inferior" if (touch_top and touch_bottom) else "superior" if touch_top else "inferior"
                report["issues"].append(f"Contenido pegado al borde {where}")
            elif inset_card and str(image_source or "").strip().lower() in {"openai_image", "asset_library"}:
                # Full artwork adapted with a soft background can look like an inset
                # card to the heuristic, while still preserving every source element.
                report["score"] -= 5
                report["issues"].append("Composicion adaptada con bordes suaves")
            else:
                report["score"] -= 18
                report["issues"].append("Riesgo de recorte o composicion encajonada en bordes")

        report["passed"] = report["score"] >= 85
        if not report["passed"]:
            report["recommendations"].append("Regenerar imagen antes de publicar")
        return report

    def _validate_ig_video(self, *, video_path: Path, target_seconds: float, require_audio: bool) -> dict[str, Any]:
        from moviepy.editor import VideoFileClip

        report = {"passed": True, "score": 100, "issues": [], "checks": {}, "recommendations": []}
        if not video_path.exists() or video_path.stat().st_size == 0:
            report.update({"passed": False, "score": 0, "issues": ["Video missing"], "recommendations": ["Regenerar video"]})
            return report

        clip = VideoFileClip(str(video_path))
        try:
            duration = float(clip.duration or 0.0)
            width, height = clip.size
            has_audio = clip.audio is not None and (clip.audio.duration or 0) > 0
        finally:
            clip.close()

        report["checks"] = {"duration": round(duration, 2), "size": [width, height], "has_audio": has_audio}

        if width >= height:
            report["score"] -= 20
            report["issues"].append("Formato no vertical (9:16)")
        if abs(duration - target_seconds) > target_seconds * 0.25:
            report["score"] -= 12
            report["issues"].append("Duracion fuera de tolerancia")
        if require_audio and not has_audio:
            report["score"] -= 20
            report["issues"].append("Audio faltante")

        report["passed"] = report["score"] >= 85 and not report["issues"]
        if report["score"] < 85:
            report["recommendations"].append("Revisar musica/duracion")
        return report

    @staticmethod
    def _is_within(path: Path, root: Path) -> bool:
        try:
            return path.resolve().is_relative_to(root.resolve())
        except Exception:
            return False

    def _infer_ig_format_for_image(self, path: Path) -> str:
        try:
            with Image.open(path) as img:
                w, h = img.size
            ratio = float(w) / float(max(1, h))
        except Exception:
            return "feed"
        feed_delta = abs(ratio - (1080 / 1350))
        story_delta = abs(ratio - (1080 / 1920))
        return "feed" if feed_delta <= story_delta else "story"

    def _validate_library_image_quality(self, path: Path) -> dict[str, Any]:
        format_type = self._infer_ig_format_for_image(path)
        return self._validate_ig_image(image_path=path, image_source="asset_library", format_type=format_type)

    def _iter_category_library_images(self, category_id: str) -> list[Path]:
        category = self._normalize_category_id(category_id)
        images_dir = self.publish_assets_root / category / "images"
        rows: list[Path] = []
        if images_dir.exists():
            rows.extend([p for p in images_dir.rglob("*") if p.is_file() and self._is_image_path(p)])
            return sorted(rows, key=lambda p: p.name.lower())
        # Legacy compatibility: images directly under category folder.
        legacy_dir = self.publish_assets_root / category
        if legacy_dir.exists():
            rows.extend([p for p in legacy_dir.rglob("*") if p.is_file() and self._is_image_path(p) and "videos" not in p.parts])
        return sorted(rows, key=lambda p: p.name.lower())

    def _append_quality_reject_log(self, payload: dict[str, Any]) -> None:
        row = dict(payload or {})
        row["ts"] = self._now_iso()
        try:
            with self.quality_reject_log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def _append_quality_sweep_log(self, payload: dict[str, Any]) -> None:
        row = dict(payload or {})
        row["ts"] = self._now_iso()
        try:
            with self.quality_sweep_log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        except Exception:
            pass

    @staticmethod
    def _parse_iso_ts(raw: str) -> datetime | None:
        value = str(raw or "").strip()
        if not value:
            return None
        try:
            if value.endswith("Z"):
                value = value[:-1] + "+00:00"
            return datetime.fromisoformat(value)
        except Exception:
            return None

    def _prune_recent_state_asset_keys(self, asset_keys: set[str]) -> None:
        if not asset_keys:
            return
        state = self._load_state()
        state["recent_assets"] = [x for x in (state.get("recent_assets") or []) if str(x) not in asset_keys]
        recent_by_category = state.get("recent_assets_by_category")
        if isinstance(recent_by_category, dict):
            for cat, rows in list(recent_by_category.items()):
                if isinstance(rows, list):
                    recent_by_category[cat] = [x for x in rows if str(x) not in asset_keys]
            state["recent_assets_by_category"] = recent_by_category
        state["recent_videos"] = [x for x in (state.get("recent_videos") or []) if str(x) not in asset_keys]
        self._save_state(state)

    def sweep_library_quality(self, *, force: bool = False, delete_failed: bool | None = None) -> dict[str, Any]:
        enabled = bool(self.settings.instagram_quality_sweep_enabled)
        interval_minutes = max(1, int(self.settings.instagram_quality_sweep_interval_minutes))
        min_score = max(0, int(self.settings.instagram_publish_quality_min_score))
        keep_min = max(0, int(self.settings.instagram_quality_reject_keep_min_pass_assets_per_category))
        do_delete = bool(self.settings.instagram_quality_reject_delete_assets if delete_failed is None else delete_failed)

        state = self._load_state()
        now = datetime.now(timezone.utc)
        last_run = self._parse_iso_ts(str(state.get("last_quality_sweep_at") or ""))
        due = True
        if last_run is not None:
            due = now - last_run >= timedelta(minutes=interval_minutes)

        report: dict[str, Any] = {
            "ok": True,
            "enabled": enabled,
            "forced": bool(force),
            "due": bool(due),
            "delete_failed": do_delete,
            "min_score": min_score,
            "keep_min_pass_assets_per_category": keep_min,
            "interval_minutes": interval_minutes,
            "removed_assets": [],
            "skipped_assets": [],
            "categories": [],
        }
        if (not force) and ((not enabled) or (not due)):
            report["skipped_reason"] = "disabled" if not enabled else "interval_not_due"
            self._append_quality_sweep_log(report)
            return report

        removed_keys: set[str] = set()
        category_ids = sorted(
            {
                str(cat.get("id") or "").strip()
                for cat in self.categories
                if isinstance(cat, dict) and str(cat.get("id") or "").strip()
            }
        )
        if not category_ids:
            category_ids = sorted([p.name for p in self.publish_assets_root.iterdir() if p.is_dir()]) if self.publish_assets_root.exists() else []

        for category_id in category_ids:
            rows = self._iter_category_library_images(category_id)
            if not rows:
                report["categories"].append(
                    {"category_id": category_id, "total": 0, "pass": 0, "fail": 0, "removed": 0, "skipped": 0}
                )
                continue
            pass_rows: list[Path] = []
            fail_rows: list[tuple[Path, int, list[str]]] = []
            for path in rows:
                q = self._validate_library_image_quality(path)
                score = int(q.get("score") or 0)
                if score >= min_score:
                    pass_rows.append(path)
                else:
                    fail_rows.append((path, score, [str(x) for x in (q.get("issues") or []) if str(x).strip()]))

            removed_count = 0
            skipped_count = 0
            if do_delete:
                if len(pass_rows) < keep_min:
                    for path, score, _issues in fail_rows:
                        report["skipped_assets"].append(
                            {
                                "path": str(path),
                                "category_id": category_id,
                                "score": score,
                                "reason": "below_min_pass_pool",
                            }
                        )
                    skipped_count += len(fail_rows)
                else:
                    for path, score, issues in fail_rows:
                        if not self._is_within(path, self.publish_assets_root):
                            skipped_count += 1
                            report["skipped_assets"].append(
                                {
                                    "path": str(path),
                                    "category_id": category_id,
                                    "score": score,
                                    "reason": "outside_publish_assets_root",
                                }
                            )
                            continue
                        try:
                            path.unlink(missing_ok=False)
                            removed_count += 1
                            key = self._asset_key(path)
                            removed_keys.add(key)
                            report["removed_assets"].append(
                                {"path": str(path), "category_id": category_id, "score": score, "issues": issues}
                            )
                        except Exception as exc:  # noqa: BLE001
                            skipped_count += 1
                            report["skipped_assets"].append(
                                {
                                    "path": str(path),
                                    "category_id": category_id,
                                    "score": score,
                                    "reason": f"delete_error:{exc}",
                                }
                            )
            report["categories"].append(
                {
                    "category_id": category_id,
                    "total": len(rows),
                    "pass": len(pass_rows),
                    "fail": len(fail_rows),
                    "removed": removed_count,
                    "skipped": skipped_count,
                }
            )

        if removed_keys:
            self._prune_recent_state_asset_keys(removed_keys)
        self._refresh_asset_library()
        self._sync_asset_catalog()
        state = self._load_state()
        state["last_quality_sweep_at"] = self._now_iso()
        self._save_state(state)
        self._append_quality_sweep_log(report)
        return report

    def handle_quality_gate_failure(self, *, draft: dict[str, Any], gate: dict[str, Any]) -> dict[str, Any]:
        draft_id = str(draft.get("draft_id") or "").strip()
        min_score = max(0, int(self.settings.instagram_publish_quality_min_score))
        keep_min = max(0, int(self.settings.instagram_quality_reject_keep_min_pass_assets_per_category))
        delete_assets = bool(self.settings.instagram_quality_reject_delete_assets)

        report: dict[str, Any] = {
            "ok": True,
            "draft_id": draft_id,
            "deleted_draft_dir": False,
            "removed_assets": [],
            "skipped_assets": [],
            "gate_issues": list(gate.get("issues") or []),
            "min_score": min_score,
            "keep_min_pass_assets_per_category": keep_min,
            "delete_assets_enabled": delete_assets,
        }

        image_qc_gate = gate.get("image_qc") if isinstance(gate.get("image_qc"), dict) else {}
        image_qc_draft = draft.get("image_qc") if isinstance(draft.get("image_qc"), dict) else {}
        image_failed = (not bool(image_qc_gate.get("passed", True))) or (not bool(image_qc_draft.get("passed", True)))

        candidate_paths: list[Path] = []
        asset_key = str(draft.get("asset_key") or "").strip()
        if asset_key:
            candidate_paths.append(Path(asset_key))
        asset_rel = str(draft.get("asset_rel_path") or "").strip().replace("\\", "/")
        if asset_rel:
            candidate_paths.append(self.publish_assets_root / asset_rel)
        ingest = draft.get("library_ingest") if isinstance(draft.get("library_ingest"), dict) else {}
        for p in ingest.get("image_targets") or []:
            if str(p).strip():
                candidate_paths.append(Path(str(p)))

        dedup_candidates: list[Path] = []
        seen_keys: set[str] = set()
        for p in candidate_paths:
            key = self._asset_key(p)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            dedup_candidates.append(p)

        passable_cache: dict[str, set[str]] = {}
        removed_asset_keys: set[str] = set()
        if image_failed and delete_assets:
            for candidate in dedup_candidates:
                if not candidate.exists() or not candidate.is_file() or not self._is_image_path(candidate):
                    continue
                if not self._is_within(candidate, self.publish_assets_root):
                    continue

                quality = self._validate_library_image_quality(candidate)
                score = int(quality.get("score") or 0)
                if score >= min_score:
                    report["skipped_assets"].append(
                        {
                            "path": str(candidate),
                            "reason": "asset_passes_quality",
                            "score": score,
                        }
                    )
                    continue

                rel = self._asset_rel_path(candidate)
                category_id = str(rel).split("/", 1)[0].strip() or self._normalize_category_id(str(draft.get("category_id") or "general"))
                if category_id not in passable_cache:
                    passable_keys: set[str] = set()
                    for img in self._iter_category_library_images(category_id):
                        q = self._validate_library_image_quality(img)
                        if int(q.get("score") or 0) >= min_score:
                            passable_keys.add(self._asset_key(img))
                    passable_cache[category_id] = passable_keys

                key = self._asset_key(candidate)
                remaining_passable = len(passable_cache.get(category_id) or set())
                if key in (passable_cache.get(category_id) or set()):
                    remaining_passable = max(0, remaining_passable - 1)
                if remaining_passable < keep_min:
                    report["skipped_assets"].append(
                        {
                            "path": str(candidate),
                            "reason": "keep_min_pass_assets_guard",
                            "score": score,
                            "remaining_passable_after_delete": remaining_passable,
                        }
                    )
                    continue

                try:
                    candidate.unlink(missing_ok=False)
                    removed_asset_keys.add(key)
                    if key in (passable_cache.get(category_id) or set()):
                        passable_cache[category_id].discard(key)
                    report["removed_assets"].append(
                        {
                            "path": str(candidate),
                            "score": score,
                            "category_id": category_id,
                            "issues": list(quality.get("issues") or []),
                        }
                    )
                except Exception as exc:  # noqa: BLE001
                    report["skipped_assets"].append(
                        {
                            "path": str(candidate),
                            "reason": f"delete_error:{exc}",
                            "score": score,
                        }
                    )

        draft_dir_raw = str(draft.get("draft_dir") or "").strip()
        if draft_dir_raw:
            draft_dir = Path(draft_dir_raw)
            if draft_dir.exists() and self._is_within(draft_dir, self.drafts_root):
                try:
                    shutil.rmtree(draft_dir, ignore_errors=True)
                    report["deleted_draft_dir"] = True
                except Exception:
                    report["deleted_draft_dir"] = False

        if removed_asset_keys:
            self._prune_recent_state_asset_keys(removed_asset_keys)

        self._refresh_asset_library()
        self._sync_asset_catalog()
        self._append_quality_reject_log(report)
        return report

    def create_draft(self, *, objective: str | None = None, force_category: str | None = None, use_meta_history: bool = True, catalog: dict[str, Any] | None = None) -> DraftResult:
        objective_resolved = (objective or "").strip().lower() or None
        if objective_resolved and objective_resolved not in {"captar_clientes", "captar_proveedores", "branding"}:
            raise GenerationError("Objective invalido para IG draft")

        self._refresh_asset_library()
        self._sync_asset_catalog()

        if catalog is None:
            catalog = self.build_publication_catalog(use_meta_history=use_meta_history)

        state = self._load_state()
        category = self._pick_category(catalog=catalog, state=state, objective=objective_resolved, force_category=force_category)
        variant = self._pick_variant(category, state)
        service = self._pick_service(category, state)
        locale = self._pick_locale(state)
        format_type = self._pick_format(state)
        effective_objective = objective_resolved or str(category.get("objective") or "branding")

        run_id, run_dir = create_run_dir(self.drafts_root, f"{category.get('id')}_{service}_{format_type}")

        try:
            image_path, image_source, image_prompt, image_source_meta = self._generate_image(
                category=category,
                variant=variant,
                service=service,
                locale=locale,
                draft_dir=run_dir,
                state=state,
                objective=effective_objective,
                format_type=format_type,
            )
        except Exception:
            # Keep drafts folder clean on generation failures (API/budget/validation errors).
            try:
                shutil.rmtree(run_dir, ignore_errors=True)
            except Exception:
                pass
            raise

        copy = self._build_copy(
            category=category,
            variant=variant,
            service=service,
            locale=locale,
            format_type=format_type,
            objective=effective_objective,
            catalog=catalog,
        )

        (run_dir / "caption.txt").write_text(copy["caption"], encoding="utf-8")
        (run_dir / "short_text.txt").write_text(copy["short_text"], encoding="utf-8")
        (run_dir / "hashtags.txt").write_text(" ".join(copy["hashtags"]), encoding="utf-8")

        image_report = self._validate_ig_image(
            image_path=image_path,
            image_source=image_source,
            format_type=format_type,
        )
        write_json(run_dir / "image_qc.json", image_report)

        video_path: Path | None = None
        music_path: Path | None = None
        music_source = "none"
        video_source = "none"
        video_asset_meta: dict[str, Any] = {}
        video_report: dict[str, Any] | None = None
        if self.settings.instagram_generate_video_from_image:
            try:
                video_path = self._new_generated_media_pool_path(
                    category_id=str(category.get("id") or "general"),
                    prefix="video",
                    media_kind="video",
                    extension=".mp4",
                )
                video_path, music_path, music_source = self._render_video_from_image(
                    category_id=str(category.get("id") or "general"),
                    image_path=image_path,
                    output_path=video_path,
                    duration_seconds=float(self.settings.instagram_video_duration_seconds),
                    add_music=bool(self.settings.enable_background_music),
                )
                video_report = self._validate_ig_video(
                    video_path=video_path,
                    target_seconds=float(self.settings.instagram_video_duration_seconds),
                    require_audio=bool(self.settings.enable_background_music),
                )
                video_source = "generated_from_image"
                write_json(run_dir / "video_qc.json", video_report)
            except Exception as exc:  # noqa: BLE001
                fallback_error = str(exc)
                try:
                    query = " ".join(
                        [
                            str(category.get("label") or ""),
                            str(service or ""),
                            str(locale or ""),
                            str(copy.get("hook") or ""),
                            str(copy.get("value") or ""),
                        ]
                    ).strip()
                    video_item, video_asset_meta = self._select_library_video(
                        query=query,
                        category_id=str(category.get("id") or "general"),
                        state=state,
                    )
                    fallback_target = run_dir / f"video_lib{video_item.path.suffix.lower() or '.mp4'}"
                    shutil.copy2(video_item.path, fallback_target)
                    video_path = fallback_target
                    music_path = None
                    music_source = "library_video_no_music"
                    video_source = "library_video"
                    video_report = self._validate_ig_video(
                        video_path=video_path,
                        target_seconds=float(self.settings.instagram_video_duration_seconds),
                        require_audio=False,
                    )
                    write_json(run_dir / "video_qc.json", video_report)
                except Exception as fallback_exc:  # noqa: BLE001
                    video_source = "generation_failed"
                    video_report = {
                        "passed": False,
                        "score": 0,
                        "issues": [
                            f"Video generation failed: {fallback_error}",
                            f"Library fallback failed: {fallback_exc}",
                        ],
                        "checks": {},
                        "recommendations": ["Revisar dependencias de video y biblioteca local"],
                    }
                    write_json(run_dir / "video_qc.json", video_report)

        payload = {
            "draft_id": run_id,
            "draft_dir": str(run_dir),
            "created_at": self._now_iso(),
            "status": "draft",
            "category_id": str(category.get("id") or "general"),
            "category_label": str(category.get("label") or "General"),
            "format_type": format_type,
            "objective": effective_objective,
            "service": copy["service"],
            "locale": copy["locale"],
            "hook": copy["hook"],
            "value": copy["value"],
            "proof": copy["proof"],
            "cta": copy["cta"],
            "short_text": copy["short_text"],
            "caption": copy["caption"],
            "hashtags": copy["hashtags"],
            "whatsapp_url": copy["whatsapp_url"],
            "whatsapp_phone": copy["whatsapp_phone"],
            "image_path": str(image_path),
            "image_source": image_source,
            "image_prompt": image_prompt,
            "image_qc": image_report,
            "video_path": str(video_path) if video_path else "",
            "video_music_path": str(music_path) if music_path else "",
            "video_music_source": music_source,
            "video_source": video_source,
            "video_qc": video_report or {},
            "video_asset_key": str(video_asset_meta.get("asset_key") or ""),
            "video_asset_rel_path": str(video_asset_meta.get("asset_rel_path") or ""),
            "video_asset_category_id": str(video_asset_meta.get("asset_category_id") or ""),
            "video_asset_category_confidence": int(video_asset_meta.get("asset_category_confidence") or 0),
            "asset_key": str(image_source_meta.get("asset_key") or ""),
            "asset_rel_path": str(image_source_meta.get("asset_rel_path") or ""),
            "asset_category_id": str(image_source_meta.get("asset_category_id") or "general"),
            "asset_category_confidence": int(image_source_meta.get("asset_category_confidence") or 0),
            "asset_rotation_pool": int(image_source_meta.get("asset_rotation_pool") or 0),
            "asset_avoid_count": int(image_source_meta.get("asset_avoid_count") or 0),
            "asset_sequence_index": int(image_source_meta.get("asset_sequence_index") or 0),
            "catalog_file": str(self.catalog_path),
            "plan_file": str(self.plan_path),
        }

        if self.settings.instagram_library_sync_from_drafts:
            library_ingest = self._ingest_draft_media_into_library(payload)
        else:
            library_ingest = {
                "skipped": True,
                "reason": "library_sync_from_drafts_disabled",
                "category_id": payload["category_id"],
                "copied_images": 0,
                "copied_videos": 0,
                "copied_audios": 0,
                "image_targets": [],
                "video_targets": [],
                "audio_targets": [],
                "primary_image_path": "",
                "primary_video_path": "",
                "primary_audio_path": "",
            }
        primary_image = str(library_ingest.get("primary_image_path") or "").strip()
        primary_video = str(library_ingest.get("primary_video_path") or "").strip()
        primary_audio = str(library_ingest.get("primary_audio_path") or "").strip()
        if primary_image:
            payload["image_path"] = primary_image
        if primary_video:
            payload["video_path"] = primary_video
        if primary_audio:
            payload["video_music_path"] = primary_audio
        payload["library_ingest"] = library_ingest
        write_json(run_dir / "draft.json", payload)

        state["counter"] = int(state.get("counter", 0)) + 1
        recent_categories = list(state.get("recent_categories") or [])
        recent_categories.append(payload["category_id"])
        state["recent_categories"] = recent_categories[-12:]

        recent_formats = list(state.get("recent_formats") or [])
        recent_formats.append(format_type)
        state["recent_formats"] = recent_formats[-12:]

        asset_key = str(payload.get("asset_key") or "").strip()
        if asset_key:
            recent_assets = list(state.get("recent_assets") or [])
            recent_assets.append(asset_key)
            keep_global = max(12, int(self.settings.instagram_asset_rotation_window) * 2)
            state["recent_assets"] = recent_assets[-keep_global:]

            recent_by_category = state.get("recent_assets_by_category") or {}
            if not isinstance(recent_by_category, dict):
                recent_by_category = {}
            cat_key = payload["category_id"]
            cat_list = list(recent_by_category.get(cat_key) or [])
            cat_list.append(asset_key)
            keep_cat = max(6, int(self.settings.instagram_asset_category_rotation_window) * 2)
            recent_by_category[cat_key] = cat_list[-keep_cat:]
            state["recent_assets_by_category"] = recent_by_category

        video_asset_key = str(payload.get("video_asset_key") or "").strip()
        if video_asset_key:
            recent_videos = list(state.get("recent_videos") or [])
            recent_videos.append(video_asset_key)
            state["recent_videos"] = recent_videos[-24:]

        state["last_generated_at"] = payload["created_at"]
        self._save_state(state)

        self.build_publication_plan(catalog=catalog)
        return DraftResult(draft_id=run_id, draft_dir=run_dir, payload=self._to_web_payload(payload))

    def mark_sequential_image_published(self, draft: dict[str, Any]) -> None:
        if not self.settings.instagram_sequential_image_library:
            return
        asset_key = str(draft.get("asset_key") or "").strip()
        if not asset_key:
            return
        state = self._load_state()
        if str(state.get("last_sequence_published_asset_key") or "") == asset_key:
            return
        pool_size = max(1, int(draft.get("asset_rotation_pool") or len(self._sequential_image_pool()) or 1))
        published_index = max(0, int(draft.get("asset_sequence_index") or 0))
        state["image_sequence_index"] = (published_index + 1) % pool_size
        state["last_sequence_published_asset_key"] = asset_key
        state["last_sequence_published_at"] = self._now_iso()
        self._save_state(state)

    def list_drafts(self, *, limit: int = 40, include_payload: bool = False) -> list[dict[str, Any]]:
        if not self.drafts_root.exists():
            return []

        rows: list[dict[str, Any]] = []
        for draft_dir in sorted([p for p in self.drafts_root.iterdir() if p.is_dir()], reverse=True):
            data = self._safe_read_json(draft_dir / "draft.json", None)
            if not isinstance(data, dict):
                continue
            row = self._to_web_payload(data)
            if include_payload:
                rows.append(row)
            else:
                rows.append(
                    {
                        "draft_id": row.get("draft_id"),
                        "created_at": row.get("created_at"),
                        "status": row.get("status"),
                        "category_id": row.get("category_id"),
                        "category_label": row.get("category_label"),
                        "format_type": row.get("format_type"),
                        "objective": row.get("objective"),
                        "caption_preview": row.get("caption_preview"),
                        "short_text_preview": row.get("short_text_preview"),
                        "image_url": row.get("image_url"),
                        "draft_dir_url": row.get("draft_dir_url"),
                        "image_source": row.get("image_source"),
                    }
                )
            if len(rows) >= max(1, limit):
                break
        return rows

    def get_draft(self, draft_id: str) -> dict[str, Any]:
        if not draft_id:
            raise GenerationError("draft_id requerido")
        target = (self.drafts_root / draft_id).resolve()
        if not target.exists() or target.parent != self.drafts_root.resolve():
            raise GenerationError(f"Draft no encontrado: {draft_id}")
        payload = self._safe_read_json(target / "draft.json", None)
        if not isinstance(payload, dict):
            raise GenerationError(f"Draft invalido: {draft_id}")
        return self._to_web_payload(payload)

    def simulate_publish(self, draft_id: str) -> dict[str, Any]:
        target = (self.drafts_root / draft_id).resolve()
        if not target.exists() or target.parent != self.drafts_root.resolve():
            raise GenerationError(f"Draft no encontrado: {draft_id}")

        draft_path = target / "draft.json"
        payload = self._safe_read_json(draft_path, None)
        if not isinstance(payload, dict):
            raise GenerationError(f"Draft invalido: {draft_id}")

        payload["status"] = "simulated_published"
        payload["published_at"] = self._now_iso()
        payload["published_channel"] = "instagram_simulated"
        self.mark_sequential_image_published(payload)
        write_json(draft_path, payload)

        with self.publish_log_path.open("a", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {
                        "draft_id": payload.get("draft_id"),
                        "published_at": payload.get("published_at"),
                        "status": payload.get("status"),
                        "category_id": payload.get("category_id"),
                        "format_type": payload.get("format_type"),
                        "objective": payload.get("objective"),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )

        return self._to_web_payload(payload)

    def auto_cycle_once(self, *, objective: str | None = None, force_category: str | None = None, publish: bool = True, simulate_publish: bool = True, use_meta_history: bool = True) -> dict[str, Any]:
        catalog = self.build_publication_catalog(use_meta_history=use_meta_history)
        draft = self.create_draft(
            objective=objective,
            force_category=force_category,
            use_meta_history=use_meta_history,
            catalog=catalog,
        )

        publication = {"mode": "none", "status": "draft_only"}
        draft_payload = draft.payload

        if publish:
            if simulate_publish or self.settings.instagram_simulate_publish:
                draft_payload = self.simulate_publish(draft.draft_id)
                publication = {
                    "mode": "simulated",
                    "status": "ok",
                    "draft_id": draft.draft_id,
                    "published_at": draft_payload.get("published_at"),
                }
            else:
                publication = {
                    "mode": "real",
                    "status": "blocked",
                    "reason": "Publicacion real IG no implementada en modo local.",
                }

        plan = self.build_publication_plan(catalog=catalog)
        return {
            "ok": True,
            "generated_at": self._now_iso(),
            "catalog_file": str(self.catalog_path),
            "plan_file": str(self.plan_path),
            "draft": draft_payload,
            "publication": publication,
            "next_plan_items": (plan.get("items") or [])[:5],
        }

    def status(self) -> dict[str, Any]:
        state = self._load_state()
        latest_catalog = self._safe_read_json(self.catalog_path, {})
        latest_plan = self._safe_read_json(self.plan_path, {})
        asset_catalog = self._safe_read_json(self.asset_catalog_path, {})
        budget_state = self._load_openai_budget()
        budget_last_event = self._read_last_jsonl_event(self.openai_budget_events_path)
        return {
            "ok": True,
            "drafts_root": str(self.drafts_root),
            "publish_assets_root": str(self.publish_assets_root),
            "source_assets_root": str(self.settings.assets_root),
            "catalog_path": str(self.catalog_path),
            "plan_path": str(self.plan_path),
            "state_path": str(self.state_path),
            "counter": int(state.get("counter", 0)),
            "asset_catalog": {
                "path": str(self.asset_catalog_path),
                "generated_at": (asset_catalog or {}).get("generated_at") if isinstance(asset_catalog, dict) else None,
                "total_images": int(((asset_catalog or {}).get("total_images") or 0)) if isinstance(asset_catalog, dict) else 0,
                "total_videos": int(((asset_catalog or {}).get("total_videos") or 0)) if isinstance(asset_catalog, dict) else 0,
                "total_audios": int(((asset_catalog or {}).get("total_audios") or 0)) if isinstance(asset_catalog, dict) else 0,
                "counts_by_category": ((asset_catalog or {}).get("counts_by_category") or {}) if isinstance(asset_catalog, dict) else {},
                "counts_by_category_videos": ((asset_catalog or {}).get("counts_by_category_videos") or {}) if isinstance(asset_catalog, dict) else {},
                "counts_by_category_audios": ((asset_catalog or {}).get("counts_by_category_audios") or {}) if isinstance(asset_catalog, dict) else {},
            },
            "openai_budget": {
                "path": str(self.openai_budget_path),
                "events_path": str(self.openai_budget_events_path),
                "month": budget_state.get("month"),
                "images_generated": int(budget_state.get("images_generated", 0)),
                "spent_estimated_usd": float(budget_state.get("spent_estimated_usd", 0.0)),
                "monthly_budget_usd": float(self.settings.instagram_openai_monthly_budget_usd),
                "estimated_cost_per_image_usd": float(self.settings.instagram_openai_image_estimated_cost_usd),
                "last_event": budget_last_event,
            },
            "recent_categories": list(state.get("recent_categories") or []),
            "recent_formats": list(state.get("recent_formats") or []),
            "latest_catalog_at": latest_catalog.get("generated_at"),
            "latest_plan_at": latest_plan.get("generated_at"),
            "categories": [
                {
                    "id": cat.get("id"),
                    "label": cat.get("label"),
                    "objective": cat.get("objective"),
                }
                for cat in self.categories
            ],
        }








