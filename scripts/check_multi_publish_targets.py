from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from conecta_video_ai.pipelines import StudioService
from conecta_video_ai.settings import load_settings


def _get_json(url: str) -> dict[str, Any]:
    req = Request(url=url, method="GET")
    with urlopen(req, timeout=60) as resp:
        raw = resp.read().decode("utf-8")
    return json.loads(raw) if raw.strip() else {}


def _safe_json(url: str) -> tuple[dict[str, Any] | None, str | None]:
    try:
        return _get_json(url), None
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        return None, f"HTTP {exc.code}: {detail}"
    except URLError as exc:
        return None, f"Network error: {exc}"
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)


def _target_report(target: dict[str, Any], *, app_token: str) -> dict[str, Any]:
    name = str(target.get("name") or "target")
    version = str(target.get("meta_graph_version") or "v21.0").strip() or "v21.0"
    access_token = str(target.get("meta_access_token") or "").strip()
    page_id = str(target.get("meta_page_id") or "").strip()
    ig_id = str(target.get("meta_instagram_user_id") or "").strip()
    publish_instagram = bool(target.get("publish_instagram", True))
    crosspost_facebook = bool(target.get("crosspost_facebook", False))

    missing: list[str] = []
    if not access_token:
        missing.append("meta_access_token")
    if not page_id:
        missing.append("meta_page_id")
    if publish_instagram and not ig_id:
        missing.append("meta_instagram_user_id")
    if missing:
        return {"target": name, "ok": False, "missing": missing}

    debug_url = f"https://graph.facebook.com/{version}/debug_token?" + urlencode(
        {"input_token": access_token, "access_token": app_token}
    )
    debug_data, debug_err = _safe_json(debug_url)
    if debug_err:
        return {"target": name, "ok": False, "error": f"debug_token failed: {debug_err}"}
    debug_payload = (debug_data or {}).get("data") or {}

    page_url = f"https://graph.facebook.com/{version}/{page_id}?" + urlencode(
        {"fields": "id,name,is_owned,instagram_business_account{id,username}", "access_token": access_token}
    )
    page_data, page_err = _safe_json(page_url)
    if page_err:
        return {"target": name, "ok": False, "error": f"page inspect failed: {page_err}"}

    scopes = debug_payload.get("scopes") or []
    if not isinstance(scopes, list):
        scopes = []

    page_obj = page_data or {}
    page_ig = page_obj.get("instagram_business_account") or {}
    page_ig_id = str(page_ig.get("id") or "").strip()

    notes: list[str] = []
    if publish_instagram and page_ig_id and ig_id and page_ig_id != ig_id:
        notes.append("configured_ig_id_differs_from_page_linked_ig")
    if crosspost_facebook and "pages_manage_posts" not in scopes:
        notes.append("missing_pages_manage_posts_for_facebook_post")
    if publish_instagram and "instagram_content_publish" not in scopes:
        notes.append("missing_instagram_content_publish")

    ok = bool(debug_payload.get("is_valid")) and not notes
    return {
        "target": name,
        "ok": ok,
        "is_primary": bool(target.get("is_primary", False)),
        "publish_instagram": publish_instagram,
        "crosspost_facebook": crosspost_facebook,
        "token": {
            "is_valid": bool(debug_payload.get("is_valid")),
            "type": debug_payload.get("type"),
            "scopes": scopes,
        },
        "page": {
            "id": page_obj.get("id"),
            "name": page_obj.get("name"),
            "is_owned": page_obj.get("is_owned"),
            "linked_instagram_id": page_ig_id or None,
            "linked_instagram_username": page_ig.get("username"),
        },
        "configured_instagram_id": ig_id or None,
        "notes": notes,
    }


def main() -> int:
    settings = load_settings()
    app_id = str(settings.meta_app_id or "").strip()
    app_secret = str(settings.meta_app_secret or "").strip()
    if not app_id or not app_secret:
        print(
            json.dumps(
                {"ok": False, "error": "Faltan META_APP_ID/META_APP_SECRET para validar tokens."},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2

    service = StudioService.__new__(StudioService)
    service.settings = settings
    targets = service._load_instagram_publish_targets()
    if not targets:
        print(json.dumps({"ok": False, "error": "No hay destinos configurados."}, ensure_ascii=False, indent=2))
        return 2

    app_token = f"{app_id}|{app_secret}"
    reports = [_target_report(t, app_token=app_token) for t in targets]
    ok_count = len([r for r in reports if bool(r.get("ok"))])
    payload = {
        "ok": ok_count == len(reports),
        "targets_total": len(reports),
        "targets_ok": ok_count,
        "targets_failed": len(reports) - ok_count,
        "reports": reports,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
