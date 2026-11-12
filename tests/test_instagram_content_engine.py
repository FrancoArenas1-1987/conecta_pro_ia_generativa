import json
from pathlib import Path
import wave
import yaml
from PIL import Image, ImageDraw

from conecta_video_ai.assets import AssetLibrary
from conecta_video_ai.instagram_content_engine import InstagramContentEngine
from conecta_video_ai.models import BrandContext, VisualIdentity, VoiceProfile
from conecta_video_ai.providers import OllamaProvider
from conecta_video_ai.settings import AppSettings


class _FakeOpenAIImageProvider:
    def generate_image(self, prompt: str, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (1080, 1920), color=(120, 80, 150)).save(output_path)


def _context(tmp_path: Path) -> BrandContext:
    qr = tmp_path / "qr_conectapro_reel.png"
    Image.new("RGB", (1024, 1024), color=(255, 255, 255)).save(qr)

    return BrandContext(
        company_name="ConectaProIA",
        tagline="Conexion confiable por WhatsApp",
        mission="Mision",
        positioning={"core_value": "x", "differentiation": ["y"]},
        brand_promises=["No compartimos datos"],
        audience=["personas"],
        voice=VoiceProfile(tone="claro", style=["simple"], avoid=["promesas absolutas"]),
        key_messages=["WhatsApp"],
        legal_safety=["intermediario"],
        service_scope="Biobio",
        call_to_action="Hablar por WhatsApp ahora",
        whatsapp_url="https://wa.me/56983434503",
        website_url="https://conectaproia.cl",
        logo_candidates=[],
        whatsapp_qr_path=str(qr),
        visual_identity=VisualIdentity(
            primary_color="#0B132B",
            secondary_color="#1C2541",
            accent_color="#5BC0BE",
            text_color="#FFFFFF",
        ),
    )


def _instagram_paths(output_root: Path) -> dict[str, Path]:
    return {
        "instagram_plan_path": output_root / "instagram" / "catalog" / "publication_plan.json",
        "instagram_openai_budget_path": output_root / "instagram" / "budget" / "openai_image_usage.json",
        "instagram_asset_catalog_path": output_root / "instagram" / "catalog" / "asset_catalog.json",
    }


def test_instagram_auto_cycle_generates_local_drafts(tmp_path: Path):
    assets_root = tmp_path / "assets"
    assets_root.mkdir(parents=True, exist_ok=True)

    output_root = tmp_path / "output" / "runs"
    publish_assets_root = output_root / "instagram" / "publish_assets"
    (publish_assets_root / "gasfiteria").mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (1080, 1350), color=(45, 90, 180)).save(publish_assets_root / "gasfiteria" / "template.png")
    settings = AppSettings(
        output_root=output_root,
        tracking_root=tmp_path / "tracking",
        context_path=tmp_path / "context.yaml",
        assets_root=assets_root,
        instagram_categories_path=Path("config/instagram_publication_categories.yaml"),
        instagram_drafts_root=output_root / "instagram" / "drafts",
        instagram_catalog_path=output_root / "instagram" / "catalog" / "publication_catalog.json",
        instagram_state_path=output_root / "instagram" / "state.json",
        instagram_publish_assets_root=publish_assets_root,
        **_instagram_paths(output_root),
        instagram_enable_openai_images=False,
        instagram_require_ai_image=False,
        instagram_branding_required=False,
        instagram_simulate_publish=True,
        meta_access_token="",
        meta_page_id="",
    )

    engine = InstagramContentEngine(
        settings=settings,
        context=_context(tmp_path),
        provider=OllamaProvider(model="dummy", executable="ollama"),
        asset_library=AssetLibrary(assets_root),
        openai_image_provider=None,
    )

    catalog = engine.build_publication_catalog(use_meta_history=False)
    assert catalog["generated_at"]
    assert settings.instagram_catalog_path.exists()

    result = engine.auto_cycle_once(
        use_meta_history=False,
        publish=True,
        simulate_publish=True,
        force_category="gasfiteria",
    )
    assert result["ok"] is True

    draft = result["draft"]
    assert draft["draft_id"]
    assert draft["status"] == "simulated_published"
    assert draft["image_url"] is not None
    assert isinstance(draft.get("image_qc"), dict)
    assert "score" in (draft.get("image_qc") or {})

    draft_dir = Path(draft["draft_dir"])
    assert (draft_dir / "draft.json").exists()
    assert (draft_dir / "caption.txt").exists()
    assert (draft_dir / "short_text.txt").exists()

    listed = engine.list_drafts(limit=5)
    assert len(listed) >= 1


def test_sequential_flat_library_advances_only_after_publish(tmp_path: Path):
    assets_root = tmp_path / "assets"
    assets_root.mkdir(parents=True, exist_ok=True)
    output_root = tmp_path / "output" / "runs"
    image_library = tmp_path / "imagenes_ig"
    image_library.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (1080, 1350), color=(10, 20, 30)).save(image_library / "01_primera.jpg")
    Image.new("RGB", (1080, 1350), color=(40, 50, 60)).save(image_library / "02_segunda.jpg")

    settings = AppSettings(
        output_root=output_root,
        tracking_root=tmp_path / "tracking",
        context_path=tmp_path / "context.yaml",
        assets_root=assets_root,
        instagram_categories_path=Path("config/instagram_publication_categories.yaml"),
        instagram_drafts_root=output_root / "instagram" / "drafts",
        instagram_catalog_path=output_root / "instagram" / "catalog" / "publication_catalog.json",
        instagram_state_path=output_root / "instagram" / "state.json",
        instagram_publish_assets_root=image_library,
        **_instagram_paths(output_root),
        instagram_enable_openai_images=False,
        instagram_require_ai_image=False,
        instagram_branding_required=False,
        instagram_simulate_publish=True,
        instagram_generate_video_from_image=False,
        instagram_sequential_image_library=True,
        instagram_library_sync_from_drafts=False,
        meta_access_token="",
        meta_page_id="",
    )

    engine = InstagramContentEngine(
        settings=settings,
        context=_context(tmp_path),
        provider=OllamaProvider(model="dummy", executable="ollama"),
        asset_library=AssetLibrary(assets_root),
        openai_image_provider=None,
    )

    draft_only = engine.auto_cycle_once(
        use_meta_history=False,
        publish=False,
        simulate_publish=True,
        force_category="general",
    )["draft"]
    assert draft_only["asset_rel_path"] == "01_primera.jpg"
    assert engine._load_state()["image_sequence_index"] == 0

    first_published = engine.auto_cycle_once(
        use_meta_history=False,
        publish=True,
        simulate_publish=True,
        force_category="general",
    )["draft"]
    assert first_published["asset_rel_path"] == "01_primera.jpg"
    assert engine._load_state()["image_sequence_index"] == 1

    second_published = engine.auto_cycle_once(
        use_meta_history=False,
        publish=True,
        simulate_publish=True,
        force_category="general",
    )["draft"]
    assert second_published["asset_rel_path"] == "02_segunda.jpg"
    assert engine._load_state()["image_sequence_index"] == 0


def test_sequential_library_restarts_when_previous_published_file_was_removed(tmp_path: Path):
    assets_root = tmp_path / "assets"
    assets_root.mkdir(parents=True, exist_ok=True)
    output_root = tmp_path / "output" / "runs"
    image_library = tmp_path / "imagenes_ig"
    image_library.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (1080, 1350), color=(10, 20, 30)).save(image_library / "01_primera.jpg")
    Image.new("RGB", (1080, 1350), color=(40, 50, 60)).save(image_library / "02_segunda.jpg")

    settings = AppSettings(
        output_root=output_root,
        tracking_root=tmp_path / "tracking",
        context_path=tmp_path / "context.yaml",
        assets_root=assets_root,
        instagram_categories_path=Path("config/instagram_publication_categories.yaml"),
        instagram_drafts_root=output_root / "instagram" / "drafts",
        instagram_catalog_path=output_root / "instagram" / "catalog" / "publication_catalog.json",
        instagram_state_path=output_root / "instagram" / "state.json",
        instagram_publish_assets_root=image_library,
        **_instagram_paths(output_root),
        instagram_enable_openai_images=False,
        instagram_require_ai_image=False,
        instagram_branding_required=False,
        instagram_generate_video_from_image=False,
        instagram_sequential_image_library=True,
        instagram_library_sync_from_drafts=False,
    )
    engine = InstagramContentEngine(
        settings=settings,
        context=_context(tmp_path),
        provider=OllamaProvider(model="dummy", executable="ollama"),
        asset_library=AssetLibrary(assets_root),
        openai_image_provider=None,
    )
    engine._sync_asset_catalog()

    item, meta = engine._next_sequential_image(
        {
            "image_sequence_index": 1,
            "last_sequence_published_asset_key": str(image_library / "archivo_eliminado.jpg").lower(),
        }
    )
    assert item.path.name == "01_primera.jpg"
    assert meta["asset_sequence_index"] == 0


