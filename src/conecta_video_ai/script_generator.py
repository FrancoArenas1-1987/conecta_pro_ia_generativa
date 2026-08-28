from __future__ import annotations

import re

from pydantic import ValidationError

from .exceptions import GenerationError
from .models import BrandContext, DialogueTurn, ImageCreative, ScriptSection, VideoScript
from .prompts import PromptBuilder
from .providers import OllamaProvider
from .whatsapp_links import normalize_whatsapp_click_url


SPEAKER_PREFIX_RE = re.compile(
    r"^\s*(?:persona\s*\d+|usuario|cliente|asesor(?:\s+conectaproia)?|conectaproia|anfitrion|narrador)\s*:\s*",
    flags=re.IGNORECASE,
)
STAGE_RE = re.compile(r"\((.*?)\)|\[(.*?)\]")


MOJIBAKE_REPLACEMENTS = {
    "Â¡": "¡",
    "Â¿": "¿",
    "Ã¡": "á",
    "Ã©": "é",
    "Ã­": "í",
    "Ã³": "ó",
    "Ãº": "ú",
    "Ã±": "ñ",
    "Ã": "Á",
    "Ã‰": "É",
    "Ã": "Í",
    "Ã“": "Ó",
    "Ãš": "Ú",
    "Ã‘": "Ñ",
    "Ą": "¡",
}


def _fix_mojibake(value: str) -> str:
    if not value:
        return value

    out = value
    for bad, good in MOJIBAKE_REPLACEMENTS.items():
        out = out.replace(bad, good)

    if any(m in out for m in ("Ã", "Â", "â", "�")):
        try:
            fixed = out.encode("latin-1", errors="ignore").decode("utf-8", errors="ignore")
            if fixed.strip():
                out = fixed
        except Exception:
            pass

    for bad, good in MOJIBAKE_REPLACEMENTS.items():
        out = out.replace(bad, good)

    return out


def _normalize_text(value: str) -> str:
    cleaned = _fix_mojibake(str(value or ""))
    cleaned = re.sub(r"[^0-9A-Za-zÁÉÍÓÚáéíóúÑñÜü¿?¡!.,:;()'\"%+\-/ ]+", "", cleaned)
    return " ".join(cleaned.split()).strip()


def _strip_speaker_and_stage(value: str) -> str:
    text = _normalize_text(value)
    text = STAGE_RE.sub("", text)
    while SPEAKER_PREFIX_RE.match(text):
        text = SPEAKER_PREFIX_RE.sub("", text, count=1)

    bad_prefixes = ["escena", "acto", "narracion", "narrador", "tono", "acotacion"]
    low = text.lower()
    for bp in bad_prefixes:
        if low.startswith(bp + ":"):
            text = text.split(":", 1)[1].strip() if ":" in text else text
            break

    return " ".join(text.split()).strip()


def _normalize_dialogue_line(value: str) -> str:
    line = _strip_speaker_and_stage(value)
    if not line:
        return line

    if len(line.split()) < 4:
        line = f"{line}. Escríbeme por WhatsApp."

    if line and line[-1] not in ".!?":
        line += "."
    return line


def _clip_words(text: str, max_words: int) -> str:
    words = [w for w in _normalize_text(text).split() if w]
    if not words:
        return ""
    out = " ".join(words[:max_words]).strip()
    if out and out[-1] not in ".!?":
        out += "."
    return out


def _normalize_speaker(value: str) -> str:
    s = _normalize_text(value).lower()
    if not s:
        return "Persona"
    if any(k in s for k in ["asesor", "conectapro", "experto", "persona 2"]):
        return "Asesor"
    if any(k in s for k in ["cliente", "usuario", "persona 1"]):
        return "Cliente"
    return "Cliente"


