from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.chdir(PROJECT_ROOT)
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from conecta_video_ai.pipelines import StudioService
from conecta_video_ai.settings import load_settings


def _in_pool(path_text: str, pool_root: Path) -> bool:
    raw = str(path_text or "").strip()
    if not raw:
        return False
    try:
        return Path(raw).resolve().is_relative_to(pool_root.resolve())
    except Exception:
        txt = raw.replace("/", "\\").lower()
        return "output\\runs\\instagram\\publish_assets\\" in txt


def _audit_drafts(drafts_root: Path, pool_root: Path) -> dict:
    stats = {
        "drafts": 0,
        "image_in_pool": 0,
        "video_in_pool": 0,
        "audio_in_pool": 0,
        "missing_image": 0,
        "missing_video": 0,
        "missing_audio": 0,
        "with_library_ingest": 0,
    }
    for draft_dir in sorted([p for p in drafts_root.iterdir() if p.is_dir()], key=lambda x: x.name.lower()):
        draft_path = draft_dir / "draft.json"
        if not draft_path.exists():
            continue
        try:
            payload = json.loads(draft_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue

        stats["drafts"] += 1
        if isinstance(payload.get("library_ingest"), dict):
            stats["with_library_ingest"] += 1

        image_path = str(payload.get("image_path") or "").strip()
        video_path = str(payload.get("video_path") or "").strip()
        audio_path = str(payload.get("video_music_path") or "").strip()

        if image_path:
            if _in_pool(image_path, pool_root):
                stats["image_in_pool"] += 1
            if not Path(image_path).exists():
                stats["missing_image"] += 1
        if video_path:
            if _in_pool(video_path, pool_root):
                stats["video_in_pool"] += 1
            if not Path(video_path).exists():
                stats["missing_video"] += 1
        if audio_path:
            if _in_pool(audio_path, pool_root):
                stats["audio_in_pool"] += 1
            if not Path(audio_path).exists():
                stats["missing_audio"] += 1
    return stats


def _repair_draft_paths(service: StudioService, *, dry_run: bool = False) -> dict:
    engine = service.instagram_engine
    drafts_root = Path(engine.drafts_root)
    fixed = 0
    touched = 0
    examined = 0
    unchanged = 0
    write_errors = 0
    for draft_dir in sorted([p for p in drafts_root.iterdir() if p.is_dir()], key=lambda x: x.name.lower()):
        draft_path = draft_dir / "draft.json"
        if not draft_path.exists():
            continue
        try:
            payload = json.loads(draft_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        examined += 1
        original = dict(payload)

        ingest = payload.get("library_ingest")
        if not isinstance(ingest, dict):
            ingest = {}
        needs_ingest = not ingest
        if not needs_ingest:
            needs_ingest = not any(str(ingest.get(k) or "").strip() for k in ("primary_image_path", "primary_video_path", "primary_audio_path"))

        if needs_ingest:
            ingest = engine._ingest_draft_media_into_library(payload)  # noqa: SLF001
            payload["library_ingest"] = ingest
            touched += 1

        primary_image = str(ingest.get("primary_image_path") or "").strip()
        if not primary_image:
            targets = ingest.get("image_targets")
            if isinstance(targets, list) and targets:
                primary_image = str(targets[0] or "").strip()
        primary_video = str(ingest.get("primary_video_path") or "").strip()
        if not primary_video:
            targets = ingest.get("video_targets")
            if isinstance(targets, list) and targets:
                primary_video = str(targets[0] or "").strip()
        primary_audio = str(ingest.get("primary_audio_path") or "").strip()
        if not primary_audio:
            targets = ingest.get("audio_targets")
            if isinstance(targets, list) and targets:
                primary_audio = str(targets[0] or "").strip()

        changed = False
        if primary_image and Path(primary_image).exists() and str(payload.get("image_path") or "") != primary_image:
            payload["image_path"] = primary_image
            changed = True
        if primary_video and Path(primary_video).exists() and str(payload.get("video_path") or "") != primary_video:
            payload["video_path"] = primary_video
            changed = True
        if primary_audio and Path(primary_audio).exists() and str(payload.get("video_music_path") or "") != primary_audio:
            payload["video_music_path"] = primary_audio
            changed = True

        if changed:
            fixed += 1
            if not dry_run:
                try:
                    draft_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                except Exception:
                    write_errors += 1
        elif payload == original:
            unchanged += 1

    # Refresh catalog after path repair.
    sync_warning = ""
    try:
        engine._sync_asset_catalog()  # noqa: SLF001
    except Exception as exc:  # noqa: BLE001
        sync_warning = str(exc)
    return {
        "examined": examined,
        "ingest_touched": touched,
        "paths_fixed": fixed,
        "unchanged": unchanged,
        "write_errors": write_errors,
        "dry_run": bool(dry_run),
        "post_sync_warning": sync_warning,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Sincroniza y repara la biblioteca media de Instagram")
    parser.add_argument("--audit-only", action="store_true", help="Solo audita, no sincroniza ni corrige")
    parser.add_argument("--skip-repair", action="store_true", help="Sincroniza pero no corrige rutas de drafts")
    parser.add_argument("--dry-run", action="store_true", help="No escribe cambios (solo para repair)")
    args = parser.parse_args()

    settings = load_settings()
    service = StudioService(settings)
    drafts_root = Path(service.instagram_engine.drafts_root)
    pool_root = Path(service.instagram_engine.publish_assets_root)

    before = _audit_drafts(drafts_root, pool_root)
    sync_report = {"ok": True, "skipped": bool(args.audit_only)}
    repair_report = {"ok": True, "skipped": bool(args.audit_only or args.skip_repair)}
    if not args.audit_only:
        try:
            sync_report = service.instagram_engine.sync_asset_catalog()
        except Exception as exc:  # noqa: BLE001
            sync_report = {"ok": False, "error": str(exc)}
        if not settings.instagram_library_sync_from_drafts:
            repair_report = {
                "ok": True,
                "skipped": True,
                "reason": "library_sync_from_drafts_disabled",
            }
        elif not args.skip_repair:
            repair_report = _repair_draft_paths(service, dry_run=bool(args.dry_run))

    after = _audit_drafts(drafts_root, pool_root)
    report = {
        "ok": True,
        "project_root": str(PROJECT_ROOT),
        "audit_before": before,
        "sync": sync_report,
        "repair": repair_report,
        "audit_after": after,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