def test_instagram_ai_image_is_saved_in_category_pool(tmp_path: Path):
    assets_root = tmp_path / "assets"
    assets_root.mkdir(parents=True, exist_ok=True)

    output_root = tmp_path / "output" / "runs"
    publish_assets_root = output_root / "instagram" / "publish_assets"
    settings = AppSettings(
        output_root=output_root,
        tracking_root=tmp_path / "tracking",
        context_path=tmp_path / "context.yaml",
        assets_root=assets_root,
        instagram_categories_path=Path("config/instagram_publication_categories.yaml"),
        instagram_drafts_root=output_root / "instagram" / "drafts",
        instagram_catalog_path=output_root / "instagram" / "catalog" / "publication_catalog.json",
        instagram_state_path=output_root / "instagram" / "state.json",
        instagram_publish_assets_root=publish_assets_root,
        **_instagram_paths(output_root),
        instagram_enable_openai_images=True,
        instagram_require_ai_image=True,
        instagram_openai_monthly_budget_usd=10.0,
        instagram_openai_image_estimated_cost_usd=0.1,
        instagram_branding_required=False,
        instagram_simulate_publish=True,
        meta_access_token="",
        meta_page_id="",
    )

    engine = InstagramContentEngine(
        settings=settings,
        context=_context(tmp_path),
        provider=OllamaProvider(model="dummy", executable="ollama"),
        asset_library=AssetLibrary(assets_root),
        openai_image_provider=_FakeOpenAIImageProvider(),
    )

    result = engine.auto_cycle_once(
        use_meta_history=False,
        publish=False,
        simulate_publish=True,
        force_category="legal",
    )
    draft = result["draft"]

    assert draft["image_source"] == "openai_image"
    assert str(draft["asset_rel_path"]).startswith("legal/")
    assert "/images/" in str(draft["asset_rel_path"])
    assert (publish_assets_root / draft["asset_rel_path"]).exists()
    assert isinstance(draft.get("image_qc"), dict)
    assert int((draft.get("image_qc") or {}).get("score", 0)) > 0





def test_reference_image_drives_new_ai_variant(tmp_path: Path):
    assets_root = tmp_path / "assets"
    assets_root.mkdir(parents=True, exist_ok=True)

    output_root = tmp_path / "output" / "runs"
    publish_assets_root = output_root / "instagram" / "publish_assets"
    (publish_assets_root / "kinesiologia").mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (1080, 1350), color=(45, 170, 160)).save(publish_assets_root / "kinesiologia" / "base.png")

    settings = AppSettings(
        output_root=output_root,
        tracking_root=tmp_path / "tracking",
        context_path=tmp_path / "context.yaml",
        assets_root=assets_root,
        instagram_categories_path=Path("config/instagram_publication_categories.yaml"),
        instagram_drafts_root=output_root / "instagram" / "drafts",
        instagram_catalog_path=output_root / "instagram" / "catalog" / "publication_catalog.json",
        instagram_state_path=output_root / "instagram" / "state.json",
        instagram_publish_assets_root=publish_assets_root,
        **_instagram_paths(output_root),
        instagram_enable_openai_images=True,
        instagram_require_ai_image=True,
        instagram_openai_monthly_budget_usd=10.0,
        instagram_openai_image_estimated_cost_usd=0.1,
        instagram_branding_required=False,
        instagram_simulate_publish=True,
        meta_access_token="",
        meta_page_id="",
    )

    engine = InstagramContentEngine(
        settings=settings,
        context=_context(tmp_path),
        provider=OllamaProvider(model="dummy", executable="ollama"),
        asset_library=AssetLibrary(assets_root),
        openai_image_provider=_FakeOpenAIImageProvider(),
    )

    result = engine.auto_cycle_once(
        use_meta_history=False,
        publish=False,
        simulate_publish=True,
        force_category="kinesiologia",
    )
    draft = result["draft"]
    assert draft["image_source"] == "openai_image"
    assert str(draft["asset_rel_path"]).startswith("kinesiologia/images/openai")
    assert (publish_assets_root / draft["asset_rel_path"]).exists()


def test_budget_block_falls_back_to_library_when_enabled(tmp_path: Path):
    assets_root = tmp_path / "assets"
    assets_root.mkdir(parents=True, exist_ok=True)

    output_root = tmp_path / "output" / "runs"
    publish_assets_root = output_root / "instagram" / "publish_assets"
    (publish_assets_root / "legal").mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (1080, 1350), color=(35, 70, 130)).save(publish_assets_root / "legal" / "base.png")

    settings = AppSettings(
        output_root=output_root,
        tracking_root=tmp_path / "tracking",
        context_path=tmp_path / "context.yaml",
        assets_root=assets_root,
        instagram_categories_path=Path("config/instagram_publication_categories.yaml"),
        instagram_drafts_root=output_root / "instagram" / "drafts",
        instagram_catalog_path=output_root / "instagram" / "catalog" / "publication_catalog.json",
        instagram_state_path=output_root / "instagram" / "state.json",
        instagram_publish_assets_root=publish_assets_root,
        **_instagram_paths(output_root),
        instagram_enable_openai_images=True,
        instagram_require_ai_image=True,
        instagram_ai_library_fallback_enabled=True,
        instagram_openai_monthly_budget_usd=0.05,
        instagram_openai_image_estimated_cost_usd=0.25,
        instagram_branding_required=False,
        instagram_simulate_publish=True,
        meta_access_token="",
        meta_page_id="",
    )

    engine = InstagramContentEngine(
        settings=settings,
        context=_context(tmp_path),
        provider=OllamaProvider(model="dummy", executable="ollama"),
        asset_library=AssetLibrary(assets_root),
        openai_image_provider=_FakeOpenAIImageProvider(),
    )

    result = engine.auto_cycle_once(
        use_meta_history=False,
        publish=False,
        simulate_publish=True,
        force_category="legal",
    )
    draft = result["draft"]
    assert draft["image_source"] in {"category_template", "asset_library"}
    budget_event = engine._read_last_jsonl_event(engine.openai_budget_events_path)
    assert str(budget_event.get("reason") or "") == "budget_cap_reached"


def test_openai_is_used_when_budget_available_even_on_odd_counter(tmp_path: Path):
    assets_root = tmp_path / "assets"
    assets_root.mkdir(parents=True, exist_ok=True)

    output_root = tmp_path / "output" / "runs"
    publish_assets_root = output_root / "instagram" / "publish_assets"
    cat_dir = publish_assets_root / "zzz_tmp"
    cat_dir.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (1080, 1350), color=(35, 70, 130)).save(cat_dir / "base.png")

    settings = AppSettings(
        output_root=output_root,
        tracking_root=tmp_path / "tracking",
        context_path=tmp_path / "context.yaml",
        assets_root=assets_root,
        instagram_categories_path=Path("config/instagram_publication_categories.yaml"),
        instagram_drafts_root=output_root / "instagram" / "drafts",
        instagram_catalog_path=output_root / "instagram" / "catalog" / "publication_catalog.json",
        instagram_state_path=output_root / "instagram" / "state.json",
        instagram_publish_assets_root=publish_assets_root,
        **_instagram_paths(output_root),
        instagram_enable_openai_images=True,
        instagram_require_ai_image=True,
        instagram_ai_library_fallback_enabled=True,
        instagram_openai_monthly_budget_usd=10.0,
        instagram_openai_image_estimated_cost_usd=0.1,
        instagram_openai_use_interleaving=False,
        instagram_branding_required=False,
        instagram_simulate_publish=True,
        meta_access_token="",
        meta_page_id="",
    )

    engine = InstagramContentEngine(
        settings=settings,
        context=_context(tmp_path),
        provider=OllamaProvider(model="dummy", executable="ollama"),
        asset_library=AssetLibrary(assets_root),
        openai_image_provider=_FakeOpenAIImageProvider(),
    )

    out, source, prompt, _meta = engine._generate_base_image(
        category={"id": "zzz_tmp", "label": "Tmp", "objective": "captar_clientes"},
        variant={"hook": "h", "value": "v", "proof": "p", "cta": "c", "short_text": "s"},
        service="servicio",
        locale="Concepción",
        draft_dir=output_root / "instagram" / "drafts" / "tmp1",
        state={"counter": 1},
        objective="captar_clientes",
        format_type="feed",
    )
    assert out.exists()
    assert source == "openai_image"
    assert "openai_skipped=" not in prompt