def _normalize_dialogue_turns(turns: list[DialogueTurn], cta: str, max_turns: int = 6) -> list[DialogueTurn]:
    normalized: list[DialogueTurn] = []
    for turn in turns:
        speaker = _normalize_speaker(turn.speaker)
        line = _normalize_dialogue_line(turn.line)
        if speaker and line:
            normalized.append(DialogueTurn(speaker=speaker, line=_clip_words(line, max_words=10)))

    if len(normalized) > max_turns:
        normalized = normalized[: max_turns - 1] + [normalized[-1]]

    if len(normalized) < 4:
        return normalized

    normalized = [
        DialogueTurn(speaker=("Cliente" if i % 2 == 0 else "Asesor"), line=t.line)
        for i, t in enumerate(normalized)
    ]

    close = _normalize_text(cta)
    if close and close.lower() not in normalized[-1].line.lower():
        normalized[-1] = DialogueTurn(
            speaker="Asesor",
            line=_clip_words(close, max_words=9),
        )

    return normalized


def _extract_seed_turns_from_inline(seed: str) -> list[DialogueTurn]:
    text = _normalize_text(seed)
    if not text:
        return []

    marker = re.compile(r"(persona\s*\d+|usuario|cliente|asesor(?:\s+conectaproia)?|conectaproia)\s*:", re.IGNORECASE)
    matches = list(marker.finditer(text))
    if not matches:
        return []

    turns: list[DialogueTurn] = []
    for i, m in enumerate(matches):
        speaker_raw = m.group(1)
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        line_raw = text[start:end].strip(" /|;,.\n\t")
        line = _normalize_dialogue_line(line_raw)
        if line:
            turns.append(DialogueTurn(speaker=_normalize_speaker(speaker_raw), line=line))
    return turns


def _parse_seed_dialogue(dialogue_seed: str) -> list[DialogueTurn]:
    seed = dialogue_seed or ""
    if not seed.strip():
        return []

    turns = _extract_seed_turns_from_inline(seed)
    if turns:
        return turns

    raw_lines = [ln.strip() for ln in seed.replace("\r", "\n").splitlines() if ln.strip()]
    if len(raw_lines) == 1 and "/" in raw_lines[0]:
        raw_lines = [p.strip() for p in raw_lines[0].split("/") if p.strip()]

    parsed: list[DialogueTurn] = []
    for line in raw_lines:
        match = re.match(r"^\s*([A-Za-z0-9ÁÉÍÓÚáéíóúÑñ ._-]{2,40})\s*:\s*(.+)$", line)
        if not match:
            continue
        speaker = _normalize_speaker(match.group(1))
        sentence = _normalize_dialogue_line(match.group(2))
        if sentence:
            parsed.append(DialogueTurn(speaker=speaker, line=sentence))
    return parsed


def _to_dialogue(raw_dialogue: list[dict]) -> list[DialogueTurn]:
    turns: list[DialogueTurn] = []
    for item in raw_dialogue:
        speaker = _normalize_speaker(item.get("speaker", ""))
        line = _normalize_dialogue_line(item.get("line", item.get("text", "")))
        if line:
            turns.append(DialogueTurn(speaker=speaker, line=line))
    return turns


def _build_dialogue_fallback(topic: str, cta: str) -> list[DialogueTurn]:
    t = _normalize_text(topic) or "un problema urgente"
    return [
        DialogueTurn(speaker="Cliente", line=f"Se me complicó {t} y necesito ayuda hoy."),
        DialogueTurn(speaker="Asesor", line="Usa ConectaProIA: responde por WhatsApp en minutos."),
        DialogueTurn(speaker="Cliente", line="Quiero alguien confiable y disponible en mi comuna."),
        DialogueTurn(speaker="Asesor", line="Te mostramos perfiles verificados y opciones claras."),
        DialogueTurn(speaker="Cliente", line="Buenísimo, lo pruebo ahora mismo."),
        DialogueTurn(speaker="Asesor", line=_normalize_text(cta) or "Hablar por WhatsApp ahora."),
    ]


