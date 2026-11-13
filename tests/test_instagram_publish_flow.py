import json
from pathlib import Path

from PIL import Image
import pytest

import conecta_video_ai.pipelines as pipelines
from conecta_video_ai.pipelines import StudioService
from conecta_video_ai.settings import AppSettings


class _FakeEngine:
    def __init__(self, *, draft_path: Path, post_image_path: Path, story_image_path: Path):
        self.draft_path = draft_path
        self.post_image_path = post_image_path
        self.story_image_path = story_image_path

    def get_draft(self, draft_id: str) -> dict:
        return json.loads(self.draft_path.read_text(encoding="utf-8"))

    def ensure_publish_image_variants(self, *, draft: dict) -> dict:
        return {
            "generated_at": "2026-01-01T00:00:00Z",
            "source_image_path": str(draft.get("image_path")),
            "post_image_path": str(self.post_image_path),
            "story_image_path": str(self.story_image_path),
            "post_image_qc": {"passed": True, "score": 100},
            "story_image_qc": {"passed": True, "score": 100},
        }

    def simulate_publish(self, draft_id: str) -> dict:
        raise AssertionError("No se esperaba ruta simulada")


class _FakePublisher:
    last_instance = None

    def __init__(self, settings):
        self.post_urls: list[str] = []
        self.story_urls: list[str] = []
        _FakePublisher.last_instance = self

    def remote_url_reachable(self, url: str):
        return True, "ok"

    def publish_image_post(self, *, image_url: str, caption: str) -> dict:
        self.post_urls.append(image_url)
        return {
            "channel": "instagram_graph",
            "status": "published",
            "creation_id": "c-post",
            "post_id": "post-1",
            "url": "https://instagram.test/post-1",
            "media_type": "IMAGE",
            "published_at": "2026-01-01T00:00:00Z",
            "raw_media": {},
        }

    def publish_story_image(self, *, image_url: str) -> dict:
        self.story_urls.append(image_url)
        return {
            "channel": "instagram_graph_story",
            "status": "published",
            "creation_id": "c-story",
            "post_id": "story-1",
            "url": "https://instagram.test/story-1",
            "media_type": "IMAGE",
            "published_at": "2026-01-01T00:00:01Z",
            "raw_media": {},
        }


class _FakePublisherMulti:
    def __init__(
        self,
        settings,
        *,
        access_token: str | None = None,
        page_id: str | None = None,
        ig_user_id: str | None = None,
        graph_version: str | None = None,
    ):
        self.access_token = access_token or settings.meta_access_token or ""
        self.page_id = page_id or settings.meta_page_id or ""
        self.ig_user_id = ig_user_id or settings.meta_instagram_user_id or ""
        self.graph_version = graph_version or settings.meta_graph_version

    def remote_url_reachable(self, url: str):
        return True, "ok"

    def publish_image_post(self, *, image_url: str, caption: str) -> dict:
        return {
            "channel": "instagram_graph",
            "status": "published",
            "creation_id": f"c-post-{self.ig_user_id}",
            "post_id": f"post-{self.ig_user_id}",
            "url": f"https://instagram.test/{self.ig_user_id}/post",
            "media_type": "IMAGE",
            "published_at": "2026-01-01T00:00:00Z",
            "raw_media": {},
        }

    def publish_story_image(self, *, image_url: str) -> dict:
        return {
            "channel": "instagram_graph_story",
            "status": "published",
            "creation_id": f"c-story-{self.ig_user_id}",
            "post_id": f"story-{self.ig_user_id}",
            "url": f"https://instagram.test/{self.ig_user_id}/story",
            "media_type": "IMAGE",
            "published_at": "2026-01-01T00:00:01Z",
            "raw_media": {},
        }

    def publish_facebook_photo(self, *, image_url: str, caption: str) -> dict:
        return {
            "channel": "facebook_graph",
            "status": "published",
            "post_id": f"fb-{self.page_id}",
            "raw": {},
        }