def test_sync_library_from_drafts_copies_images_and_videos_into_category_media_dirs(tmp_path: Path):
    assets_root = tmp_path / "assets"
    assets_root.mkdir(parents=True, exist_ok=True)

    output_root = tmp_path / "output" / "runs"
    publish_assets_root = output_root / "instagram" / "publish_assets"
    draft_dir = output_root / "instagram" / "drafts" / "d1_legal_story"
    draft_dir.mkdir(parents=True, exist_ok=True)

    image_path = draft_dir / "image.jpg"
    Image.new("RGB", (1080, 1920), color=(220, 210, 190)).save(image_path, format="JPEG", quality=95)
    video_path = draft_dir / "video.mp4"
    video_path.write_bytes(b"fake-mp4-content")
    audio_path = draft_dir / "video_music.wav"
    with wave.open(str(audio_path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(22050)
        wav_file.writeframes(b"\x00\x00" * 22050)

    (draft_dir / "draft.json").write_text(
        json.dumps(
            {
                "draft_id": "d1_legal_story",
                "draft_dir": str(draft_dir),
                "status": "draft",
                "category_id": "legal",
                "format_type": "story",
                "image_path": str(image_path),
                "video_path": str(video_path),
                "video_music_path": str(audio_path),
                "image_source": "asset_library",
                "image_qc": {"passed": True, "score": 92},
                "video_qc": {"passed": True, "score": 90},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    settings = AppSettings(
        output_root=output_root,
        tracking_root=tmp_path / "tracking",
        context_path=tmp_path / "context.yaml",
        assets_root=assets_root,
        instagram_categories_path=Path("config/instagram_publication_categories.yaml"),
        instagram_drafts_root=output_root / "instagram" / "drafts",
        instagram_catalog_path=output_root / "instagram" / "catalog" / "publication_catalog.json",
        instagram_state_path=output_root / "instagram" / "state.json",
        instagram_publish_assets_root=publish_assets_root,
        **_instagram_paths(output_root),
        instagram_enable_openai_images=False,
        instagram_require_ai_image=False,
        instagram_branding_required=False,
        instagram_simulate_publish=True,
        meta_access_token="",
        meta_page_id="",
    )

    engine = InstagramContentEngine(
        settings=settings,
        context=_context(tmp_path),
        provider=OllamaProvider(model="dummy", executable="ollama"),
        asset_library=AssetLibrary(assets_root),
        openai_image_provider=None,
    )

    report = engine.sync_library_from_drafts()
    assert report["ok"] is True
    assert int(report.get("copied_images", 0)) >= 1
    assert int(report.get("copied_videos", 0)) >= 1
    assert int(report.get("copied_audios", 0)) >= 1

    legal_images = list((publish_assets_root / "legal" / "images").glob("*"))
    legal_videos = list((publish_assets_root / "legal" / "videos").glob("*"))
    legal_audios = list((publish_assets_root / "legal" / "audios").glob("*"))
    assert any(p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"} for p in legal_images)
    assert any(p.suffix.lower() in {".mp4", ".mov", ".mkv", ".webm", ".m4v"} for p in legal_videos)
    assert any(p.suffix.lower() in {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"} for p in legal_audios)


def test_sync_library_from_drafts_tolerates_sync_state_write_lock(tmp_path: Path, monkeypatch):
    assets_root = tmp_path / "assets"
    assets_root.mkdir(parents=True, exist_ok=True)

    output_root = tmp_path / "output" / "runs"
    publish_assets_root = output_root / "instagram" / "publish_assets"
    draft_dir = output_root / "instagram" / "drafts" / "d2_general_feed"
    draft_dir.mkdir(parents=True, exist_ok=True)

    image_path = draft_dir / "image.jpg"
    Image.new("RGB", (1080, 1350), color=(210, 210, 210)).save(image_path, format="JPEG", quality=95)
    (draft_dir / "draft.json").write_text(
        json.dumps(
            {
                "draft_id": "d2_general_feed",
                "draft_dir": str(draft_dir),
                "status": "draft",
                "category_id": "general",
                "format_type": "feed",
                "image_path": str(image_path),
                "image_source": "asset_library",
                "image_qc": {"passed": True, "score": 95},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    settings = AppSettings(
        output_root=output_root,
        tracking_root=tmp_path / "tracking",
        context_path=tmp_path / "context.yaml",
        assets_root=assets_root,
        instagram_categories_path=Path("config/instagram_publication_categories.yaml"),
        instagram_drafts_root=output_root / "instagram" / "drafts",
        instagram_catalog_path=output_root / "instagram" / "catalog" / "publication_catalog.json",
        instagram_state_path=output_root / "instagram" / "state.json",
        instagram_publish_assets_root=publish_assets_root,
        **_instagram_paths(output_root),
        instagram_enable_openai_images=False,
        instagram_require_ai_image=False,
        instagram_branding_required=False,
        instagram_simulate_publish=True,
        meta_access_token="",
        meta_page_id="",
    )

    engine = InstagramContentEngine(
        settings=settings,
        context=_context(tmp_path),
        provider=OllamaProvider(model="dummy", executable="ollama"),
        asset_library=AssetLibrary(assets_root),
        openai_image_provider=None,
    )

    def _locked_state_write(_state):
        raise PermissionError("mock lock on state file")

    monkeypatch.setattr(engine, "_save_library_sync_state", _locked_state_write)
    report = engine.sync_library_from_drafts()
    assert report["ok"] is True
    assert any("library_sync_state_write_permission_denied" in str(w) for w in (report.get("warnings") or []))


def test_handle_quality_gate_failure_removes_failed_library_asset_and_draft_dir(tmp_path: Path):
    assets_root = tmp_path / "assets"
    assets_root.mkdir(parents=True, exist_ok=True)

    output_root = tmp_path / "output" / "runs"
    publish_assets_root = output_root / "instagram" / "publish_assets"
    legal_images_dir = publish_assets_root / "legal" / "images"
    legal_images_dir.mkdir(parents=True, exist_ok=True)
    bad_asset = legal_images_dir / "bad_candidate.png"
    good_asset = legal_images_dir / "good_candidate.png"
    bad_asset.write_bytes(b"bad")
    good_asset.write_bytes(b"good")

    draft_dir = output_root / "instagram" / "drafts" / "d_bad_legal"
    draft_dir.mkdir(parents=True, exist_ok=True)
    (draft_dir / "draft.json").write_text("{}", encoding="utf-8")

    settings = AppSettings(
        output_root=output_root,
        tracking_root=tmp_path / "tracking",
        context_path=tmp_path / "context.yaml",
        assets_root=assets_root,
        instagram_categories_path=Path("config/instagram_publication_categories.yaml"),
        instagram_drafts_root=output_root / "instagram" / "drafts",
        instagram_catalog_path=output_root / "instagram" / "catalog" / "publication_catalog.json",
        instagram_state_path=output_root / "instagram" / "state.json",
        instagram_publish_assets_root=publish_assets_root,
        **_instagram_paths(output_root),
        instagram_publish_quality_min_score=90,
        instagram_quality_reject_delete_assets=True,
        instagram_quality_reject_keep_min_pass_assets_per_category=1,
        instagram_enable_openai_images=False,
        instagram_require_ai_image=False,
        instagram_branding_required=False,
        instagram_simulate_publish=True,
        meta_access_token="",
        meta_page_id="",
    )

    engine = InstagramContentEngine(
        settings=settings,
        context=_context(tmp_path),
        provider=OllamaProvider(model="dummy", executable="ollama"),
        asset_library=AssetLibrary(assets_root),
        openai_image_provider=None,
    )

    bad_key = engine._asset_key(bad_asset)
    engine._save_state(
        {
            "recent_assets": [bad_key],
            "recent_assets_by_category": {"legal": [bad_key]},
            "recent_videos": [],
        }
    )

    def _fake_validate(path: Path) -> dict:
        if path.name == "bad_candidate.png":
            return {"passed": False, "score": 70, "issues": ["blur"]}
        return {"passed": True, "score": 95, "issues": []}

    engine._validate_library_image_quality = _fake_validate  # type: ignore[method-assign]

    draft = {
        "draft_id": "d_bad_legal",
        "draft_dir": str(draft_dir),
        "category_id": "legal",
        "asset_key": str(bad_asset),
        "asset_rel_path": "legal/images/bad_candidate.png",
        "image_qc": {"passed": False, "score": 70},
    }
    gate = {
        "issues": ["image_qc insuficiente (score=70, min=90)"],
        "image_qc": {"passed": False, "score": 70},
    }

    report = engine.handle_quality_gate_failure(draft=draft, gate=gate)
    assert report["ok"] is True
    assert report["deleted_draft_dir"] is True
    assert len(report["removed_assets"]) == 1
    assert str(report["removed_assets"][0]["path"]).endswith("bad_candidate.png")
    assert not bad_asset.exists()
    assert good_asset.exists()
    assert not draft_dir.exists()

    state = engine._load_state()
    assert bad_key not in (state.get("recent_assets") or [])
    assert bad_key not in (state.get("recent_assets_by_category", {}).get("legal") or [])

    assert engine.quality_reject_log_path.exists()
    lines = [ln for ln in engine.quality_reject_log_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) >= 1
    last = json.loads(lines[-1])
    assert last.get("draft_id") == "d_bad_legal"
    assert len(last.get("removed_assets") or []) == 1


def test_handle_quality_gate_failure_keeps_asset_if_guard_would_empty_passable_pool(tmp_path: Path):
    assets_root = tmp_path / "assets"
    assets_root.mkdir(parents=True, exist_ok=True)

    output_root = tmp_path / "output" / "runs"
    publish_assets_root = output_root / "instagram" / "publish_assets"
    legal_images_dir = publish_assets_root / "legal" / "images"
    legal_images_dir.mkdir(parents=True, exist_ok=True)
    candidate = legal_images_dir / "only_candidate.png"
    candidate.write_bytes(b"candidate")

    draft_dir = output_root / "instagram" / "drafts" / "d_guard_legal"
    draft_dir.mkdir(parents=True, exist_ok=True)
    (draft_dir / "draft.json").write_text("{}", encoding="utf-8")

    settings = AppSettings(
        output_root=output_root,
        tracking_root=tmp_path / "tracking",
        context_path=tmp_path / "context.yaml",
        assets_root=assets_root,
        instagram_categories_path=Path("config/instagram_publication_categories.yaml"),
        instagram_drafts_root=output_root / "instagram" / "drafts",
        instagram_catalog_path=output_root / "instagram" / "catalog" / "publication_catalog.json",
        instagram_state_path=output_root / "instagram" / "state.json",
        instagram_publish_assets_root=publish_assets_root,
        **_instagram_paths(output_root),
        instagram_publish_quality_min_score=90,
        instagram_quality_reject_delete_assets=True,
        instagram_quality_reject_keep_min_pass_assets_per_category=1,
        instagram_enable_openai_images=False,
        instagram_require_ai_image=False,
        instagram_branding_required=False,
        instagram_simulate_publish=True,
        meta_access_token="",
        meta_page_id="",
    )

    engine = InstagramContentEngine(
        settings=settings,
        context=_context(tmp_path),
        provider=OllamaProvider(model="dummy", executable="ollama"),
        asset_library=AssetLibrary(assets_root),
        openai_image_provider=None,
    )

    def _all_fail(_path: Path) -> dict:
        return {"passed": False, "score": 70, "issues": ["blur"]}

    engine._validate_library_image_quality = _all_fail  # type: ignore[method-assign]

    draft = {
        "draft_id": "d_guard_legal",
        "draft_dir": str(draft_dir),
        "category_id": "legal",
        "asset_key": str(candidate),
        "asset_rel_path": "legal/images/only_candidate.png",
        "image_qc": {"passed": False, "score": 70},
    }
    gate = {
        "issues": ["image_qc insuficiente (score=70, min=90)"],
        "image_qc": {"passed": False, "score": 70},
    }

    report = engine.handle_quality_gate_failure(draft=draft, gate=gate)
    assert report["ok"] is True
    assert candidate.exists()
    assert len(report["removed_assets"]) == 0
    assert any(str(x.get("reason") or "") == "keep_min_pass_assets_guard" for x in (report.get("skipped_assets") or []))
    assert not draft_dir.exists()


def test_sweep_library_quality_removes_failing_assets_and_updates_catalog(tmp_path: Path):
    assets_root = tmp_path / "assets"
    assets_root.mkdir(parents=True, exist_ok=True)

    output_root = tmp_path / "output" / "runs"
    publish_assets_root = output_root / "instagram" / "publish_assets"
    legal_images_dir = publish_assets_root / "legal" / "images"
    legal_images_dir.mkdir(parents=True, exist_ok=True)
    good = legal_images_dir / "good.jpg"
    bad = legal_images_dir / "bad.jpg"
    Image.new("RGB", (1080, 1350), color=(180, 200, 220)).save(good, format="JPEG", quality=95)
    Image.new("RGB", (420, 420), color=(120, 80, 60)).save(bad, format="JPEG", quality=90)

    settings = AppSettings(
        output_root=output_root,
        tracking_root=tmp_path / "tracking",
        context_path=tmp_path / "context.yaml",
        assets_root=assets_root,
        instagram_categories_path=Path("config/instagram_publication_categories.yaml"),
        instagram_drafts_root=output_root / "instagram" / "drafts",
        instagram_catalog_path=output_root / "instagram" / "catalog" / "publication_catalog.json",
        instagram_state_path=output_root / "instagram" / "state.json",
        instagram_publish_assets_root=publish_assets_root,
        **_instagram_paths(output_root),
        instagram_publish_quality_min_score=90,
        instagram_quality_reject_delete_assets=True,
        instagram_quality_reject_keep_min_pass_assets_per_category=1,
        instagram_quality_sweep_enabled=True,
        instagram_quality_sweep_interval_minutes=60,
        instagram_enable_openai_images=False,
        instagram_require_ai_image=False,
        instagram_branding_required=False,
        instagram_simulate_publish=True,
        meta_access_token="",
        meta_page_id="",
    )

    engine = InstagramContentEngine(
        settings=settings,
        context=_context(tmp_path),
        provider=OllamaProvider(model="dummy", executable="ollama"),
        asset_library=AssetLibrary(assets_root),
        openai_image_provider=None,
    )

    report = engine.sweep_library_quality(force=True)
    assert report["ok"] is True
    assert bad.exists() is False
    assert good.exists() is True
    assert len(report.get("removed_assets") or []) >= 1

    catalog = json.loads(settings.instagram_asset_catalog_path.read_text(encoding="utf-8"))
    pass_counts = catalog.get("counts_by_category_quality_pass") or {}
    assert int(pass_counts.get("legal") or 0) >= 1

    state = json.loads(settings.instagram_state_path.read_text(encoding="utf-8"))
    assert str(state.get("last_quality_sweep_at") or "").strip() != ""


def test_sweep_library_quality_respects_interval_when_not_forced(tmp_path: Path):
    assets_root = tmp_path / "assets"
    assets_root.mkdir(parents=True, exist_ok=True)

    output_root = tmp_path / "output" / "runs"
    publish_assets_root = output_root / "instagram" / "publish_assets"
    legal_images_dir = publish_assets_root / "legal" / "images"
    legal_images_dir.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (1080, 1350), color=(210, 210, 220)).save(legal_images_dir / "good.jpg", format="JPEG", quality=95)

    settings = AppSettings(
        output_root=output_root,
        tracking_root=tmp_path / "tracking",
        context_path=tmp_path / "context.yaml",
        assets_root=assets_root,
        instagram_categories_path=Path("config/instagram_publication_categories.yaml"),
        instagram_drafts_root=output_root / "instagram" / "drafts",
        instagram_catalog_path=output_root / "instagram" / "catalog" / "publication_catalog.json",
        instagram_state_path=output_root / "instagram" / "state.json",
        instagram_publish_assets_root=publish_assets_root,
        **_instagram_paths(output_root),
        instagram_quality_sweep_enabled=True,
        instagram_quality_sweep_interval_minutes=120,
        instagram_enable_openai_images=False,
        instagram_require_ai_image=False,
        instagram_branding_required=False,
        instagram_simulate_publish=True,
        meta_access_token="",
        meta_page_id="",
    )

    engine = InstagramContentEngine(
        settings=settings,
        context=_context(tmp_path),
        provider=OllamaProvider(model="dummy", executable="ollama"),
        asset_library=AssetLibrary(assets_root),
        openai_image_provider=None,
    )
    first = engine.sweep_library_quality(force=True)
    second = engine.sweep_library_quality(force=False)
    assert first["ok"] is True
    assert second["ok"] is True
    assert str(second.get("skipped_reason") or "") == "interval_not_due"


def test_select_library_asset_prefers_quality_passed_items(tmp_path: Path):
    assets_root = tmp_path / "assets"
    assets_root.mkdir(parents=True, exist_ok=True)
    output_root = tmp_path / "output" / "runs"
    publish_assets_root = output_root / "instagram" / "publish_assets"
    legal_images_dir = publish_assets_root / "legal" / "images"
    legal_images_dir.mkdir(parents=True, exist_ok=True)
    low = legal_images_dir / "low.jpg"
    high = legal_images_dir / "high.jpg"
    Image.new("RGB", (420, 420), color=(30, 30, 30)).save(low, format="JPEG", quality=90)
    Image.new("RGB", (1080, 1350), color=(180, 220, 200)).save(high, format="JPEG", quality=95)

    settings = AppSettings(
        output_root=output_root,
        tracking_root=tmp_path / "tracking",
        context_path=tmp_path / "context.yaml",
        assets_root=assets_root,
        instagram_categories_path=Path("config/instagram_publication_categories.yaml"),
        instagram_drafts_root=output_root / "instagram" / "drafts",
        instagram_catalog_path=output_root / "instagram" / "catalog" / "publication_catalog.json",
        instagram_state_path=output_root / "instagram" / "state.json",
        instagram_publish_assets_root=publish_assets_root,
        **_instagram_paths(output_root),
        instagram_publish_quality_min_score=90,
        instagram_enable_openai_images=False,
        instagram_require_ai_image=False,
        instagram_branding_required=False,
        instagram_simulate_publish=True,
        meta_access_token="",
        meta_page_id="",
    )
    engine = InstagramContentEngine(
        settings=settings,
        context=_context(tmp_path),
        provider=OllamaProvider(model="dummy", executable="ollama"),
        asset_library=AssetLibrary(assets_root),
        openai_image_provider=None,
    )
    selected, meta = engine._select_library_asset(
        query="legal abogado contrato",
        category_id="legal",
        state={"counter": 0, "recent_assets": [], "recent_assets_by_category": {}},
    )
    assert selected.path.name == "high.jpg"
    assert str(meta.get("asset_rel_path") or "").endswith("legal/images/high.jpg")

def test_music_library_track_is_used_when_available(tmp_path: Path):
    assets_root = tmp_path / "assets"
    assets_root.mkdir(parents=True, exist_ok=True)

    output_root = tmp_path / "output" / "runs"
    publish_assets_root = output_root / "instagram" / "publish_assets"
    (publish_assets_root / "electricidad").mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (1080, 1350), color=(50, 110, 200)).save(publish_assets_root / "electricidad" / "base.png")

    music_root = tmp_path / "music" / "story"
    music_root.mkdir(parents=True, exist_ok=True)
    wav_path = music_root / "track1.wav"
    with wave.open(str(wav_path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(44100)
        wav.writeframes(b"\x00\x00" * 44100)

    settings = AppSettings(
        output_root=output_root,
        tracking_root=tmp_path / "tracking",
        context_path=tmp_path / "context.yaml",
        assets_root=assets_root,
        instagram_categories_path=Path("config/instagram_publication_categories.yaml"),
        instagram_drafts_root=output_root / "instagram" / "drafts",
        instagram_catalog_path=output_root / "instagram" / "catalog" / "publication_catalog.json",
        instagram_state_path=output_root / "instagram" / "state.json",
        instagram_publish_assets_root=publish_assets_root,
        **_instagram_paths(output_root),
        instagram_music_library_root=music_root,
        instagram_music_use_library_first=True,
        instagram_enable_openai_images=False,
        instagram_require_ai_image=False,
        instagram_branding_required=False,
        instagram_simulate_publish=True,
        meta_access_token="",
        meta_page_id="",
    )

    engine = InstagramContentEngine(
        settings=settings,
        context=_context(tmp_path),
        provider=OllamaProvider(model="dummy", executable="ollama"),
        asset_library=AssetLibrary(assets_root),
        openai_image_provider=None,
    )
    selected = engine._pick_music_library_track(seed=7)
    assert selected is not None
    assert selected.name == "track1.wav"


def test_category_descriptor_template_overrides_legacy_prompt_source(tmp_path: Path):
    assets_root = tmp_path / "assets"
    assets_root.mkdir(parents=True, exist_ok=True)

    output_root = tmp_path / "output" / "runs"
    publish_assets_root = output_root / "instagram" / "publish_assets"
    legal_dir = publish_assets_root / "legal"
    legal_dir.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (1080, 1350), color=(40, 75, 140)).save(legal_dir / "legal_base.png")

    categories_path = tmp_path / "instagram_publication_categories.yaml"
    categories_path.write_text(
        "\n".join(
            [
                "defaults: {}",
                "categories:",
                "  - id: legal",
                "    label: Legacy Legal",
                "    objective: captar_clientes",
                "    services: [legacy_service]",
                "    image_prompt_templates:",
                "      - LEGACY_TEMPLATE_SHOULD_NOT_APPEAR",
            ]
        ),
        encoding="utf-8",
    )

    descriptors_path = tmp_path / "instagram_category_descriptors.yaml"
    descriptors_path.write_text(
        "\n".join(
            [
                "prompt_framework:",
                "  common_strengths: [FRAMEWORK_COMMON_STRENGTH]",
                "  common_layout_rules: [FRAMEWORK_LAYOUT_RULE]",
                "  common_brand_rules: [FRAMEWORK_TRUST_RULE]",
                "  global_negative_rules: [FRAMEWORK_NEGATIVE_RULE]",
                "  reference_policy: FRAMEWORK_REFERENCE_POLICY",
                "categories:",
                "  - id: legal",
                "    label: Asesoria Legal",
                "    objective: captar_clientes",
                "    category_context: LEGAL_CONTEXT",
                "    visual_brief: LEGAL_VISUAL",
                "    image_prompt_templates:",
                "      - DESCRIPTOR_TEMPLATE_USED",
                "    services: [abogado]",
                "    reference_asset_patterns: [legal_base.png]",
                "    creative_template:",
                "      subject_profile: LEGAL_SUBJECT_PROFILE",
                "      scene_profile: LEGAL_SCENE_PROFILE",
                "      color_direction: LEGAL_COLOR_DIRECTION",
                "      lighting_direction: LEGAL_LIGHTING_DIRECTION",
                "      camera_direction: LEGAL_CAMERA_DIRECTION",
                "      tone_keywords: [LEGAL_TONE]",
                "      differentiators: [LEGAL_DIFFERENTIATOR]",
                "      scene_anchors: [LEGAL_ANCHOR]",
                "      composition_rules: [LEGAL_COMPOSITION_RULE]",
                "      trust_cues: [LEGAL_TRUST_CUE]",
                "      avoid: [LEGAL_AVOID_RULE]",
            ]
        ),
        encoding="utf-8",
    )

    settings = AppSettings(
        output_root=output_root,
        tracking_root=tmp_path / "tracking",
        context_path=tmp_path / "context.yaml",
        assets_root=assets_root,
        instagram_categories_path=categories_path,
        instagram_category_descriptors_path=descriptors_path,
        instagram_drafts_root=output_root / "instagram" / "drafts",
        instagram_catalog_path=output_root / "instagram" / "catalog" / "publication_catalog.json",
        instagram_state_path=output_root / "instagram" / "state.json",
        instagram_publish_assets_root=publish_assets_root,
        **_instagram_paths(output_root),
        instagram_enable_openai_images=True,
        instagram_require_ai_image=True,
        instagram_openai_monthly_budget_usd=10.0,
        instagram_openai_image_estimated_cost_usd=0.1,
        instagram_branding_required=False,
        instagram_simulate_publish=True,
        meta_access_token="",
        meta_page_id="",
    )

    engine = InstagramContentEngine(
        settings=settings,
        context=_context(tmp_path),
        provider=OllamaProvider(model="dummy", executable="ollama"),
        asset_library=AssetLibrary(assets_root),
        openai_image_provider=_FakeOpenAIImageProvider(),
    )

    result = engine.auto_cycle_once(
        use_meta_history=False,
        publish=False,
        simulate_publish=True,
        force_category="legal",
    )
    prompt = str(result["draft"]["image_prompt"])
    assert "DESCRIPTOR_TEMPLATE_USED" in prompt
    assert "LEGACY_TEMPLATE_SHOULD_NOT_APPEAR" not in prompt
    assert "LEGAL_SUBJECT_PROFILE" in prompt
    assert "LEGAL_DIFFERENTIATOR" in prompt
    assert "FRAMEWORK_NEGATIVE_RULE" in prompt


def test_reference_asset_pattern_prefers_base_over_generated_names(tmp_path: Path):
    assets_root = tmp_path / "assets"
    assets_root.mkdir(parents=True, exist_ok=True)

    output_root = tmp_path / "output" / "runs"
    publish_assets_root = output_root / "instagram" / "publish_assets"
    legal_dir = publish_assets_root / "legal"
    legal_dir.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (1080, 1350), color=(20, 40, 80)).save(legal_dir / "openai_legal_20260101_000000.jpg")
    Image.new("RGB", (1080, 1350), color=(80, 60, 120)).save(legal_dir / "legal_base.png")

    categories_path = tmp_path / "instagram_publication_categories.yaml"
    categories_path.write_text("defaults: {}\ncategories: []\n", encoding="utf-8")

    descriptors_path = tmp_path / "instagram_category_descriptors.yaml"
    descriptors_path.write_text(
        "\n".join(
            [
                "categories:",
                "  - id: legal",
                "    label: Asesoria Legal",
                "    objective: captar_clientes",
                "    image_prompt_templates: [DESCRIPTOR_TEMPLATE]",
                "    reference_asset_patterns: [legal_base.png]",
            ]
        ),
        encoding="utf-8",
    )

    settings = AppSettings(
        output_root=output_root,
        tracking_root=tmp_path / "tracking",
        context_path=tmp_path / "context.yaml",
        assets_root=assets_root,
        instagram_categories_path=categories_path,
        instagram_category_descriptors_path=descriptors_path,
        instagram_drafts_root=output_root / "instagram" / "drafts",
        instagram_catalog_path=output_root / "instagram" / "catalog" / "publication_catalog.json",
        instagram_state_path=output_root / "instagram" / "state.json",
        instagram_publish_assets_root=publish_assets_root,
        **_instagram_paths(output_root),
        instagram_enable_openai_images=False,
        instagram_require_ai_image=False,
        instagram_branding_required=False,
        instagram_simulate_publish=True,
        meta_access_token="",
        meta_page_id="",
    )

    engine = InstagramContentEngine(
        settings=settings,
        context=_context(tmp_path),
        provider=OllamaProvider(model="dummy", executable="ollama"),
        asset_library=AssetLibrary(assets_root),
        openai_image_provider=None,
    )

    chosen, meta = engine._select_category_reference_asset(category_id="legal")
    assert chosen is not None
    assert chosen.path.name == "legal_base.png"
    assert str(meta.get("asset_rel_path") or "").endswith("/legal_base.png")


def test_story_openai_image_uses_no_crop_layout(tmp_path: Path):
    assets_root = tmp_path / "assets"
    assets_root.mkdir(parents=True, exist_ok=True)
    output_root = tmp_path / "output" / "runs"
    publish_assets_root = output_root / "instagram" / "publish_assets"
    (publish_assets_root / "kinesiologia").mkdir(parents=True, exist_ok=True)

    base = tmp_path / "source_openai.jpg"
    canvas = Image.new("RGB", (1024, 1536), color=(245, 245, 245))
    draw = ImageDraw.Draw(canvas)
    draw.rectangle([0, 0, 40, 1535], fill=(230, 20, 20))
    draw.rectangle([983, 0, 1023, 1535], fill=(20, 210, 20))
    canvas.save(base, format="JPEG", quality=95)

    settings = AppSettings(
        output_root=output_root,
        tracking_root=tmp_path / "tracking",
        context_path=tmp_path / "context.yaml",
        assets_root=assets_root,
        instagram_categories_path=Path("config/instagram_publication_categories.yaml"),
        instagram_drafts_root=output_root / "instagram" / "drafts",
        instagram_catalog_path=output_root / "instagram" / "catalog" / "publication_catalog.json",
        instagram_state_path=output_root / "instagram" / "state.json",
        instagram_publish_assets_root=publish_assets_root,
        **_instagram_paths(output_root),
        instagram_enable_openai_images=False,
        instagram_require_ai_image=False,
        instagram_branding_required=False,
        instagram_simulate_publish=True,
        meta_access_token="",
        meta_page_id="",
    )
    engine = InstagramContentEngine(
        settings=settings,
        context=_context(tmp_path),
        provider=OllamaProvider(model="dummy", executable="ollama"),
        asset_library=AssetLibrary(assets_root),
        openai_image_provider=None,
    )

    out = tmp_path / "story_out.jpg"
    engine._apply_branding_overlay(
        base_image=base,
        output_path=out,
        objective="captar_clientes",
        format_type="story",
        overlay_text="",
        asset_has_qr=False,
        image_source="openai_image",
    )

    with Image.open(out).convert("RGB") as result:
        assert result.size == (1080, 1920)
        left = result.getpixel((8, 960))
        right = result.getpixel((1071, 960))
        assert left[0] > left[1] and left[0] > left[2]
        assert right[1] > right[0] and right[1] > right[2]


def test_publish_variants_are_generated_per_channel(tmp_path: Path):
    assets_root = tmp_path / "assets"
    assets_root.mkdir(parents=True, exist_ok=True)
    output_root = tmp_path / "output" / "runs"
    publish_assets_root = output_root / "instagram" / "publish_assets"
    (publish_assets_root / "sincosto").mkdir(parents=True, exist_ok=True)

    settings = AppSettings(
        output_root=output_root,
        tracking_root=tmp_path / "tracking",
        context_path=tmp_path / "context.yaml",
        assets_root=assets_root,
        instagram_categories_path=Path("config/instagram_publication_categories.yaml"),
        instagram_drafts_root=output_root / "instagram" / "drafts",
        instagram_catalog_path=output_root / "instagram" / "catalog" / "publication_catalog.json",
        instagram_state_path=output_root / "instagram" / "state.json",
        instagram_publish_assets_root=publish_assets_root,
        **_instagram_paths(output_root),
        instagram_enable_openai_images=False,
        instagram_require_ai_image=False,
        instagram_branding_required=False,
        instagram_simulate_publish=True,
        meta_access_token="",
        meta_page_id="",
    )
    engine = InstagramContentEngine(
        settings=settings,
        context=_context(tmp_path),
        provider=OllamaProvider(model="dummy", executable="ollama"),
        asset_library=AssetLibrary(assets_root),
        openai_image_provider=None,
    )

    draft_dir = output_root / "instagram" / "drafts" / "test_story"
    draft_dir.mkdir(parents=True, exist_ok=True)
    source = draft_dir / "image.jpg"
    Image.new("RGB", (1080, 1920), color=(245, 240, 200)).save(source, format="JPEG", quality=95)
    (draft_dir / "draft.json").write_text(
        json.dumps(
            {
                "draft_id": "test_story",
                "draft_dir": str(draft_dir),
                "image_path": str(source),
                "image_source": "openai_image",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    payload = engine.ensure_publish_image_variants(
        draft={
            "draft_id": "test_story",
            "draft_dir": str(draft_dir),
            "image_path": str(source),
            "image_source": "openai_image",
        }
    )

    post_path = Path(str(payload["post_image_path"]))
    story_path = Path(str(payload["story_image_path"]))
    assert post_path.exists()
    assert story_path.exists()

    with Image.open(post_path) as post_img:
        assert post_img.size == (1080, 1350)
    with Image.open(story_path) as story_img:
        assert story_img.size == (1080, 1920)

    stored = json.loads((draft_dir / "draft.json").read_text(encoding="utf-8"))
    assert isinstance(stored.get("publish_media"), dict)
    assert stored["publish_media"]["post_image_path"] == str(post_path)
    assert stored["publish_media"]["story_image_path"] == str(story_path)


def test_validate_image_detects_content_touching_bottom_edge(tmp_path: Path):
    assets_root = tmp_path / "assets"
    assets_root.mkdir(parents=True, exist_ok=True)
    output_root = tmp_path / "output" / "runs"
    publish_assets_root = output_root / "instagram" / "publish_assets"
    (publish_assets_root / "general").mkdir(parents=True, exist_ok=True)

    settings = AppSettings(
        output_root=output_root,
        tracking_root=tmp_path / "tracking",
        context_path=tmp_path / "context.yaml",
        assets_root=assets_root,
        instagram_categories_path=Path("config/instagram_publication_categories.yaml"),
        instagram_drafts_root=output_root / "instagram" / "drafts",
        instagram_catalog_path=output_root / "instagram" / "catalog" / "publication_catalog.json",
        instagram_state_path=output_root / "instagram" / "state.json",
        instagram_publish_assets_root=publish_assets_root,
        **_instagram_paths(output_root),
        instagram_enable_openai_images=False,
        instagram_require_ai_image=False,
        instagram_branding_required=False,
        instagram_simulate_publish=True,
        meta_access_token="",
        meta_page_id="",
    )
    engine = InstagramContentEngine(
        settings=settings,
        context=_context(tmp_path),
        provider=OllamaProvider(model="dummy", executable="ollama"),
        asset_library=AssetLibrary(assets_root),
        openai_image_provider=None,
    )

    img_path = tmp_path / "touch_bottom.jpg"
    canvas = Image.new("RGB", (1080, 1920), color=(245, 236, 188))
    draw = ImageDraw.Draw(canvas)
    draw.rectangle([80, 1650, 1000, 1919], fill=(15, 138, 72))
    draw.text((130, 1840), "WHATSAPP +56 9 8343 4503", fill=(255, 255, 255))
    canvas.save(img_path, format="JPEG", quality=95)

    report = engine._validate_ig_image(image_path=img_path, image_source="openai_image", format_type="story")
    assert report["score"] < 90
    assert any("borde inferior" in issue for issue in report["issues"])


def test_auto_bootstrap_descriptor_for_new_category_folder(tmp_path: Path):
    assets_root = tmp_path / "assets"
    assets_root.mkdir(parents=True, exist_ok=True)

    output_root = tmp_path / "output" / "runs"
    publish_assets_root = output_root / "instagram" / "publish_assets"
    nueva_dir = publish_assets_root / "fonoaudiologia"
    nueva_dir.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (1080, 1350), color=(178, 212, 226)).save(nueva_dir / "base_fono.png")

    categories_path = tmp_path / "instagram_publication_categories.yaml"
    categories_path.write_text("defaults: {}\ncategories: []\n", encoding="utf-8")

    descriptors_path = tmp_path / "instagram_category_descriptors.yaml"
    descriptors_path.write_text("prompt_framework: {}\ncategories: []\n", encoding="utf-8")

    settings = AppSettings(
        output_root=output_root,
        tracking_root=tmp_path / "tracking",
        context_path=tmp_path / "context.yaml",
        assets_root=assets_root,
        instagram_categories_path=categories_path,
        instagram_category_descriptors_path=descriptors_path,
        instagram_drafts_root=output_root / "instagram" / "drafts",
        instagram_catalog_path=output_root / "instagram" / "catalog" / "publication_catalog.json",
        instagram_state_path=output_root / "instagram" / "state.json",
        instagram_publish_assets_root=publish_assets_root,
        **_instagram_paths(output_root),
        instagram_enable_openai_images=False,
        instagram_require_ai_image=False,
        instagram_branding_required=False,
        instagram_simulate_publish=True,
        meta_access_token="",
        meta_page_id="",
    )

    engine = InstagramContentEngine(
        settings=settings,
        context=_context(tmp_path),
        provider=OllamaProvider(model="dummy", executable="ollama"),
        asset_library=AssetLibrary(assets_root),
        openai_image_provider=None,
    )

    assert "fonoaudiologia" in engine.category_map

    parsed = yaml.safe_load(descriptors_path.read_text(encoding="utf-8")) or {}
    cats = parsed.get("categories") or []
    row = next((c for c in cats if isinstance(c, dict) and c.get("id") == "fonoaudiologia"), None)
    assert row is not None
    assert row.get("label") == "Fonoaudiologia"
    assert row.get("reference_asset_patterns") == ["base_fono.png"]
    assert isinstance(row.get("creative_template"), dict)
    assert isinstance(row.get("analysis"), dict)
    assert isinstance((row.get("analysis") or {}).get("composition"), dict)
    assert isinstance((row.get("analysis") or {}).get("ocr"), dict)
    assert isinstance((row.get("analysis") or {}).get("semantic_tags"), list)

    state_path = output_root / "instagram" / "catalog" / "descriptor_bootstrap_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert "fonoaudiologia" in (state.get("generated") or {})


def test_infer_category_prefers_specific_legal_terms_over_generic_contact_terms(tmp_path: Path):
    assets_root = tmp_path / "assets"
    assets_root.mkdir(parents=True, exist_ok=True)
    output_root = tmp_path / "output" / "runs"
    publish_assets_root = output_root / "instagram" / "publish_assets"
    (publish_assets_root / "legal").mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (1080, 1350), color=(70, 95, 150)).save(publish_assets_root / "legal" / "base.png")

    settings = AppSettings(
        output_root=output_root,
        tracking_root=tmp_path / "tracking",
        context_path=tmp_path / "context.yaml",
        assets_root=assets_root,
        instagram_categories_path=Path("config/instagram_publication_categories.yaml"),
        instagram_drafts_root=output_root / "instagram" / "drafts",
        instagram_catalog_path=output_root / "instagram" / "catalog" / "publication_catalog.json",
        instagram_state_path=output_root / "instagram" / "state.json",
        instagram_publish_assets_root=publish_assets_root,
        **_instagram_paths(output_root),
        instagram_enable_openai_images=False,
        instagram_require_ai_image=False,
        instagram_branding_required=False,
        instagram_simulate_publish=True,
        meta_access_token="",
        meta_page_id="",
    )

    engine = InstagramContentEngine(
        settings=settings,
        context=_context(tmp_path),
        provider=OllamaProvider(model="dummy", executable="ollama"),
        asset_library=AssetLibrary(assets_root),
        openai_image_provider=None,
    )

    caption = (
        "Necesitas orientacion legal? ConectaProIA te conecta por WhatsApp con profesionales legales. "
        "Servicio: asesoria legal | revision de contrato | abogado en Concepcion."
    )
    assert engine._infer_category(caption) == "legal"


def test_pick_category_applies_strict_cooldown_against_recent_repeats(tmp_path: Path):
    assets_root = tmp_path / "assets"
    assets_root.mkdir(parents=True, exist_ok=True)
    output_root = tmp_path / "output" / "runs"
    publish_assets_root = output_root / "instagram" / "publish_assets"
    for cat in ["legal", "electricidad", "gasfiteria"]:
        folder = publish_assets_root / cat
        folder.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (1080, 1350), color=(60, 80, 120)).save(folder / f"{cat}.png")

    categories_path = tmp_path / "instagram_publication_categories.yaml"
    categories_path.write_text(
        "\n".join(
            [
                "defaults:",
                "  rotate_window: 3",
                "categories:",
                "  - id: legal",
                "    label: Legal",
                "    objective: captar_clientes",
                "    keywords: [legal, abogado, contrato]",
                "    services: [asesoria legal]",
                "    variants: [{hook: h, value: v, proof: p, cta: c, short_text: s}]",
                "  - id: electricidad",
                "    label: Electricidad",
                "    objective: captar_clientes",
                "    keywords: [electricidad, electricista]",
                "    services: [electricista]",
                "    variants: [{hook: h, value: v, proof: p, cta: c, short_text: s}]",
                "  - id: gasfiteria",
                "    label: Gasfiteria",
                "    objective: captar_clientes",
                "    keywords: [gasfiteria, calefon]",
                "    services: [gasfiter]",
                "    variants: [{hook: h, value: v, proof: p, cta: c, short_text: s}]",
            ]
        ),
        encoding="utf-8",
    )
    descriptors_path = tmp_path / "instagram_category_descriptors.yaml"
    descriptors_path.write_text("prompt_framework: {}\ncategories: []\n", encoding="utf-8")

    settings = AppSettings(
        output_root=output_root,
        tracking_root=tmp_path / "tracking",
        context_path=tmp_path / "context.yaml",
        assets_root=assets_root,
        instagram_categories_path=categories_path,
        instagram_category_descriptors_path=descriptors_path,
        instagram_drafts_root=output_root / "instagram" / "drafts",
        instagram_catalog_path=output_root / "instagram" / "catalog" / "publication_catalog.json",
        instagram_state_path=output_root / "instagram" / "state.json",
        instagram_publish_assets_root=publish_assets_root,
        **_instagram_paths(output_root),
        instagram_enable_openai_images=False,
        instagram_require_ai_image=False,
        instagram_branding_required=False,
        instagram_simulate_publish=True,
        meta_access_token="",
        meta_page_id="",
    )
    engine = InstagramContentEngine(
        settings=settings,
        context=_context(tmp_path),
        provider=OllamaProvider(model="dummy", executable="ollama"),
        asset_library=AssetLibrary(assets_root),
        openai_image_provider=None,
    )

    catalog = {
        "counts": {"combined": {"legal": 2, "electricidad": 9, "gasfiteria": 10}},
        "recent_media": [
            {"category_id": "legal"},
            {"category_id": "legal"},
            {"category_id": "legal"},
        ],
    }
    state = {
        "counter": 17,
        "recent_categories": ["electricidad", "legal", "legal"],
    }
    selected = engine._pick_category(catalog=catalog, state=state, objective="captar_clientes", force_category=None)
    assert str(selected.get("id")) != "legal"


def test_pick_category_has_weighted_random_variation_across_counters(tmp_path: Path):
    assets_root = tmp_path / "assets"
    assets_root.mkdir(parents=True, exist_ok=True)
    output_root = tmp_path / "output" / "runs"
    publish_assets_root = output_root / "instagram" / "publish_assets"
    for cat in ["legal", "electricidad", "gasfiteria"]:
        folder = publish_assets_root / cat
        folder.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (1080, 1350), color=(80, 70, 120)).save(folder / f"{cat}.png")

    categories_path = tmp_path / "instagram_publication_categories.yaml"
    categories_path.write_text(
        "\n".join(
            [
                "defaults:",
                "  rotate_window: 3",
                "categories:",
                "  - id: legal",
                "    label: Legal",
                "    objective: captar_clientes",
                "    keywords: [legal, abogado, contrato]",
                "    services: [asesoria legal]",
                "    variants: [{hook: h, value: v, proof: p, cta: c, short_text: s}]",
                "  - id: electricidad",
                "    label: Electricidad",
                "    objective: captar_clientes",
                "    keywords: [electricidad, electricista]",
                "    services: [electricista]",
                "    variants: [{hook: h, value: v, proof: p, cta: c, short_text: s}]",
                "  - id: gasfiteria",
                "    label: Gasfiteria",
                "    objective: captar_clientes",
                "    keywords: [gasfiteria, calefon]",
                "    services: [gasfiter]",
                "    variants: [{hook: h, value: v, proof: p, cta: c, short_text: s}]",
            ]
        ),
        encoding="utf-8",
    )
    descriptors_path = tmp_path / "instagram_category_descriptors.yaml"
    descriptors_path.write_text("prompt_framework: {}\ncategories: []\n", encoding="utf-8")

    settings = AppSettings(
        output_root=output_root,
        tracking_root=tmp_path / "tracking",
        context_path=tmp_path / "context.yaml",
        assets_root=assets_root,
        instagram_categories_path=categories_path,
        instagram_category_descriptors_path=descriptors_path,
        instagram_drafts_root=output_root / "instagram" / "drafts",
        instagram_catalog_path=output_root / "instagram" / "catalog" / "publication_catalog.json",
        instagram_state_path=output_root / "instagram" / "state.json",
        instagram_publish_assets_root=publish_assets_root,
        **_instagram_paths(output_root),
        instagram_enable_openai_images=False,
        instagram_require_ai_image=False,
        instagram_branding_required=False,
        instagram_simulate_publish=True,
        meta_access_token="",
        meta_page_id="",
    )
    engine = InstagramContentEngine(
        settings=settings,
        context=_context(tmp_path),
        provider=OllamaProvider(model="dummy", executable="ollama"),
        asset_library=AssetLibrary(assets_root),
        openai_image_provider=None,
    )

    catalog = {"counts": {"combined": {"legal": 4, "electricidad": 4, "gasfiteria": 4}}, "recent_media": []}
    picks: set[str] = set()
    for c in range(12):
        selected = engine._pick_category(
            catalog=catalog,
            state={"counter": c, "recent_categories": ["legal", "electricidad", "gasfiteria"]},
            objective="captar_clientes",
            force_category=None,
        )
        picks.add(str(selected.get("id") or ""))
    assert len([p for p in picks if p]) >= 2


def test_ensure_publish_image_variants_uses_base_image_path_as_variant_source(tmp_path: Path):
    assets_root = tmp_path / "assets"
    assets_root.mkdir(parents=True, exist_ok=True)
    output_root = tmp_path / "output" / "runs"
    publish_assets_root = output_root / "instagram" / "publish_assets"
    (publish_assets_root / "proveedores").mkdir(parents=True, exist_ok=True)

    settings = AppSettings(
        output_root=output_root,
        tracking_root=tmp_path / "tracking",
        context_path=tmp_path / "context.yaml",
        assets_root=assets_root,
        instagram_categories_path=Path("config/instagram_publication_categories.yaml"),
        instagram_drafts_root=output_root / "instagram" / "drafts",
        instagram_catalog_path=output_root / "instagram" / "catalog" / "publication_catalog.json",
        instagram_state_path=output_root / "instagram" / "state.json",
        instagram_publish_assets_root=publish_assets_root,
        **_instagram_paths(output_root),
        instagram_enable_openai_images=False,
        instagram_require_ai_image=False,
        instagram_branding_required=False,
        instagram_simulate_publish=True,
        meta_access_token="",
        meta_page_id="",
    )
    engine = InstagramContentEngine(
        settings=settings,
        context=_context(tmp_path),
        provider=OllamaProvider(model="dummy", executable="ollama"),
        asset_library=AssetLibrary(assets_root),
        openai_image_provider=None,
    )

    draft_dir = output_root / "instagram" / "drafts" / "d_variants_base_source"
    draft_dir.mkdir(parents=True, exist_ok=True)
    base_source = draft_dir / "base_master.jpg"
    transformed_story = draft_dir / "image.jpg"
    Image.new("RGB", (1080, 1350), color=(40, 170, 90)).save(base_source, format="JPEG", quality=95)
    Image.new("RGB", (1080, 1920), color=(200, 40, 40)).save(transformed_story, format="JPEG", quality=95)

    payload = engine.ensure_publish_image_variants(
        draft={
            "draft_dir": str(draft_dir),
            "image_path": str(transformed_story),
            "base_image_path": str(base_source),
            "image_source": "category_template",
            "asset_key": str(base_source),
        }
    )
    assert str(payload.get("variant_source_path") or "") == str(base_source.resolve())

    post = Path(str(payload["post_image_path"]))
    with Image.open(post).convert("RGB") as img:
        center = img.getpixel((img.width // 2, img.height // 2))
    # If base_source is used, output center keeps the green-ish base color.
    assert center[1] > center[0]
    assert center[1] > center[2]


def test_apply_branding_overlay_ignores_short_text_when_disabled(tmp_path: Path):
    assets_root = tmp_path / "assets"
    assets_root.mkdir(parents=True, exist_ok=True)
    output_root = tmp_path / "output" / "runs"
    publish_assets_root = output_root / "instagram" / "publish_assets"
    (publish_assets_root / "general").mkdir(parents=True, exist_ok=True)

    settings = AppSettings(
        output_root=output_root,
        tracking_root=tmp_path / "tracking",
        context_path=tmp_path / "context.yaml",
        assets_root=assets_root,
        instagram_categories_path=Path("config/instagram_publication_categories.yaml"),
        instagram_drafts_root=output_root / "instagram" / "drafts",
        instagram_catalog_path=output_root / "instagram" / "catalog" / "publication_catalog.json",
        instagram_state_path=output_root / "instagram" / "state.json",
        instagram_publish_assets_root=publish_assets_root,
        **_instagram_paths(output_root),
        instagram_overlay_short_text_enabled=False,
        instagram_qr_overlay_enabled=False,
        instagram_enable_openai_images=False,
        instagram_require_ai_image=False,
        instagram_branding_required=False,
        instagram_simulate_publish=True,
        meta_access_token="",
        meta_page_id="",
    )
    engine = InstagramContentEngine(
        settings=settings,
        context=_context(tmp_path),
        provider=OllamaProvider(model="dummy", executable="ollama"),
        asset_library=AssetLibrary(assets_root),
        openai_image_provider=None,
    )

    src = tmp_path / "src.jpg"
    Image.new("RGB", (1080, 1350), color=(80, 120, 170)).save(src, format="JPEG", quality=95)
    out_with_text = tmp_path / "out_with_text.jpg"
    out_without_text = tmp_path / "out_without_text.jpg"

    engine._apply_branding_overlay(
        base_image=src,
        output_path=out_with_text,
        objective="captar_clientes",
        format_type="story",
        overlay_text="Activa mas oportunidades.",
        asset_has_qr=False,
        image_source="category_template",
    )
    engine._apply_branding_overlay(
        base_image=src,
        output_path=out_without_text,
        objective="captar_clientes",
        format_type="story",
        overlay_text="",
        asset_has_qr=False,
        image_source="category_template",
    )

    assert out_with_text.read_bytes() == out_without_text.read_bytes()








def test_registry_publishes_only_primary_and_aligns_alias(tmp_path):
    from conecta_video_ai.service_images import save_registry, digest
    assets_root = tmp_path / "assets"
    assets_root.mkdir()
    primary = assets_root / "desarrollo_software_sistemas_informaticos_01.png"
    other = assets_root / "desarrollo_software_02.png"
    for p in [primary, other]:
        Image.new("RGB", (1080, 1350), color=(80,90,100)).save(p)
    output_root = tmp_path / "output/runs"
    save_registry(output_root / "instagram/catalog/service_images.json", {"services": {
        "desarrollo_web": {"status":"approved","active":True,"provider_count":1,
                           "image":primary.name,"sha256":digest(primary)}
    }})
    settings = AppSettings(output_root=output_root, instagram_publish_assets_root=assets_root,
                           instagram_drafts_root=output_root / "drafts",
                           instagram_catalog_path=output_root / "catalog.json",
                           instagram_state_path=output_root / "state.json",
                           **_instagram_paths(output_root))
    engine = InstagramContentEngine(settings=settings, context=_context(tmp_path),
             provider=OllamaProvider(model="dummy", executable="ollama"),
             asset_library=AssetLibrary(assets_root), openai_image_provider=None)
    chosen, details = engine._select_library_asset(query="software", category_id="desarrollo_software", state={"recent_assets":[str(primary)]})
    assert chosen.path.resolve()==primary.resolve()
    assert details["asset_category_id"]=="desarrollo_web"
    catalog=engine._asset_catalog_map()
    assert catalog[engine._asset_key(other)]["excluded"] is True
    assert catalog[engine._asset_key(primary)]["category_id"]=="desarrollo_web"
