from __future__ import annotations

import json
import sys

from conecta_video_ai.meta_connector import MetaConnectorError, MetaCredentials, MetaGraphClient
from conecta_video_ai.settings import load_settings


def _print_json(payload: dict) -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main() -> int:
    settings = load_settings()

    missing: list[str] = []
    if not (settings.meta_access_token or "").strip():
        missing.append("META_ACCESS_TOKEN")
    if not (settings.meta_page_id or "").strip():
        missing.append("META_PAGE_ID")

    if missing:
        _print_json({"ok": False, "missing_env": missing})
        return 2

    try:
        client = MetaGraphClient(
            MetaCredentials(
                app_id=settings.meta_app_id or "",
                app_secret=settings.meta_app_secret or "",
                access_token=settings.meta_access_token or "",
                page_id=settings.meta_page_id or "",
                instagram_user_id=settings.meta_instagram_user_id,
                graph_version=settings.meta_graph_version,
            )
        )
        report = client.inspect_account(media_limit=5)
        _print_json(report)
        return 0
    except MetaConnectorError as exc:
        _print_json({"ok": False, "error": str(exc)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
