from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from .models import BrandContext, ImageCreative, StoryboardScene, VideoScript


@dataclass
class QualityReport:
    passed: bool
    score: int
    issues: list[str]


def _contains_forbidden(text: str, forbidden_terms: list[str]) -> list[str]:
    low = text.lower()
    hits = []
    for term in forbidden_terms:
        t = term.strip().lower()
        if t and t in low:
            hits.append(term)
    return hits


def evaluate_video_script(script: VideoScript, context: BrandContext) -> QualityReport:
    issues: list[str] = []
    score = 100

    section_text = [f"{s.title} {s.narration} {s.onscreen_text}" for s in script.sections]
    dialogue_text = [f"{d.speaker}: {d.line}" for d in script.dialogue]
    full_text = " ".join([script.hook, script.cta] + section_text + dialogue_text)
    normalized = re.sub(r"\s+", " ", full_text).strip()

    if len(script.sections) < 3:
        score -= 20
        issues.append("Debe tener al menos 3 secciones para sostener narrativa")

    if script.style != "conversion" and len(script.hook.split()) < 5:
        score -= 10
        issues.append("Hook demasiado corto")

    if "whatsapp" not in normalized.lower():
        score -= 12
        issues.append("El guion debe mencionar WhatsApp")

    if context.call_to_action.lower() not in script.cta.lower():
        score -= 8
        issues.append("CTA no alineado al contexto oficial")

    for i, section in enumerate(script.sections, start=1):
        wc = len(section.narration.split())
        if script.style not in {"dialogo", "conversion"}:
            if wc < 6:
                score -= 4
                issues.append(f"Seccion {i}: narracion demasiado corta")
            if wc > 55:
                score -= 4
                issues.append(f"Seccion {i}: narracion demasiado extensa")
        else:
            if wc < 3:
                score -= 2
                issues.append(f"Seccion {i}: narracion insuficiente para soporte visual")

    if script.style == "dialogo":
        if len(script.dialogue) < 4:
            score -= 14
            issues.append("Modo dialogo requiere al menos 4 turnos")

        speakers = [d.speaker.strip().lower() for d in script.dialogue if d.speaker.strip()]
        unique_speakers = set(speakers)
        if len(unique_speakers) < 2:
            score -= 15
            issues.append("Dialogo requiere al menos 2 speakers")

        for i, turn in enumerate(script.dialogue, start=1):
            words = len(turn.line.split())
            if words < 4:
                score -= 3
                issues.append(f"Turno {i}: linea demasiado corta")
            if words > 30:
                score -= 3
                issues.append(f"Turno {i}: linea demasiado larga")

            low_line = turn.line.lower()
            if any(tok in low_line for tok in ["persona 1:", "persona 2:", "cliente:", "asesor:", "escena "]):
                score -= 4
                issues.append(f"Turno {i}: linea contiene etiquetas o acotaciones no narrables")

    forbidden_list = context.voice.avoid + ["garantizado", "100%", "sin riesgo"]
    if script.style == "conversion" and "100% gratis" in normalized.lower():
        forbidden_list = [x for x in forbidden_list if str(x).strip().lower() != "100%"]

    forbidden_hits = _contains_forbidden(normalized, forbidden_list)
    if forbidden_hits:
        score -= min(20, 5 * len(forbidden_hits))
        issues.append(f"Terminos no permitidos: {', '.join(sorted(set(forbidden_hits)))}")

    if "{{" in normalized or "}}" in normalized:
        score -= 15
        issues.append("Marcadores sin reemplazar detectados")

    score = max(0, score)
    return QualityReport(passed=score >= 85, score=score, issues=issues)


def evaluate_storyboard(scenes: list[StoryboardScene], target_seconds: float | None) -> QualityReport:
    issues: list[str] = []
    score = 100

    if not scenes:
        return QualityReport(False, 0, ["Storyboard vacio"])

    total = sum(scene.duration_seconds for scene in scenes)
    if target_seconds:
        tolerance = target_seconds * 0.25
        if abs(total - target_seconds) > tolerance:
            score -= 20
            issues.append(f"Duracion total fuera de tolerancia ({round(total,2)}s)")

    short_mode = bool(target_seconds and target_seconds <= 12)
    for scene in scenes:
        min_scene = (0.9 if short_mode else 1.0) if scene.visual_style == "dialogo" else (1.0 if scene.visual_style == "conversion" else (1.2 if short_mode else 1.4))
        if scene.duration_seconds < min_scene:
            score -= 4
            issues.append(f"Escena {scene.index}: duracion muy corta")
        if scene.duration_seconds > 16:
            score -= 4
            issues.append(f"Escena {scene.index}: duracion muy larga")
        if len(scene.headline.strip()) < 3:
            score -= 5
            issues.append(f"Escena {scene.index}: headline debil")
        if len(scene.body.strip()) < 4:
            score -= 5
            issues.append(f"Escena {scene.index}: cuerpo insuficiente")

    score = max(0, score)
    return QualityReport(passed=score >= 85, score=score, issues=issues)


def evaluate_image_creative(creative: ImageCreative, context: BrandContext) -> QualityReport:
    issues: list[str] = []
    score = 100

    if len(creative.headline.split()) > 8:
        score -= 12
        issues.append("Headline demasiado largo")
    if len(creative.subheadline.split()) > 14:
        score -= 12
        issues.append("Subheadline demasiado largo")
    if len(creative.call_to_action.split()) > 5:
        score -= 10
        issues.append("CTA demasiado largo")
    if context.call_to_action.lower().split()[0] not in creative.call_to_action.lower():
        score -= 6
        issues.append("CTA poco alineado con la marca")

    forbidden_hits = _contains_forbidden(
        f"{creative.headline} {creative.subheadline} {creative.call_to_action}",
        context.voice.avoid + ["garantizado", "100%", "gratis para siempre"],
    )
    if forbidden_hits:
        score -= 15
        issues.append("Texto contiene terminos no permitidos")

    score = max(0, score)
    return QualityReport(passed=score >= 85, score=score, issues=issues)


def evaluate_image_file(path: Path, expected_w: int, expected_h: int) -> QualityReport:
    issues: list[str] = []
    score = 100

    if not path.exists() or path.stat().st_size == 0:
        return QualityReport(False, 0, ["Imagen no generada o vacia"])

    with Image.open(path) as img:
        w, h = img.size

    if w != expected_w or h != expected_h:
        score -= 20
        issues.append(f"Resolucion distinta a la solicitada: {w}x{h}")

    return QualityReport(passed=score >= 85, score=score, issues=issues)
