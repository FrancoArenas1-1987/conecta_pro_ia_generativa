from pathlib import Path
from types import SimpleNamespace
import json
import pytest
from conecta_video_ai.service_images import reconcile, approved_paths, read_registry
from conecta_video_ai.image_budget import ImageBudget, BudgetBlocked
from scripts.instagram_image_factory import choose_next_service, DbService


def test_adopts_alias_once_and_never_regenerates_changed_file(tmp_path):
    image = tmp_path / "software.png"
    image.write_bytes(b"original")
    path = tmp_path / "registry.json"
    service = DbService("desarrollo_web", "Software", 2)
    catalog = {"items": [{"category_id": "desarrollo_software", "rel_path": image.name, "quality_passed": True}]}
    registry = reconcile(path, [service], tmp_path, catalog)
    assert approved_paths(registry, tmp_path) == {"desarrollo_web": image}
    # An unrelated new image or quality revision cannot displace an approval.
    registry = reconcile(path, [service], tmp_path, {"items": []})
    assert registry["services"][service.code]["status"] == "approved"
    image.write_bytes(b"changed")
    registry = reconcile(path, [service], tmp_path, catalog)
    assert not approved_paths(registry, tmp_path)
    assert choose_next_service([service], assets_root=tmp_path, registry=registry) is None


def test_only_missing_services_generated_and_unavailable_not_published(tmp_path):
    service = DbService("electricidad", "Electricidad", 1)
    path = tmp_path / "registry.json"
    registry = reconcile(path, [service], tmp_path, {"items": []})
    assert choose_next_service([service], assets_root=tmp_path, registry=registry).action == "create"
    registry = reconcile(path, [], tmp_path, {"items": []})
    assert not approved_paths(registry, tmp_path)


def test_budget_reservations_and_quota_resume(tmp_path):
    b = ImageBudget(tmp_path / "budget.db", limit=0.5, reserve_usd=0.3)
    first = b.reserve("dentista")
    with pytest.raises(BudgetBlocked, match="monthly"):
        ImageBudget(b.path, 0.5, 0.3).reserve("gasfiteria")
    b.failed(first, "credit_balance_exhausted")
    with pytest.raises(BudgetBlocked, match="quota"):
        b.reserve("gasfiteria")
    b.resume()
    second = b.reserve("gasfiteria")
    b.complete(second, {"model": "gpt-image-1", "usage": {"output_tokens": 6240, "input_tokens_details": {"text_tokens": 500, "image_tokens": 0}}})
    with b.connect() as db:
        assert db.execute("SELECT amount FROM requests WHERE id=?", (second,)).fetchone()[0] == pytest.approx(0.2521)


def test_history_import_idempotent_and_no_double_charge(tmp_path):
    b = ImageBudget(tmp_path / "budget.db", 5)
    for n, extra in [(1, {}), (2, {"budget_request_id": "tracked"})]:
        (tmp_path / f"image-factory_2026090{n}T120000Z.log").write_text("log\n" + json.dumps({"created": True, **extra}))
    b.import_history(tmp_path, 0.25)
    b.import_history(tmp_path, 0.25)
    with b.connect() as db:
        assert db.execute("SELECT COUNT(*),SUM(amount) FROM requests").fetchone() == (1, 0.25)


def test_corrupt_registry_fails_closed(tmp_path):
    path = tmp_path / "registry.json"
    path.write_text("{}")
    with pytest.raises(ValueError):
        read_registry(path)


def test_factory_main_returns_nonzero_on_failed_generation(tmp_path, monkeypatch):
    import scripts.instagram_image_factory as factory
    monkeypatch.setattr(factory, "STATE_DIR", tmp_path / "image_factory")
    monkeypatch.setattr(factory, "REGISTRY_PATH", tmp_path / "registry.json")
    monkeypatch.setattr(factory, "load_db_services", lambda **kw: [])
    monkeypatch.setattr(factory, "load_settings", lambda: SimpleNamespace(instagram_publish_assets_root=tmp_path, instagram_asset_catalog_path=tmp_path / "catalog.json"))
    monkeypatch.setattr(factory, "acquire_lock", lambda: (True, "ok"))
    monkeypatch.setattr(factory, "release_lock", lambda: None)
    monkeypatch.setattr(factory, "generate_one", lambda **kw: {"ok": False, "status": "failed"})
    monkeypatch.setattr(factory.sys, "argv", ["factory", "--dry-run"])
    with pytest.raises(SystemExit) as exc:
        factory.main()
    assert exc.value.code == 1


def test_carousel_checks_again_after_exact_interval(monkeypatch):
    import scripts.run_instagram_carousel_once as carousel
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(carousel, "read_json", lambda *args: {"last_published_at": (now-timedelta(hours=48)+timedelta(minutes=10)).isoformat()})
    assert carousel.should_skip(48)[0]
    monkeypatch.setattr(carousel, "read_json", lambda *args: {"last_published_at": (now-timedelta(hours=48)-timedelta(minutes=5)).isoformat()})
    assert carousel.should_skip(48) == (False, None)
