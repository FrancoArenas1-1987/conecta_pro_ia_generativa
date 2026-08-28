from __future__ import annotations

import asyncio
import re
import tempfile
from pathlib import Path

import edge_tts

from .exceptions import RenderError


VOICE_BY_SPEAKER = {
    "usuario": "es-CL-LorenzoNeural",
    "cliente": "es-CL-LorenzoNeural",
    "persona 1": "es-CL-LorenzoNeural",
    "asesor": "es-CL-CatalinaNeural",
    "conectaproia": "es-CL-CatalinaNeural",
    "asesor conectaproia": "es-CL-CatalinaNeural",
    "persona 2": "es-CL-CatalinaNeural",
}

SPANISH_FALLBACKS = [
    "es-CL-CatalinaNeural",
    "es-CL-LorenzoNeural",
    "es-MX-DaliaNeural",
    "es-ES-ElviraNeural",
]

MOJIBAKE_MAP = {
    "?": "",
    "??": "?",
    "??": "?",
    "??": "?",
    "??": "?",
    "??": "?",
    "??": "?",
    "??": "?",
    "??": "?",
    "??": "?",
    "??": "?",
    "??": "?",
    "??": "?",
    "??": "?",
    "??": "?",
}

LABEL_RE = re.compile(
    r"(?:^|\s|[\/|])(?:persona\s*\d+|usuario|cliente|asesor(?:\s+conectaproia)?|conectaproia|narrador|escena\s*\d+)(?:\s*\([^)]*\))?\s*:\s*",
    flags=re.IGNORECASE,
)
PREFIX_RE = re.compile(
    r"^\s*(?:persona\s*\d+|usuario|cliente|asesor(?:\s+conectaproia)?|conectaproia|narrador|escena\s*\d+)(?:\s*\([^)]*\))?\s*:\s*",
    flags=re.IGNORECASE,
)


def _sanitize_for_voice(text: str) -> str:
    out = " ".join((text or "").split())
    if not out:
        return out

    for bad, good in MOJIBAKE_MAP.items():
        out = out.replace(bad, good)

    out = LABEL_RE.sub(" ", out)
    while PREFIX_RE.match(out):
        out = PREFIX_RE.sub("", out, count=1)

    out = re.sub(r"\((.*?)\)|\[(.*?)\]", "", out)
    out = re.sub(r"^\s*escena\s*\d+\s*[-?:]\s*", "", out, flags=re.IGNORECASE)
    out = re.sub(r"^\s*[-*?]+\s*", "", out)
    out = re.sub(r"\s+", " ", out).strip()

    replacements = {
        r"\bsolucion\b": "soluci?n",
        r"\brapido\b": "r?pido",
        r"\brapida\b": "r?pida",
        r"\bconexion\b": "conexi?n",
        r"\bcomun\b": "com?n",
        r"\btecnicos\b": "t?cnicos",
        r"\btecnico\b": "t?cnico",
        r"\basi\b": "as?",
        r"\bmas\b": "m?s",
        r"\bfacil\b": "f?cil",
        r"\bautomatico\b": "autom?tico",
        r"\bwhatsapp\b": "WhatsApp",
    }
    for pattern, repl in replacements.items():
        out = re.sub(pattern, repl, out, flags=re.IGNORECASE)

    if out and out[-1] not in ".!?":
        out += "."
    return out


async def _synthesize_edge_async(text: str, out_media: Path, voice: str) -> None:
    communicator = edge_tts.Communicate(text=text, voice=voice, rate="-2%", volume="+0%")
    await communicator.save(str(out_media))


def _pick_edge_voice(speaker: str | None) -> str:
    if speaker:
        key = " ".join(speaker.lower().split())
        for label, voice in VOICE_BY_SPEAKER.items():
            if label in key:
                return voice
    return SPANISH_FALLBACKS[0]


def _pick_openai_voice(speaker: str | None, primary: str, secondary: str) -> str:
    if speaker:
        low = speaker.lower()
        if any(marker in low for marker in ["persona 2", "asesor", "conecta"]):
            return secondary or primary
    return primary


