from datetime import datetime, timezone

from conecta_video_ai.publish_schedule import publish_window_status
from conecta_video_ai.settings import AppSettings, load_settings


def test_publish_window_blocks_chile_early_morning():
    status = publish_window_status(
        enabled=True,
        timezone_name="America/Santiago",
        allowed_windows="11:00-20:30",
        now_utc=datetime(2026, 8, 29, 6, 15, tzinfo=timezone.utc),
    )

    assert status["allowed"] is False
    assert status["reason"] == "outside_publish_time_window"
    assert status["local_now"].startswith("2026-08-29T02:15:00")
    assert status["next_allowed_local"].startswith("2026-08-29T11:00:00")


def test_publish_window_allows_chile_afternoon():
    status = publish_window_status(
        enabled=True,
        timezone_name="America/Santiago",
        allowed_windows="11:00-20:30",
        now_utc=datetime(2026, 8, 29, 18, 30, tzinfo=timezone.utc),
    )

    assert status["allowed"] is True
    assert status["reason"] == "inside_publish_time_window"
    assert status["local_now"].startswith("2026-08-29T14:30:00")


def test_publish_window_can_be_configured_from_env(monkeypatch, tmp_path):
    cfg = tmp_path / "app.yaml"
    cfg.write_text("output_root: output/runs\n", encoding="utf-8")
    monkeypatch.setenv("INSTAGRAM_PUBLISH_TIME_WINDOW_ENABLED", "false")
    monkeypatch.setenv("INSTAGRAM_PUBLISH_TIMEZONE", "America/Santiago")
    monkeypatch.setenv("INSTAGRAM_PUBLISH_ALLOWED_WINDOWS", "12:00-18:00")

    settings = load_settings(cfg)

    assert isinstance(settings, AppSettings)
    assert settings.instagram_publish_time_window_enabled is False
    assert settings.instagram_publish_timezone == "America/Santiago"
    assert settings.instagram_publish_allowed_windows == "12:00-18:00"
