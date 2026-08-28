from __future__ import annotations

import json
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

from .exceptions import PreflightError
from .settings import AppSettings


def _check_command(cmd: list[str], friendly_name: str) -> None:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except FileNotFoundError as exc:
        raise PreflightError(f"{friendly_name} no esta instalado o no esta en PATH") from exc

    if proc.returncode != 0:
        msg = proc.stderr.strip() or proc.stdout.strip() or "unknown error"
        raise PreflightError(f"{friendly_name} check failed: {msg}")


def _check_ollama_model(executable: str, model: str) -> None:
    try:
        proc = subprocess.run([executable, "list"], capture_output=True, text=True, check=False)
    except FileNotFoundError as exc:
        raise PreflightError(f"Ollama no encontrado en: {executable}") from exc

    if proc.returncode != 0:
        msg = proc.stderr.strip() or proc.stdout.strip() or "unknown error"
        raise PreflightError(f"Cannot list Ollama models: {msg}")

    if model not in proc.stdout:
        raise PreflightError(
            f"Ollama model '{model}' not found. Run: \"{executable}\" pull {model}"
        )


def _check_openai_tts(settings: AppSettings) -> None:
    if not settings.openai_api_key:
        raise PreflightError(
            "OPENAI_API_KEY no configurada. Define la variable para usar TTS OpenAI premium."
        )

    _check_command(["python", "-c", "import openai"], "openai dependency")


def _check_openai_scene_images(settings: AppSettings) -> None:
    if not settings.openai_api_key:
        raise PreflightError(
            "OPENAI_API_KEY no configurada. Define la variable en .env para usar imagenes OpenAI por escena."
        )

    _check_command(["python", "-c", "import openai"], "openai dependency")


def _check_comfyui(settings: AppSettings) -> None:
    if not settings.comfyui_workflow_template.exists():
        raise PreflightError(
            "No se encontro plantilla workflow para ComfyUI: "
            f"{settings.comfyui_workflow_template}"
        )

    req = urllib.request.Request(settings.comfyui_base_url.rstrip("/") + "/system_stats", method="GET")
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as exc:
        raise PreflightError(
            f"ComfyUI no responde en {settings.comfyui_base_url}. "
            "Inicia ComfyUI antes de generar videos con engine='comfyui'."
        ) from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PreflightError("ComfyUI respondio un formato invalido en /system_stats") from exc

    if not isinstance(data, dict):
        raise PreflightError("ComfyUI /system_stats no devolvio un objeto JSON valido")


def run_preflight(
    settings: AppSettings,
    require_tts: bool,
    video_engine: str = "studio",
    require_openai_scene_images: bool = False,
    require_openai_tts: bool = False,
) -> None:
    if not settings.context_path.exists():
        raise PreflightError(f"Context file missing: {settings.context_path}")

    if not settings.assets_root.exists():
        raise PreflightError(f"Assets folder missing: {settings.assets_root}")

    _check_command([settings.ollama_executable, "--version"], "Ollama")
    _check_ollama_model(settings.ollama_executable, settings.ollama_model)

    _check_command(["python", "-c", "import moviepy, PIL, yaml, pydantic, flask"], "Python dependencies")

    if require_tts:
        provider = (settings.tts_provider or "edge").strip().lower()
        if provider == "openai":
            _check_openai_tts(settings)
        elif provider == "edge":
            _check_command(["python", "-c", "import edge_tts"], "edge-tts dependency")
        else:
            raise PreflightError(f"TTS provider no soportado: {settings.tts_provider}")

    if video_engine == "comfyui":
        _check_comfyui(settings)

    if require_openai_scene_images:
        _check_openai_scene_images(settings)

    if require_openai_tts:
        _check_openai_tts(settings)


def ensure_output_root(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