def _synthesize_openai(
    text: str,
    out_media: Path,
    *,
    api_key: str,
    model: str,
    voice: str,
    speed: float,
) -> None:
    try:
        from openai import OpenAI
    except Exception as exc:  # noqa: BLE001
        raise RenderError("OpenAI package missing for TTS provider") from exc

    client = OpenAI(api_key=api_key)
    try:
        response = client.audio.speech.create(
            model=model,
            voice=voice,
            input=text,
            response_format="mp3",
            speed=speed,
        )
        response.stream_to_file(str(out_media))
    except Exception as exc:  # noqa: BLE001
        raise RenderError(f"OpenAI TTS synthesis failed: {exc}") from exc


def synthesize_voice(
    text: str,
    out_media: Path,
    speaker: str | None = None,
    *,
    provider: str = "edge",
    strict: bool = True,
    openai_api_key: str | None = None,
    openai_model: str = "gpt-4o-mini-tts",
    openai_voice_primary: str = "alloy",
    openai_voice_secondary: str = "sage",
    openai_speed: float = 1.0,
) -> Path:
    out_media.parent.mkdir(parents=True, exist_ok=True)

    clean_text = _sanitize_for_voice(text)
    if len(clean_text) < 3:
        raise RenderError("TTS text is too short")

    provider_norm = (provider or "edge").strip().lower()

    if provider_norm == "openai":
        if not openai_api_key:
            raise RenderError("OPENAI_API_KEY is required for OpenAI TTS")

        voice = _pick_openai_voice(speaker, openai_voice_primary, openai_voice_secondary)
        try:
            _synthesize_openai(
                clean_text,
                out_media,
                api_key=openai_api_key,
                model=openai_model,
                voice=voice,
                speed=openai_speed,
            )
        except Exception:
            if strict:
                raise
            # Fallback to edge only if strict mode disabled.
            provider_norm = "edge"

    if provider_norm == "edge":
        base_voice = _pick_edge_voice(speaker)
        last_error: Exception | None = None
        for candidate in [base_voice] + [v for v in SPANISH_FALLBACKS if v != base_voice]:
            try:
                asyncio.run(_synthesize_edge_async(clean_text, out_media, candidate))
                last_error = None
                break
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                continue

        if last_error is not None:
            raise RenderError(f"Edge TTS synthesis failed: {last_error}")

    if provider_norm not in {"openai", "edge"}:
        raise RenderError(f"Unsupported TTS provider: {provider}")

    if not out_media.exists() or out_media.stat().st_size == 0:
        raise RenderError("TTS output file is missing or empty")

    return out_media


def synthesize_dialogue(
    turns: list[tuple[str, str]],
    out_media: Path,
    *,
    provider: str = "edge",
    strict: bool = True,
    openai_api_key: str | None = None,
    openai_model: str = "gpt-4o-mini-tts",
    openai_voice_primary: str = "alloy",
    openai_voice_secondary: str = "sage",
    openai_speed: float = 1.0,
) -> Path:
    if not turns:
        raise RenderError("Dialogue TTS requires at least one turn")

    out_media.parent.mkdir(parents=True, exist_ok=True)

    from moviepy.editor import AudioClip, AudioFileClip, concatenate_audioclips

    with tempfile.TemporaryDirectory(prefix="conecta_tts_") as temp_dir:
        clips: list[object] = []
        try:
            for idx, (speaker, line) in enumerate(turns, start=1):
                line_text = _sanitize_for_voice(line)
                if not line_text:
                    continue

                segment_path = Path(temp_dir) / f"line_{idx:02d}.mp3"
                synthesize_voice(
                    line_text,
                    segment_path,
                    speaker=speaker,
                    provider=provider,
                    strict=strict,
                    openai_api_key=openai_api_key,
                    openai_model=openai_model,
                    openai_voice_primary=openai_voice_primary,
                    openai_voice_secondary=openai_voice_secondary,
                    openai_speed=openai_speed,
                )
                clip = AudioFileClip(str(segment_path))
                clips.append(clip)

                if idx < len(turns):
                    pause = AudioClip(lambda t: 0.0, duration=0.16, fps=44100)
                    clips.append(pause)

            if not clips:
                raise RenderError("Dialogue TTS produced no audio clips")

            final_audio = concatenate_audioclips(clips)
            final_audio.write_audiofile(str(out_media), fps=44100, nbytes=2, verbose=False, logger=None)
            final_audio.close()
        finally:
            for clip in clips:
                close_fn = getattr(clip, "close", None)
                if callable(close_fn):
                    try:
                        close_fn()
                    except Exception:
                        pass

    if not out_media.exists() or out_media.stat().st_size == 0:
        raise RenderError("Dialogue TTS output file is missing or empty")

    return out_media
