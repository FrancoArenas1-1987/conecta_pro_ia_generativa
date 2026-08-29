from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def _parse_hhmm(value: str) -> time | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    parts = raw.split(":")
    if len(parts) != 2:
        return None
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError:
        return None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return time(hour=hour, minute=minute)


def _parse_windows(raw_windows: str) -> list[tuple[time, time]]:
    windows: list[tuple[time, time]] = []
    for chunk in str(raw_windows or "").replace(";", ",").split(","):
        raw = chunk.strip()
        if not raw:
            continue
        if "-" not in raw:
            return []
        start_raw, end_raw = raw.split("-", 1)
        start = _parse_hhmm(start_raw)
        end = _parse_hhmm(end_raw)
        if start is None or end is None:
            return []
        windows.append((start, end))
    return windows


def _resolve_timezone(timezone_name: str):
    name = str(timezone_name or "").strip() or "America/Santiago"
    try:
        return ZoneInfo(name), "zoneinfo"
    except ZoneInfoNotFoundError:
        if name == "America/Santiago":
            return timezone(timedelta(hours=-4), name), "fixed_offset_fallback"
        return timezone.utc, "utc_fallback"


def _minutes(value: time) -> int:
    return (int(value.hour) * 60) + int(value.minute)


def _is_time_in_window(local_time: time, start: time, end: time) -> bool:
    now_min = _minutes(local_time)
    start_min = _minutes(start)
    end_min = _minutes(end)
    if start_min <= end_min:
        return start_min <= now_min <= end_min
    return now_min >= start_min or now_min <= end_min


def _next_window_start(local_now: datetime, windows: list[tuple[time, time]]) -> datetime | None:
    candidates: list[datetime] = []
    for start, _end in windows:
        candidate = local_now.replace(hour=start.hour, minute=start.minute, second=0, microsecond=0)
        if candidate <= local_now:
            candidate = candidate + timedelta(days=1)
        candidates.append(candidate)
    if not candidates:
        return None
    return min(candidates)


def publish_window_status(
    *,
    enabled: bool,
    timezone_name: str,
    allowed_windows: str,
    now_utc: datetime | None = None,
) -> dict:
    tz, timezone_status = _resolve_timezone(timezone_name)
    now = now_utc or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now = now.astimezone(timezone.utc)
    local_now = now.astimezone(tz)
    windows = _parse_windows(allowed_windows)
    window_labels = [f"{start.strftime('%H:%M')}-{end.strftime('%H:%M')}" for start, end in windows]

    base = {
        "enabled": bool(enabled),
        "timezone": str(timezone_name or "America/Santiago"),
        "timezone_status": timezone_status,
        "local_now": local_now.replace(microsecond=0).isoformat(),
        "allowed_windows": window_labels,
    }
    if not enabled:
        return {**base, "allowed": True, "reason": "publish_time_window_disabled"}
    if not windows:
        return {**base, "allowed": False, "reason": "invalid_publish_time_windows"}
    if any(_is_time_in_window(local_now.time(), start, end) for start, end in windows):
        return {**base, "allowed": True, "reason": "inside_publish_time_window"}

    next_allowed = _next_window_start(local_now, windows)
    payload = {**base, "allowed": False, "reason": "outside_publish_time_window"}
    if next_allowed is not None:
        payload["next_allowed_local"] = next_allowed.isoformat()
        payload["next_allowed_utc"] = next_allowed.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return payload