def generate_conversion_reel_script(context: BrandContext, topic: str) -> tuple[VideoScript, dict]:
    whatsapp = normalize_whatsapp_click_url(context.whatsapp_url)
    website = context.website_url or "https://conectaproia.cl"

    sections = [
        ScriptSection(
            index=1,
            title="Gancho",
            narration="¿Te ha fallado un maestro?",
            onscreen_text="¿Te ha fallado un maestro?",
        ),
        ScriptSection(
            index=2,
            title="Dolor",
            narration="No responde. No llega. Te deja esperando.",
            onscreen_text="No responde. No llega. Te deja esperando.",
        ),
        ScriptSection(
            index=3,
            title="Frustracion",
            narration="Pierdes tiempo y el problema sigue igual.",
            onscreen_text="Tu problema sigue igual.",
        ),
        ScriptSection(
            index=4,
            title="Solucion",
            narration="ConectaProIA te conecta por WhatsApp con profesionales verificados en minutos.",
            onscreen_text="ConectaProIA por WhatsApp",
        ),
        ScriptSection(
            index=5,
            title="Resultado",
            narration="Llega el profesional, resuelve y recuperas tu tranquilidad.",
            onscreen_text="Problema resuelto, cliente feliz",
        ),
        ScriptSection(
            index=6,
            title="CTA",
            narration=f"Escríbenos ahora. Contactar es gratis. {whatsapp}. {website}.",
            onscreen_text=f"Escríbenos ahora - 100% gratis\n{whatsapp}\n{website}",
        ),
    ]

    script = VideoScript(
        topic=_normalize_text(topic) or "Reel de conversion ConectaProIA",
        style="conversion",
        hook="¿Te ha fallado un maestro?",
        sections=sections,
        dialogue=[],
        cta="Escríbenos ahora - 100% gratis | Hablar por WhatsApp ahora",
    )
    payload = script.model_dump(mode="json")
    return script, payload


def _to_video_script(
    payload: dict,
    topic: str,
    fallback_cta: str,
    fallback_style: str,
) -> VideoScript:
    try:
        raw_sections = payload.get("sections", [])
        section_models = [
            ScriptSection(
                index=i,
                title=_normalize_text(item.get("title", f"Seccion {i}")),
                narration=_normalize_text(item.get("narration", "")),
                onscreen_text=_normalize_text(item.get("onscreen_text", "")),
            )
            for i, item in enumerate(raw_sections, start=1)
        ]

        style_value = fallback_style
        dialogue = _to_dialogue(payload.get("dialogue", []))

        if style_value == "dialogo":
            if len(dialogue) < 4:
                dialogue = _build_dialogue_fallback(topic, fallback_cta)
            dialogue = _normalize_dialogue_turns(dialogue, cta=fallback_cta)

        return VideoScript(
            topic=_normalize_text(topic),
            style=style_value,
            hook=_normalize_text(payload.get("hook", topic)),
            sections=section_models,
            dialogue=dialogue,
            cta=_normalize_text(fallback_cta),
        )
    except ValidationError as exc:
        raise GenerationError(f"Invalid video script schema: {exc}") from exc


