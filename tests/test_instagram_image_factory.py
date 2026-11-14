from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

import scripts.instagram_image_factory as factory
from scripts.instagram_image_factory import DbService, choose_next_service, preflight_layout, sha256_file
from scripts.instagram_layout_guard import LayoutGuard, assert_layouts


def test_choose_next_service_creates_missing_asset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(factory, "MANIFEST_DIR", tmp_path / "manifests")
    service = DbService(code="nuevo_servicio", name="Nuevo servicio", provider_count=2)

    decision = choose_next_service([service], assets_root=tmp_path / "imagenes_ig")

    assert decision is not None
    assert decision.service.code == "nuevo_servicio"
    assert decision.action == "create"
    assert decision.reason == "missing_image"


def test_choose_next_service_skips_existing_accepted_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest_dir = tmp_path / "manifests"
    monkeypatch.setattr(factory, "MANIFEST_DIR", manifest_dir)
    assets_root = tmp_path / "imagenes_ig"
    assets_root.mkdir()
    image_path = assets_root / "gasfiteria_01.png"
    image_path.write_bytes(b"fake-image")
    service = DbService(code="gasfiteria", name="Gasfiteria", provider_count=3)
    manifest_dir.mkdir()
    (manifest_dir / "gasfiteria.json").write_text(
        json.dumps(
            {
                "accepted": True,
                "quality_standard_version": factory.QUALITY_STANDARD_VERSION,
                "service_code": "gasfiteria",
                "provider_count": 3,
                "image_sha256": sha256_file(image_path),
            }
        ),
        encoding="utf-8",
    )

    assert choose_next_service([service], assets_root=assets_root) is None


def test_choose_next_service_preserves_old_quality_standard_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest_dir = tmp_path / "manifests"
    monkeypatch.setattr(factory, "MANIFEST_DIR", manifest_dir)
    assets_root = tmp_path / "imagenes_ig"
    assets_root.mkdir()
    image_path = assets_root / "electricidad_01.png"
    image_path.write_bytes(b"fake-image")
    service = DbService(code="electricidad", name="Electricidad", provider_count=31)
    manifest_dir.mkdir()
    (manifest_dir / "electricidad.json").write_text(
        json.dumps(
            {
                "accepted": True,
                "service_code": "electricidad",
                "provider_count": 31,
                "image_sha256": sha256_file(image_path),
            }
        ),
        encoding="utf-8",
    )

    decision = choose_next_service([service], assets_root=assets_root)

    assert decision is None


def test_layout_guard_rejects_overlapping_footer_and_decoration() -> None:
    guard = LayoutGuard(asset_name="asset.png", width=1080, height=1350)
    guard.add("footer", (60, 1200, 960, 1260))
    guard.add("accent_line", (80, 1230, 980, 1238))

    with pytest.raises(RuntimeError, match="footer se superpone con accent_line"):
        assert_layouts([guard])


def test_preflight_layout_accepts_reference_template(tmp_path: Path) -> None:
    service = DbService(code="electricidad", name="Electricidad", provider_count=31)

    result = preflight_layout(service, tmp_path / "work")

    assert result["ok"] is True
    assert result["layout"]["issues"] == []
    with Image.open(result["image_path"]) as img:
        assert img.size == (factory.W, factory.H)

@pytest.mark.parametrize('name', [
    'Lavandería / Tintorería',
    'Restaurante / Comida preparada',
    'Desarrollo de sistemas informáticos',
    'Aire acondicionado / Calefacción',
    'Reparación de computadores / notebooks.',
    'Cámaras / Seguridad',
    'Traductores inglés español',
    'ÁÉÍÓÚ Ñandú y atención profesional especializada',
])
def test_variable_copy_stays_above_contact(tmp_path, name):
    result = preflight_layout(DbService('regression', name, 123456), tmp_path)
    boxes = {b['name']: b for b in result['layout']['boxes']}
    assert result['layout']['issues'] == []
    assert boxes['title']['y2'] <= 410
    assert boxes['description']['y2'] <= 556
    assert boxes['card_service']['y2'] < boxes['cta_panel']['y1'] - 8
    assert boxes['cta']['x2'] <= 1000
    assert boxes['phone']['x2'] <= 1000


