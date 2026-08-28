from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from ..exceptions import GenerationError


class ComfyUIProvider:
    def __init__(
        self,
        base_url: str,
        workflow_template_path: Path,
        poll_seconds: float = 2.0,
        timeout_seconds: int = 1200,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.workflow_template_path = workflow_template_path
        self.poll_seconds = max(0.5, float(poll_seconds))
        self.timeout_seconds = max(30, int(timeout_seconds))

    def _url(self, path: str) -> str:
        if not path.startswith("/"):
            path = "/" + path
        return f"{self.base_url}{path}"

    def _request_json(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        data: bytes | None = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

        req = urllib.request.Request(self._url(path), data=data, method=method.upper(), headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
        except urllib.error.URLError as exc:
            raise GenerationError(f"No se pudo conectar a ComfyUI en {self.base_url}: {exc}") from exc

        try:
            return json.loads(raw) if raw else {}
        except json.JSONDecodeError as exc:
            raise GenerationError(f"Respuesta JSON invalida desde ComfyUI: {raw[:200]}") from exc

    def healthcheck(self) -> None:
        self._request_json("GET", "/system_stats")

    def _load_workflow_template(self) -> dict[str, Any]:
        if not self.workflow_template_path.exists():
            raise GenerationError(
                f"Plantilla ComfyUI no encontrada: {self.workflow_template_path}. "
                "Debes exportar un workflow JSON desde ComfyUI."
            )

        try:
            content = self.workflow_template_path.read_text(encoding="utf-8")
            data = json.loads(content)
        except Exception as exc:  # noqa: BLE001
            raise GenerationError(f"No se pudo leer workflow ComfyUI: {exc}") from exc

        if not isinstance(data, dict):
            raise GenerationError("Workflow ComfyUI invalido: se esperaba un objeto JSON")

        return data

    def _replace_tokens(self, node: Any, mapping: dict[str, str]) -> Any:
        if isinstance(node, str):
            result = node
            for k, v in mapping.items():
                result = result.replace(k, v)
            return result
        if isinstance(node, list):
            return [self._replace_tokens(item, mapping) for item in node]
        if isinstance(node, dict):
            return {key: self._replace_tokens(value, mapping) for key, value in node.items()}
        return node

    def _submit_prompt(self, workflow: dict[str, Any]) -> str:
        payload = {
            "prompt": workflow,
            "client_id": str(uuid.uuid4()),
        }
        data = self._request_json("POST", "/prompt", payload)
        prompt_id = str(data.get("prompt_id", "")).strip()
        if not prompt_id:
            node_errors = data.get("node_errors")
            raise GenerationError(f"ComfyUI rechazo el workflow: {node_errors or data}")
        return prompt_id

    def _wait_for_completion(self, prompt_id: str) -> dict[str, Any]:
        deadline = time.time() + self.timeout_seconds
        last_status = ""

        while time.time() < deadline:
            history = self._request_json("GET", f"/history/{urllib.parse.quote(prompt_id)}")
            entry = history.get(prompt_id)
            if isinstance(entry, dict) and entry.get("outputs"):
                return entry

            queue = self._request_json("GET", "/queue")
            running = queue.get("queue_running", [])
            pending = queue.get("queue_pending", [])
            running_ids = {str(item[1]) for item in running if isinstance(item, list) and len(item) > 1}
            pending_ids = {str(item[1]) for item in pending if isinstance(item, list) and len(item) > 1}

            if prompt_id in running_ids:
                status = "running"
            elif prompt_id in pending_ids:
                status = "pending"
            else:
                status = "unknown"

            if status != last_status:
                last_status = status

            time.sleep(self.poll_seconds)

        raise GenerationError(f"Timeout esperando resultado de ComfyUI ({self.timeout_seconds}s)")

    @staticmethod
    def _extract_media_output(history_entry: dict[str, Any]) -> dict[str, str]:
        outputs = history_entry.get("outputs")
        if not isinstance(outputs, dict):
            raise GenerationError("ComfyUI no devolvio outputs validos")

        for node_out in outputs.values():
            if not isinstance(node_out, dict):
                continue
            for key in ("videos", "gifs", "images"):
                files = node_out.get(key)
                if isinstance(files, list) and files:
                    item = files[0]
                    if isinstance(item, dict) and item.get("filename"):
                        return {
                            "filename": str(item.get("filename")),
                            "subfolder": str(item.get("subfolder", "")),
                            "type": str(item.get("type", "output")),
                        }

        raise GenerationError("No se encontro archivo de salida en history de ComfyUI")

    def _download_output(self, media: dict[str, str], output_path: Path) -> None:
        params = {
            "filename": media["filename"],
            "subfolder": media.get("subfolder", ""),
            "type": media.get("type", "output"),
        }
        query = urllib.parse.urlencode(params)
        url = self._url(f"/view?{query}")

        req = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = resp.read()
        except urllib.error.URLError as exc:
            raise GenerationError(f"No se pudo descargar archivo generado desde ComfyUI: {exc}") from exc

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(data)

        if not output_path.exists() or output_path.stat().st_size == 0:
            raise GenerationError("Archivo descargado de ComfyUI esta vacio")

    def generate_video(
        self,
        *,
        prompt_text: str,
        negative_prompt: str,
        duration_seconds: int,
        width: int,
        height: int,
        fps: int,
        output_path: Path,
        seed: int,
    ) -> Path:
        workflow = self._load_workflow_template()

        num_frames = max(16, int(duration_seconds * max(1, fps)))
        mapping = {
            "{{PROMPT}}": prompt_text,
            "{{NEGATIVE_PROMPT}}": negative_prompt,
            "{{WIDTH}}": str(width),
            "{{HEIGHT}}": str(height),
            "{{FPS}}": str(max(1, fps)),
            "{{DURATION_SECONDS}}": str(max(1, duration_seconds)),
            "{{NUM_FRAMES}}": str(num_frames),
            "{{SEED}}": str(int(seed)),
        }
        rendered_workflow = self._replace_tokens(workflow, mapping)

        prompt_id = self._submit_prompt(rendered_workflow)
        history_entry = self._wait_for_completion(prompt_id)
        media = self._extract_media_output(history_entry)
        self._download_output(media, output_path)
        return output_path