def generate_fast_video_script(
    *,
    context: BrandContext,
    topic: str,
    style: str,
    dialogue_seed: str | None = None,
    duration_seconds: int | None = None,
) -> tuple[VideoScript, dict]:
    normalized_topic = _normalize_text(topic) or "ConectaProIA"

    if style == "conversion":
        return generate_conversion_reel_script(context, normalized_topic)

    if style == "dialogo":
        default_dialogue = _build_dialogue_fallback(normalized_topic, context.call_to_action)
        seeded = _parse_seed_dialogue(dialogue_seed or "")
        dialogue = seeded if len(seeded) >= 4 else default_dialogue
        dialogue = _normalize_dialogue_turns(dialogue, cta=context.call_to_action)

        sections = [
            ScriptSection(index=1, title="Problema real", narration="Una persona necesita resolver un problema hoy y no tiene un dato confiable.", onscreen_text="Necesito ayuda urgente"),
            ScriptSection(index=2, title="Solucion clara", narration="ConectaProIA conecta por WhatsApp con profesionales verificados y disponibles.", onscreen_text="Conexion por WhatsApp"),
            ScriptSection(index=3, title="Cierre", narration="Flujo simple, rapido y con accion inmediata.", onscreen_text="Contacta ahora"),
        ]

        script = VideoScript(
            topic=normalized_topic,
            style="dialogo",
            hook="Reel dinamico: problema real y solucion inmediata",
            sections=sections,
            dialogue=dialogue,
            cta=context.call_to_action,
        )
        payload = script.model_dump(mode="json")
        return script, payload

    sections = [
        ScriptSection(index=1, title="Problema", narration=f"Cuando aparece {normalized_topic}, perder tiempo buscando datos genera estres.", onscreen_text="Problema urgente"),
        ScriptSection(index=2, title="Solucion", narration="ConectaProIA te conecta por WhatsApp con profesionales verificados en minutos.", onscreen_text="Solucion por WhatsApp"),
        ScriptSection(index=3, title="Beneficio", narration="Resuelves rapido, comparas opciones y avanzas con confianza.", onscreen_text="Rapido y confiable"),
    ]

    script = VideoScript(
        topic=normalized_topic,
        style="promo",
        hook="Soluciona hoy con profesionales confiables",
        sections=sections,
        dialogue=[],
        cta=context.call_to_action,
    )
    payload = script.model_dump(mode="json")
    return script, payload


def generate_video_script(
    provider: OllamaProvider,
    context: BrandContext,
    topic: str,
    duration_seconds: int | None,
    sections: int,
    style: str,
    dialogue_seed: str | None = None,
) -> tuple[VideoScript, dict]:
    if style == "conversion":
        return generate_conversion_reel_script(context, topic)

    prompt = PromptBuilder.video_script_prompt(
        context=context,
        topic=topic,
        duration_seconds=duration_seconds,
        sections=sections,
        style=style,
        dialogue_seed=dialogue_seed,
    )
    payload = provider.generate_json(prompt)
    return _to_video_script(payload, topic=topic, fallback_cta=context.call_to_action, fallback_style=style), payload


def revise_video_script(
    provider: OllamaProvider,
    topic: str,
    duration_seconds: int | None,
    fallback_cta: str,
    previous_payload: dict,
    issues: list[str],
    style: str,
) -> tuple[VideoScript, dict]:
    if style == "conversion":
        # Conversion template is deterministic and should not be revised by LLM.
        raise GenerationError("Conversion reel script should be generated from deterministic template")

    prompt = PromptBuilder.revise_video_script_prompt(previous_payload=previous_payload, issues=issues, style=style)
    payload = provider.generate_json(prompt)
    return _to_video_script(payload, topic=topic, fallback_cta=fallback_cta, fallback_style=style), payload


def _to_image_creative(payload: dict) -> ImageCreative:
    try:
        normalized = {
            "headline": _normalize_text(payload.get("headline", "")),
            "subheadline": _normalize_text(payload.get("subheadline", "")),
            "call_to_action": _normalize_text(payload.get("call_to_action", "")),
            "service_focus": _normalize_text(payload.get("service_focus", "")),
        }
        return ImageCreative.model_validate(normalized)
    except ValidationError as exc:
        raise GenerationError(f"Invalid image creative schema: {exc}") from exc


def generate_image_creative(
    provider: OllamaProvider,
    context: BrandContext,
    brief: str,
    service: str,
) -> tuple[ImageCreative, dict]:
    prompt = PromptBuilder.image_copy_prompt(context=context, brief=brief, service=service)
    payload = provider.generate_json(prompt)
    return _to_image_creative(payload), payload


def revise_image_creative(
    provider: OllamaProvider,
    previous_payload: dict,
    issues: list[str],
) -> tuple[ImageCreative, dict]:
    prompt = PromptBuilder.revise_image_copy_prompt(previous_payload=previous_payload, issues=issues)
    payload = provider.generate_json(prompt)
    return _to_image_creative(payload), payload

