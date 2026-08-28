from __future__ import annotations

import json
import mimetypes
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .performance_tracker import SocialPublisherAdapter


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _http_json(
    *,
    method: str,
    url: str,
    headers: dict[str, str] | None = None,
    json_body: dict | None = None,
    form_body: dict | None = None,
    timeout: int = 60,
) -> dict[str, Any]:
    body: bytes | None = None
    req_headers = dict(headers or {})

    if json_body is not None:
        body = json.dumps(json_body).encode("utf-8")
        req_headers.setdefault("Content-Type", "application/json")
    elif form_body is not None:
        body = urlencode(form_body).encode("utf-8")
        req_headers.setdefault("Content-Type", "application/x-www-form-urlencoded")

    req = Request(url=url, data=body, method=method.upper(), headers=req_headers)
    try:
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw.strip() else {}
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"HTTP {exc.code} {url}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"Network error {url}: {exc}") from exc


def _http_bytes(
    *,
    method: str,
    url: str,
    headers: dict[str, str],
    data: bytes,
    timeout: int = 300,
) -> None:
    req = Request(url=url, data=data, method=method.upper(), headers=headers)
    try:
        with urlopen(req, timeout=timeout):
            return
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"HTTP {exc.code} upload {url}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"Network error upload {url}: {exc}") from exc


