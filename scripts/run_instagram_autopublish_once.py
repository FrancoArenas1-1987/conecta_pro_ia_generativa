from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.chdir(PROJECT_ROOT)
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from conecta_video_ai.publication_supply import synchronize_registry
from conecta_video_ai.campaign_queue import (
    CampaignSelectionError, mark_image_slot_completed, run_campaign_slot, safe_error,
)
from conecta_video_ai.publish_schedule import publish_window_status
from conecta_video_ai.pipelines import StudioService
from conecta_video_ai.settings import load_settings


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _append_log(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _safe_read_json(path: Path, fallback: dict[str, Any] | None = None) -> dict[str, Any]:
    if not path.exists():
        return dict(fallback or {})
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return dict(fallback or {})
    if isinstance(data, dict):
        return data
    return dict(fallback or {})


def _safe_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _acquire_runner_lock(lock_path: Path, *, stale_minutes: int = 240) -> tuple[bool, str]:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)

    def _try_create() -> bool:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return False
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            payload = {"pid": os.getpid(), "acquired_at": now.replace(microsecond=0).isoformat().replace("+00:00", "Z")}
            f.write(json.dumps(payload, ensure_ascii=False))
        return True

    if _try_create():
        return True, "acquired"

    lock_data = _safe_read_json(lock_path, {})
    acquired_raw = str(lock_data.get("acquired_at") or "").strip()
    acquired_at = _parse_utc_iso(acquired_raw)
    if acquired_at is not None:
        age_minutes = (now - acquired_at).total_seconds() / 60.0
        if age_minutes > float(max(5, stale_minutes)):
            try:
                lock_path.unlink(missing_ok=True)
            except Exception:
                return False, "active_lock_unreadable"
            if _try_create():
                return True, "stale_lock_recovered"

    holder_pid = lock_data.get("pid")
    holder = f"pid={holder_pid}" if holder_pid is not None else "pid=unknown"
    return False, f"active_lock:{holder}"


def _release_runner_lock(lock_path: Path) -> None:
    try:
        lock_path.unlink(missing_ok=True)
    except Exception:
        return


def _runner_lock_path(settings) -> Path:
    root_marker = str(settings.output_root or "").strip().lower()
    digest = hashlib.sha1(root_marker.encode("utf-8")).hexdigest()[:12]
    return Path(tempfile.gettempdir()) / f"conectaproia_ig_autopublish_{digest}.lock"


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


def _is_antispam_error(error_text: str) -> bool:
    msg = str(error_text or "").lower()
    return (
        '"code":368' in msg
        or "code=368" in msg
        or " code 368" in msg
        or "error_subcode\":1390008" in msg
    )


def _active_antispam_cooldown_until(settings) -> str | None:
    state = _safe_read_json(settings.instagram_state_path, {})
    until_raw = str(state.get("anti_spam_cooldown_until") or "").strip()
    until_dt = _parse_utc_iso(until_raw)
    now = datetime.now(timezone.utc)
    if until_dt is None:
        return None
    if until_dt <= now:
        # Auto-clear expired cooldown metadata to keep state clean.
        state.pop("anti_spam_cooldown_until", None)
        state.pop("anti_spam_cooldown_set_at", None)
        state.pop("anti_spam_cooldown_reason", None)
        _safe_write_json(settings.instagram_state_path, state)
        return None
    return until_dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _set_antispam_cooldown(settings, *, reason: str) -> str:
    minutes = max(1, int(settings.instagram_antispam_cooldown_minutes))
    now = datetime.now(timezone.utc).replace(microsecond=0)
    until = now + timedelta(minutes=minutes)
    state = _safe_read_json(settings.instagram_state_path, {})
    state["anti_spam_cooldown_until"] = until.isoformat().replace("+00:00", "Z")
    state["anti_spam_cooldown_set_at"] = now.isoformat().replace("+00:00", "Z")
    state["anti_spam_cooldown_reason"] = str(reason or "")[:800]
    _safe_write_json(settings.instagram_state_path, state)
    return str(state["anti_spam_cooldown_until"])


def _latest_published_utc(settings) -> datetime | None:
    drafts_root = Path(settings.instagram_drafts_root)
    if not drafts_root.exists():
        return None
    latest: datetime | None = None
    for draft_dir in sorted([p for p in drafts_root.iterdir() if p.is_dir()], key=lambda p: p.name.lower(), reverse=True):
        payload = _safe_read_json(draft_dir / "draft.json", None)
        if not isinstance(payload, dict):
            continue
        if str(payload.get("status") or "").strip().lower() not in {"published", "published_with_errors", "publication_uncertain"}:
            continue
        published_at = _parse_utc_iso(str(payload.get("published_at") or payload.get("publication_attempted_at") or "").strip())
        if published_at is None:
            continue
        if latest is None or published_at > latest:
            latest = published_at
    return latest


