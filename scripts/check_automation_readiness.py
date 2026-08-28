from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.chdir(PROJECT_ROOT)
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from conecta_video_ai.settings import load_settings


def _get_json(url: str) -> dict:
    req = Request(url=url, method="GET")
    with urlopen(req, timeout=60) as resp:
        raw = resp.read().decode("utf-8")
    return json.loads(raw) if raw.strip() else {}


def _iso_to_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def main() -> int:
    s = load_settings()
    token_mode = (s.meta_token_mode or "user_refresh").strip().lower()
    use_system_mode = token_mode == "system_user"

    missing = []
    if not (s.meta_app_id or "").strip():
        missing.append("META_APP_ID")
    if not (s.meta_app_secret or "").strip():
        missing.append("META_APP_SECRET")
    if not (s.meta_access_token or "").strip():
        missing.append("META_ACCESS_TOKEN")
    if not (s.meta_page_id or "").strip():
        missing.append("META_PAGE_ID")
    if not (s.meta_instagram_user_id or "").strip():
        missing.append("META_INSTAGRAM_USER_ID")
    if not use_system_mode and not (s.meta_user_access_token or "").strip():
        missing.append("META_USER_ACCESS_TOKEN")

    if missing:
        print(json.dumps({"ok": False, "missing_env": missing, "token_mode": token_mode}, ensure_ascii=False, indent=2))
        return 2

    app_token = f"{s.meta_app_id}|{s.meta_app_secret}"

    page_debug = _get_json(
        f"https://graph.facebook.com/{s.meta_graph_version}/debug_token?"
        + urlencode({"input_token": s.meta_access_token, "access_token": app_token})
    )
    page_data = (page_debug or {}).get("data") or {}

    user_data = {}
    if (s.meta_user_access_token or "").strip():
        user_debug = _get_json(
            f"https://graph.facebook.com/{s.meta_graph_version}/debug_token?"
            + urlencode({"input_token": s.meta_user_access_token, "access_token": app_token})
        )
        user_data = (user_debug or {}).get("data") or {}

    page_scopes = set(page_data.get("scopes") or [])
    user_scopes = set(user_data.get("scopes") or [])

    publish_via_base_url = bool((s.instagram_public_base_url or "").strip())
    can_stage_locally = "pages_manage_posts" in page_scopes

    blockers: list[str] = []
    if not bool(page_data.get("is_valid")):
        blockers.append("META_ACCESS_TOKEN invalido o expirado")

    token_type = str(page_data.get("type") or "").upper()
    if not use_system_mode and token_type != "PAGE":
        blockers.append("META_ACCESS_TOKEN no es token de PAGINA (modo user_refresh)")

    publish_scopes = page_scopes.union(user_scopes)
    if "instagram_content_publish" not in publish_scopes:
        blockers.append("Falta scope instagram_content_publish")

    if not publish_via_base_url and not can_stage_locally:
        blockers.append(
            "No hay forma de obtener URL publica automatica por imagen: configura INSTAGRAM_PUBLIC_BASE_URL o agrega pages_manage_posts"
        )

    user_exp = _iso_to_dt(s.meta_user_token_expires_at)
    exp_hours = None
    if user_exp:
        exp_hours = round((user_exp - datetime.now(timezone.utc)).total_seconds() / 3600, 2)

    payload = {
        "ok": len(blockers) == 0,
        "mode": "strict_no_fallback",
        "token_mode": token_mode,
        "blockers": blockers,
        "access_token": {
            "type": page_data.get("type"),
            "is_valid": page_data.get("is_valid"),
            "profile_id": page_data.get("profile_id"),
            "scopes": sorted(page_scopes),
        },
        "user_token": {
            "type": user_data.get("type") if user_data else None,
            "is_valid": user_data.get("is_valid") if user_data else None,
            "expires_at": s.meta_user_token_expires_at,
            "expires_in_hours": exp_hours,
            "scopes": sorted(user_scopes),
        },
        "publish_paths": {
            "via_instagram_public_base_url": publish_via_base_url,
            "via_meta_local_staging": can_stage_locally,
        },
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