def test_fitted_text_preserves_full_copy_and_measures_drawn_bounds():
    from PIL import ImageDraw
    draw = ImageDraw.Draw(Image.new('RGB', (600, 300)))
    calls = []
    original = draw.text
    def record(xy, text, **kwargs):
        calls.append((xy, text, kwargs))
        return original(xy, text, **kwargs)
    draw.text = record
    text = 'Árbol ' + 'especialización '*5 + ' WhatsApp'
    box = factory.draw_fitted_text(draw, (20, 20, 550, 270), text, factory.FONTS['body'], 'black', min_size=24)
    assert ''.join(t.replace(' ', '') for _, t, _ in calls) == text.replace(' ', '')
    for xy, text, kwargs in calls:
        actual = draw.textbbox(xy, text, font=kwargs['font'], anchor=kwargs['anchor'])
        assert box[0] <= actual[0] <= actual[2] <= box[2]
        assert box[1] <= actual[1] <= actual[3] <= box[3]


def test_impossible_copy_fails_before_writing_candidate(tmp_path):
    with pytest.raises(RuntimeError, match='cannot fit'):
        preflight_layout(DbService('oversized', 'Servicio ' * 200, 1), tmp_path)
    assert not (tmp_path / 'preflight_candidate.png').exists()


@pytest.mark.parametrize("failure_stage", ["composition", "accounting"])
def test_paid_source_is_not_regenerated_after_local_processing_error(tmp_path, monkeypatch, failure_stage):
    from types import SimpleNamespace
    from unittest.mock import Mock
    service = DbService('example', 'Servicio de prueba', 2)
    settings = SimpleNamespace(instagram_publish_assets_root=tmp_path / 'assets',
        instagram_asset_catalog_path=tmp_path / 'catalog.json', openai_api_key='test',
        openai_image_model='test', openai_image_size='test', openai_image_quality='test',
        instagram_openai_monthly_budget_usd=5)
    monkeypatch.setattr(factory, 'STATE_DIR', tmp_path / 'state')
    monkeypatch.setattr(factory, 'REGISTRY_PATH', tmp_path / 'registry.json')
    monkeypatch.setattr(factory, 'load_settings', lambda: settings)
    monkeypatch.setattr(factory, 'StudioService', lambda _: object())
    monkeypatch.setattr(factory, 'load_db_services', lambda **kw: [service])
    monkeypatch.setattr(factory, 'preflight_layout', lambda *a: {'ok': True})
    monkeypatch.setattr(factory, 'ensure_catalog_entries', lambda *a, **kw: {})
    monkeypatch.setattr(factory, 'find_reference_seed', lambda *a: None)
    monkeypatch.setattr(factory, 'append_log', lambda *a: None)
    monkeypatch.setattr(factory, 'write_state_result', lambda *a: None)
    provider = Mock(last_usage={})
    def generate(prompt, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'paid-source')
    provider.generate_image.side_effect = generate
    monkeypatch.setattr(factory, 'OpenAIImageProvider', lambda **kw: provider)
    budget = Mock()
    budget.reserve.return_value = 'reservation'
    if failure_stage == 'accounting':
        budget.complete.side_effect = RuntimeError('local accounting failed')
    monkeypatch.setattr(factory, 'ImageBudget', lambda *a: budget)
    compose = Mock(side_effect=RuntimeError('local processing failed'))
    monkeypatch.setattr(factory, 'compose_asset', compose)
    result = factory.generate_one(max_attempts=3)
    assert result['ok'] is False
    assert provider.generate_image.call_count == 1
    assert budget.complete.call_count == 1
    budget.failed.assert_not_called()
    registry = factory.read_registry(factory.REGISTRY_PATH)
    row = registry['services']['example']
    assert row['status'] == 'needs_review'
    assert Path(row['review_source']).read_bytes() == b'paid-source'
    assert factory.generate_one(max_attempts=3)['reason'] == 'no_pending_services'
    assert provider.generate_image.call_count == 1


