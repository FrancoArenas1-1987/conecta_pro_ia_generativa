from __future__ import annotations

import json
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from conecta_video_ai.settings import load_settings


def main() -> int:
    settings = load_settings()
    token = (settings.meta_access_token or "").strip()
    version = (settings.meta_graph_version or "v21.0").strip() or "v21.0"

    if not token:
        print(json.dumps({"ok": False, "error": "META_ACCESS_TOKEN vacio en .env"}, ensure_ascii=False, indent=2))
        return 2

    params = {
        "fields": "id,name,category,access_token",
        "access_token": token,
    }
    url = f"https://graph.facebook.com/{version}/me/accounts?{urlencode(params)}"

    req = Request(url=url, method="GET")
    try:
        with urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        print(json.dumps({"ok": False, "error": f"HTTP {exc.code}", "detail": detail}, ensure_ascii=False, indent=2))
        return 1
    except URLError as exc:
        print(json.dumps({"ok": False, "error": f"Network error: {exc}"}, ensure_ascii=False, indent=2))
        return 1

    if payload.get("error"):
        print(json.dumps({"ok": False, "error": payload.get("error")}, ensure_ascii=False, indent=2))
        return 1

    pages = payload.get("data") or []
    reduced = [
        {
            "id": str(p.get("id") or ""),
            "name": p.get("name"),
            "category": p.get("category"),
        }
        for p in pages
    ]

    print(json.dumps({"ok": True, "count": len(reduced), "pages": reduced}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())