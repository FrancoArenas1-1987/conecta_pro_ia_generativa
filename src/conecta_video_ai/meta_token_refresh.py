from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .exceptions import GenerationError


class MetaTokenRefreshError(GenerationError):
    pass


@dataclass
class MetaTokenRefreshResult:
    user_access_token: str
    user_expires_in_seconds: int
    user_expires_at_utc: str
    page_id: str
    page_name: str
    page_access_token: str
    instagram_user_id: str | None
    instagram_username: str | None
    graph_version: str


class MetaTokenRefresher:
    def __init__(self, *, app_id: str, app_secret: str, graph_version: str = "v21.0") -> None:
        self.app_id = (app_id or "").strip()
        self.app_secret = (app_secret or "").strip()
        self.graph_version = (graph_version or "v21.0").strip() or "v21.0"

        if not self.app_id:
            raise MetaTokenRefreshError("META_APP_ID no configurado")
        if not self.app_secret:
            raise MetaTokenRefreshError("META_APP_SECRET no configurado")

    def _base_url(self, *, with_version: bool = True) -> str:
        if with_version:
            return f"https://graph.facebook.com/{self.graph_version}"
        return "https://graph.facebook.com"

    def _get(self, path: str, params: dict[str, Any], *, with_version: bool = True) -> dict[str, Any]:
        qs = urlencode({k: v for k, v in params.items() if v is not None})
        url = f"{self._base_url(with_version=with_version)}{path}?{qs}"
        req = Request(url=url, method="GET")
        try:
            with urlopen(req, timeout=90) as resp:
                payload = resp.read().decode("utf-8")
                data = json.loads(payload) if payload.strip() else {}
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise MetaTokenRefreshError(f"Meta Graph HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise MetaTokenRefreshError(f"Meta Graph network error: {exc}") from exc
        except Exception as exc:  # noqa: BLE001
            raise MetaTokenRefreshError(f"Meta Graph unexpected error: {exc}") from exc

        if isinstance(data, dict) and data.get("error"):
            err = data.get("error") or {}
            message = str(err.get("message") or "Meta Graph error")
            code = err.get("code")
            sub = err.get("error_subcode")
            raise MetaTokenRefreshError(f"Meta Graph error code={code} subcode={sub}: {message}")

        return data

    def exchange_long_lived_user_token(self, short_or_long_user_token: str) -> tuple[str, int]:
        token = (short_or_long_user_token or "").strip()
        if not token:
            raise MetaTokenRefreshError("Token de usuario no configurado para renovar")

        data = self._get(
            "/oauth/access_token",
            {
                "grant_type": "fb_exchange_token",
                "client_id": self.app_id,
                "client_secret": self.app_secret,
                "fb_exchange_token": token,
            },
            with_version=True,
        )
        access_token = str(data.get("access_token") or "").strip()
        expires_in = int(data.get("expires_in") or 0)

        if not access_token:
            raise MetaTokenRefreshError("No se recibio access_token al renovar token largo")
        if expires_in <= 0:
            expires_in = 60 * 24 * 60 * 60

        return access_token, expires_in

    def list_pages(self, user_access_token: str) -> list[dict[str, Any]]:
        data = self._get(
            "/me/accounts",
            {
                "access_token": user_access_token,
                "fields": "id,name,access_token,tasks,instagram_business_account{id,username,name}",
                "limit": 200,
            },
        )
        pages = data.get("data") or []
        if not isinstance(pages, list):
            return []
        return [x for x in pages if isinstance(x, dict)]

    def fetch_page_by_id(self, *, user_access_token: str, page_id: str) -> dict[str, Any]:
        pid = (page_id or "").strip()
        if not pid:
            raise MetaTokenRefreshError("META_PAGE_ID requerido para resolver pagina por ID")

        data = self._get(
            f"/{pid}",
            {
                "access_token": user_access_token,
                "fields": "id,name,access_token,instagram_business_account{id,username,name}",
            },
        )
        if not isinstance(data, dict) or not str(data.get("id") or "").strip():
            raise MetaTokenRefreshError("No se pudo resolver pagina por ID con token de usuario")
        return data

    def resolve_page(self, pages: list[dict[str, Any]], preferred_page_id: str | None = None) -> dict[str, Any]:
        if not pages:
            raise MetaTokenRefreshError("No se encontraron paginas en /me/accounts. Revisa permisos pages_show_list")

        preferred = (preferred_page_id or "").strip()
        if preferred:
            for item in pages:
                if str(item.get("id") or "").strip() == preferred:
                    return item

        return pages[0]

    def refresh(self, *, current_user_token: str, preferred_page_id: str | None = None) -> MetaTokenRefreshResult:
        user_token, expires_in = self.exchange_long_lived_user_token(current_user_token)

        pages = self.list_pages(user_token)
        if pages:
            page = self.resolve_page(pages, preferred_page_id=preferred_page_id)
        else:
            preferred = (preferred_page_id or "").strip()
            if not preferred:
                raise MetaTokenRefreshError(
                    "No se encontraron paginas en /me/accounts y no hay META_PAGE_ID para resolver por ID."
                )
            page = self.fetch_page_by_id(user_access_token=user_token, page_id=preferred)

        page_id = str(page.get("id") or "").strip()
        page_name = str(page.get("name") or "").strip() or "Facebook Page"
        page_access_token = str(page.get("access_token") or "").strip()
        ig = page.get("instagram_business_account") or {}
        ig_id = str(ig.get("id") or "").strip() or None
        ig_username = str(ig.get("username") or "").strip() or None

        if not page_id:
            raise MetaTokenRefreshError("No se pudo resolver page_id al renovar token")
        if not page_access_token:
            raise MetaTokenRefreshError(
                "No se obtuvo page access token. Asegura que el token de usuario tenga alcance de pagina."
            )

        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        return MetaTokenRefreshResult(
            user_access_token=user_token,
            user_expires_in_seconds=expires_in,
            user_expires_at_utc=expires_at.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            page_id=page_id,
            page_name=page_name,
            page_access_token=page_access_token,
            instagram_user_id=ig_id,
            instagram_username=ig_username,
            graph_version=self.graph_version,
        )


_ENV_LINE_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")


def _sanitize_env_value(value: str) -> str:
    return str(value or "").strip().replace("\r", " ").replace("\n", " ")


def _prune_env_backups(*, env_path: Path, backups_to_keep: int) -> None:
    keep = max(0, int(backups_to_keep))
    pattern = f"{env_path.name}.bak_*"
    backups = [p for p in env_path.parent.glob(pattern) if p.is_file()]
    backups.sort(key=lambda p: (p.stat().st_mtime, p.name), reverse=True)
    for stale in backups[keep:]:
        try:
            stale.unlink(missing_ok=False)
        except Exception:
            continue


def update_env_file(
    *,
    env_path: Path,
    updates: dict[str, str],
    create_backup: bool = True,
    backups_to_keep: int | None = None,
) -> Path | None:
    env_path = Path(env_path)
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()
    else:
        lines = []

    backup_path: Path | None = None
    if create_backup and env_path.exists():
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = env_path.with_suffix(f".bak_{stamp}")
        backup_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    key_to_line: dict[str, int] = {}
    for idx, line in enumerate(lines):
        m = _ENV_LINE_RE.match(line.strip())
        if m:
            key_to_line[m.group(1)] = idx

    for key, raw_value in updates.items():
        value = _sanitize_env_value(raw_value)
        new_line = f"{key}={value}"
        if key in key_to_line:
            lines[key_to_line[key]] = new_line
        else:
            lines.append(new_line)

    env_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    if backups_to_keep is not None:
        _prune_env_backups(env_path=env_path, backups_to_keep=backups_to_keep)
    return backup_path