def test_linux_font_bearings_and_variable_copy(tmp_path, monkeypatch):
    import os
    from PIL import ImageFont
    directories = [Path('/usr/share/fonts/truetype/dejavu'), Path(os.getenv('IG_TEST_FONT_DIR', '/nonexistent'))]
    directory = next((p for p in directories if (p / 'DejaVuSans.ttf').exists()), None)
    if directory is None:
        pytest.skip('Set IG_TEST_FONT_DIR or run in the Linux production image')
    for key, value in list(factory.FONTS.items()):
        filename = 'DejaVuSans.ttf' if key in ('body', 'tiny') else 'DejaVuSans-Bold.ttf'
        monkeypatch.setitem(factory.FONTS, key, ImageFont.truetype(str(directory / filename), value.size))
    for name in ['Electricidad', 'Lavandería / Tintorería', 'Restaurante / Comida preparada', 'Traductor Inglés - Español']:
        assert preflight_layout(DbService('regression', name, 123456), tmp_path)['layout']['issues'] == []


@pytest.mark.parametrize(("code", "required"), [
    ("aire_acondicionado_calefaccion", "wall-mounted split air conditioner"),
    ("calefont_termos", "domestic water heater"),
    ("peluqueria_canina", "dog grooming"),
    ("medico_veterinario", "healthy dog"),
    ("fletes_mudanzas", "moving van"),
])
def test_specific_scene_precedes_broad_keyword(code, required):
    assert required in factory.visual_scene_hint(DbService(code, code, 3))


def test_composition_does_not_claim_verification_speed_or_live_inventory(tmp_path, monkeypatch):
    base = tmp_path / "base.png"
    Image.new("RGB", (1080, 1350), "white").save(base)
    captured = []
    original = factory.draw_fitted_text
    def capture(draw, box, text, *args, **kwargs):
        captured.append(text)
        return original(draw, box, text, *args, **kwargs)
    monkeypatch.setattr(factory, "draw_fitted_text", capture)
    factory.compose_asset(base_path=base, output_path=tmp_path / "final.png",
        service=DbService("gasfiteria", "Gasfiteria", 9876))
    rendered = " ".join(captured).lower()
    assert "buscar contactos es gratis" in rendered
    assert "el servicio lo cobra cada profesional" in rendered
    assert "gasfíter" in rendered
    for forbidden in ["verificad", "rápida", "9876", "profesionales activos", "servicio disponible"]:
        assert forbidden not in rendered


@pytest.mark.parametrize("label", ["climatización", "kinesiología", "hamburguesas", "electrodomésticos", "sanitización"])
def test_headline_shrinks_before_splitting_words_or_punctuation(label, monkeypatch):
    draw = factory.ImageDraw.Draw(Image.new("RGB", (1080, 1350), "white"))
    lines = []
    original = draw.text
    def capture(position, text, *args, **kwargs):
        lines.append(text)
        return original(position, text, *args, **kwargs)
    monkeypatch.setattr(draw, "text", capture)
    factory.draw_fitted_text(draw, (64, 182, 604, 410), "¿Buscas\n"+label+"?",
        factory.FONTS["title"], "black", min_size=38, gap=10)
    assert lines == ["¿Buscas", label+"?"]


def test_unbreakable_unreadable_word_fails_instead_of_slicing_letters():
    draw = factory.ImageDraw.Draw(Image.new("RGB", (600, 300)))
    with pytest.raises(RuntimeError, match="cannot fit"):
        factory.draw_fitted_text(draw, (20, 20, 550, 270), "especialización"*5,
            factory.FONTS["body"], "black", min_size=24)