class _FakeEngineAutoCycle:
    def __init__(self):
        self.calls = 0
        self.cleanup_calls = 0

    def auto_cycle_once(self, **kwargs) -> dict:
        self.calls += 1
        if self.calls == 1:
            return {
                "ok": True,
                "draft": {
                    "draft_id": "draft-fail",
                    "image_qc": {"passed": False, "score": 70},
                    "video_qc": {},
                },
            }
        return {
            "ok": True,
            "draft": {
                "draft_id": "draft-pass",
                "image_qc": {"passed": True, "score": 96},
                "video_qc": {},
            },
        }

    def handle_quality_gate_failure(self, *, draft: dict, gate: dict) -> dict:
        self.cleanup_calls += 1
        return {"ok": True, "draft_id": draft.get("draft_id"), "issues": list(gate.get("issues") or [])}


class _AlwaysFailEngineAutoCycle:
    def __init__(self):
        self.calls = 0
        self.cleanup_calls = 0

    def auto_cycle_once(self, **kwargs) -> dict:
        self.calls += 1
        return {
            "ok": True,
            "draft": {
                "draft_id": f"draft-fail-{self.calls}",
                "image_qc": {"passed": False, "score": 70},
                "video_qc": {},
            },
        }

    def handle_quality_gate_failure(self, *, draft: dict, gate: dict) -> dict:
        self.cleanup_calls += 1
        return {"ok": True, "draft_id": draft.get("draft_id"), "issues": list(gate.get("issues") or [])}


