from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel


class AppSettings(BaseModel):
    output_root: Path = Path("output/runs")
    tracking_root: Path = Path("output/tracking")
    context_path: Path = Path("config/context_conecta_pro_ia.yaml")
    assets_root: Path = Path(r"C:\Franco\conectapro_rrss")

    default_duration_seconds: int = 45
    default_scene_count: int = 5
    frame_width: int = 1080
    frame_height: int = 1920
    fps: int = 24

    retry_attempts: int = 3
    retry_wait_seconds: int = 2
    quality_min_score: int = 85
    quality_max_iterations: int = 3

    post_review_enabled: bool = True
    post_review_min_score: int = 90
    post_review_strict: bool = True

    marketing_min_score: int = 88
    marketing_max_iterations: int = 3
    continuity_min_score: int = 85
    continuity_max_regenerations: int = 2
    enable_variant_exploration: bool = True
    max_variant_candidates: int = 12

    log_level: str = "INFO"

    default_provider: str = "ollama"
    ollama_model: str = "llama3.1:8b"
    ollama_executable: str = "ollama"
    enable_tts: bool = True
    enable_background_music: bool = True
    background_music_level: float = 0.22

    tts_provider: str = "edge"
    tts_strict: bool = True
    openai_tts_model: str = "gpt-4o-mini-tts"
    openai_tts_voice_primary: str = "alloy"
    openai_tts_voice_secondary: str = "sage"
    openai_tts_speed: float = 1.0

    publish_min_score: int = 90
    publish_require_audio_when_tts: bool = True

    # Social publishing layer
    social_publish_enabled: bool = False
    social_channel: str = "local_dryrun"  # local_dryrun|youtube|tiktok
    auto_publish_on_generate: bool = False
    metricool_enabled: bool = False
    metricool_csv_path: Path | None = None

    youtube_access_token: str | None = None
    youtube_refresh_token: str | None = None
    youtube_client_id: str | None = None
    youtube_client_secret: str | None = None
    youtube_privacy_status: str = "public"

    tiktok_access_token: str | None = None
    tiktok_refresh_token: str | None = None
    tiktok_client_key: str | None = None
    tiktok_client_secret: str | None = None
    tiktok_privacy_level: str = "PUBLIC_TO_EVERYONE"

    meta_app_id: str | None = None
    meta_app_secret: str | None = None
    meta_access_token: str | None = None
    meta_user_access_token: str | None = None
    meta_user_token_expires_at: str | None = None
    meta_page_id: str | None = None
    meta_instagram_user_id: str | None = None
    meta_graph_version: str = "v21.0"
    meta_token_mode: str = "user_refresh"  # user_refresh|system_user

    # Instagram auto content layer
    instagram_categories_path: Path = Path("config/instagram_publication_categories.yaml")
    instagram_category_descriptors_path: Path = Path("config/instagram_category_descriptors.yaml")
    instagram_drafts_root: Path = Path("output/runs/instagram/drafts")
    instagram_catalog_path: Path = Path("output/runs/instagram/catalog/publication_catalog.json")
    instagram_plan_path: Path = Path("output/runs/instagram/catalog/publication_plan.json")
    instagram_state_path: Path = Path("output/runs/instagram/state.json")
    instagram_recent_media_limit: int = 30
    instagram_post_interval_minutes: int = 960
    instagram_plan_horizon_hours: int = 24
    instagram_short_text_max_chars: int = 90
    instagram_enable_openai_images: bool = True
    instagram_require_ai_image: bool = True
    instagram_ai_library_fallback_enabled: bool = False
    instagram_branding_required: bool = True
    instagram_simulate_publish: bool = True
    instagram_generate_video_from_image: bool = True
    instagram_video_duration_seconds: int = 8
    instagram_publish_media_mode: str = "auto"  # auto|image_only|video_only|both
    instagram_publish_quality_gate_enabled: bool = False
    instagram_publish_quality_min_score: int = 90
    instagram_publish_quality_max_regenerations: int = 2
    instagram_publish_quality_max_attempts: int = 12
    instagram_publish_quality_burst_max_attempts: int = 3
    instagram_publish_require_video_qc: bool = True
    instagram_publish_auto_video_fallback_enabled: bool = True
    instagram_publish_video_failure_cooldown_minutes: int = 360
    instagram_publish_preflight_targets_enabled: bool = True
    instagram_publish_preflight_targets_strict: bool = False
    instagram_quality_reject_delete_assets: bool = True
    instagram_quality_reject_keep_min_pass_assets_per_category: int = 1
    instagram_quality_sweep_enabled: bool = True
    instagram_quality_sweep_interval_minutes: int = 60
    instagram_overlay_short_text_enabled: bool = False
    instagram_qr_overlay_enabled: bool = False
    instagram_music_library_root: Path = Path("config/music/story")
    instagram_music_use_library_first: bool = True
    instagram_music_force_track: str | None = None
    instagram_whatsapp_client_url: str | None = None
    instagram_whatsapp_provider_url: str | None = None
    instagram_public_base_url: str | None = None
    instagram_crosspost_facebook: bool = False
    instagram_publish_facebook_story: bool = False
    instagram_publish_targets_path: Path = Path("config/instagram_publish_targets.yaml")
    instagram_openai_monthly_budget_usd: float = 5.0
    instagram_openai_image_estimated_cost_usd: float = 0.25
    instagram_openai_use_interleaving: bool = False
    instagram_openai_max_generation_attempts: int = 1
    instagram_openai_budget_path: Path = Path("output/runs/instagram/budget/openai_image_usage.json")
    instagram_asset_catalog_path: Path = Path("output/runs/instagram/catalog/asset_catalog.json")
    instagram_asset_overrides_path: Path = Path("config/instagram_asset_overrides.yaml")
    instagram_publish_assets_root: Path = Path("output/runs/instagram/publish_assets")
    instagram_sequential_image_library: bool = False
    instagram_library_sync_from_drafts: bool = True
    instagram_asset_rotation_window: int = 18
    instagram_asset_category_rotation_window: int = 8
    instagram_antispam_cooldown_minutes: int = 2880

    # Video generation backends:
    # - studio: local compositor from curated assets
    # - comfyui: text-to-video workflow executed in ComfyUI server
    video_engine: str = "studio"
    comfyui_base_url: str = "http://127.0.0.1:8188"
    comfyui_workflow_template: Path = Path("config/comfyui/workflow_t2v.json")
    comfyui_negative_prompt: str = (
        "blurry, low quality, distorted faces, extra limbs, bad anatomy, watermark, logo, text artifacts"
    )
    comfyui_timeout_seconds: int = 1200
    comfyui_poll_seconds: float = 2.0

    # Optional premium scene image generation with OpenAI Images API.
    openai_api_key: str | None = None
    openai_image_model: str = "gpt-image-1"
    openai_image_size: str = "1024x1536"
    openai_image_quality: str = "high"
    openai_scene_images: bool = False
    openai_scene_images_strict: bool = True
    openai_scene_max_images: int = 24


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        content = yaml.safe_load(f) or {}
    if not isinstance(content, dict):
        raise ValueError(f"Invalid YAML map: {path}")
    return content


