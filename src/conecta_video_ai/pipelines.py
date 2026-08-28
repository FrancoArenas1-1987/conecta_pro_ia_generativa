from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tenacity import retry, stop_after_attempt, wait_fixed
import yaml

from .assets import AssetLibrary
from .campaign_engine import CampaignDefinition, campaign_from_payload, run_campaign
from .context_loader import load_brand_context
from .continuity_validator import ContinuityReport, validate_continuity
from .exceptions import GenerationError
from .image_renderer import render_social_image
from .insights_engine import generate_insights
from .instagram_graph_publisher import (
    InstagramGraphPublisher,
    resolve_public_image_url,
    resolve_public_video_url,
)
from .instagram_content_engine import InstagramContentEngine
from .logging_utils import build_logger
from .marketing_optimizer import optimize_marketing
from .marketing_validator import MarketingReport, evaluate_marketing
from .models import CampaignRequest, GenerationOutput, ImageRequest, StoryboardScene, VideoRequest, VideoScript
from .music_engine import generate_instrumental_bed, mix_voice_and_music
from .performance_tracker import LocalDryRunPublisher, PerformanceRecord, PerformanceTracker
from .social_publishers import TikTokPublisher, YouTubePublisher
from .preflight import ensure_output_root, run_preflight
from .prompts import PromptBuilder
from .providers import ComfyUIProvider, OllamaProvider, OpenAIImageProvider
from .quality import (
    QualityReport,
    evaluate_image_creative,
    evaluate_image_file,
    evaluate_storyboard,
    evaluate_video_script,
)
from .scene_bible import build_scene_bible, build_scene_manifest, resolve_objective
from .script_generator import (
    generate_conversion_reel_script,
    generate_image_creative,
    generate_video_script,
    revise_image_creative,
    revise_video_script,
)
from .settings import AppSettings
from .storage import create_run_dir, write_json
from .storyboard import build_storyboard
from .tts_engine import synthesize_dialogue, synthesize_voice
from .variant_generator import VariantSelection, generate_variants, select_best_variant
from .video_post_review import review_generated_video
from .video_renderer import mux_audio_track, render_video

