from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import json


class MetaConnectorError(RuntimeError):
    pass


@dataclass
class MetaCredentials:
    app_id: str
    app_secret: str
    access_token: str
    page_id: str
    instagram_user_id: str | None = None
    graph_version: str = "v21.0"


class MetaGraphClient:
    def __init__(self, credentials: MetaCredentials) -> None:
        self.credentials = credentials

        if not credentials.access_token.strip():
            raise MetaConnectorError("META_ACCESS_TOKEN no configurado")
        if not credentials.page_id.strip():
            raise MetaConnectorError("META_PAGE_ID no configurado")

    def _base_url(self) -> str:
        version = (self.credentials.graph_version or "v21.0").strip() or "v21.0"
        return f"https://graph.facebook.com/{version}"

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        all_params = dict(params)
        all_params["access_token"] = self.credentials.access_token
        qs = urlencode({k: v for k, v in all_params.items() if v is not None})
        url = f"{self._base_url()}{path}?{qs}"
        req = Request(url=url, method="GET")

        try:
            with urlopen(req, timeout=60) as resp:
                payload = resp.read().decode("utf-8")
                data = json.loads(payload) if payload.strip() else {}
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise MetaConnectorError(f"Meta Graph HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise MetaConnectorError(f"Meta Graph network error: {exc}") from exc
        except Exception as exc:  # noqa: BLE001
            raise MetaConnectorError(f"Meta Graph unexpected error: {exc}") from exc

        if isinstance(data, dict) and data.get("error"):
            err = data.get("error") or {}
            message = str(err.get("message") or "Meta Graph error")
            code = err.get("code")
            sub = err.get("error_subcode")
            raise MetaConnectorError(f"Meta Graph error code={code} subcode={sub}: {message}")

        return data

    def _debug_scopes(self) -> list[str]:
        app_id = (self.credentials.app_id or "").strip()
        app_secret = (self.credentials.app_secret or "").strip()
        if not app_id or not app_secret:
            return []

        qs = urlencode(
            {
                "input_token": self.credentials.access_token,
                "access_token": f"{app_id}|{app_secret}",
            }
        )
        url = f"{self._base_url()}/debug_token?{qs}"
        req = Request(url=url, method="GET")

        try:
            with urlopen(req, timeout=60) as resp:
                payload = resp.read().decode("utf-8")
                data = json.loads(payload) if payload.strip() else {}
        except Exception:
            return []

        token_data = (data or {}).get("data") or {}
        scopes = token_data.get("scopes") or []
        if isinstance(scopes, list):
            return [str(x).strip() for x in scopes if str(x).strip()]
        return []

    def inspect_account(self, media_limit: int = 5) -> dict[str, Any]:
        media_limit = max(1, min(int(media_limit), 25))
        scopes = self._debug_scopes()

        page = self._get(
            f"/{self.credentials.page_id}",
            {
                "fields": "id,name,link,instagram_business_account{id,username,name,profile_picture_url,followers_count,media_count}",
            },
        )

        ig = page.get("instagram_business_account") or {}
        ig_id = (self.credentials.instagram_user_id or ig.get("id") or "").strip()

        result: dict[str, Any] = {
            "ok": True,
            "graph_version": self.credentials.graph_version,
            "page": {
                "id": page.get("id"),
                "name": page.get("name"),
                "link": page.get("link"),
            },
            "instagram_connected": bool(ig_id),
            "instagram": None,
            "recent_media": [],
            "scopes": scopes,
            "capabilities": {
                "read_page": True,
                "read_instagram_profile": False,
                "read_instagram_media": False,
                "publish_instagram": any(scope in scopes for scope in {"instagram_content_publish", "instagram_business_content_publish"}),
            },
        }

        if not ig_id:
            return result

        profile = self._get(
            f"/{ig_id}",
            {
                "fields": "id,username,name,biography,followers_count,follows_count,media_count,profile_picture_url",
            },
        )

        media = self._get(
            f"/{ig_id}/media",
            {
                "fields": "id,caption,media_type,media_url,thumbnail_url,permalink,timestamp",
                "limit": media_limit,
            },
        )

        result["instagram"] = {
            "id": profile.get("id"),
            "username": profile.get("username"),
            "name": profile.get("name"),
            "followers_count": profile.get("followers_count"),
            "follows_count": profile.get("follows_count"),
            "media_count": profile.get("media_count"),
            "profile_picture_url": profile.get("profile_picture_url"),
        }
        result["recent_media"] = media.get("data") or []
        result["capabilities"]["read_instagram_profile"] = True
        result["capabilities"]["read_instagram_media"] = True
        return result