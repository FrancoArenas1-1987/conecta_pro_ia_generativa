from __future__ import annotations

import json
import mimetypes
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from .exceptions import GenerationError
from .settings import AppSettings


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class InstagramGraphPublisher:
    def __init__(
        self,
        settings: AppSettings,
        *,
        access_token: str | None = None,
        page_id: str | None = None,
        ig_user_id: str | None = None,
        graph_version: str | None = None,
    ) -> None:
        self.settings = settings
        self.graph_version = (graph_version or settings.meta_graph_version or "v21.0").strip() or "v21.0"
        self.access_token = (access_token or settings.meta_access_token or "").strip()
        self.page_id = (page_id or settings.meta_page_id or "").strip()
        self.ig_user_id = (ig_user_id or settings.meta_instagram_user_id or "").strip()

        if not self.access_token:
            raise GenerationError("META_ACCESS_TOKEN no configurado para publicar en Instagram")
        if not self.page_id:
            raise GenerationError("META_PAGE_ID no configurado para publicar en Instagram")

    def _require_ig_user_id(self) -> None:
        if not self.ig_user_id:
            raise GenerationError(
                "META_INSTAGRAM_USER_ID no configurado para publicar en Instagram. "
                "Configura meta_instagram_user_id para destinos con publish_instagram=true."
            )

    def _base_url(self) -> str:
        return f"https://graph.facebook.com/{self.graph_version}"

    def _http(
        self,
        *,
        method: str,
        path: str,
        params: dict[str, Any],
        access_token: str | None = None,
    ) -> dict[str, Any]:
        token = (access_token or self.access_token).strip()
        if not token:
            raise GenerationError("Meta Graph access token vacio")

        all_params = {k: v for k, v in params.items() if v is not None}
        all_params["access_token"] = token

        url = f"{self._base_url()}{path}"
        method_up = method.upper()
        headers: dict[str, str] = {}

        if method_up == "GET":
            qs = urlencode(all_params)
            req = Request(url=f"{url}?{qs}", method="GET")
        else:
            body = urlencode(all_params).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            req = Request(url=url, data=body, method=method_up, headers=headers)

        try:
            with urlopen(req, timeout=90) as resp:
                payload = resp.read().decode("utf-8")
                data = json.loads(payload) if payload.strip() else {}
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise GenerationError(f"Meta Graph HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise GenerationError(f"Meta Graph network error: {exc}") from exc
        except Exception as exc:  # noqa: BLE001
            raise GenerationError(f"Meta Graph unexpected error: {exc}") from exc

        if isinstance(data, dict) and data.get("error"):
            err = data.get("error") or {}
            msg = str(err.get("message") or "Meta Graph error")
            code = err.get("code")
            sub = err.get("error_subcode")
            raise GenerationError(f"Meta Graph error code={code} subcode={sub}: {msg}")

        return data

    @staticmethod
    def _remote_url_reachable(url: str, *, timeout: int = 20) -> tuple[bool, str]:
        clean = (url or "").strip()
        if not clean:
            return False, "empty_url"

        try:
            head = Request(url=clean, method="HEAD")
            with urlopen(head, timeout=timeout) as resp:
                code = int(getattr(resp, "status", 200) or 200)
                if 200 <= code < 400:
                    return True, f"http_{code}"
        except Exception:
            pass

        try:
            get = Request(url=clean, method="GET")
            with urlopen(get, timeout=timeout) as resp:
                code = int(getattr(resp, "status", 200) or 200)
                if 200 <= code < 400:
                    return True, f"http_{code}"
                return False, f"http_{code}"
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)

    def remote_url_reachable(self, url: str, *, timeout: int = 20) -> tuple[bool, str]:
        return self._remote_url_reachable(url, timeout=timeout)

    @staticmethod
    def _video_status_summary(meta: dict[str, Any]) -> tuple[bool, bool, bool, str]:
        """
        Returns:
        - ready: processing finished and safe to consume source URL
        - failed: upstream status indicates terminal failure
        - known: we recognized at least one status token
        - detail: normalized joined status tokens for diagnostics
        """
        raw_status = meta.get("status")
        tokens: list[str] = []

        def _push(value: Any) -> None:
            text = str(value or "").strip()
            if not text:
                return
            norm = text.upper().replace("-", "_").replace(" ", "_")
            if norm:
                tokens.append(norm)

        if isinstance(raw_status, str):
            _push(raw_status)
        elif isinstance(raw_status, dict):
            for key in (
                "video_status",
                "processing_status",
                "publishing_phase",
                "processing_phase",
                "uploading_phase",
                "status",
                "state",
            ):
                value = raw_status.get(key)
                if isinstance(value, dict):
                    for nested in ("status", "state", "phase", "value"):
                        _push(value.get(nested))
                else:
                    _push(value)
            errors = raw_status.get("errors")
            if isinstance(errors, list) and errors:
                return False, True, True, "STATUS_ERRORS_PRESENT"

        ready = any(
            t in {"READY", "FINISHED", "COMPLETE", "COMPLETED", "PUBLISHED", "READY_FOR_PUBLISH"}
            for t in tokens
        )
        failed = any(
            t in {"ERROR", "FAILED", "FAIL", "EXPIRED", "REJECTED", "BLOCKED", "NOT_SUPPORTED"}
            for t in tokens
        )
        known = len(tokens) > 0
        detail = "|".join(tokens[:8]) if tokens else "UNKNOWN"
        return ready, failed, known, detail

    def _http_multipart(
        self,
        *,
        path: str,
        fields: dict[str, str],
        file_field: str,
        file_path: Path,
        access_token: str | None = None,
    ) -> dict[str, Any]:
        token = (access_token or self.access_token).strip()
        if not token:
            raise GenerationError("Meta Graph access token vacio")

        boundary = f"----ConectaBoundary{int(time.time() * 1000)}{os.getpid()}"
        file_bytes = file_path.read_bytes()
        filename = file_path.name
        content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"

        fields_payload = dict(fields)
        fields_payload["access_token"] = token

        body = bytearray()
        for key, value in fields_payload.items():
            body.extend(f"--{boundary}\r\n".encode("utf-8"))
            body.extend(f"Content-Disposition: form-data; name=\"{key}\"\r\n\r\n".encode("utf-8"))
            body.extend(str(value).encode("utf-8"))
            body.extend(b"\r\n")

        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(
            f"Content-Disposition: form-data; name=\"{file_field}\"; filename=\"{filename}\"\r\n".encode("utf-8")
        )
        body.extend(f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"))
        body.extend(file_bytes)
        body.extend(b"\r\n")
        body.extend(f"--{boundary}--\r\n".encode("utf-8"))

        req = Request(
            url=f"{self._base_url()}{path}",
            data=bytes(body),
            method="POST",
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )

        try:
            with urlopen(req, timeout=120) as resp:
                payload = resp.read().decode("utf-8")
                data = json.loads(payload) if payload.strip() else {}
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise GenerationError(f"Meta Graph HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise GenerationError(f"Meta Graph network error: {exc}") from exc
        except Exception as exc:  # noqa: BLE001
            raise GenerationError(f"Meta Graph unexpected error: {exc}") from exc

        if isinstance(data, dict) and data.get("error"):
            err = data.get("error") or {}
            msg = str(err.get("message") or "Meta Graph error")
            code = err.get("code")
            sub = err.get("error_subcode")
            raise GenerationError(f"Meta Graph error code={code} subcode={sub}: {msg}")

        return data

    def create_media_container(
        self,
        *,
        image_url: str,
        caption: str = "",
        media_type: str | None = None,
        is_carousel_item: bool = False,
    ) -> str:
        self._require_ig_user_id()
        params: dict[str, Any] = {"image_url": image_url}
        cap = (caption or "").strip()
        if cap:
            params["caption"] = cap
        mt = (media_type or "").strip().upper()
        if mt:
            params["media_type"] = mt
        if is_carousel_item:
            params["is_carousel_item"] = "true"

        data = self._http(
            method="POST",
            path=f"/{self.ig_user_id}/media",
            params=params,
        )
        creation_id = str(data.get("id") or "").strip()
        if not creation_id:
            raise GenerationError(f"No se obtuvo creation_id al crear media container: {data}")
        return creation_id

    def create_video_container(
        self,
        *,
        video_url: str,
        caption: str = "",
        media_type: str = "REELS",
        share_to_feed: bool = True,
    ) -> str:
        self._require_ig_user_id()
        params: dict[str, Any] = {
            "video_url": (video_url or "").strip(),
            "media_type": (media_type or "REELS").strip().upper(),
        }
        cap = (caption or "").strip()
        if cap:
            params["caption"] = cap
        if params["media_type"] == "REELS":
            params["share_to_feed"] = "true" if bool(share_to_feed) else "false"

        data = self._http(
            method="POST",
            path=f"/{self.ig_user_id}/media",
            params=params,
        )
        creation_id = str(data.get("id") or "").strip()
        if not creation_id:
            raise GenerationError(f"No se obtuvo creation_id al crear video container: {data}")
        return creation_id

    def create_carousel_container(self, *, children: list[str], caption: str) -> str:
        self._require_ig_user_id()
        child_ids = [str(x or "").strip() for x in children if str(x or "").strip()]
        if len(child_ids) < 2:
            raise GenerationError("Un carrusel IG requiere al menos 2 elementos")
        if len(child_ids) > 10:
            raise GenerationError("Un carrusel IG no puede superar 10 elementos")

        data = self._http(
            method="POST",
            path=f"/{self.ig_user_id}/media",
            params={
                "media_type": "CAROUSEL",
                "children": ",".join(child_ids),
                "caption": (caption or "").strip(),
            },
        )
        creation_id = str(data.get("id") or "").strip()
        if not creation_id:
            raise GenerationError(f"No se obtuvo creation_id al crear carousel container: {data}")
        return creation_id

    def publish_media_container(self, *, creation_id: str) -> str:
        self._require_ig_user_id()
        data = self._http(
            method="POST",
            path=f"/{self.ig_user_id}/media_publish",
            params={"creation_id": creation_id},
        )
        media_id = str(data.get("id") or "").strip()
        if not media_id:
            raise GenerationError(f"No se obtuvo media_id al publicar container: {data}")
        return media_id

    def fetch_media(self, *, media_id: str) -> dict[str, Any]:
        self._require_ig_user_id()
        return self._http(
            method="GET",
            path=f"/{media_id}",
            params={"fields": "id,permalink,media_type,timestamp"},
        )

    def fetch_container_status(self, *, creation_id: str) -> dict[str, Any]:
        self._require_ig_user_id()
        return self._http(
            method="GET",
            path=f"/{creation_id}",
            params={"fields": "id,status_code,status"},
        )

    def resolve_page_access_token(self) -> str:
        data = self._http(
            method="GET",
            path=f"/{self.page_id}",
            params={"fields": "id,name,access_token"},
        )
        page_token = str(data.get("access_token") or "").strip()
        if not page_token:
            raise GenerationError(
                "No se obtuvo page access token para publicar como pagina. "
                "Revisa permisos del system user y acceso al activo pagina."
            )
        return page_token

    def inspect_page_identity(self) -> dict[str, Any]:
        data = self._http(
            method="GET",
            path=f"/{self.page_id}",
            params={"fields": "id,name,is_owned,instagram_business_account{id,username}"},
        )
        ig = data.get("instagram_business_account") if isinstance(data.get("instagram_business_account"), dict) else {}
        return {
            "page_id": str(data.get("id") or "").strip(),
            "page_name": str(data.get("name") or "").strip(),
            "is_owned": bool(data.get("is_owned", False)),
            "linked_instagram_user_id": str(ig.get("id") or "").strip(),
            "linked_instagram_username": str(ig.get("username") or "").strip(),
        }

    def wait_until_container_ready(
        self,
        *,
        creation_id: str,
        max_wait_seconds: int = 120,
        poll_seconds: float = 3.0,
    ) -> dict[str, Any]:
        max_wait = max(10, int(max_wait_seconds))
        poll = max(1.0, float(poll_seconds))
        deadline = time.monotonic() + max_wait
        last_payload: dict[str, Any] = {}

        while time.monotonic() < deadline:
            payload = self.fetch_container_status(creation_id=creation_id)
            last_payload = payload
            status_code = str(payload.get("status_code") or payload.get("status") or "").strip().upper()

            if status_code in {"FINISHED", "PUBLISHED"}:
                return payload
            if status_code in {"ERROR", "EXPIRED", "FAILED"}:
                raise GenerationError(
                    f"Media container no disponible para publicar (status={status_code}): {payload}"
                )
            time.sleep(poll)

        raise GenerationError(
            f"Timeout esperando media container listo para publicar (creation_id={creation_id}): {last_payload}"
        )

    def stage_local_image_for_public_url(self, *, image_path: Path, caption: str = "") -> str:
        if not image_path.exists():
            raise GenerationError(f"Imagen local no encontrada para staging Meta: {image_path}")

        page_token = self.resolve_page_access_token()

        try:
            data = self._http_multipart(
                path=f"/{self.page_id}/photos",
                fields={
                    "published": "false",
                    "caption": (caption or "").strip()[:2200],
                },
                file_field="source",
                file_path=image_path,
                access_token=page_token,
            )
        except GenerationError as exc:
            msg = str(exc)
            if "pages_manage_posts" in msg:
                raise GenerationError(
                    "Meta requiere permiso pages_manage_posts para staging automatico de imagen local. "
                    "Agrega ese scope al token y vuelve a intentar."
                ) from exc
            raise

        photo_id = str(data.get("id") or "").strip()
        if not photo_id:
            raise GenerationError(f"No se obtuvo photo_id en staging Meta: {data}")

        meta = self._http(
            method="GET",
            path=f"/{photo_id}",
            params={"fields": "id,images,source,link"},
            access_token=page_token,
        )
        src = str(meta.get("source") or "").strip()
        if src:
            return src

        images = meta.get("images") or []
        if isinstance(images, list) and images:
            first = images[0] if isinstance(images[0], dict) else {}
            src = str(first.get("source") or "").strip()
            if src:
                return src

        link = str(meta.get("link") or "").strip()
        if link:
            return link

        raise GenerationError(f"No se obtuvo URL publica desde staging Meta para photo_id={photo_id}")

    def stage_local_video_for_public_url(self, *, video_path: Path, description: str = "") -> str:
        if not video_path.exists():
            raise GenerationError(f"Video local no encontrado para staging Meta: {video_path}")

        page_token = self.resolve_page_access_token()
        data = self._http_multipart(
            path=f"/{self.page_id}/videos",
            fields={
                "published": "false",
                "description": (description or "").strip()[:2200],
            },
            file_field="source",
            file_path=video_path,
            access_token=page_token,
        )
        video_id = str(data.get("id") or data.get("video_id") or "").strip()
        if not video_id:
            raise GenerationError(f"No se obtuvo video_id en staging Meta: {data}")

        deadline = time.monotonic() + 240.0
        last_meta: dict[str, Any] = {}
        last_src = ""
        src_seen_count = 0
        while time.monotonic() < deadline:
            meta = self._http(
                method="GET",
                path=f"/{video_id}",
                params={"fields": "id,source,permalink_url,status"},
                access_token=page_token,
            )
            last_meta = meta
            src = str(meta.get("source") or "").strip()
            ready, failed, status_known, status_detail = self._video_status_summary(meta)
            if src:
                if src == last_src:
                    src_seen_count += 1
                else:
                    last_src = src
                    src_seen_count = 1

                url_ok, _url_reason = self._remote_url_reachable(src, timeout=20)
                if ready and url_ok:
                    return src
                if (not status_known) and url_ok and src_seen_count >= 2:
                    # Some pages return source before exposing a stable status object.
                    # Require consistency across polls to reduce early/ephemeral URLs.
                    return src

            status = str(meta.get("status") or "").strip().upper()
            if status in {"ERROR", "FAILED", "EXPIRED"}:
                raise GenerationError(f"Staging video fallo (video_id={video_id}, status={status}): {meta}")
            if failed:
                raise GenerationError(
                    f"Staging video fallo por estado interno (video_id={video_id}, status={status_detail}): {meta}"
                )
            time.sleep(3.0)

        raise GenerationError(
            f"No se obtuvo URL publica de video lista para IG desde staging Meta (video_id={video_id}, last={last_meta})"
        )

    def publish_image_post(self, *, image_url: str, caption: str) -> dict[str, Any]:
        creation_id = self.create_media_container(image_url=image_url, caption=caption)
        self.wait_until_container_ready(creation_id=creation_id)

        media_id = ""
        last_error: Exception | None = None
        for attempt in range(1, 6):
            try:
                media_id = self.publish_media_container(creation_id=creation_id)
                break
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                msg = str(exc).lower()
                retryable = (
                    ("media id is not available" in msg)
                    or ('"code":9007' in msg)
                    or ('"error_subcode":2207027' in msg)
                )
                if (not retryable) or attempt >= 5:
                    raise
                time.sleep(2.5 * attempt)

        if not media_id:
            raise GenerationError(f"No se pudo publicar media container: {last_error}")

        media = self.fetch_media(media_id=media_id)
        return {
            "channel": "instagram_graph",
            "status": "published",
            "creation_id": creation_id,
            "post_id": media_id,
            "url": str(media.get("permalink") or ""),
            "media_type": str(media.get("media_type") or ""),
            "published_at": _now_iso(),
            "raw_media": media,
        }

    def publish_story_image(self, *, image_url: str) -> dict[str, Any]:
        creation_id = self.create_media_container(image_url=image_url, media_type="STORIES")
        self.wait_until_container_ready(creation_id=creation_id)
        media_id = self.publish_media_container(creation_id=creation_id)
        media = self.fetch_media(media_id=media_id)
        return {
            "channel": "instagram_graph_story",
            "status": "published",
            "creation_id": creation_id,
            "post_id": media_id,
            "url": str(media.get("permalink") or ""),
            "media_type": str(media.get("media_type") or ""),
            "published_at": _now_iso(),
            "raw_media": media,
        }

    def publish_reel_video(self, *, video_url: str, caption: str) -> dict[str, Any]:
        creation_id = self.create_video_container(video_url=video_url, caption=caption, media_type="REELS", share_to_feed=True)
        self.wait_until_container_ready(creation_id=creation_id, max_wait_seconds=360, poll_seconds=4.0)

        media_id = ""
        last_error: Exception | None = None
        for attempt in range(1, 7):
            try:
                media_id = self.publish_media_container(creation_id=creation_id)
                break
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt >= 6:
                    raise
                time.sleep(2.5 * attempt)

        if not media_id:
            raise GenerationError(f"No se pudo publicar Reel: {last_error}")

        media = self.fetch_media(media_id=media_id)
        return {
            "channel": "instagram_graph_reel",
            "status": "published",
            "creation_id": creation_id,
            "post_id": media_id,
            "url": str(media.get("permalink") or ""),
            "media_type": str(media.get("media_type") or ""),
            "published_at": _now_iso(),
            "raw_media": media,
        }

    def publish_story_video(self, *, video_url: str) -> dict[str, Any]:
        creation_id = self.create_video_container(video_url=video_url, caption="", media_type="STORIES", share_to_feed=False)
        self.wait_until_container_ready(creation_id=creation_id, max_wait_seconds=360, poll_seconds=4.0)
        media_id = self.publish_media_container(creation_id=creation_id)
        media = self.fetch_media(media_id=media_id)
        return {
            "channel": "instagram_graph_story_video",
            "status": "published",
            "creation_id": creation_id,
            "post_id": media_id,
            "url": str(media.get("permalink") or ""),
            "media_type": str(media.get("media_type") or ""),
            "published_at": _now_iso(),
            "raw_media": media,
        }

    def publish_carousel_post(self, *, image_urls: list[str], caption: str) -> dict[str, Any]:
        urls = [str(x or "").strip() for x in image_urls if str(x or "").strip()]
        if len(urls) < 2:
            raise GenerationError("Un carrusel IG requiere al menos 2 imagenes publicas")
        if len(urls) > 10:
            raise GenerationError("Un carrusel IG no puede superar 10 imagenes")

        child_creation_ids: list[str] = []
        for url in urls:
            child_id = self.create_media_container(image_url=url, is_carousel_item=True)
            self.wait_until_container_ready(creation_id=child_id)
            child_creation_ids.append(child_id)

        creation_id = self.create_carousel_container(children=child_creation_ids, caption=caption)
        self.wait_until_container_ready(creation_id=creation_id)

        media_id = self.publish_media_container(creation_id=creation_id)
        media = self.fetch_media(media_id=media_id)
        return {
            "channel": "instagram_graph_carousel",
            "status": "published",
            "creation_id": creation_id,
            "child_creation_ids": child_creation_ids,
            "post_id": media_id,
            "url": str(media.get("permalink") or ""),
            "media_type": str(media.get("media_type") or ""),
            "published_at": _now_iso(),
            "raw_media": media,
        }

    def publish_facebook_photo(self, *, image_url: str, caption: str) -> dict[str, Any]:
        page_token = self.resolve_page_access_token()
        data = self._http(
            method="POST",
            path=f"/{self.page_id}/photos",
            params={
                "url": image_url,
                "caption": caption,
                "published": "true",
            },
            access_token=page_token,
        )
        post_id = str(data.get("post_id") or data.get("id") or "").strip()
        return {
            "channel": "facebook_graph",
            "status": "published",
            "post_id": post_id or None,
            "raw": data,
        }

    def publish_facebook_multi_photo(self, *, image_urls: list[str], caption: str) -> dict[str, Any]:
        urls = [str(x or "").strip() for x in image_urls if str(x or "").strip()]
        if len(urls) < 2:
            raise GenerationError("Una publicacion multi-foto FB requiere al menos 2 imagenes")

        page_token = self.resolve_page_access_token()
        attached: list[dict[str, str]] = []
        staged: list[dict[str, Any]] = []
        for url in urls:
            data = self._http(
                method="POST",
                path=f"/{self.page_id}/photos",
                params={
                    "url": url,
                    "published": "false",
                },
                access_token=page_token,
            )
            photo_id = str(data.get("id") or data.get("post_id") or "").strip()
            if not photo_id:
                raise GenerationError(f"No se obtuvo photo_id para multi-foto FB: {data}")
            attached.append({"media_fbid": photo_id})
            staged.append(data)

        data = self._http(
            method="POST",
            path=f"/{self.page_id}/feed",
            params={
                "message": (caption or "").strip(),
                "attached_media": json.dumps(attached, ensure_ascii=False),
            },
            access_token=page_token,
        )
        post_id = str(data.get("id") or data.get("post_id") or "").strip()
        return {
            "channel": "facebook_graph_multi_photo",
            "status": "published",
            "post_id": post_id or None,
            "photo_ids": [x["media_fbid"] for x in attached],
            "raw": data,
            "staged": staged,
        }

    def publish_facebook_video(self, *, video_url: str, description: str) -> dict[str, Any]:
        page_token = self.resolve_page_access_token()
        data = self._http(
            method="POST",
            path=f"/{self.page_id}/videos",
            params={
                "file_url": video_url,
                "description": (description or "").strip(),
                "published": "true",
            },
            access_token=page_token,
        )
        post_id = str(data.get("post_id") or data.get("id") or "").strip()
        return {
            "channel": "facebook_graph_video",
            "status": "published",
            "post_id": post_id or None,
            "raw": data,
        }

    def publish_facebook_story_photo(self, *, image_url: str) -> dict[str, Any]:
        page_token = self.resolve_page_access_token()
        staged = self._http(
            method="POST",
            path=f"/{self.page_id}/photos",
            params={
                "url": image_url,
                "published": "false",
            },
            access_token=page_token,
        )
        photo_id = str(staged.get("id") or staged.get("post_id") or "").strip()
        if not photo_id:
            raise GenerationError(f"No se obtuvo photo_id para Facebook Story: {staged}")

        data = self._http(
            method="POST",
            path=f"/{self.page_id}/photo_stories",
            params={"photo_id": photo_id},
            access_token=page_token,
        )
        story_id = str(data.get("id") or data.get("post_id") or "").strip()
        return {
            "channel": "facebook_graph_story",
            "status": "published",
            "story_id": story_id or None,
            "photo_id": photo_id,
            "raw": data,
        }

    def _upload_story_video(self, *, upload_url: str, video_id: str, video_url: str, page_token: str) -> dict:
        parsed = urlparse(upload_url)
        if (parsed.scheme != "https" or parsed.hostname != "rupload.facebook.com" or parsed.port is not None
                or parsed.username or parsed.password or not parsed.path.startswith("/video-upload/")
                or parsed.path.rstrip("/").split("/")[-1] != video_id):
            raise GenerationError("Invalid Facebook upload destination")
        request = Request(upload_url, data=b"", method="POST",
                          headers={"Authorization": "OAuth " + page_token, "file_url": video_url})
        try:
            with urlopen(request, timeout=120) as response:
                result = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise GenerationError(f"Facebook Story transfer HTTP {exc.code}: {detail}") from None
        except (URLError, ValueError, OSError):
            raise GenerationError("Facebook Story transfer failed; publication was not requested") from None
        if result.get("success") is not True:
            raise GenerationError("Facebook Story transfer was not acknowledged")
        return result

    def _wait_story_phase(self, *, video_id: str, page_token: str, published: bool,
                         max_wait_seconds: int = 240) -> dict:
        deadline = time.monotonic() + max_wait_seconds
        while True:
            data = self._http(method="GET", path=f"/{video_id}", params={"fields": "status"},
                              access_token=page_token)
            status = data.get("status") or {}
            if not isinstance(status, dict):
                raise GenerationError("Facebook Story status was not structured")
            failed = str(status.get("video_status", "")).lower() in {"error", "failed"}
            for phase in ["uploading_phase", "processing_phase", "publishing_phase"]:
                detail = status.get(phase) or {}
                failed = failed or bool(detail.get("errors")) or str(detail.get("status", "")).lower() in {"error", "failed"}
            if failed or status.get("errors"):
                raise GenerationError("Facebook Story processing failed: " + json.dumps(status))
            if published:
                complete = str((status.get("publishing_phase") or {}).get("status", "")).lower() == "complete"
                if complete:
                    return data
            elif str((status.get("uploading_phase") or {}).get("status", "")).lower() == "complete":
                return data
            if time.monotonic() >= deadline:
                raise GenerationError("Facebook Story status timed out; inspect recorded video_id before retrying")
            time.sleep(3)

    def publish_facebook_story_video(self, *, video_url: str,
                                     progress: Callable[[dict], None] | None = None) -> dict[str, Any]:
        """Start, transfer, finish once, then confirm processing. Never blindly retry finish."""
        if urlparse(video_url).scheme != "https":
            raise GenerationError("Facebook Story source must use HTTPS")
        def checkpoint(phase, **values):
            if progress:
                progress({"phase": phase, **values})
        page_token = self.resolve_page_access_token()
        checkpoint("starting")
        started = self._http(method="POST", path=f"/{self.page_id}/video_stories",
                             params={"upload_phase": "start"}, access_token=page_token)
        video_id = str(started.get("video_id") or "").strip()
        upload_url = str(started.get("upload_url") or "").strip()
        if not video_id or not upload_url:
            raise GenerationError("Facebook Story start did not return video_id and upload_url")
        checkpoint("session_created", video_id=video_id)
        self._upload_story_video(upload_url=upload_url, video_id=video_id,
                                 video_url=video_url, page_token=page_token)
        checkpoint("transferred", video_id=video_id)
        self._wait_story_phase(video_id=video_id, page_token=page_token, published=False)
        # Persist the video id before the only call that can create the public Story.
        checkpoint("finishing", video_id=video_id, publication_may_have_occurred=True)
        data = self._http(method="POST", path=f"/{self.page_id}/video_stories",
                          params={"upload_phase": "finish", "video_id": video_id, "video_state": "PUBLISHED"},
                          access_token=page_token)
        story_id = str(data.get("post_id") or data.get("id") or "").strip()
        if data.get("success") is False or (data.get("success") is not True and not story_id):
            raise GenerationError("Facebook Story finish was not acknowledged; reconcile recorded video_id")
        checkpoint("finish_acknowledged", video_id=video_id, story_id=story_id or None,
                   publication_may_have_occurred=True)
        status = self._wait_story_phase(video_id=video_id, page_token=page_token, published=True)
        if not story_id:
            stories = self._http(method="GET", path=f"/{self.page_id}/stories",
                                 params={"limit": 50}, access_token=page_token)
            matching = [row for row in stories.get("data", [])
                        if str(row.get("media_id")) == video_id and row.get("status") == "published"]
            if len(matching) != 1 or not matching[0].get("post_id"):
                raise GenerationError("Published Facebook video has no unambiguous Story receipt; reconcile video_id")
            story_id = str(matching[0]["post_id"])
        checkpoint("confirmed", video_id=video_id, story_id=story_id)
        return {"channel": "facebook_graph_story_video", "status": "published",
                "story_id": story_id, "post_id": story_id, "video_id": video_id,
                "published_at": _now_iso(), "raw": data, "processing_status": status}


def resolve_public_image_url(*, settings: AppSettings, image_path: Path, explicit_public_url: str | None = None) -> str:
    explicit = (explicit_public_url or "").strip()
    if explicit:
        return explicit

    base = (settings.instagram_public_base_url or "").strip().rstrip("/")
    if base:
        try:
            rel = image_path.resolve().relative_to(settings.output_root.resolve())
        except Exception as exc:
            raise GenerationError(
                "No se pudo mapear imagen local a URL publica. Verifica output root y ruta del draft."
            ) from exc
        return f"{base}/generated/{rel.as_posix()}"

    raise GenerationError(
        "No existe URL publica para la imagen del draft. Configura INSTAGRAM_PUBLIC_BASE_URL o envia public_image_url al publicar."
    )


def resolve_public_video_url(*, settings: AppSettings, video_path: Path, explicit_public_url: str | None = None) -> str:
    explicit = (explicit_public_url or "").strip()
    if explicit:
        return explicit

    base = (settings.instagram_public_base_url or "").strip().rstrip("/")
    if base:
        try:
            rel = video_path.resolve().relative_to(settings.output_root.resolve())
        except Exception as exc:
            raise GenerationError(
                "No se pudo mapear video local a URL publica. Verifica output root y ruta del draft."
            ) from exc
        return f"{base}/generated/{rel.as_posix()}"

    raise GenerationError(
        "No existe URL publica para el video del draft. Configura INSTAGRAM_PUBLIC_BASE_URL o envia public_video_url al publicar."
    )
