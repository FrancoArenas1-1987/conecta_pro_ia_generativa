from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from conecta_video_ai.meta_token_refresh import MetaTokenRefreshError, MetaTokenRefresher, update_env_file
from conecta_video_ai.settings import load_settings


def _json_print(payload: dict) -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _resolve_keep_backups(args_keep_backups: int | None) -> int:
    if args_keep_backups is not None:
        return max(0, int(args_keep_backups))
    raw = os.getenv("META_ENV_BACKUPS_TO_KEEP", "0").strip()
    try:
        return max(0, int(raw))
    except Exception:
        return 0


def _remove_env_backups(env_file: Path) -> int:
    removed = 0
    pattern = f"{env_file.name}.bak_*"
    for stale in env_file.parent.glob(pattern):
        if not stale.is_file():
            continue
        try:
            stale.unlink()
            removed += 1
        except Exception:
            continue
    return removed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Renueva token Meta automaticamente y actualiza .env")
    parser.add_argument("--env-file", type=Path, default=Path(".env"), help="Ruta de archivo .env")
    parser.add_argument("--page-id", type=str, default=None, help="Forzar page_id especifico")
    parser.add_argument(
        "--user-token",
        type=str,
        default=None,
        help="Token usuario base para renovar (si no se define, usa META_USER_ACCESS_TOKEN)",
    )
    parser.add_argument(
        "--keep-backups",
        type=int,
        default=None,
        help="Cantidad de backups .env.bak_* a conservar (default: META_ENV_BACKUPS_TO_KEEP o 0)",
    )
    parser.add_argument("--dry-run", action="store_true", help="No escribe .env, solo muestra resultado")
    args = parser.parse_args(argv)

    settings = load_settings()

    user_token = (args.user_token or settings.meta_user_access_token or "").strip()
    if not user_token:
        _json_print({"ok": False, "error": "Falta token base de usuario. Define META_USER_ACCESS_TOKEN o usa --user-token."})
        return 2

    page_hint = (args.page_id or settings.meta_page_id or "").strip() or None

    try:
        keep_backups = _resolve_keep_backups(args.keep_backups)
        refresher = MetaTokenRefresher(
            app_id=settings.meta_app_id or "",
            app_secret=settings.meta_app_secret or "",
            graph_version=settings.meta_graph_version,
        )
        result = refresher.refresh(current_user_token=user_token, preferred_page_id=page_hint)

        updates: dict[str, str] = {
            "META_USER_ACCESS_TOKEN": result.user_access_token,
            "META_USER_TOKEN_EXPIRES_AT": result.user_expires_at_utc,
            "META_ACCESS_TOKEN": result.page_access_token,
            "META_PAGE_ID": result.page_id,
        }
        if result.instagram_user_id:
            updates["META_INSTAGRAM_USER_ID"] = result.instagram_user_id

        backup = None
        removed_backups = 0
        if not args.dry_run:
            create_backup = keep_backups > 0
            backup = update_env_file(
                env_path=args.env_file,
                updates=updates,
                create_backup=create_backup,
                backups_to_keep=keep_backups if create_backup else None,
            )
            if keep_backups == 0:
                removed_backups = _remove_env_backups(args.env_file)

        payload = {
            "ok": True,
            "graph_version": result.graph_version,
            "user_token": {
                "expires_in_seconds": result.user_expires_in_seconds,
                "expires_at_utc": result.user_expires_at_utc,
            },
            "page": {
                "id": result.page_id,
                "name": result.page_name,
            },
            "instagram": {
                "user_id": result.instagram_user_id,
                "username": result.instagram_username,
            },
            "env_file": str(args.env_file),
            "updated_keys": sorted(list(updates.keys())),
            "backup_file": str(backup) if backup else None,
            "backup_keep_count": keep_backups,
            "backup_files_removed": removed_backups,
            "dry_run": bool(args.dry_run),
            "mode": "strict",
        }
        _json_print(payload)
        return 0

    except MetaTokenRefreshError as exc:
        _json_print({"ok": False, "error": str(exc), "mode": "strict"})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