class YouTubePublisher(SocialPublisherAdapter):
    channel_name = "youtube"

    def __init__(
        self,
        *,
        access_token: str | None,
        refresh_token: str | None,
        client_id: str | None,
        client_secret: str | None,
        privacy_status: str = "public",
        category_id: str = "22",
    ) -> None:
        self.access_token = (access_token or "").strip()
        self.refresh_token = (refresh_token or "").strip()
        self.client_id = (client_id or "").strip()
        self.client_secret = (client_secret or "").strip()
        self.privacy_status = privacy_status
        self.category_id = category_id

    def _ensure_token(self) -> str:
        if self.access_token:
            return self.access_token

        if not (self.refresh_token and self.client_id and self.client_secret):
            raise RuntimeError("YouTube credentials incompletas. Define token o refresh credentials.")

        payload = _http_json(
            method="POST",
            url="https://oauth2.googleapis.com/token",
            form_body={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": self.refresh_token,
                "grant_type": "refresh_token",
            },
        )
        token = str(payload.get("access_token", "")).strip()
        if not token:
            raise RuntimeError(f"No se pudo refrescar token YouTube: {payload}")
        self.access_token = token
        return token

    @staticmethod
    def _build_multipart(metadata: dict, video_bytes: bytes, video_type: str) -> tuple[bytes, str]:
        boundary = "conectaproia-boundary"
        parts = [
            (
                f"--{boundary}\r\n"
                "Content-Type: application/json; charset=UTF-8\r\n\r\n"
                f"{json.dumps(metadata)}\r\n"
            ).encode("utf-8"),
            (
                f"--{boundary}\r\n"
                f"Content-Type: {video_type}\r\n\r\n"
            ).encode("utf-8"),
            video_bytes,
            f"\r\n--{boundary}--\r\n".encode("utf-8"),
        ]
        return b"".join(parts), boundary

    def publish_video(self, *, video_path: Path, caption: str, tags: list[str] | None = None) -> dict:
        token = self._ensure_token()
        video_bytes = video_path.read_bytes()
        video_type = mimetypes.guess_type(video_path.name)[0] or "video/mp4"

        clean_caption = " ".join((caption or "").split())
        title = clean_caption[:90] if clean_caption else f"ConectaProIA {video_path.stem}"

        metadata = {
            "snippet": {
                "title": title,
                "description": clean_caption,
                "tags": tags or ["conectaproia"],
                "categoryId": self.category_id,
            },
            "status": {
                "privacyStatus": self.privacy_status,
                "selfDeclaredMadeForKids": False,
            },
        }

        body, boundary = self._build_multipart(metadata, video_bytes, video_type)
        url = "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=multipart&part=snippet,status"
        req = Request(
            url=url,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": f"multipart/related; boundary={boundary}",
                "Content-Length": str(len(body)),
            },
        )
        try:
            with urlopen(req, timeout=600) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"YouTube upload failed: HTTP {exc.code} {detail}") from exc
        except URLError as exc:
            raise RuntimeError(f"YouTube upload network error: {exc}") from exc

        post_id = str(payload.get("id", "")).strip()
        if not post_id:
            raise RuntimeError(f"YouTube upload sin id: {payload}")

        return {
            "channel": self.channel_name,
            "post_id": post_id,
            "published_at": _now_iso(),
            "caption": clean_caption,
            "tags": tags or [],
            "url": f"https://www.youtube.com/watch?v={post_id}",
            "raw": payload,
        }

    def fetch_post_metrics(self, *, post_id: str) -> dict:
        token = self._ensure_token()
        payload = _http_json(
            method="GET",
            url=f"https://www.googleapis.com/youtube/v3/videos?part=statistics,snippet&id={post_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        items = payload.get("items") or []
        if not items:
            return {"post_id": post_id, "views": 0, "likes": 0, "comments": 0}

        stats = items[0].get("statistics") or {}
        return {
            "post_id": post_id,
            "views": int(stats.get("viewCount", 0) or 0),
            "likes": int(stats.get("likeCount", 0) or 0),
            "comments": int(stats.get("commentCount", 0) or 0),
        }


class TikTokPublisher(SocialPublisherAdapter):
    channel_name = "tiktok"

    def __init__(
        self,
        *,
        access_token: str | None,
        refresh_token: str | None,
        client_key: str | None,
        client_secret: str | None,
        privacy_level: str = "PUBLIC_TO_EVERYONE",
    ) -> None:
        self.access_token = (access_token or "").strip()
        self.refresh_token = (refresh_token or "").strip()
        self.client_key = (client_key or "").strip()
        self.client_secret = (client_secret or "").strip()
        self.privacy_level = privacy_level

    def _ensure_token(self) -> str:
        if self.access_token:
            return self.access_token

        if not (self.refresh_token and self.client_key and self.client_secret):
            raise RuntimeError("TikTok credentials incompletas. Define token o refresh credentials.")

        payload = _http_json(
            method="POST",
            url="https://open.tiktokapis.com/v2/oauth/token/",
            form_body={
                "client_key": self.client_key,
                "client_secret": self.client_secret,
                "grant_type": "refresh_token",
                "refresh_token": self.refresh_token,
            },
        )
        token = str(payload.get("access_token", "")).strip()
        if not token:
            raise RuntimeError(f"No se pudo refrescar token TikTok: {payload}")
        self.access_token = token
        new_refresh = str(payload.get("refresh_token", "")).strip()
        if new_refresh:
            self.refresh_token = new_refresh
        return token

    def publish_video(self, *, video_path: Path, caption: str, tags: list[str] | None = None) -> dict:
        token = self._ensure_token()
        data = video_path.read_bytes()
        size = len(data)
        chunk = max(5_000_000, min(size, 20_000_000))
        chunks = (size + chunk - 1) // chunk

        init_payload = _http_json(
            method="POST",
            url="https://open.tiktokapis.com/v2/post/publish/video/init/",
            headers={"Authorization": f"Bearer {token}"},
            json_body={
                "post_info": {
                    "title": " ".join((caption or "").split())[:2200],
                    "privacy_level": self.privacy_level,
                    "disable_duet": False,
                    "disable_comment": False,
                    "disable_stitch": False,
                    "video_cover_timestamp_ms": 500,
                },
                "source_info": {
                    "source": "FILE_UPLOAD",
                    "video_size": size,
                    "chunk_size": chunk,
                    "total_chunk_count": chunks,
                },
            },
        )

        if (init_payload.get("error") or {}).get("code") not in {None, "ok"}:
            raise RuntimeError(f"TikTok init error: {init_payload}")

        pdata = init_payload.get("data") or {}
        publish_id = str(pdata.get("publish_id", "")).strip()
        upload_url = str(pdata.get("upload_url", "")).strip()
        if not publish_id or not upload_url:
            raise RuntimeError(f"TikTok init invalido: {init_payload}")

        _http_bytes(
            method="PUT",
            url=upload_url,
            headers={
                "Content-Type": "video/mp4",
                "Content-Length": str(size),
            },
            data=data,
            timeout=600,
        )

        status_payload = {}
        for _ in range(20):
            time.sleep(2)
            status_payload = _http_json(
                method="POST",
                url="https://open.tiktokapis.com/v2/post/publish/status/fetch/",
                headers={"Authorization": f"Bearer {token}"},
                json_body={"publish_id": publish_id},
            )
            st = str(((status_payload.get("data") or {}).get("status") or "")).upper()
            if st in {"PUBLISH_COMPLETE", "SEND_TO_USER_INBOX", "FAILED"}:
                break

        data_status = status_payload.get("data") or {}
        public_ids = data_status.get("publicaly_available_post_id") or []
        post_id = str(public_ids[0]) if public_ids else publish_id

        return {
            "channel": self.channel_name,
            "post_id": post_id,
            "publish_id": publish_id,
            "published_at": _now_iso(),
            "caption": " ".join((caption or "").split()),
            "tags": tags or [],
            "status": data_status.get("status"),
            "raw": status_payload,
        }

    def fetch_post_metrics(self, *, post_id: str) -> dict:
        token = self._ensure_token()

        # If it's a publish_id (not yet public video id), fetch posting status only.
        if post_id.startswith("v_") or "~" in post_id:
            status = _http_json(
                method="POST",
                url="https://open.tiktokapis.com/v2/post/publish/status/fetch/",
                headers={"Authorization": f"Bearer {token}"},
                json_body={"publish_id": post_id},
            )
            return {
                "post_id": post_id,
                "status": (status.get("data") or {}).get("status"),
                "fail_reason": (status.get("data") or {}).get("fail_reason"),
            }

        # Public video metadata query (requires proper scopes).
        payload = _http_json(
            method="POST",
            url=(
                "https://open.tiktokapis.com/v2/video/query/"
                "?fields=id,title,view_count,like_count,comment_count,share_count"
            ),
            headers={"Authorization": f"Bearer {token}"},
            json_body={"filters": {"video_ids": [post_id]}},
        )
        videos = (payload.get("data") or {}).get("videos") or []
        if not videos:
            return {"post_id": post_id, "views": 0, "likes": 0, "comments": 0, "shares": 0}

        v = videos[0]
        return {
            "post_id": post_id,
            "views": int(v.get("view_count", 0) or 0),
            "likes": int(v.get("like_count", 0) or 0),
            "comments": int(v.get("comment_count", 0) or 0),
            "shares": int(v.get("share_count", 0) or 0),
        }