def _active_publish_interval_guard(settings) -> tuple[bool, str | None, float | None]:
    interval_minutes = max(15, int(settings.instagram_post_interval_minutes))
    last_published = _latest_published_utc(settings)
    if last_published is None:
        return False, None, None
    now = datetime.now(timezone.utc)
    delta_min = (now - last_published).total_seconds() / 60.0
    if delta_min < float(interval_minutes):
        remaining = max(0.0, float(interval_minutes) - delta_min)
        return True, str(int(round(remaining))), delta_min
    return False, None, delta_min


def main() -> None:
    parser = argparse.ArgumentParser(description="Ejecuta 1 ciclo IG real (post+story, IG+Facebook)")
    parser.add_argument("--objective", choices=["captar_clientes", "captar_proveedores", "branding"], default=None)
    parser.add_argument("--category", type=str, default=None)
    parser.add_argument("--use-meta-history", action=argparse.BooleanOptionalAction, default=True)
    args = parser.parse_args()

    settings = load_settings()
    log_path = settings.output_root / "instagram" / "automation_hourly_log.jsonl"
    schedule_status = publish_window_status(
        enabled=bool(settings.instagram_publish_time_window_enabled),
        timezone_name=str(settings.instagram_publish_timezone),
        allowed_windows=str(settings.instagram_publish_allowed_windows),
    )
    if not bool(schedule_status.get("allowed", False)):
        payload = {
            "ok": True,
            "skipped": True,
            "reason": str(schedule_status.get("reason") or "publish_time_window_closed"),
            "schedule": schedule_status,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        _append_log(log_path, {"ts": _now_iso(), "mode": "hourly_once", **payload})
        return

    # Enforce hourly real publishing, but respect .env/app.yaml quality/economy toggles.
    # This avoids hard-stopping the flow when monthly image budget is reached.
    # All paid image creation belongs to the missing-service factory.
    settings.instagram_enable_openai_images = False
    settings.instagram_require_ai_image = False
    settings.instagram_ai_library_fallback_enabled = True
    settings.instagram_simulate_publish = False
    settings.instagram_crosspost_facebook = bool(settings.instagram_crosspost_facebook)
    settings.instagram_publish_quality_gate_enabled = True
    settings.instagram_publish_auto_video_fallback_enabled = bool(settings.instagram_publish_auto_video_fallback_enabled)
    settings.instagram_publish_preflight_targets_enabled = bool(settings.instagram_publish_preflight_targets_enabled)
    # Preserve budget and estimated image cost from config/.env.
    # Do not override economics in the hourly runner.
    settings.instagram_openai_monthly_budget_usd = float(settings.instagram_openai_monthly_budget_usd)
    settings.instagram_openai_image_estimated_cost_usd = float(settings.instagram_openai_image_estimated_cost_usd)

    lock_path = _runner_lock_path(settings)
    lock_acquired, lock_note = _acquire_runner_lock(lock_path)
    if not lock_acquired:
        payload = {
            "ok": False,
            "skipped": True,
            "reason": "runner_lock_active",
            "lock_note": lock_note,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        _append_log(log_path, {"ts": _now_iso(), "mode": "hourly_once", **payload})
        return

    try:
        service = StudioService(settings)
        log_path = settings.output_root / "instagram" / "automation_hourly_log.jsonl"

        entry: dict = {
            "ts": _now_iso(),
            "mode": "hourly_once",
            "objective": args.objective,
            "category": args.category,
            "effective": {
                "enable_openai_images": settings.instagram_enable_openai_images,
                "require_ai_image": settings.instagram_require_ai_image,
                "simulate_publish": settings.instagram_simulate_publish,
                "crosspost_facebook": settings.instagram_crosspost_facebook,
                "publish_media_mode_configured": settings.instagram_publish_media_mode,
                "publish_media_mode_effective": service._instagram_publish_media_mode(),
                "quality_gate_enabled": settings.instagram_publish_quality_gate_enabled,
                "quality_gate_min_score": settings.instagram_publish_quality_min_score,
                "quality_burst_max_attempts": settings.instagram_publish_quality_burst_max_attempts,
                "antispam_cooldown_minutes": settings.instagram_antispam_cooldown_minutes,
                "post_interval_minutes": settings.instagram_post_interval_minutes,
                "publish_time_window_enabled": settings.instagram_publish_time_window_enabled,
                "publish_timezone": settings.instagram_publish_timezone,
                "publish_allowed_windows": settings.instagram_publish_allowed_windows,
                "publish_window_status": schedule_status,
                "video_fallback_enabled": settings.instagram_publish_auto_video_fallback_enabled,
                "preflight_targets_enabled": settings.instagram_publish_preflight_targets_enabled,
            },
        }

        try:
            entry["library_sync"] = service.instagram_engine.sync_asset_catalog()
        except Exception as exc:  # noqa: BLE001
            entry["library_sync"] = {"ok": False, "error": str(exc)}

        cooldown_until = _active_antispam_cooldown_until(settings)
        if cooldown_until:
            entry.update(
                {
                    "ok": False,
                    "skipped": True,
                    "reason": "anti_spam_cooldown_active",
                    "anti_spam_cooldown_until": cooldown_until,
                }
            )
            print(json.dumps({"ok": False, "skipped": True, "reason": "anti_spam_cooldown_active", "until": cooldown_until}, ensure_ascii=False, indent=2))
            _append_log(log_path, entry)
            return

        interval_blocked, interval_remaining, delta_min = _active_publish_interval_guard(settings)
        if interval_blocked:
            entry.update(
                {
                    "ok": False,
                    "skipped": True,
                    "reason": "publish_interval_guard_active",
                    "minutes_since_last_published": delta_min,
                    "minutes_remaining": interval_remaining,
                }
            )
            print(
                json.dumps(
                    {
                        "ok": False,
                        "skipped": True,
                        "reason": "publish_interval_guard_active",
                        "minutes_remaining": interval_remaining,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            _append_log(log_path, entry)
            return

        try:
            entry["live_supply"] = synchronize_registry(settings.output_root / "instagram/catalog/service_images.json")
            service.instagram_engine.sync_asset_catalog()
            result = None
            # Campaigns share the same timer, lock, interval and antispam guards.
            # Explicit category/objective invocations keep their original intent.
            if not args.category and not args.objective:
                try:
                    result = run_campaign_slot(service)
                except CampaignSelectionError as exc:
                    entry["campaign_selection_error"] = str(exc)
            is_campaign = result is not None
            if not is_campaign:
                sweep_report = service.instagram_engine.sweep_library_quality(force=False)
                entry["quality_sweep"] = sweep_report
                result = service.run_instagram_auto_cycle(
                    objective=args.objective,
                    force_category=args.category,
                    publish=True,
                    simulate_publish=False,
                    use_meta_history=bool(args.use_meta_history),
                    public_image_url=None,
                    public_video_url=None,
                )
            entry["campaign_id"] = result.get("campaign_id") if is_campaign else None
            draft = result.get("draft") if isinstance(result, dict) else {}
            publication = result.get("publication") if isinstance(result, dict) else {}
            publication_status = str((publication or {}).get("status") or "").strip().lower()
            entry_ok = publication_status == "ok"
            if entry_ok and not is_campaign:
                try:
                    mark_image_slot_completed(settings)
                except Exception as exc:
                    # A queue bookkeeping error must not relabel a published image.
                    entry["campaign_state_error"] = safe_error(exc)
            entry.update(
                {
                    "ok": entry_ok,
                    "draft_id": (draft or {}).get("draft_id"),
                    "post_id": (draft or {}).get("post_id"),
                    "post_url": (draft or {}).get("post_url"),
                    "story_id": (draft or {}).get("story_id"),
                    "story_url": (draft or {}).get("story_url"),
                    "published_channel": (draft or {}).get("published_channel"),
                    "story_channel": (draft or {}).get("story_channel"),
                    "facebook_publication": (draft or {}).get("facebook_publication"),
                    "facebook_story": (draft or {}).get("facebook_story"),
                    "quality_gate": result.get("quality_gate") if isinstance(result, dict) else None,
                    "quality_regeneration_attempt": result.get("quality_regeneration_attempt") if isinstance(result, dict) else None,
                    "publication": publication,
                    "publication_errors": (draft or {}).get("publication_errors"),
                    "targets_preflight": (draft or {}).get("targets_preflight"),
                }
            )
            print(json.dumps({"ok": entry_ok, "result": result}, ensure_ascii=False, indent=2))
        except Exception as exc:  # noqa: BLE001
            error_text = str(exc)
            entry.update({"ok": False, "error": error_text})
            if _is_antispam_error(error_text):
                until = _set_antispam_cooldown(settings, reason=error_text)
                entry["anti_spam_cooldown_until"] = until
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))

        _append_log(log_path, entry)
        if not bool(entry.get("ok", False)):
            raise SystemExit(1)
    finally:
        _release_runner_lock(lock_path)


if __name__ == "__main__":
    main()
