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


def test_choose_next_service_rebuilds_old_quality_standard_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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

    assert decision is not None
    assert decision.action == "rebuild"
    assert decision.reason == "missing_or_stale_factory_manifest"


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