def _detect_ollama_executable() -> str:
    if os.getenv("OLLAMA_EXECUTABLE"):
        return os.getenv("OLLAMA_EXECUTABLE") or "ollama"

    candidates = [
        r"C:\Users\franc\AppData\Local\Programs\Ollama\ollama.exe",
        r"C:\Program Files\Ollama\ollama.exe",
    ]
    for path in candidates:
        if Path(path).exists():
            return path
    return "ollama"


def load_settings(default_path: Path = Path("config/app.yaml")) -> AppSettings:
    dotenv_override = os.getenv("DOTENV_OVERRIDE", "true").strip().lower() in {"1", "true", "yes", "on"}
    load_dotenv(override=dotenv_override)
    data = _read_yaml(default_path)

    env_map = {
        "OUTPUT_ROOT": "output_root",
        "TRACKING_ROOT": "tracking_root",
        "CONTEXT_PATH": "context_path",
        "ASSETS_ROOT": "assets_root",
        "LOG_LEVEL": "log_level",
        "DEFAULT_PROVIDER": "default_provider",
        "OLLAMA_MODEL": "ollama_model",
        "VIDEO_ENGINE": "video_engine",
        "COMFYUI_BASE_URL": "comfyui_base_url",
        "COMFYUI_WORKFLOW_TEMPLATE": "comfyui_workflow_template",
        "COMFYUI_NEGATIVE_PROMPT": "comfyui_negative_prompt",
        "OPENAI_API_KEY": "openai_api_key",
        "OPENAI_IMAGE_MODEL": "openai_image_model",
        "OPENAI_IMAGE_SIZE": "openai_image_size",
        "OPENAI_IMAGE_QUALITY": "openai_image_quality",
        "TTS_PROVIDER": "tts_provider",
        "OPENAI_TTS_MODEL": "openai_tts_model",
        "OPENAI_TTS_VOICE_PRIMARY": "openai_tts_voice_primary",
        "OPENAI_TTS_VOICE_SECONDARY": "openai_tts_voice_secondary",
        "SOCIAL_CHANNEL": "social_channel",
        "YOUTUBE_ACCESS_TOKEN": "youtube_access_token",
        "YOUTUBE_REFRESH_TOKEN": "youtube_refresh_token",
        "YOUTUBE_CLIENT_ID": "youtube_client_id",
        "YOUTUBE_CLIENT_SECRET": "youtube_client_secret",
        "YOUTUBE_PRIVACY_STATUS": "youtube_privacy_status",
        "TIKTOK_ACCESS_TOKEN": "tiktok_access_token",
        "TIKTOK_REFRESH_TOKEN": "tiktok_refresh_token",
        "TIKTOK_CLIENT_KEY": "tiktok_client_key",
        "TIKTOK_CLIENT_SECRET": "tiktok_client_secret",
        "TIKTOK_PRIVACY_LEVEL": "tiktok_privacy_level",
        "META_APP_ID": "meta_app_id",
        "META_APP_SECRET": "meta_app_secret",
        "META_ACCESS_TOKEN": "meta_access_token",
        "META_USER_ACCESS_TOKEN": "meta_user_access_token",
        "META_USER_TOKEN_EXPIRES_AT": "meta_user_token_expires_at",
        "META_PAGE_ID": "meta_page_id",
        "META_INSTAGRAM_USER_ID": "meta_instagram_user_id",
        "META_GRAPH_VERSION": "meta_graph_version",
        "META_TOKEN_MODE": "meta_token_mode",
        "INSTAGRAM_CATEGORIES_PATH": "instagram_categories_path",
        "INSTAGRAM_CATEGORY_DESCRIPTORS_PATH": "instagram_category_descriptors_path",
        "INSTAGRAM_DRAFTS_ROOT": "instagram_drafts_root",
        "INSTAGRAM_CATALOG_PATH": "instagram_catalog_path",
        "INSTAGRAM_PLAN_PATH": "instagram_plan_path",
        "INSTAGRAM_WHATSAPP_CLIENT_URL": "instagram_whatsapp_client_url",
        "INSTAGRAM_WHATSAPP_PROVIDER_URL": "instagram_whatsapp_provider_url",
        "INSTAGRAM_PUBLIC_BASE_URL": "instagram_public_base_url",
        "INSTAGRAM_PUBLISH_TARGETS_PATH": "instagram_publish_targets_path",
        "INSTAGRAM_STATE_PATH": "instagram_state_path",
        "INSTAGRAM_OPENAI_BUDGET_PATH": "instagram_openai_budget_path",
        "INSTAGRAM_ASSET_CATALOG_PATH": "instagram_asset_catalog_path",
        "INSTAGRAM_ASSET_OVERRIDES_PATH": "instagram_asset_overrides_path",
        "INSTAGRAM_PUBLISH_ASSETS_ROOT": "instagram_publish_assets_root",
        "INSTAGRAM_MUSIC_LIBRARY_ROOT": "instagram_music_library_root",
        "INSTAGRAM_MUSIC_FORCE_TRACK": "instagram_music_force_track",
        "INSTAGRAM_PUBLISH_MEDIA_MODE": "instagram_publish_media_mode",
    }
    for env_key, config_key in env_map.items():
        if os.getenv(env_key):
            data[config_key] = os.getenv(env_key)

    bool_map = {
        "ENABLE_TTS": "enable_tts",
        "ENABLE_BACKGROUND_MUSIC": "enable_background_music",
        "TTS_STRICT": "tts_strict",
        "PUBLISH_REQUIRE_AUDIO_WHEN_TTS": "publish_require_audio_when_tts",
        "POST_REVIEW_STRICT": "post_review_strict",
        "OPENAI_SCENE_IMAGES": "openai_scene_images",
        "OPENAI_SCENE_IMAGES_STRICT": "openai_scene_images_strict",
        "ENABLE_VARIANT_EXPLORATION": "enable_variant_exploration",
        "SOCIAL_PUBLISH_ENABLED": "social_publish_enabled",
        "AUTO_PUBLISH_ON_GENERATE": "auto_publish_on_generate",
        "METRICOOL_ENABLED": "metricool_enabled",
        "INSTAGRAM_ENABLE_OPENAI_IMAGES": "instagram_enable_openai_images",
        "INSTAGRAM_REQUIRE_AI_IMAGE": "instagram_require_ai_image",
        "INSTAGRAM_AI_LIBRARY_FALLBACK_ENABLED": "instagram_ai_library_fallback_enabled",
        "INSTAGRAM_BRANDING_REQUIRED": "instagram_branding_required",
        "INSTAGRAM_SIMULATE_PUBLISH": "instagram_simulate_publish",
        "INSTAGRAM_CROSSPOST_FACEBOOK": "instagram_crosspost_facebook",
        "INSTAGRAM_PUBLISH_FACEBOOK_STORY": "instagram_publish_facebook_story",
        "INSTAGRAM_GENERATE_VIDEO_FROM_IMAGE": "instagram_generate_video_from_image",
        "INSTAGRAM_MUSIC_USE_LIBRARY_FIRST": "instagram_music_use_library_first",
        "INSTAGRAM_PUBLISH_QUALITY_GATE_ENABLED": "instagram_publish_quality_gate_enabled",
        "INSTAGRAM_PUBLISH_REQUIRE_VIDEO_QC": "instagram_publish_require_video_qc",
        "INSTAGRAM_PUBLISH_AUTO_VIDEO_FALLBACK_ENABLED": "instagram_publish_auto_video_fallback_enabled",
        "INSTAGRAM_PUBLISH_PREFLIGHT_TARGETS_ENABLED": "instagram_publish_preflight_targets_enabled",
        "INSTAGRAM_PUBLISH_PREFLIGHT_TARGETS_STRICT": "instagram_publish_preflight_targets_strict",
        "INSTAGRAM_QUALITY_REJECT_DELETE_ASSETS": "instagram_quality_reject_delete_assets",
        "INSTAGRAM_QUALITY_SWEEP_ENABLED": "instagram_quality_sweep_enabled",
        "INSTAGRAM_OVERLAY_SHORT_TEXT_ENABLED": "instagram_overlay_short_text_enabled",
        "INSTAGRAM_QR_OVERLAY_ENABLED": "instagram_qr_overlay_enabled",
        "INSTAGRAM_OPENAI_USE_INTERLEAVING": "instagram_openai_use_interleaving",
        "INSTAGRAM_SEQUENTIAL_IMAGE_LIBRARY": "instagram_sequential_image_library",
        "INSTAGRAM_LIBRARY_SYNC_FROM_DRAFTS": "instagram_library_sync_from_drafts",
    }
    for env_key, config_key in bool_map.items():
        if os.getenv(env_key):
            data[config_key] = os.getenv(env_key).lower() == "true"

    float_map = {
        "BACKGROUND_MUSIC_LEVEL": "background_music_level",
        "OPENAI_TTS_SPEED": "openai_tts_speed",
        "COMFYUI_POLL_SECONDS": "comfyui_poll_seconds",
        "INSTAGRAM_OPENAI_MONTHLY_BUDGET_USD": "instagram_openai_monthly_budget_usd",
        "INSTAGRAM_OPENAI_IMAGE_ESTIMATED_COST_USD": "instagram_openai_image_estimated_cost_usd",
    }
    for env_key, config_key in float_map.items():
        if os.getenv(env_key):
            data[config_key] = float(os.getenv(env_key))

    int_map = {
        "PUBLISH_MIN_SCORE": "publish_min_score",
        "COMFYUI_TIMEOUT_SECONDS": "comfyui_timeout_seconds",
        "OPENAI_SCENE_MAX_IMAGES": "openai_scene_max_images",
        "MARKETING_MIN_SCORE": "marketing_min_score",
        "MARKETING_MAX_ITERATIONS": "marketing_max_iterations",
        "CONTINUITY_MIN_SCORE": "continuity_min_score",
        "CONTINUITY_MAX_REGENERATIONS": "continuity_max_regenerations",
        "MAX_VARIANT_CANDIDATES": "max_variant_candidates",
        "INSTAGRAM_RECENT_MEDIA_LIMIT": "instagram_recent_media_limit",
        "INSTAGRAM_POST_INTERVAL_MINUTES": "instagram_post_interval_minutes",
        "INSTAGRAM_PLAN_HORIZON_HOURS": "instagram_plan_horizon_hours",
        "INSTAGRAM_SHORT_TEXT_MAX_CHARS": "instagram_short_text_max_chars",
        "INSTAGRAM_ASSET_ROTATION_WINDOW": "instagram_asset_rotation_window",
        "INSTAGRAM_ASSET_CATEGORY_ROTATION_WINDOW": "instagram_asset_category_rotation_window",
        "INSTAGRAM_VIDEO_DURATION_SECONDS": "instagram_video_duration_seconds",
        "INSTAGRAM_OPENAI_MAX_GENERATION_ATTEMPTS": "instagram_openai_max_generation_attempts",
        "INSTAGRAM_PUBLISH_QUALITY_MIN_SCORE": "instagram_publish_quality_min_score",
        "INSTAGRAM_PUBLISH_QUALITY_MAX_REGENERATIONS": "instagram_publish_quality_max_regenerations",
        "INSTAGRAM_PUBLISH_QUALITY_MAX_ATTEMPTS": "instagram_publish_quality_max_attempts",
        "INSTAGRAM_PUBLISH_QUALITY_BURST_MAX_ATTEMPTS": "instagram_publish_quality_burst_max_attempts",
        "INSTAGRAM_PUBLISH_VIDEO_FAILURE_COOLDOWN_MINUTES": "instagram_publish_video_failure_cooldown_minutes",
        "INSTAGRAM_QUALITY_REJECT_KEEP_MIN_PASS_ASSETS_PER_CATEGORY": "instagram_quality_reject_keep_min_pass_assets_per_category",
        "INSTAGRAM_QUALITY_SWEEP_INTERVAL_MINUTES": "instagram_quality_sweep_interval_minutes",
        "INSTAGRAM_ANTISPAM_COOLDOWN_MINUTES": "instagram_antispam_cooldown_minutes",
    }
    for env_key, config_key in int_map.items():
        if os.getenv(env_key):
            data[config_key] = int(os.getenv(env_key))

    if os.getenv("METRICOOL_CSV_PATH"):
        data["metricool_csv_path"] = os.getenv("METRICOOL_CSV_PATH")

    data["ollama_executable"] = _detect_ollama_executable()
    return AppSettings(**data)