def test_publish_instagram_draft_uses_distinct_post_and_story_image_variants(monkeypatch, tmp_path: Path):
    draft_dir = tmp_path / "draft_1"
    draft_dir.mkdir(parents=True, exist_ok=True)

    source_image = draft_dir / "image.jpg"
    post_image = draft_dir / "publish_variants" / "image_post_feed.jpg"
    story_image = draft_dir / "publish_variants" / "image_story.jpg"
    post_image.parent.mkdir(parents=True, exist_ok=True)

    Image.new("RGB", (1080, 1920), color=(240, 230, 200)).save(source_image, format="JPEG", quality=95)
    Image.new("RGB", (1080, 1350), color=(230, 220, 180)).save(post_image, format="JPEG", quality=95)
    Image.new("RGB", (1080, 1920), color=(220, 210, 170)).save(story_image, format="JPEG", quality=95)

    draft_payload = {
        "draft_id": "draft_1",
        "draft_dir": str(draft_dir),
        "status": "draft",
        "caption": "ConectaProIA: encuentra contactos. El servicio lo cobra cada profesional. WhatsApp: https://wa.me/56983434503",
        "hook": "Hook",
        "value": "Value",
        "cta": "CTA",
        "image_path": str(source_image),
        "image_source": "openai_image",
        "video_path": "",
        "image_qc": {"passed": True, "score": 100},
        "video_qc": {},
    }
    draft_json_path = draft_dir / "draft.json"
    draft_json_path.write_text(json.dumps(draft_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    settings = AppSettings(
        instagram_whatsapp_client_url="https://wa.me/56983434503",
        instagram_whatsapp_provider_url="https://wa.me/56961903199",
        output_root=tmp_path / "output",
        tracking_root=tmp_path / "tracking",
        context_path=tmp_path / "context.yaml",
        assets_root=tmp_path / "assets",
        meta_access_token="tok_primary",
        meta_page_id="page_primary",
        meta_instagram_user_id="ig_primary",
        instagram_publish_media_mode="image_only",
        instagram_crosspost_facebook=False,
        instagram_publish_quality_gate_enabled=True,
        instagram_publish_require_video_qc=False,
    )

    service = StudioService.__new__(StudioService)
    service.settings = settings
    service.instagram_engine = _FakeEngine(
        draft_path=draft_json_path,
        post_image_path=post_image,
        story_image_path=story_image,
    )

    monkeypatch.setattr(pipelines, "InstagramGraphPublisher", _FakePublisher)

    def _resolve_public_url(*, settings, image_path: Path, explicit_public_url: str | None = None) -> str:
        return f"https://cdn.test/{Path(image_path).name}"

    monkeypatch.setattr(pipelines, "resolve_public_image_url", _resolve_public_url)

    published = service.publish_instagram_draft(draft_id="draft_1", simulate=False)
    assert published["status"] == "published"

    fake_pub = _FakePublisher.last_instance
    assert fake_pub is not None
    assert fake_pub.post_urls == ["https://cdn.test/image_post_feed.jpg"]
    assert fake_pub.story_urls == ["https://cdn.test/image_story.jpg"]

    stored = json.loads(draft_json_path.read_text(encoding="utf-8"))
    assert stored["public_image_url"] == "https://cdn.test/image_post_feed.jpg"
    assert stored["public_image_story_url"] == "https://cdn.test/image_story.jpg"


@pytest.mark.parametrize(
    ("format_type", "expected_posts", "expected_stories"),
    [
        ("feed", 1, 0),
        ("story", 0, 1),
    ],
)
def test_publish_instagram_draft_respects_feed_or_story_channel(
    monkeypatch,
    tmp_path: Path,
    format_type: str,
    expected_posts: int,
    expected_stories: int,
):
    draft_dir = tmp_path / f"draft_{format_type}"
    draft_dir.mkdir(parents=True, exist_ok=True)
    source_image = draft_dir / "image.jpg"
    post_image = draft_dir / "image_post_feed.jpg"
    story_image = draft_dir / "image_story.jpg"
    Image.new("RGB", (1080, 1350), color=(210, 220, 230)).save(source_image, format="JPEG")
    Image.new("RGB", (1080, 1350), color=(220, 210, 230)).save(post_image, format="JPEG")
    Image.new("RGB", (1080, 1920), color=(230, 210, 220)).save(story_image, format="JPEG")
    draft_path = draft_dir / "draft.json"
    draft_path.write_text(
        json.dumps(
            {
                "draft_id": f"draft_{format_type}",
                "draft_dir": str(draft_dir),
                "status": "draft",
                "format_type": format_type,
                "caption": "ConectaProIA: encuentra contactos. El servicio lo cobra cada profesional. WhatsApp: https://wa.me/56983434503",
                "image_path": str(source_image),
                "video_path": "",
                "image_qc": {"passed": True, "score": 100},
                "video_qc": {},
            }
        ),
        encoding="utf-8",
    )
    settings = AppSettings(
        instagram_whatsapp_client_url="https://wa.me/56983434503",
        instagram_whatsapp_provider_url="https://wa.me/56961903199",
        output_root=tmp_path / "output",
        tracking_root=tmp_path / "tracking",
        context_path=tmp_path / "context.yaml",
        assets_root=tmp_path / "assets",
        meta_access_token="tok_primary",
        meta_page_id="page_primary",
        meta_instagram_user_id="ig_primary",
        instagram_publish_media_mode="image_only",
        instagram_crosspost_facebook=False,
        instagram_publish_quality_gate_enabled=False,
    )
    service = StudioService.__new__(StudioService)
    service.settings = settings
    service.instagram_engine = _FakeEngine(
        draft_path=draft_path,
        post_image_path=post_image,
        story_image_path=story_image,
    )
    monkeypatch.setattr(pipelines, "InstagramGraphPublisher", _FakePublisher)
    monkeypatch.setattr(
        pipelines,
        "resolve_public_image_url",
        lambda *, settings, image_path, explicit_public_url=None: f"https://cdn.test/{Path(image_path).name}",
    )

    service.publish_instagram_draft(draft_id=f"draft_{format_type}", simulate=False)
    fake_pub = _FakePublisher.last_instance
    assert len(fake_pub.post_urls) == expected_posts
    assert len(fake_pub.story_urls) == expected_stories


def test_run_instagram_auto_cycle_retries_after_quality_reject_and_cleans_once(tmp_path: Path):
    settings = AppSettings(
        instagram_whatsapp_client_url="https://wa.me/56983434503",
        instagram_whatsapp_provider_url="https://wa.me/56961903199",
        output_root=tmp_path / "output",
        tracking_root=tmp_path / "tracking",
        context_path=tmp_path / "context.yaml",
        assets_root=tmp_path / "assets",
        instagram_publish_quality_gate_enabled=True,
        instagram_publish_quality_min_score=90,
        instagram_publish_require_video_qc=False,
        instagram_publish_quality_max_regenerations=0,
        instagram_publish_quality_max_attempts=3,
    )

    service = StudioService.__new__(StudioService)
    service.settings = settings
    service.instagram_engine = _FakeEngineAutoCycle()

    result = service.run_instagram_auto_cycle(
        publish=False,
        simulate_publish=False,
        use_meta_history=False,
    )

    assert result["quality_gate"]["passed"] is True
    assert int(result["quality_regeneration_attempt"]) == 1
    assert service.instagram_engine.calls == 2
    assert service.instagram_engine.cleanup_calls == 1


def test_run_instagram_auto_cycle_caps_quality_attempt_bursts(tmp_path: Path):
    settings = AppSettings(
        instagram_whatsapp_client_url="https://wa.me/56983434503",
        instagram_whatsapp_provider_url="https://wa.me/56961903199",
        output_root=tmp_path / "output",
        tracking_root=tmp_path / "tracking",
        context_path=tmp_path / "context.yaml",
        assets_root=tmp_path / "assets",
        instagram_publish_quality_gate_enabled=True,
        instagram_publish_quality_min_score=90,
        instagram_publish_require_video_qc=False,
        instagram_publish_quality_max_regenerations=0,
        instagram_publish_quality_max_attempts=12,
        instagram_publish_quality_burst_max_attempts=3,
    )

    service = StudioService.__new__(StudioService)
    service.settings = settings
    service.instagram_engine = _AlwaysFailEngineAutoCycle()

    with pytest.raises(Exception, match=r"tras 3 intentos"):
        service.run_instagram_auto_cycle(
            publish=False,
            simulate_publish=False,
            use_meta_history=False,
        )

    assert service.instagram_engine.calls == 3
    assert service.instagram_engine.cleanup_calls == 3


def test_quality_gate_is_channel_specific_for_feed_and_story(tmp_path: Path):
    settings = AppSettings(
        instagram_whatsapp_client_url="https://wa.me/56983434503",
        instagram_whatsapp_provider_url="https://wa.me/56961903199",
        output_root=tmp_path / "output",
        tracking_root=tmp_path / "tracking",
        context_path=tmp_path / "context.yaml",
        assets_root=tmp_path / "assets",
        instagram_publish_quality_gate_enabled=True,
        instagram_publish_quality_min_score=90,
        instagram_publish_require_video_qc=False,
    )
    service = StudioService.__new__(StudioService)
    service.settings = settings

    feed_gate = service._evaluate_instagram_quality_gate(
        {
            "format_type": "feed",
            "publish_media": {
                "post_image_qc": {"passed": True, "score": 96},
                "story_image_qc": {"passed": False, "score": 82},
            },
            "video_qc": {},
        }
    )
    assert feed_gate["passed"] is True
    assert feed_gate["issues"] == []
    assert "post" in (feed_gate.get("required_image_channels") or [])
    assert "story" not in (feed_gate.get("required_image_channels") or [])
    assert any("story_image_qc insuficiente" in w for w in (feed_gate.get("warnings") or []))

    story_gate = service._evaluate_instagram_quality_gate(
        {
            "format_type": "story",
            "publish_media": {
                "post_image_qc": {"passed": False, "score": 82},
                "story_image_qc": {"passed": True, "score": 96},
            },
            "video_qc": {},
        }
    )
    assert story_gate["passed"] is True
    assert story_gate["issues"] == []
    assert "story" in (story_gate.get("required_image_channels") or [])
    assert "post" not in (story_gate.get("required_image_channels") or [])
    assert any("post_image_qc insuficiente" in w for w in (story_gate.get("warnings") or []))

    reel_gate = service._evaluate_instagram_quality_gate(
        {
            "format_type": "reel",
            "publish_media": {
                "post_image_qc": {"passed": False, "score": 82},
                "story_image_qc": {"passed": True, "score": 96},
            },
            "video_qc": {},
        }
    )
    assert reel_gate["passed"] is False
    assert any("post_image_qc insuficiente" in i for i in (reel_gate.get("issues") or []))


def test_load_instagram_publish_targets_reads_env_bound_targets(monkeypatch, tmp_path: Path):
    cfg_path = tmp_path / "instagram_publish_targets.yaml"
    cfg_path.write_text(
        """
targets:
  - name: dueno_extra
    enabled: true
    publish_instagram: true
    crosspost_facebook: true
    meta_access_token_env: TARGET_META_TOKEN
    meta_page_id_env: TARGET_META_PAGE
    meta_instagram_user_id_env: TARGET_META_IG
    meta_graph_version: v25.0
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("TARGET_META_TOKEN", "tok_extra")
    monkeypatch.setenv("TARGET_META_PAGE", "page_extra")
    monkeypatch.setenv("TARGET_META_IG", "ig_extra")

    settings = AppSettings(
        instagram_whatsapp_client_url="https://wa.me/56983434503",
        instagram_whatsapp_provider_url="https://wa.me/56961903199",
        output_root=tmp_path / "output",
        tracking_root=tmp_path / "tracking",
        context_path=tmp_path / "context.yaml",
        assets_root=tmp_path / "assets",
        meta_access_token="tok_primary",
        meta_page_id="page_primary",
        meta_instagram_user_id="ig_primary",
        meta_graph_version="v25.0",
        instagram_publish_targets_path=cfg_path,
    )
    service = StudioService.__new__(StudioService)
    service.settings = settings

    targets = service._load_instagram_publish_targets()
    assert len(targets) == 2
    assert targets[0]["is_primary"] is True
    assert targets[0]["meta_instagram_user_id"] == "ig_primary"
    assert targets[1]["name"] == "dueno_extra"
    assert targets[1]["meta_access_token"] == "tok_extra"
    assert targets[1]["meta_page_id"] == "page_extra"
    assert targets[1]["meta_instagram_user_id"] == "ig_extra"


def test_publish_instagram_draft_replicates_to_multiple_targets(monkeypatch, tmp_path: Path):
    draft_dir = tmp_path / "draft_multi"
    draft_dir.mkdir(parents=True, exist_ok=True)

    source_image = draft_dir / "image.jpg"
    post_image = draft_dir / "publish_variants" / "image_post_feed.jpg"
    story_image = draft_dir / "publish_variants" / "image_story.jpg"
    post_image.parent.mkdir(parents=True, exist_ok=True)

    Image.new("RGB", (1080, 1920), color=(210, 220, 230)).save(source_image, format="JPEG", quality=95)
    Image.new("RGB", (1080, 1350), color=(220, 210, 230)).save(post_image, format="JPEG", quality=95)
    Image.new("RGB", (1080, 1920), color=(230, 210, 220)).save(story_image, format="JPEG", quality=95)

    draft_payload = {
        "draft_id": "draft_multi",
        "draft_dir": str(draft_dir),
        "status": "draft",
        "caption": "ConectaProIA: encuentra contactos. El servicio lo cobra cada profesional. WhatsApp: https://wa.me/56983434503",
        "hook": "Hook",
        "value": "Value",
        "cta": "CTA",
        "image_path": str(source_image),
        "video_path": "",
        "image_qc": {"passed": True, "score": 100},
        "video_qc": {},
    }
    draft_json_path = draft_dir / "draft.json"
    draft_json_path.write_text(json.dumps(draft_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    targets_path = tmp_path / "instagram_publish_targets.yaml"
    targets_path.write_text(
        """
targets:
  - name: dueno_extra
    enabled: true
    publish_instagram: true
    crosspost_facebook: true
    publish_facebook_story: false
    meta_access_token_env: TARGET2_TOKEN
    meta_page_id_env: TARGET2_PAGE
    meta_instagram_user_id_env: TARGET2_IG
    meta_graph_version: v25.0
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("TARGET2_TOKEN", "tok_2")
    monkeypatch.setenv("TARGET2_PAGE", "page_2")
    monkeypatch.setenv("TARGET2_IG", "ig_2")

    settings = AppSettings(
        instagram_whatsapp_client_url="https://wa.me/56983434503",
        instagram_whatsapp_provider_url="https://wa.me/56961903199",
        output_root=tmp_path / "output",
        tracking_root=tmp_path / "tracking",
        context_path=tmp_path / "context.yaml",
        assets_root=tmp_path / "assets",
        meta_access_token="tok_1",
        meta_page_id="page_1",
        meta_instagram_user_id="ig_1",
        meta_graph_version="v25.0",
        instagram_publish_targets_path=targets_path,
        instagram_publish_media_mode="image_only",
        instagram_crosspost_facebook=True,
        instagram_publish_quality_gate_enabled=True,
        instagram_publish_require_video_qc=False,
    )

    service = StudioService.__new__(StudioService)
    service.settings = settings
    service.instagram_engine = _FakeEngine(
        draft_path=draft_json_path,
        post_image_path=post_image,
        story_image_path=story_image,
    )

    monkeypatch.setattr(pipelines, "InstagramGraphPublisher", _FakePublisherMulti)

    def _resolve_public_url(*, settings, image_path: Path, explicit_public_url: str | None = None) -> str:
        return f"https://cdn.test/{Path(image_path).name}"

    monkeypatch.setattr(pipelines, "resolve_public_image_url", _resolve_public_url)

    published = service.publish_instagram_draft(draft_id="draft_multi", simulate=False)
    assert published["status"] == "published"

    stored = json.loads(draft_json_path.read_text(encoding="utf-8"))
    assert stored["post_id"] == "post-ig_1"
    assert stored["story_id"] == "story-ig_1"
    assert stored["published_targets_count"] == 2
    rows = stored.get("multi_account_publications") or []
    assert len(rows) == 2
    assert rows[0]["target"] == "principal"
    assert rows[1]["target"] == "dueno_extra"
    assert rows[1]["facebook_publication"]["status"] == "published"


def test_quality_gate_auto_mode_warns_but_does_not_block_on_video_qc(tmp_path: Path):
    video_path = tmp_path / "draft_video.mp4"
    video_path.write_bytes(b"fake-video")
    settings = AppSettings(
        instagram_whatsapp_client_url="https://wa.me/56983434503",
        instagram_whatsapp_provider_url="https://wa.me/56961903199",
        output_root=tmp_path / "output",
        tracking_root=tmp_path / "tracking",
        context_path=tmp_path / "context.yaml",
        assets_root=tmp_path / "assets",
        instagram_publish_media_mode="auto",
        instagram_publish_quality_gate_enabled=True,
        instagram_publish_quality_min_score=90,
        instagram_publish_require_video_qc=True,
    )
    service = StudioService.__new__(StudioService)
    service.settings = settings

    gate = service._evaluate_instagram_quality_gate(
        {
            "format_type": "feed",
            "publish_media": {
                "post_image_qc": {"passed": True, "score": 95},
                "story_image_qc": {"passed": True, "score": 95},
            },
            "video_path": str(video_path),
            "video_qc": {"passed": False, "score": 40},
        }
    )
    assert gate["passed"] is True
    assert gate["video_required"] is False
    assert any("video_qc no aprobado" in w for w in (gate.get("warnings") or []))


def test_run_instagram_auto_cycle_falls_back_to_image_only_after_publish_error(tmp_path: Path):
    class _PassEngine:
        def __init__(self):
            self.calls = 0

        def auto_cycle_once(self, **kwargs) -> dict:
            self.calls += 1
            return {
                "ok": True,
                "draft": {
                    "draft_id": "draft-pass",
                    "image_qc": {"passed": True, "score": 96},
                    "video_qc": {},
                },
            }

        def handle_quality_gate_failure(self, *, draft: dict, gate: dict) -> dict:
            raise AssertionError("No se esperaba limpieza por quality gate")

    settings = AppSettings(
        instagram_whatsapp_client_url="https://wa.me/56983434503",
        instagram_whatsapp_provider_url="https://wa.me/56961903199",
        output_root=tmp_path / "output",
        tracking_root=tmp_path / "tracking",
        context_path=tmp_path / "context.yaml",
        assets_root=tmp_path / "assets",
        instagram_state_path=tmp_path / "output" / "instagram" / "state.json",
        instagram_publish_media_mode="auto",
        instagram_publish_quality_gate_enabled=True,
        instagram_publish_require_video_qc=False,
        instagram_publish_auto_video_fallback_enabled=True,
    )

    service = StudioService.__new__(StudioService)
    service.settings = settings
    service.instagram_engine = _PassEngine()

    publish_modes: list[str] = []

    def _fake_publish(**kwargs):
        publish_modes.append(str(service.settings.instagram_publish_media_mode))
        if len(publish_modes) == 1:
            raise Exception("video publish failed")
        return {
            "post_id": "post-1",
            "post_url": "https://instagram.test/post-1",
            "story_id": "story-1",
            "story_url": "https://instagram.test/story-1",
            "published_at": "2026-01-01T00:00:00Z",
        }

    service.publish_instagram_draft = _fake_publish  # type: ignore[method-assign]

    out = service.run_instagram_auto_cycle(
        publish=True,
        simulate_publish=False,
        use_meta_history=False,
    )

    assert out["publication"]["status"] == "ok"
    assert out["publication"]["fallback_used"] is True
    assert publish_modes == ["auto", "image_only"]
    assert service.settings.instagram_publish_media_mode == "auto"


def test_preflight_targets_disables_instagram_when_page_linked_ig_differs(tmp_path: Path):
    settings = AppSettings(
        instagram_whatsapp_client_url="https://wa.me/56983434503",
        instagram_whatsapp_provider_url="https://wa.me/56961903199",
        output_root=tmp_path / "output",
        tracking_root=tmp_path / "tracking",
        context_path=tmp_path / "context.yaml",
        assets_root=tmp_path / "assets",
        instagram_publish_preflight_targets_enabled=True,
        instagram_publish_preflight_targets_strict=False,
    )
    service = StudioService.__new__(StudioService)
    service.settings = settings

    class _IdentityPublisher:
        def inspect_page_identity(self):
            return {
                "page_id": "page_1",
                "page_name": "Page 1",
                "is_owned": True,
                "linked_instagram_user_id": "ig_linked",
                "linked_instagram_username": "page_linked",
            }

    service._build_instagram_publisher = lambda target: _IdentityPublisher()  # type: ignore[method-assign]

    selected, report = service._preflight_publish_targets(
        [
            {
                "name": "principal",
                "is_primary": True,
                "meta_access_token": "tok",
                "meta_page_id": "page_1",
                "meta_instagram_user_id": "ig_configured",
                "publish_instagram": True,
                "crosspost_facebook": True,
            }
        ]
    )

    assert len(selected) == 1
    assert selected[0]["publish_instagram"] is False
    assert selected[0]["crosspost_facebook"] is True
    rows = report.get("reports") or []
    assert rows and rows[0]["status"] == "instagram_disabled_link_mismatch"