class StudioService:
    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings
        self.context = load_brand_context(settings.context_path)
        self.provider = OllamaProvider(settings.ollama_model, executable=settings.ollama_executable)
        self.asset_library = AssetLibrary(settings.assets_root)
        self.tracker = PerformanceTracker(settings.tracking_root)
        self.publisher = self._build_social_publisher()
        self.openai_image_provider: OpenAIImageProvider | None = None
        if settings.openai_api_key:
            self.openai_image_provider = OpenAIImageProvider(
                api_key=settings.openai_api_key,
                model=settings.openai_image_model,
                size=settings.openai_image_size,
                quality=settings.openai_image_quality,
            )

        self.instagram_engine = InstagramContentEngine(
            settings=self.settings,
            context=self.context,
            provider=self.provider,
            asset_library=self.asset_library,
            openai_image_provider=self.openai_image_provider,
        )

    def _build_social_publisher(self, *, channel: str | None = None, force_enable: bool = False):
        enabled = bool(self.settings.social_publish_enabled or force_enable)
        if not enabled:
            return LocalDryRunPublisher()

        selected_channel = (channel or self.settings.social_channel or "").strip().lower()
        if selected_channel == "youtube":
            return YouTubePublisher(
                access_token=self.settings.youtube_access_token,
                refresh_token=self.settings.youtube_refresh_token,
                client_id=self.settings.youtube_client_id,
                client_secret=self.settings.youtube_client_secret,
                privacy_status=self.settings.youtube_privacy_status,
            )

        if selected_channel == "tiktok":
            return TikTokPublisher(
                access_token=self.settings.tiktok_access_token,
                refresh_token=self.settings.tiktok_refresh_token,
                client_key=self.settings.tiktok_client_key,
                client_secret=self.settings.tiktok_client_secret,
                privacy_level=self.settings.tiktok_privacy_level,
            )

        if selected_channel in {"local", "local_dryrun", "none", ""}:
            return LocalDryRunPublisher()

        raise GenerationError(
            f"SOCIAL_CHANNEL no soportado: {selected_channel}. Usa youtube, tiktok o local_dryrun."
        )

    @staticmethod
    def _safe_read_json(path: Path, fallback: dict | list | None = None):
        if not path.exists():
            return fallback if fallback is not None else {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return fallback if fallback is not None else {}

    @staticmethod
    def _safe_write_json(path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _safe_read_yaml(path: Path, fallback: dict | list | None = None):
        if not path.exists():
            return fallback if fallback is not None else {}
        try:
            with path.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except Exception:
            return fallback if fallback is not None else {}
        return data

    @staticmethod
    def _truthy(value: object, *, default: bool = False) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if not text:
            return default
        return text in {"1", "true", "yes", "on", "si", "sí"}

    @staticmethod
    def _target_field(raw: dict, *, key: str, env_key: str) -> str:
        direct = str(raw.get(key) or "").strip()
        if direct:
            return direct
        env_name = str(raw.get(env_key) or "").strip()
        if not env_name:
            return ""
        return str(os.getenv(env_name) or "").strip()

    def _load_instagram_publish_targets(self) -> list[dict]:
        primary = {
            "name": "principal",
            "enabled": True,
            "is_primary": True,
            "meta_access_token": str(self.settings.meta_access_token or "").strip(),
            "meta_page_id": str(self.settings.meta_page_id or "").strip(),
            "meta_instagram_user_id": str(self.settings.meta_instagram_user_id or "").strip(),
            "meta_graph_version": str(self.settings.meta_graph_version or "v21.0").strip() or "v21.0",
            "publish_instagram": True,
            "crosspost_facebook": bool(self.settings.instagram_crosspost_facebook),
            "publish_facebook_story": bool(self.settings.instagram_publish_facebook_story),
        }

        targets: list[dict] = [primary]
        cfg_path = Path(self.settings.instagram_publish_targets_path)
        cfg = self._safe_read_yaml(cfg_path, {})
        if not isinstance(cfg, dict):
            return targets

        rows = cfg.get("targets")
        if not isinstance(rows, list):
            return targets

        for idx, item in enumerate(rows, start=1):
            if not isinstance(item, dict):
                continue
            enabled = self._truthy(item.get("enabled"), default=True)
            if not enabled:
                continue

            name = str(item.get("name") or f"target_{idx}").strip() or f"target_{idx}"
            access_token = self._target_field(item, key="meta_access_token", env_key="meta_access_token_env")
            page_id = self._target_field(item, key="meta_page_id", env_key="meta_page_id_env")
            ig_user_id = self._target_field(item, key="meta_instagram_user_id", env_key="meta_instagram_user_id_env")
            graph_version = str(item.get("meta_graph_version") or self.settings.meta_graph_version or "v21.0").strip() or "v21.0"
            publish_instagram = self._truthy(item.get("publish_instagram"), default=True)
            crosspost_facebook = self._truthy(item.get("crosspost_facebook"), default=True)
            publish_facebook_story = self._truthy(item.get("publish_facebook_story"), default=False)

            if not access_token or not page_id:
                continue
            if publish_instagram and not ig_user_id:
                continue

            targets.append(
                {
                    "name": name,
                    "enabled": True,
                    "is_primary": False,
                    "meta_access_token": access_token,
                    "meta_page_id": page_id,
                    "meta_instagram_user_id": ig_user_id,
                    "meta_graph_version": graph_version,
                    "publish_instagram": publish_instagram,
                    "crosspost_facebook": crosspost_facebook,
                    "publish_facebook_story": publish_facebook_story,
                }
            )
        return targets

    def _build_instagram_publisher(self, target: dict) -> InstagramGraphPublisher:
        try:
            return InstagramGraphPublisher(
                self.settings,
                access_token=str(target.get("meta_access_token") or "").strip(),
                page_id=str(target.get("meta_page_id") or "").strip(),
                ig_user_id=str(target.get("meta_instagram_user_id") or "").strip(),
                graph_version=str(target.get("meta_graph_version") or self.settings.meta_graph_version or "v21.0").strip() or "v21.0",
            )
        except TypeError:
            # Compatibilidad con dobles de prueba que aceptan solo (settings).
            return InstagramGraphPublisher(self.settings)

    def list_video_publish_queue(self, ready_only: bool = True) -> list[dict]:
        root = self.settings.output_root / "videos"
        if not root.exists():
            return []

        items: list[dict] = []
        for run_dir in sorted([p for p in root.iterdir() if p.is_dir()], reverse=True):
            metadata_path = run_dir / "metadata.json"
            meta = self._safe_read_json(metadata_path, {})
            if not meta:
                continue

            publish_status = str(meta.get("publish_status", "queued")).strip().lower() or "queued"
            if ready_only and publish_status == "published":
                continue

            video_path = Path(str(meta.get("video", ""))) if meta.get("video") else None
            if not video_path or not video_path.exists():
                continue

            rel = video_path.resolve().relative_to(self.settings.output_root.resolve())
            items.append(
                {
                    "run_id": run_dir.name,
                    "topic": meta.get("topic"),
                    "style": meta.get("resolved_style"),
                    "objective": meta.get("objective"),
                    "publish_status": publish_status,
                    "channel": (meta.get("publication") or {}).get("channel"),
                    "post_id": (meta.get("publication") or {}).get("post_id"),
                    "post_url": (meta.get("publication") or {}).get("url"),
                    "video_url": f"/generated/{rel.as_posix()}",
                    "run_dir": str(run_dir),
                }
            )

        return items

    def publish_video_run(self, *, run_id: str, channel: str | None = None, force: bool = False) -> dict:
        video_root = self.settings.output_root / "videos"
        run_dir = (video_root / run_id).resolve()
        if not run_dir.exists() or run_dir.parent != video_root.resolve():
            raise GenerationError(f"Run no encontrado: {run_id}")

        metadata_path = run_dir / "metadata.json"
        if not metadata_path.exists():
            raise GenerationError(f"metadata.json no existe para run: {run_id}")

        meta = self._safe_read_json(metadata_path, {})
        if not meta:
            raise GenerationError(f"metadata.json invalido para run: {run_id}")

        publish_status = str(meta.get("publish_status", "queued")).strip().lower() or "queued"
        if publish_status == "published" and not force:
            return {
                "ok": True,
                "run_id": run_id,
                "already_published": True,
                "publication": meta.get("publication") or {},
            }

        video_file = Path(str(meta.get("video", "")))
        if not video_file.exists():
            raise GenerationError(f"Video no existe para publicar: {video_file}")

        publisher = self._build_social_publisher(channel=channel, force_enable=True)

        script_data = self._safe_read_json(run_dir / "script.json", {})
        hook = str(script_data.get("hook") or "").strip() or str(meta.get("topic") or "Video ConectaProIA")
        cta = str(script_data.get("cta") or "").strip()
        caption = f"{hook} {cta}".strip()

        publication = publisher.publish_video(
            video_path=video_file,
            caption=caption,
            tags=["conectaproia", "servicios", "whatsapp", str(meta.get("objective") or "branding")],
        )

        social_metrics: dict = {}
        post_id = str(publication.get("post_id") or "").strip()
        if post_id:
            try:
                social_metrics = publisher.fetch_post_metrics(post_id=post_id)
                views = int(social_metrics.get("views", 0) or 0)
                likes = int(social_metrics.get("likes", 0) or 0)
                comments = int(social_metrics.get("comments", 0) or 0)
                shares = int(social_metrics.get("shares", 0) or 0)
                engagement = ((likes + comments + shares) / views) if views > 0 else 0.0
                self.tracker.register_metrics(
                    run_id=run_id,
                    clicks=views,
                    whatsapp_messages=0,
                    engagement=engagement,
                    impressions=views,
                )
            except Exception:
                pass

        self.tracker.register_video(
            PerformanceRecord(
                run_id=run_id,
                variant_id=str(meta.get("variant_selected") or "base"),
                hook=hook,
                narrative=str(meta.get("resolved_style") or "promo"),
                cta=cta,
                objective=str(meta.get("objective") or "branding"),
                marketing_score=int(meta.get("marketing_score", 0) or 0),
                continuity_score=int(meta.get("continuity_score", 0) or 0),
                quality_score=int(meta.get("post_review_score", 0) or 0),
                published_at=str(publication.get("published_at") or ""),
                channel=str(publication.get("channel") or getattr(publisher, "channel_name", "unknown")),
                post_id=post_id or None,
            )
        )

        meta["publication"] = publication
        meta["social_metrics"] = social_metrics
        meta["publish_status"] = "published"
        meta["published_at"] = publication.get("published_at")
        self._safe_write_json(metadata_path, meta)

        return {
            "ok": True,
            "run_id": run_id,
            "publication": publication,
            "social_metrics": social_metrics,
        }

    def _retry(self):
        return retry(
            stop=stop_after_attempt(self.settings.retry_attempts),
            wait=wait_fixed(self.settings.retry_wait_seconds),
            reraise=True,
        )

    @staticmethod
    def _must_pass(report: QualityReport | None, label: str, min_score: int) -> None:
        if report is None:
            raise GenerationError(f"{label} quality report is missing")

        issues = " | ".join(report.issues) if report.issues else "sin detalle"
        if report.score < min_score:
            raise GenerationError(f"{label} quality below threshold ({report.score}/{min_score}): {issues}")

        if not report.passed:
            raise GenerationError(f"{label} QA did not pass despite score {report.score}: {issues}")

    @staticmethod
    def _storyboard_duration(scenes: list[StoryboardScene]) -> float:
        return round(sum(max(0.0, scene.duration_seconds) for scene in scenes), 2)

    @staticmethod
    def _audio_duration(path: Path | None) -> float:
        if path is None or not path.exists() or path.stat().st_size == 0:
            return 0.0
        from moviepy.editor import AudioFileClip

        clip = AudioFileClip(str(path))
        try:
            return float(clip.duration or 0.0)
        finally:
            clip.close()

    @staticmethod
    def _stretch_storyboard_to_seconds(scenes: list[StoryboardScene], target_seconds: float) -> list[StoryboardScene]:
        if not scenes:
            return scenes

        current = sum(scene.duration_seconds for scene in scenes)
        if current <= 0:
            return scenes

        scale = max(1.0, target_seconds / current)
        stretched: list[StoryboardScene] = []
        for scene in scenes:
            if scene.visual_style == "conversion":
                min_scene = 1.0
                max_scene = 2.0
            else:
                min_scene = 1.0 if scene.visual_style == "dialogo" else 1.3
                max_scene = 12.0

            new_duration = max(min_scene, min(max_scene, scene.duration_seconds * scale))
            stretched.append(scene.model_copy(update={"duration_seconds": round(new_duration, 2)}))

        return [scene.model_copy(update={"index": i}) for i, scene in enumerate(stretched, start=1)]

    def _generate_auto_topic(self, style: str) -> str:
        prompt = PromptBuilder.video_idea_prompt(self.context, style)
        payload = self.provider.generate_json(prompt)
        idea = " ".join(str(payload.get("idea", "")).split()).strip()
        if len(idea) < 8:
            raise GenerationError("No se pudo generar una idea automatica valida")
        return idea

    @staticmethod
    def _sections_for_style(style: str) -> int:
        if style == "conversion":
            return 6
        return 6 if style == "dialogo" else 5

    def _attach_scene_assets(self, scenes: list[StoryboardScene], topic: str, prefer_video: bool = False) -> list[StoryboardScene]:
        attached: list[StoryboardScene] = []
        used_images: set[Path] = set()
        used_videos: set[Path] = set()

        has_images = len(self.asset_library.image_items) > 0
        has_videos = len(self.asset_library.video_items) > 0

        for scene in scenes:
            query = f"{topic} {scene.headline} {scene.body} {scene.speaker or ''} {scene.visual_style}"

            image_path: Path | None = None
            if has_images:
                avoid = used_images if len(used_images) < len(self.asset_library.image_items) else set()
                image_item = self.asset_library.best_match_image(query, avoid=avoid)
                image_path = image_item.path
                used_images.add(image_path)

            video_path: Path | None = None
            if has_videos and (prefer_video or scene.visual_style in {"promo", "conversion"}):
                avoid = used_videos if len(used_videos) < len(self.asset_library.video_items) else set()
                video_item = self.asset_library.best_match_video(query, avoid=avoid)
                video_path = video_item.path
                used_videos.add(video_path)

            attached.append(scene.model_copy(update={"source_image": image_path, "source_video": video_path}))

        return attached

    def _scene_image_prompt(self, scene: StoryboardScene, topic: str, index: int, total: int, style: str) -> str:
        style_hint = {
            "conversion": "high-energy social media ad frame, strong emotions, modern lifestyle",
            "dialogo": "natural two-person conversation, realistic gestures, candid documentary style",
            "promo": "premium advertising frame, aspirational, trust-building service context",
        }.get(style, "professional marketing frame")

        return (
            "Create a photorealistic vertical image for a Chilean social media reel (9:16 framing). "
            f"Scene {index}/{total}. Brand: {self.context.company_name}. Topic: {topic}. "
            f"Visual goal: {scene.headline}. Details: {scene.body}. "
            f"Art direction: {style_hint}. "
            "Use realistic people and environments in Chile/LatAm context. "
            "No text, no captions, no logos, no watermark, no UI elements, no letters. "
            "Cinematic lighting, high detail, natural skin, commercial quality."
        )

    def _attach_openai_scene_images(
        self,
        scenes: list[StoryboardScene],
        topic: str,
        run_dir: Path,
        style: str,
    ) -> list[StoryboardScene]:
        if self.openai_image_provider is None:
            raise GenerationError("OpenAI image provider is not configured")

        max_images = max(1, self.settings.openai_scene_max_images)
        if len(scenes) > max_images and self.settings.openai_scene_images_strict:
            raise GenerationError(
                f"Storyboard has {len(scenes)} scenes, exceeds OPENAI_SCENE_MAX_IMAGES={max_images}."
            )

        images_dir = run_dir / "generated_scenes"
        images_dir.mkdir(parents=True, exist_ok=True)

        attached: list[StoryboardScene] = []
        for idx, scene in enumerate(scenes, start=1):
            if idx > max_images:
                if self.settings.openai_scene_images_strict:
                    raise GenerationError(
                        f"OpenAI scene generation exceeded max images ({max_images})."
                    )
                attached.append(scene)
                continue

            prompt = self._scene_image_prompt(scene, topic, idx, len(scenes), style)
            out_file = images_dir / f"scene_{idx:02d}.jpg"
            self.openai_image_provider.generate_image(prompt, out_file)
            attached.append(scene.model_copy(update={"source_image": out_file, "source_video": None}))

        return attached

    @staticmethod
    def _compose_comfy_prompt(script: VideoScript, topic: str) -> str:
        section_points = "; ".join([f"{s.title}: {s.narration}" for s in script.sections])

        if script.style == "dialogo" and script.dialogue:
            dialog = " ".join([f"{d.speaker}: {d.line}" for d in script.dialogue])
            return (
                "Vertical social media ad reel, cinematic lighting, natural human acting, "
                "two people talking in realistic environment, expressive gestures, modern framing, "
                f"topic: {topic}. Hook: {script.hook}. Dialogue: {dialog}. "
                f"Key moments: {section_points}. End CTA: {script.cta}."
            )

        return (
            "Vertical social media ad reel, high production quality, dynamic camera movement, "
            "professional service context, realistic people and locations, smooth transitions, "
            f"topic: {topic}. Hook: {script.hook}. Story: {section_points}. End CTA: {script.cta}."
        )

    def _build_script(self, *, request: VideoRequest, topic: str, logger, requested_style: str) -> tuple[VideoScript, dict, QualityReport, int]:
        payload = None
        script = None
        script_report = None

        if requested_style == "conversion":
            script, payload = generate_conversion_reel_script(self.context, topic)
            script_report = evaluate_video_script(script, self.context)
            logger.info(
                "Conversion script generated: score=%s passed=%s issues=%s",
                script_report.score,
                script_report.passed,
                script_report.issues,
            )
            self._must_pass(script_report, "Script", self.settings.quality_min_score)
            return script, payload, script_report, 24

        for iteration in range(1, self.settings.quality_max_iterations + 1):
            logger.info("Video script iteration %s", iteration)

            @self._retry()
            def _generate_or_revise():
                if iteration == 1:
                    return generate_video_script(
                        provider=self.provider,
                        context=self.context,
                        topic=topic,
                        duration_seconds=request.duration_seconds,
                        sections=self._sections_for_style(requested_style),
                        style=requested_style,
                        dialogue_seed=request.dialogue_seed,
                    )
                return revise_video_script(
                    provider=self.provider,
                    topic=topic,
                    duration_seconds=request.duration_seconds,
                    fallback_cta=self.context.call_to_action,
                    previous_payload=payload,
                    issues=script_report.issues if script_report else ["mejorar calidad"],
                    style=requested_style,
                )

            script, payload = _generate_or_revise()
            script_report = evaluate_video_script(script, self.context)
            logger.info(
                "Script quality: score=%s passed=%s issues=%s style=%s",
                script_report.score,
                script_report.passed,
                script_report.issues,
                script.style,
            )
            if script_report.score >= self.settings.quality_min_score and script_report.passed:
                break

        self._must_pass(script_report, "Script", self.settings.quality_min_score)
        return script, payload, script_report, (request.duration_seconds or self.settings.default_duration_seconds)

    def _prepare_storyboard(
        self,
        *,
        script: VideoScript,
        duration_target: int,
        hero_asset,
        topic: str,
        run_dir: Path,
        use_openai_scene_images: bool,
        prefer_video: bool = False,
    ) -> list[StoryboardScene]:
        raw_storyboard = build_storyboard(script, duration_target, hero_asset)
        if use_openai_scene_images:
            return self._attach_openai_scene_images(
                scenes=raw_storyboard,
                topic=topic,
                run_dir=run_dir,
                style=script.style,
            )
        return self._attach_scene_assets(raw_storyboard, topic, prefer_video=prefer_video)

    def _run_marketing_and_continuity(
        self,
        *,
        objective: str,
        script: VideoScript,
        storyboard: list[StoryboardScene],
        scene_bible: dict,
        scene_manifest: dict,
    ) -> tuple[VideoScript, list[StoryboardScene], MarketingReport, ContinuityReport, dict]:
        marketing_report = evaluate_marketing(script=script, scenes=storyboard, objective=objective)
        continuity_report = validate_continuity(
            scene_bible=scene_bible,
            scene_manifest=scene_manifest,
            script=script,
            scenes=storyboard,
        )

        optimizer_changes = {
            "changed": [],
            "estimated_score": marketing_report.score,
            "iterations": 0,
        }

        if marketing_report.score < self.settings.marketing_min_score:
            optimized = optimize_marketing(
                script=script,
                storyboard=storyboard,
                report=marketing_report,
                objective=objective,
                max_iterations=self.settings.marketing_max_iterations,
            )
            script = optimized.script
            storyboard = optimized.storyboard
            marketing_report = evaluate_marketing(script=script, scenes=storyboard, objective=objective)
            scene_manifest = build_scene_manifest(script=script, scenes=storyboard, run_id=scene_manifest.get("run_id", ""))
            continuity_report = validate_continuity(
                scene_bible=scene_bible,
                scene_manifest=scene_manifest,
                script=script,
                scenes=storyboard,
            )
            optimizer_changes = {
                "changed": optimized.changed,
                "estimated_score": optimized.estimated_score,
                "iterations": optimized.iterations,
            }

        return script, storyboard, marketing_report, continuity_report, optimizer_changes
    def create_video(self, request: VideoRequest) -> GenerationOutput:
        engine = request.engine
        use_openai_scene_images = (
            request.use_openai_images if request.use_openai_images is not None else self.settings.openai_scene_images
        )
        tts_provider = (self.settings.tts_provider or "edge").strip().lower()
        use_openai_tts = bool(request.enable_tts and tts_provider == "openai")
        run_preflight(
            self.settings,
            require_tts=request.enable_tts,
            video_engine=engine,
            require_openai_scene_images=bool(use_openai_scene_images),
            require_openai_tts=use_openai_tts,
        )

        video_root = self.settings.output_root / "videos"
        ensure_output_root(video_root)

        requested_style = request.style
        topic = " ".join((request.topic or "").split()).strip()
        if not topic:
            if request.auto_idea:

                @self._retry()
                def _idea() -> str:
                    return self._generate_auto_topic(requested_style)

                topic = _idea()
            else:
                raise GenerationError("Debes ingresar un contexto/idea o activar auto_idea")

        run_id, run_dir = create_run_dir(video_root, topic)
        logger = build_logger(f"conecta.video.{run_id}", self.settings.log_level, run_dir / "run.log")
        logger.info("Starting video generation for topic: %s", topic)
        logger.info(
            "Requested style: %s | Auto idea: %s | Engine: %s | OpenAI scene images: %s | TTS provider: %s",
            requested_style,
            request.auto_idea,
            engine,
            use_openai_scene_images,
            tts_provider,
        )

        hero_asset = self.asset_library.best_match(topic)
        logger.info("Selected asset: %s", hero_asset.path)

        objective = resolve_objective(requested_style, request.objective)
        script, payload, script_report, duration_target = self._build_script(
            request=request,
            topic=topic,
            logger=logger,
            requested_style=requested_style,
        )

        scene_bible = build_scene_bible(
            context=self.context,
            topic=topic,
            style=script.style,
            objective=objective,
            script=script,
        )

        variant_selection: VariantSelection | None = None
        if request.enable_variant_exploration and self.settings.enable_variant_exploration:
            variants = generate_variants(
                base_script=script,
                objective=objective,
                max_variants=min(request.max_variant_candidates, self.settings.max_variant_candidates),
            )
            if variants:
                variant_selection = select_best_variant(
                    variants=variants,
                    objective=objective,
                    storyboard_factory=lambda candidate_script: build_storyboard(candidate_script, duration_target, hero_asset),
                )
                script = variant_selection.selected.script
                logger.info(
                    "Variant selected: %s (%s)",
                    variant_selection.selected.variant_id,
                    variant_selection.report.score,
                )

        storyboard = self._prepare_storyboard(
            script=script,
            duration_target=duration_target,
            hero_asset=hero_asset,
            topic=topic,
            run_dir=run_dir,
            use_openai_scene_images=bool(use_openai_scene_images),
            prefer_video=False,
        )

        scene_manifest = build_scene_manifest(script=script, scenes=storyboard, run_id=run_id)
        script, storyboard, marketing_report, continuity_report, optimizer_changes = self._run_marketing_and_continuity(
            objective=objective,
            script=script,
            storyboard=storyboard,
            scene_bible=scene_bible,
            scene_manifest=scene_manifest,
        )

        if marketing_report.score < self.settings.marketing_min_score:
            raise GenerationError(
                f"Marketing score insuficiente ({marketing_report.score}/{self.settings.marketing_min_score}). "
                + " | ".join(marketing_report.issues)
            )

        if continuity_report.score < self.settings.continuity_min_score:
            raise GenerationError(
                f"Continuity score insuficiente ({continuity_report.score}/{self.settings.continuity_min_score}). "
                + " | ".join(continuity_report.issues)
            )

        storyboard_report = evaluate_storyboard(storyboard, duration_target)
        self._must_pass(storyboard_report, "Storyboard", self.settings.quality_min_score)

        voice_file: Path | None = None
        music_file: Path | None = None
        audio_file: Path | None = None

        if request.enable_tts:
            if script.style == "dialogo" and script.dialogue:
                turns = [(turn.speaker, turn.line) for turn in script.dialogue]
                voice_file = synthesize_dialogue(
                    turns,
                    run_dir / "voice.mp3",
                    provider=tts_provider,
                    strict=self.settings.tts_strict,
                    openai_api_key=self.settings.openai_api_key,
                    openai_model=self.settings.openai_tts_model,
                    openai_voice_primary=self.settings.openai_tts_voice_primary,
                    openai_voice_secondary=self.settings.openai_tts_voice_secondary,
                    openai_speed=self.settings.openai_tts_speed,
                )
            else:
                narration = " ".join([script.hook] + [s.narration for s in script.sections] + [script.cta])
                voice_file = synthesize_voice(
                    narration,
                    run_dir / "voice.mp3",
                    provider=tts_provider,
                    strict=self.settings.tts_strict,
                    openai_api_key=self.settings.openai_api_key,
                    openai_model=self.settings.openai_tts_model,
                    openai_voice_primary=self.settings.openai_tts_voice_primary,
                    openai_voice_secondary=self.settings.openai_tts_voice_secondary,
                    openai_speed=self.settings.openai_tts_speed,
                )

            if voice_file is None or not voice_file.exists() or voice_file.stat().st_size == 0:
                raise GenerationError("La voz fue solicitada pero no se pudo generar")
            logger.info("Voice generated: %s", voice_file)

        voice_seconds = self._audio_duration(voice_file)
        storyboard_seconds = self._storyboard_duration(storyboard)

        if voice_seconds > 0 and storyboard_seconds < (voice_seconds + 0.5):
            retimed_target_seconds = max(float(duration_target or 0), float(voice_seconds + 0.6))
            storyboard = self._stretch_storyboard_to_seconds(storyboard, retimed_target_seconds)
            storyboard_seconds = self._storyboard_duration(storyboard)
            storyboard_report = evaluate_storyboard(storyboard, retimed_target_seconds)
            self._must_pass(storyboard_report, "Storyboard (retimed)", self.settings.quality_min_score)
            logger.info("Storyboard retimed to fit voice: %.2fs", storyboard_seconds)

        target_seconds = max(1.0, storyboard_seconds)

        enable_music = bool(request.enable_music and self.settings.enable_background_music)
        if enable_music:
            music_file = generate_instrumental_bed(
                duration_seconds=target_seconds,
                output_path=run_dir / "music_bed.wav",
                seed=abs(hash(topic)) % 100000,
            )
            logger.info("Background music generated: %s", music_file)

        if voice_file and music_file:
            audio_file = mix_voice_and_music(
                voice_path=voice_file,
                music_path=music_file,
                output_path=run_dir / "audio_mix.mp3",
                target_duration=target_seconds,
                music_gain=self.settings.background_music_level,
                voice_gain=1.0,
            )
        elif voice_file:
            audio_file = voice_file
        elif music_file:
            audio_file = mix_voice_and_music(
                voice_path=None,
                music_path=music_file,
                output_path=run_dir / "audio_mix.mp3",
                target_duration=target_seconds,
                music_gain=self.settings.background_music_level,
                voice_gain=1.0,
            )

        script_file = run_dir / "script.json"
        storyboard_file = run_dir / "storyboard.json"
        quality_file = run_dir / "quality_report.json"
        scene_bible_file = run_dir / "scene_bible.json"
        scene_manifest_file = run_dir / "scene_manifest.json"
        marketing_file = run_dir / "marketing_report.json"
        continuity_file = run_dir / "continuity_report.json"
        variants_file = run_dir / "variants_report.json"

        write_json(script_file, script.model_dump())
        write_json(storyboard_file, {"scenes": [scene.model_dump(mode="json") for scene in storyboard]})
        write_json(
            quality_file,
            {
                "script": script_report.__dict__,
                "storyboard": storyboard_report.__dict__,
                "marketing": {
                    "score": marketing_report.score,
                    "passed": marketing_report.passed,
                    "breakdown": marketing_report.breakdown,
                    "issues": marketing_report.issues,
                },
                "continuity": continuity_report.__dict__,
            },
        )
        write_json(scene_bible_file, scene_bible)
        write_json(scene_manifest_file, build_scene_manifest(script=script, scenes=storyboard, run_id=run_id))
        write_json(
            marketing_file,
            {
                "score": marketing_report.score,
                "passed": marketing_report.passed,
                "breakdown": marketing_report.breakdown,
                "issues": marketing_report.issues,
                "recommendations": marketing_report.recommendations,
                "optimizer": optimizer_changes,
            },
        )
        write_json(continuity_file, continuity_report.__dict__)
        write_json(
            variants_file,
            {
                "enabled": bool(request.enable_variant_exploration and self.settings.enable_variant_exploration),
                "selected": variant_selection.selected.variant_id if variant_selection else "base",
                "selected_score": variant_selection.report.score if variant_selection else marketing_report.score,
                "ranking": variant_selection.ranking if variant_selection else [],
            },
        )
        video_file = run_dir / "video.mp4"

        if engine == "studio":

            @self._retry()
            def _render_video():
                render_video(
                    scenes=storyboard,
                    output_path=video_file,
                    fps=self.settings.fps,
                    width=self.settings.frame_width,
                    height=self.settings.frame_height,
                    text_color=self.context.visual_identity.text_color,
                    accent_color=self.context.visual_identity.accent_color,
                    audio_path=audio_file,
                    show_text=False,
                    brand_name=self.context.company_name,
                    logo_candidates=self.context.logo_candidates,
                    qr_code_path=self.context.whatsapp_qr_path,
                )

            _render_video()
        elif engine == "comfyui":
            comfy = ComfyUIProvider(
                base_url=self.settings.comfyui_base_url,
                workflow_template_path=self.settings.comfyui_workflow_template,
                poll_seconds=self.settings.comfyui_poll_seconds,
                timeout_seconds=self.settings.comfyui_timeout_seconds,
            )
            comfy.healthcheck()

            comfy_prompt = self._compose_comfy_prompt(script, topic)
            seed = abs(hash(f"{run_id}-{topic}")) % 2_147_483_647
            base_video = run_dir / "video_base.mp4"
            comfy_duration = max(5, int(round(max(target_seconds, float(duration_target or 0)))))

            @self._retry()
            def _generate_comfy_video():
                comfy.generate_video(
                    prompt_text=comfy_prompt,
                    negative_prompt=self.settings.comfyui_negative_prompt,
                    duration_seconds=comfy_duration,
                    width=self.settings.frame_width,
                    height=self.settings.frame_height,
                    fps=self.settings.fps,
                    output_path=base_video,
                    seed=seed,
                )

            _generate_comfy_video()
            mux_audio_track(base_video, video_file, audio_file)
            logger.info("ComfyUI base video generated: %s", base_video)
        else:
            raise GenerationError(f"Engine de video no soportado: {engine}")

        logger.info("Video generated successfully: %s", video_file)

        post_review = {
            "passed": True,
            "score": 100,
            "issues": [],
            "strengths": ["Post review disabled"],
            "checks": {},
            "recommendations": [],
        }
        post_review_file = run_dir / "post_review.json"
        if self.settings.post_review_enabled:
            post_review = review_generated_video(
                video_path=video_file,
                script=script,
                scenes=storyboard,
                topic=topic,
                target_seconds=duration_target,
                expect_audio=(request.enable_tts or request.enable_music),
                context=self.context,
                min_score=self.settings.post_review_min_score,
            )
            write_json(post_review_file, post_review)
            logger.info(
                "Post-review score=%s passed=%s issues=%s",
                post_review.get("score"),
                post_review.get("passed"),
                post_review.get("issues"),
            )

            if self.settings.post_review_strict and not post_review.get("passed", False):
                raise GenerationError(
                    f"Post-review failed ({post_review.get('score')}/{self.settings.post_review_min_score}): "
                    + " | ".join(post_review.get("issues", []))
                )

            professional_min = max(
                int(self.settings.quality_min_score),
                int(self.settings.post_review_min_score),
                int(self.settings.publish_min_score),
                int(self.settings.marketing_min_score),
                int(self.settings.continuity_min_score),
            )
            final_gate_score = min(
                int(post_review.get("score", 0)),
                int(marketing_report.score),
                int(continuity_report.score),
            )
            if final_gate_score < professional_min:
                raise GenerationError(
                    f"Video no alcanza nivel profesional ({final_gate_score}/{professional_min}). "
                    + " | ".join(post_review.get("issues", []))
                )

            if self.settings.publish_require_audio_when_tts and request.enable_tts and not post_review.get("checks", {}).get("has_audio", False):
                raise GenerationError("Video invalido para publicacion: TTS activado pero el resultado no contiene audio")

        publication = {
            "channel": "not_published",
            "status": "queued_for_review",
            "post_id": None,
            "published_at": None,
        }
        social_metrics: dict = {}
        publish_status = "queued"

        if self.settings.social_publish_enabled and self.settings.auto_publish_on_generate:
            publication = self.publisher.publish_video(
                video_path=video_file,
                caption=f"{script.hook} {script.cta}",
                tags=["conectaproia", "servicios", "whatsapp", objective],
            )
            publish_status = "published"

            post_id = str(publication.get("post_id") or "").strip()
            if post_id:
                try:
                    social_metrics = self.publisher.fetch_post_metrics(post_id=post_id)
                    views = int(social_metrics.get("views", 0) or 0)
                    likes = int(social_metrics.get("likes", 0) or 0)
                    comments = int(social_metrics.get("comments", 0) or 0)
                    shares = int(social_metrics.get("shares", 0) or 0)
                    engagement = ((likes + comments + shares) / views) if views > 0 else 0.0
                    self.tracker.register_metrics(
                        run_id=run_id,
                        clicks=views,
                        whatsapp_messages=0,
                        engagement=engagement,
                        impressions=views,
                    )
                except Exception as exc:
                    logger.warning("No se pudo obtener metricas sociales para %s: %s", post_id, exc)

            selected_variant_id = variant_selection.selected.variant_id if variant_selection else "base"
            selected_hook = variant_selection.selected.hook_template if variant_selection else script.hook
            selected_narrative = variant_selection.selected.narrative_template if variant_selection else script.style
            selected_cta = variant_selection.selected.cta_template if variant_selection else script.cta
            self.tracker.register_video(
                PerformanceRecord(
                    run_id=run_id,
                    variant_id=selected_variant_id,
                    hook=selected_hook,
                    narrative=selected_narrative,
                    cta=selected_cta,
                    objective=objective,
                    marketing_score=marketing_report.score,
                    continuity_score=continuity_report.score,
                    quality_score=int(post_review.get("score", storyboard_report.score)),
                    published_at=publication.get("published_at") or "",
                    channel=publication.get("channel") or getattr(self.publisher, "channel_name", "unknown"),
                    post_id=publication.get("post_id"),
                )
            )

        history = self.tracker.load_history()
        metrics = self.tracker.load_metrics()
        insights = generate_insights(history_rows=history, metrics_by_run=metrics)
        insights_file = run_dir / "insights_snapshot.json"
        write_json(
            insights_file,
            {
                "generated_at": insights.generated_at,
                "top_variants": insights.top_variants,
                "hook_ranking": insights.hook_ranking,
                "narrative_ranking": insights.narrative_ranking,
                "cta_ranking": insights.cta_ranking,
                "trend_warnings": insights.trend_warnings,
                "recommendations": insights.recommendations,
            },
        )

        selected_variant_id = variant_selection.selected.variant_id if variant_selection else "base"
        metadata_file = run_dir / "metadata.json"
        write_json(
            metadata_file,
            {
                "type": "video",
                "topic": topic,
                "requested_duration_seconds": duration_target,
                "duration_seconds": target_seconds,
                "requested_style": requested_style,
                "resolved_style": script.style,
                "objective": objective,
                "engine": engine,
                "scene_image_engine": "openai" if use_openai_scene_images else "library",
                "openai_scene_images": bool(use_openai_scene_images),
                "tts_provider": tts_provider,
                "tts_strict": bool(self.settings.tts_strict),
                "auto_idea": request.auto_idea,
                "asset": str(hero_asset.path),
                "video": str(video_file),
                "audio": str(audio_file) if audio_file else None,
                "voice": str(voice_file) if voice_file else None,
                "music": str(music_file) if music_file else None,
                "enable_music": bool(request.enable_music),
                "quality_min_score": self.settings.quality_min_score,
                "marketing_score": marketing_report.score,
                "continuity_score": continuity_report.score,
                "variant_selected": selected_variant_id,
                "qa_passed": True,
                "post_review_enabled": self.settings.post_review_enabled,
                "post_review_min_score": self.settings.post_review_min_score,
                "post_review_file": str(post_review_file) if self.settings.post_review_enabled else None,
                "post_review_passed": bool(post_review.get("passed", False)),
                "post_review_score": int(post_review.get("score", 0)),
                "scene_bible_file": str(scene_bible_file),
                "scene_manifest_file": str(scene_manifest_file),
                "marketing_report_file": str(marketing_file),
                "continuity_report_file": str(continuity_file),
                "variants_report_file": str(variants_file),
                "publication": publication,
                "publish_status": publish_status,
                "insights_snapshot_file": str(insights_file),
                "social_metrics": social_metrics,
            },
        )

        return GenerationOutput(
            run_id=run_id,
            run_dir=run_dir,
            type="video",
            main_file=video_file,
            metadata_file=metadata_file,
        )

    def create_campaign(self, request: CampaignRequest | dict) -> object:
        if isinstance(request, dict):
            campaign = campaign_from_payload(request)
            base_topic = str(request.get("base_topic", "Campana ConectaProIA")).strip() or "Campana ConectaProIA"
        else:
            campaign = CampaignDefinition(
                name=request.name,
                objective=request.objective,
                segments=request.segments,
                tone=request.tone,
                strategy=request.strategy,
                variants_per_segment=request.variants_per_segment,
            )
            base_topic = request.base_topic

        insights = generate_insights(
            history_rows=self.tracker.load_history(),
            metrics_by_run=self.tracker.load_metrics(),
        )

        def _generate_video(topic: str, style: str, objective: str, auto_idea: bool):
            return self.create_video(
                VideoRequest(
                    topic=topic,
                    style=style,
                    objective=objective,
                    auto_idea=auto_idea,
                    enable_tts=self.settings.enable_tts,
                    enable_music=self.settings.enable_background_music,
                    engine=self.settings.video_engine,
                    use_openai_images=self.settings.openai_scene_images,
                    enable_variant_exploration=True,
                )
            )

        return run_campaign(
            campaign=campaign,
            base_topic=base_topic,
            generate_video_fn=_generate_video,
            insights={
                "recommendations": insights.recommendations,
                "hook_ranking": insights.hook_ranking,
                "cta_ranking": insights.cta_ranking,
            },
        )
    def create_image(self, request: ImageRequest) -> GenerationOutput:
        run_preflight(self.settings, require_tts=False)
        image_root = self.settings.output_root / "images"
        ensure_output_root(image_root)

        run_id, run_dir = create_run_dir(image_root, f"{request.service}_{request.context}")
        logger = build_logger(f"conecta.image.{run_id}", self.settings.log_level, run_dir / "run.log")
        logger.info("Starting image generation for context: %s", request.context)

        asset = self.asset_library.best_match_image(f"{request.service} {request.context}")
        logger.info("Selected asset: %s", asset.path)

        creative = None
        payload = None
        creative_report = None
        for iteration in range(1, self.settings.quality_max_iterations + 1):
            logger.info("Image creative iteration %s", iteration)

            @self._retry()
            def _generate_or_revise():
                if iteration == 1:
                    return generate_image_creative(
                        provider=self.provider,
                        context=self.context,
                        brief=request.context,
                        service=request.service,
                    )
                return revise_image_creative(
                    provider=self.provider,
                    previous_payload=payload,
                    issues=creative_report.issues if creative_report else ["mejorar calidad"],
                )

            creative, payload = _generate_or_revise()
            creative_report = evaluate_image_creative(creative, self.context)
            logger.info(
                "Creative quality: score=%s passed=%s issues=%s",
                creative_report.score,
                creative_report.passed,
                creative_report.issues,
            )
            if creative_report.score >= self.settings.quality_min_score and creative_report.passed:
                break

        self._must_pass(creative_report, "Image creative", self.settings.quality_min_score)

        output_image = run_dir / "creative.jpg"
        render_social_image(
            creative=creative,
            source_image=asset.path,
            output_path=output_image,
            width=request.width,
            height=request.height,
            primary_color=self.context.visual_identity.primary_color,
            accent_color=self.context.visual_identity.accent_color,
            text_color=self.context.visual_identity.text_color,
        )

        image_report = evaluate_image_file(output_image, request.width, request.height)
        self._must_pass(image_report, "Rendered image", self.settings.quality_min_score)

        metadata_file = run_dir / "metadata.json"
        quality_file = run_dir / "quality_report.json"

        write_json(quality_file, {"creative": creative_report.__dict__, "image": image_report.__dict__})

        write_json(
            metadata_file,
            {
                "type": "image",
                "service": request.service,
                "context": request.context,
                "asset": str(asset.path),
                "creative": creative.model_dump(),
                "image": str(output_image),
                "qa_passed": True,
            },
        )
        logger.info("Image generated successfully: %s", output_image)

        return GenerationOutput(
            run_id=run_id,
            run_dir=run_dir,
            type="image",
            main_file=output_image,
            metadata_file=metadata_file,
        )

















    def build_instagram_catalog(self, *, use_meta_history: bool = True) -> dict:
        return self.instagram_engine.build_publication_catalog(use_meta_history=use_meta_history)

    def sync_instagram_assets(self) -> dict:
        return self.instagram_engine.sync_asset_catalog()

    def get_instagram_plan(self, *, horizon_hours: int | None = None) -> dict:
        return self.instagram_engine.build_publication_plan(horizon_hours=horizon_hours)

    def list_instagram_drafts(self, *, limit: int = 40) -> list[dict]:
        return self.instagram_engine.list_drafts(limit=limit)

    def get_instagram_draft(self, draft_id: str) -> dict:
        return self.instagram_engine.get_draft(draft_id)

    @staticmethod
    def _parse_utc_iso(raw: str) -> datetime | None:
        value = str(raw or "").strip()
        if not value:
            return None
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except Exception:
            return None
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    def _load_instagram_runtime_state(self) -> dict:
        data = self._safe_read_json(Path(self.settings.instagram_state_path), {})
        if isinstance(data, dict):
            return data
        return {}

    def _save_instagram_runtime_state(self, state: dict) -> None:
        self._safe_write_json(Path(self.settings.instagram_state_path), state)

    def _configured_instagram_publish_media_mode(self) -> str:
        mode = str(self.settings.instagram_publish_media_mode or "auto").strip().lower()
        if mode not in {"auto", "image_only", "video_only", "both"}:
            return "auto"
        return mode

    def _active_video_publish_cooldown_until(self) -> str | None:
        state = self._load_instagram_runtime_state()
        until_raw = str(state.get("video_publish_cooldown_until") or "").strip()
        until_dt = self._parse_utc_iso(until_raw)
        now = datetime.now(timezone.utc)
        if until_dt is None:
            return None
        if until_dt <= now:
            state.pop("video_publish_cooldown_until", None)
            state.pop("video_publish_cooldown_set_at", None)
            state.pop("video_publish_cooldown_reason", None)
            self._save_instagram_runtime_state(state)
            return None
        return until_dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")

    def _set_video_publish_cooldown(self, *, reason: str) -> str:
        minutes = max(1, int(self.settings.instagram_publish_video_failure_cooldown_minutes))
        now = datetime.now(timezone.utc).replace(microsecond=0)
        until = now + timedelta(minutes=minutes)
        state = self._load_instagram_runtime_state()
        state["video_publish_cooldown_until"] = until.isoformat().replace("+00:00", "Z")
        state["video_publish_cooldown_set_at"] = now.isoformat().replace("+00:00", "Z")
        state["video_publish_cooldown_reason"] = str(reason or "")[:800]
        self._save_instagram_runtime_state(state)
        return str(state["video_publish_cooldown_until"])

    def _clear_video_publish_cooldown(self) -> None:
        state = self._load_instagram_runtime_state()
        changed = False
        for key in ("video_publish_cooldown_until", "video_publish_cooldown_set_at", "video_publish_cooldown_reason"):
            if key in state:
                state.pop(key, None)
                changed = True
        if changed:
            self._save_instagram_runtime_state(state)

    def _instagram_publish_media_mode(self) -> str:
        mode = self._configured_instagram_publish_media_mode()
        if bool(self.settings.instagram_publish_auto_video_fallback_enabled) and mode in {"auto", "both"}:
            if self._active_video_publish_cooldown_until():
                return "image_only"
        return mode

    def _story_description(self, draft: dict) -> str:
        hook = str(draft.get("hook") or "").strip()
        value = str(draft.get("value") or "").strip()
        cta = str(draft.get("cta") or "").strip()
        merged = " ".join(x for x in [hook, value, cta] if x)
        return merged[:260].strip()

    @staticmethod
    def _target_signature(target: dict) -> str:
        page = str(target.get("meta_page_id") or "").strip()
        ig = str(target.get("meta_instagram_user_id") or "").strip()
        token = str(target.get("meta_access_token") or "").strip()
        return "|".join([page, ig, token])

    def _preflight_publish_targets(self, targets: list[dict]) -> tuple[list[dict], dict]:
        enabled = bool(self.settings.instagram_publish_preflight_targets_enabled)
        strict = bool(self.settings.instagram_publish_preflight_targets_strict)
        if not enabled:
            return targets, {"enabled": False, "strict": strict, "reports": [], "selected": len(targets)}

        reports: list[dict] = []
        selected: list[dict] = []
        seen: set[str] = set()

        for row in targets:
            target = dict(row)
            name = str(target.get("name") or "target").strip() or "target"
            publish_instagram = bool(target.get("publish_instagram", True))
            crosspost_facebook = bool(target.get("crosspost_facebook", False))
            status = "ok"
            notes: list[str] = []
            warnings: list[str] = []

            signature = self._target_signature(target)
            if signature and signature in seen:
                status = "skip_duplicate"
                notes.append("duplicate_target_signature")
                publish_instagram = False
                crosspost_facebook = False
            elif signature:
                seen.add(signature)

            page_id = str(target.get("meta_page_id") or "").strip()
            access_token = str(target.get("meta_access_token") or "").strip()
            ig_id = str(target.get("meta_instagram_user_id") or "").strip()
            if not page_id or not access_token:
                status = "skip_missing_credentials"
                notes.append("missing_meta_page_or_token")
                publish_instagram = False
                crosspost_facebook = False
            elif publish_instagram and not ig_id:
                status = "skip_missing_instagram_id"
                notes.append("missing_meta_instagram_user_id")
                publish_instagram = False

            page_identity: dict = {}
            if (publish_instagram or crosspost_facebook) and page_id and access_token:
                try:
                    publisher = self._build_instagram_publisher(target)
                    if hasattr(publisher, "inspect_page_identity"):
                        page_identity = publisher.inspect_page_identity()  # type: ignore[attr-defined]
                except Exception as exc:  # noqa: BLE001
                    msg = f"identity_check_failed:{exc}"
                    if strict:
                        status = "skip_identity_check_error"
                        notes.append(msg)
                        publish_instagram = False
                        crosspost_facebook = False
                    else:
                        warnings.append(msg)

            linked_ig = str(page_identity.get("linked_instagram_user_id") or "").strip()
            if publish_instagram and linked_ig and ig_id and linked_ig != ig_id:
                status = "instagram_disabled_link_mismatch"
                notes.append("configured_ig_id_differs_from_page_linked_ig")
                publish_instagram = False

            if not publish_instagram and not crosspost_facebook:
                if status == "ok":
                    status = "skip_no_channels"
                reports.append(
                    {
                        "target": name,
                        "status": status,
                        "notes": notes,
                        "warnings": warnings,
                        "publish_instagram": False,
                        "crosspost_facebook": False,
                        "page_identity": page_identity,
                    }
                )
                continue

            target["publish_instagram"] = publish_instagram
            target["crosspost_facebook"] = crosspost_facebook
            selected.append(target)
            reports.append(
                {
                    "target": name,
                    "status": status,
                    "notes": notes,
                    "warnings": warnings,
                    "publish_instagram": publish_instagram,
                    "crosspost_facebook": crosspost_facebook,
                    "page_identity": page_identity,
                }
            )

        return selected, {"enabled": True, "strict": strict, "reports": reports, "selected": len(selected)}

    def _evaluate_instagram_quality_gate(self, draft: dict, *, publish_mode: str | None = None) -> dict:
        enabled = bool(self.settings.instagram_publish_quality_gate_enabled)
        min_score = max(0, int(self.settings.instagram_publish_quality_min_score))
        blocking_issues: list[str] = []
        warnings: list[str] = []
        mode = str(publish_mode or self._instagram_publish_media_mode() or "auto").strip().lower()
        if mode not in {"auto", "image_only", "video_only", "both"}:
            mode = "auto"
        draft_format = str(draft.get("format_type") or "").strip().lower()
        if draft_format == "feed":
            required_image_channels = {"post"}
        elif draft_format == "story":
            required_image_channels = {"story"}
        else:
            required_image_channels = {"post", "story"}

        image_qc = draft.get("image_qc") if isinstance(draft.get("image_qc"), dict) else {}
        publish_media = draft.get("publish_media") if isinstance(draft.get("publish_media"), dict) else {}
        post_image_qc = publish_media.get("post_image_qc") if isinstance(publish_media.get("post_image_qc"), dict) else {}
        story_image_qc = publish_media.get("story_image_qc") if isinstance(publish_media.get("story_image_qc"), dict) else {}
        video_path = Path(str(draft.get("video_path") or "")).resolve() if str(draft.get("video_path") or "").strip() else None
        has_video = bool(video_path and video_path.exists())
        image_channels = {
            "post": {"available": False, "passed": False, "score": 0},
            "story": {"available": False, "passed": False, "score": 0},
        }
        quality_source = "draft_image"
        if enabled:
            # Prefer publish variants QC (feed+story) when available, because those are the
            # final assets that are actually sent to Instagram.
            if post_image_qc or story_image_qc:
                quality_source = "publish_variants"
                if post_image_qc:
                    post_score = int(post_image_qc.get("score") or 0)
                    post_passed = bool(post_image_qc.get("passed", False))
                    post_ok = post_passed and post_score >= min_score
                    image_channels["post"] = {"available": True, "passed": post_ok, "score": post_score}
                else:
                    warnings.append("post_image_qc ausente en publish_media")
                if story_image_qc:
                    story_score = int(story_image_qc.get("score") or 0)
                    story_passed = bool(story_image_qc.get("passed", False))
                    story_ok = story_passed and story_score >= min_score
                    image_channels["story"] = {"available": True, "passed": story_ok, "score": story_score}
                else:
                    warnings.append("story_image_qc ausente en publish_media")

                for channel in ("post", "story"):
                    channel_state = image_channels[channel]
                    channel_score = int(channel_state.get("score") or 0)
                    channel_available = bool(channel_state.get("available", False))
                    channel_passed = bool(channel_state.get("passed", False))
                    if channel in required_image_channels:
                        if not channel_available:
                            blocking_issues.append(f"{channel}_image_qc ausente en publish_media")
                        elif not channel_passed:
                            blocking_issues.append(f"{channel}_image_qc insuficiente (score={channel_score}, min={min_score})")
                    else:
                        if channel_available and not channel_passed:
                            warnings.append(f"{channel}_image_qc insuficiente (score={channel_score}, min={min_score})")
            else:
                image_score = int(image_qc.get("score") or 0)
                image_passed = bool(image_qc.get("passed", False))
                image_ok = bool(image_passed and image_score >= min_score)
                image_channels["post"] = {"available": bool(image_qc), "passed": image_ok, "score": image_score}
                image_channels["story"] = {"available": bool(image_qc), "passed": image_ok, "score": image_score}
                if not image_qc:
                    blocking_issues.append("image_qc ausente en draft")
                elif not image_ok:
                    blocking_issues.append(f"image_qc insuficiente (score={image_score}, min={min_score})")

            video_qc = draft.get("video_qc") if isinstance(draft.get("video_qc"), dict) else {}
            video_required = bool(self.settings.instagram_publish_require_video_qc) and (mode in {"video_only", "both"}) and has_video
            if video_required:
                if not video_qc:
                    blocking_issues.append("video_qc ausente en draft")
                elif not bool(video_qc.get("passed", False)):
                    blocking_issues.append("video_qc no aprobado")
            elif has_video and bool(self.settings.instagram_publish_require_video_qc):
                if (not video_qc) or (not bool(video_qc.get("passed", False))):
                    warnings.append("video_qc no aprobado (video no requerido en modo estable)")
        else:
            video_required = False

        return {
            "enabled": enabled,
            "min_score": min_score,
            "publish_mode": mode,
            "video_required": bool(video_required),
            "has_video": has_video,
            "passed": (not enabled) or len(blocking_issues) == 0,
            "issues": blocking_issues,
            "warnings": warnings,
            "quality_source": quality_source,
            "format_type": draft_format,
            "required_image_channels": sorted(required_image_channels),
            "image_qc": image_qc,
            "post_image_qc": post_image_qc,
            "story_image_qc": story_image_qc,
            "image_channels": image_channels,
            "video_qc": draft.get("video_qc") if isinstance(draft.get("video_qc"), dict) else {},
        }

    def publish_instagram_draft(
        self,
        *,
        draft_id: str,
        simulate: bool = True,
        public_image_url: str | None = None,
        public_video_url: str | None = None,
    ) -> dict:
        if simulate:
            return self.instagram_engine.simulate_publish(draft_id)

        draft = self.instagram_engine.get_draft(draft_id)
        draft_format = str(draft.get("format_type") or "").strip().lower()
        publish_post_channel = draft_format != "story"
        publish_story_channel = draft_format != "feed"
        image_path = Path(str(draft.get("image_path") or ""))
        if not image_path.exists():
            raise GenerationError(f"Imagen de borrador no encontrada: {image_path}")
        video_path = Path(str(draft.get("video_path") or "")) if str(draft.get("video_path") or "").strip() else None
        has_video = bool(video_path and video_path.exists())
        publish_media = self.instagram_engine.ensure_publish_image_variants(draft=draft)
        draft["publish_media"] = publish_media
        post_image_path = Path(str(publish_media.get("post_image_path") or image_path))
        story_image_path = Path(str(publish_media.get("story_image_path") or image_path))
        if not post_image_path.exists():
            post_image_path = image_path
        if not story_image_path.exists():
            story_image_path = image_path

        mode = self._instagram_publish_media_mode()
        gate = self._evaluate_instagram_quality_gate(draft, publish_mode=mode)
        if not gate["passed"]:
            raise GenerationError(f"Bloqueado por quality gate IG: {gate.get('issues')}")
        image_channels = gate.get("image_channels") if isinstance(gate.get("image_channels"), dict) else {}
        post_gate = image_channels.get("post") if isinstance(image_channels.get("post"), dict) else {}
        story_gate = image_channels.get("story") if isinstance(image_channels.get("story"), dict) else {}
        quality_gate_enabled = bool(gate.get("enabled", False))
        allow_post_image = (not quality_gate_enabled) or bool(post_gate.get("passed", True))
        allow_story_image = (not quality_gate_enabled) or bool(story_gate.get("passed", True))

        raw_targets = self._load_instagram_publish_targets()
        if not raw_targets:
            raise GenerationError("No hay destinos configurados para publicar en Instagram")
        targets, targets_preflight = self._preflight_publish_targets(raw_targets)
        if not targets:
            raise GenerationError("No hay destinos publicables tras validacion de dueños fanpage/IG y credenciales")
        primary_target = targets[0]
        primary_publisher = self._build_instagram_publisher(primary_target)

        caption = str(draft.get("caption") or "").strip()
        if not caption:
            raise GenerationError("Caption vacio en borrador IG")
        story_description = self._story_description(draft)

        want_video = (mode in {"auto", "video_only", "both"}) and has_video
        want_image = mode in {"auto", "image_only", "both"}
        if mode == "video_only" and (not has_video):
            want_image = True
            want_video = False

        def _resolve_image_public_url(local_image_path: Path, *, explicit: str | None) -> tuple[str, str]:
            try:
                resolved = resolve_public_image_url(
                    settings=self.settings,
                    image_path=local_image_path,
                    explicit_public_url=explicit,
                )
                source = "base_url_or_explicit"
                ok, reason = primary_publisher.remote_url_reachable(resolved)
                if not ok:
                    resolved = primary_publisher.stage_local_image_for_public_url(image_path=local_image_path, caption=caption)
                    source = f"meta_stage_fallback_unreachable:{reason}"
            except GenerationError:
                resolved = primary_publisher.stage_local_image_for_public_url(image_path=local_image_path, caption=caption)
                source = "meta_stage_fallback_missing_public_url"
            return resolved, source

        def _resolve_video_public_url(local_video_path: Path) -> tuple[str, str]:
            try:
                resolved = resolve_public_video_url(
                    settings=self.settings,
                    video_path=local_video_path,
                    explicit_public_url=public_video_url,
                )
                source = "base_url_or_explicit"
                ok, reason = primary_publisher.remote_url_reachable(resolved)
                if not ok:
                    resolved = primary_publisher.stage_local_video_for_public_url(video_path=local_video_path, description=caption)
                    source = f"meta_stage_fallback_unreachable:{reason}"
            except GenerationError:
                resolved = primary_publisher.stage_local_video_for_public_url(video_path=local_video_path, description=caption)
                source = "meta_stage_fallback_missing_public_url"
            return resolved, source

        resolved_public_video_url = ""
        video_url_source = ""
        video_fallback_applied = False
        video_fallback_reason = ""
        video_cooldown_until: str | None = None
        if want_video and video_path is not None:
            try:
                resolved_public_video_url, video_url_source = _resolve_video_public_url(video_path)
            except Exception as exc:  # noqa: BLE001
                if mode in {"auto", "both"}:
                    want_video = False
                    want_image = True
                    video_fallback_applied = True
                    video_fallback_reason = f"video_url_resolution_failed:{exc}"
                    video_url_source = "video_disabled_after_resolution_error"
                    if bool(self.settings.instagram_publish_auto_video_fallback_enabled):
                        video_cooldown_until = self._set_video_publish_cooldown(reason=video_fallback_reason)
                else:
                    raise

        resolved_public_post_image_url = ""
        resolved_public_story_image_url = ""
        post_image_url_source = ""
        story_image_url_source = ""

        def _ensure_channel_image_urls() -> None:
            nonlocal resolved_public_post_image_url
            nonlocal resolved_public_story_image_url
            nonlocal post_image_url_source
            nonlocal story_image_url_source
            if resolved_public_post_image_url and resolved_public_story_image_url:
                return

            same_image = False
            try:
                same_image = post_image_path.resolve() == story_image_path.resolve()
            except Exception:
                same_image = str(post_image_path) == str(story_image_path)

            resolved_public_post_image_url, post_image_url_source = _resolve_image_public_url(
                post_image_path,
                explicit=public_image_url,
            )
            if same_image:
                resolved_public_story_image_url = resolved_public_post_image_url
                story_image_url_source = post_image_url_source
            else:
                resolved_public_story_image_url, story_image_url_source = _resolve_image_public_url(
                    story_image_path,
                    explicit=None,
                )

        target_publications: list[dict] = []
        any_ig_post = False
        any_ig_story = False
        any_ig_video_success = False
        expected_any_post = False
        expected_any_story = False

        for target in targets:
            target_name = str(target.get("name") or "target").strip() or "target"
            target_result: dict = {
                "target": target_name,
                "is_primary": bool(target.get("is_primary", False)),
                "publish_instagram": bool(target.get("publish_instagram", True)),
                "crosspost_facebook": bool(target.get("crosspost_facebook", False)),
                "publish_facebook_story": bool(target.get("publish_facebook_story", False)),
                "ok": True,
            }

            try:
                publisher = self._build_instagram_publisher(target)
            except Exception as exc:  # noqa: BLE001
                target_result["ok"] = False
                target_result["error"] = f"No se pudo inicializar publisher para {target_name}: {exc}"
                target_publications.append(target_result)
                continue

            target_want_video = want_video
            target_want_image = want_image
            ig_post_results: list[dict] = []
            ig_story_results: list[dict] = []
            ig_video_error: str | None = None
            ig_errors: list[str] = []
            target_expect_post = False
            target_expect_story = False

            if bool(target.get("publish_instagram", True)):
                if target_want_video and resolved_public_video_url:
                    try:
                        ig_post_results.append(publisher.publish_reel_video(video_url=resolved_public_video_url, caption=caption))
                        ig_story_results.append(publisher.publish_story_video(video_url=resolved_public_video_url))
                        target_expect_post = True
                        target_expect_story = True
                        any_ig_video_success = True
                        if mode == "auto":
                            target_want_image = False
                    except Exception as exc:  # noqa: BLE001
                        ig_video_error = str(exc)
                        # Fallback robusto: si falla video, intenta imagen.
                        target_want_image = True
                        video_fallback_applied = True
                        video_fallback_reason = f"video_publish_failed:{exc}"
                        if bool(self.settings.instagram_publish_auto_video_fallback_enabled) and not video_cooldown_until:
                            video_cooldown_until = self._set_video_publish_cooldown(reason=video_fallback_reason)
                if target_want_image:
                    _ensure_channel_image_urls()
                if target_want_image and resolved_public_post_image_url and resolved_public_story_image_url:
                    if publish_post_channel and allow_post_image:
                        try:
                            ig_post_results.append(
                                publisher.publish_image_post(image_url=resolved_public_post_image_url, caption=caption)
                            )
                            target_expect_post = True
                        except Exception as exc:  # noqa: BLE001
                            target_result["ok"] = False
                            ig_errors.append(f"post:{exc}")
                    elif publish_post_channel:
                        target_result["instagram_post_skipped"] = "quality_gate_post_variant_failed"
                    if publish_story_channel and allow_story_image:
                        try:
                            ig_story_results.append(publisher.publish_story_image(image_url=resolved_public_story_image_url))
                            target_expect_story = True
                        except Exception as exc:  # noqa: BLE001
                            target_result["ok"] = False
                            ig_errors.append(f"story:{exc}")
                    elif publish_story_channel:
                        target_result["instagram_story_skipped"] = "quality_gate_story_variant_failed"
            else:
                target_result["instagram_skipped"] = True

            expected_any_post = expected_any_post or target_expect_post
            expected_any_story = expected_any_story or target_expect_story

            if ig_video_error:
                target_result["instagram_video_publish_error"] = ig_video_error
            if ig_errors:
                target_result["instagram_error"] = " | ".join(ig_errors)
            target_result["instagram_post_publications"] = ig_post_results
            target_result["instagram_story_publications"] = ig_story_results
            if ig_post_results:
                any_ig_post = True
            if ig_story_results:
                any_ig_story = True

            if bool(target.get("crosspost_facebook", False)):
                fb_pub_result: dict[str, object]
                if publish_post_channel:
                    try:
                        if target_want_video and resolved_public_video_url:
                            try:
                                fb_pub_result = publisher.publish_facebook_video(video_url=resolved_public_video_url, description=caption)
                            except Exception:
                                _ensure_channel_image_urls()
                                fb_pub_result = publisher.publish_facebook_photo(image_url=resolved_public_post_image_url, caption=caption)
                        else:
                            _ensure_channel_image_urls()
                            fb_pub_result = publisher.publish_facebook_photo(image_url=resolved_public_post_image_url, caption=caption)
                        target_result["facebook_publication"] = fb_pub_result
                    except Exception as exc:  # noqa: BLE001
                        target_result["ok"] = False
                        target_result["facebook_publication"] = {"status": "error", "error": str(exc)}
                else:
                    target_result["facebook_publication"] = {"status": "skipped", "reason": "story_day"}

                if publish_story_channel and bool(target.get("publish_facebook_story", False)):
                    fb_story_result: dict[str, object]
                    try:
                        if target_want_video and resolved_public_video_url:
                            try:
                                fb_story_result = publisher.publish_facebook_story_video(video_url=resolved_public_video_url)
                            except Exception:
                                _ensure_channel_image_urls()
                                fb_story_result = publisher.publish_facebook_story_photo(image_url=resolved_public_story_image_url)
                        else:
                            _ensure_channel_image_urls()
                            fb_story_result = publisher.publish_facebook_story_photo(image_url=resolved_public_story_image_url)
                        target_result["facebook_story"] = fb_story_result
                    except Exception as exc:  # noqa: BLE001
                        target_result["ok"] = False
                        target_result["facebook_story"] = {"status": "error", "error": str(exc)}
                else:
                    target_result["facebook_story"] = {"status": "skipped", "reason": "disabled_by_target_config"}

            target_publications.append(target_result)

        if any_ig_video_success:
            self._clear_video_publish_cooldown()

        if expected_any_post and not any_ig_post:
            raise GenerationError("No se obtuvo resultado de publicacion IG (post) en ningun destino")
        if expected_any_story and not any_ig_story:
            raise GenerationError("No se obtuvo resultado de publicacion IG (story) en ningun destino")
        if (not expected_any_post) and (not expected_any_story):
            raise GenerationError("No hay canales IG habilitados tras aplicar quality gate por variante")

        primary_publication = next((row for row in target_publications if bool(row.get("is_primary", False))), {})
        primary_ig_posts = primary_publication.get("instagram_post_publications") if isinstance(primary_publication.get("instagram_post_publications"), list) else []
        primary_ig_stories = primary_publication.get("instagram_story_publications") if isinstance(primary_publication.get("instagram_story_publications"), list) else []

        if not primary_ig_posts:
            for row in target_publications:
                posts = row.get("instagram_post_publications")
                if isinstance(posts, list) and posts:
                    primary_ig_posts = posts
                    break
        if not primary_ig_stories:
            for row in target_publications:
                stories = row.get("instagram_story_publications")
                if isinstance(stories, list) and stories:
                    primary_ig_stories = stories
                    break

        result = primary_ig_posts[0] if primary_ig_posts else {}
        story_result = primary_ig_stories[0] if primary_ig_stories else {}
        primary_fb_publication = (
            primary_publication.get("facebook_publication")
            if isinstance(primary_publication.get("facebook_publication"), dict)
            else {}
        )
        primary_fb_story = (
            primary_publication.get("facebook_story")
            if isinstance(primary_publication.get("facebook_story"), dict)
            else {}
        )
        primary_ig_video_error = str(primary_publication.get("instagram_video_publish_error") or "").strip() or None
        target_errors = [
            {
                "target": str(row.get("target") or ""),
                "instagram_error": row.get("instagram_error"),
                "facebook_publication": row.get("facebook_publication"),
                "facebook_story": row.get("facebook_story"),
                "error": row.get("error"),
            }
            for row in target_publications
            if not bool(row.get("ok", True))
        ]

        draft_json_path = Path(str(draft.get("draft_dir") or "")) / "draft.json"
        payload = self._safe_read_json(draft_json_path, {})
        if isinstance(payload, dict):
            published_at = result.get("published_at") or story_result.get("published_at")
            published_channel = result.get("channel") or story_result.get("channel")
            payload["status"] = "published_with_errors" if target_errors else "published"
            payload["published_at"] = published_at
            payload["published_channel"] = published_channel
            payload["post_id"] = result.get("post_id")
            payload["post_url"] = result.get("url")
            payload["creation_id"] = result.get("creation_id")
            payload["story_id"] = story_result.get("post_id")
            payload["story_url"] = story_result.get("url")
            payload["story_channel"] = story_result.get("channel")
            payload["public_image_url"] = resolved_public_post_image_url
            payload["public_image_story_url"] = resolved_public_story_image_url
            payload["public_video_url"] = resolved_public_video_url
            payload["public_image_url_source"] = post_image_url_source
            payload["public_image_story_url_source"] = story_image_url_source
            payload["public_video_url_source"] = video_url_source
            payload["story_description"] = story_description
            payload["publish_media_mode_effective"] = mode
            payload["instagram_post_publications"] = primary_ig_posts
            payload["instagram_story_publications"] = primary_ig_stories
            payload["instagram_video_publish_error"] = primary_ig_video_error
            payload["instagram_video_fallback_applied"] = video_fallback_applied
            payload["instagram_video_fallback_reason"] = video_fallback_reason
            payload["instagram_video_cooldown_until"] = video_cooldown_until
            payload["quality_gate"] = gate
            payload["quality_gate_warnings"] = list(gate.get("warnings") or [])
            payload["quality_gate_image_channels"] = gate.get("image_channels") if isinstance(gate.get("image_channels"), dict) else {}
            payload["publish_media"] = publish_media
            payload["targets_preflight"] = targets_preflight
            payload["facebook_publication"] = primary_fb_publication
            payload["facebook_story"] = primary_fb_story
            payload["multi_account_publications"] = target_publications
            payload["publication_errors"] = target_errors
            payload["published_targets_count"] = len(
                [
                    row
                    for row in target_publications
                    if (
                        isinstance(row.get("instagram_post_publications"), list)
                        and len(row.get("instagram_post_publications") or []) > 0
                    )
                    or (
                        isinstance(row.get("instagram_story_publications"), list)
                        and len(row.get("instagram_story_publications") or []) > 0
                    )
                ]
            )

            self._safe_write_json(draft_json_path, payload)
            mark_published = getattr(self.instagram_engine, "mark_sequential_image_published", None)
            if callable(mark_published):
                mark_published(payload)

        return self.instagram_engine.get_draft(draft_id)

    def run_instagram_auto_cycle(
        self,
        *,
        objective: str | None = None,
        force_category: str | None = None,
        publish: bool = True,
        simulate_publish: bool = True,
        use_meta_history: bool = True,
        public_image_url: str | None = None,
        public_video_url: str | None = None,
    ) -> dict:
        if simulate_publish:
            return self.instagram_engine.auto_cycle_once(
                objective=objective,
                force_category=force_category,
                publish=publish,
                simulate_publish=True,
                use_meta_history=use_meta_history,
            )

        try:
            sweep_report = self.instagram_engine.sweep_library_quality(force=False)
        except Exception:
            sweep_report = {"ok": False, "error": "quality_sweep_failed"}

        regen_limit = max(0, int(self.settings.instagram_publish_quality_max_regenerations))
        max_attempts_cfg = max(1, int(self.settings.instagram_publish_quality_max_attempts))
        max_attempts = max(regen_limit + 1, max_attempts_cfg)
        burst_cap = max(1, int(self.settings.instagram_publish_quality_burst_max_attempts))
        burst_guard_applied = False
        if max_attempts > burst_cap:
            max_attempts = burst_cap
            burst_guard_applied = True
        cycle: dict = {}
        draft: dict = {}
        gate: dict = {}
        for attempt in range(max_attempts):
            cycle = self.instagram_engine.auto_cycle_once(
                objective=objective,
                force_category=force_category,
                publish=False,
                simulate_publish=False,
                use_meta_history=use_meta_history,
            )
            cycle["quality_sweep"] = sweep_report
            draft = cycle.get("draft") or {}
            gate = self._evaluate_instagram_quality_gate(draft, publish_mode=self._instagram_publish_media_mode())
            cycle["quality_gate"] = gate
            cycle["quality_regeneration_attempt"] = attempt
            cycle["quality_attempts_limit"] = max_attempts
            cycle["quality_burst_guard_applied"] = burst_guard_applied
            if gate.get("passed"):
                break
            cleanup = self.instagram_engine.handle_quality_gate_failure(draft=draft, gate=gate)
            cycle["quality_rejection_cleanup"] = cleanup
            if attempt >= max_attempts - 1:
                raise GenerationError(
                    f"Quality gate IG no aprobado tras {max_attempts} intentos: {gate.get('issues')}"
                )

        if publish and isinstance(cycle, dict):
            draft_id = str(draft.get("draft_id") or "").strip()
            if not draft_id:
                raise GenerationError("No se pudo resolver draft_id para publicacion IG real")
            fallback_used = False
            fallback_reason = ""
            fallback_cooldown_until: str | None = None
            effective_mode = self._instagram_publish_media_mode()
            try:
                published = self.publish_instagram_draft(
                    draft_id=draft_id,
                    simulate=False,
                    public_image_url=public_image_url,
                    public_video_url=public_video_url,
                )
            except Exception as exc:  # noqa: BLE001
                if bool(self.settings.instagram_publish_auto_video_fallback_enabled) and effective_mode in {"auto", "both"}:
                    previous_mode = self.settings.instagram_publish_media_mode
                    self.settings.instagram_publish_media_mode = "image_only"
                    fallback_used = True
                    fallback_reason = str(exc)
                    fallback_cooldown_until = self._set_video_publish_cooldown(
                        reason=f"auto_cycle_publish_fallback:{fallback_reason}"
                    )
                    try:
                        published = self.publish_instagram_draft(
                            draft_id=draft_id,
                            simulate=False,
                            public_image_url=public_image_url,
                            public_video_url=public_video_url,
                        )
                    finally:
                        self.settings.instagram_publish_media_mode = previous_mode
                else:
                    raise
            cycle["draft"] = published
            publication_status = (
                "partial_error"
                if str(published.get("status") or "").strip().lower() == "published_with_errors"
                else "ok"
            )
            cycle["publication"] = {
                "mode": "real",
                "status": publication_status,
                "draft_id": draft_id,
                "post_id": published.get("post_id"),
                "post_url": published.get("post_url"),
                "story_id": published.get("story_id"),
                "story_url": published.get("story_url"),
                "published_at": published.get("published_at"),
                "fallback_used": fallback_used,
                "fallback_reason": fallback_reason,
                "fallback_cooldown_until": fallback_cooldown_until,
            }

        return cycle

    def instagram_status(self) -> dict:
        return self.instagram_engine.status()




