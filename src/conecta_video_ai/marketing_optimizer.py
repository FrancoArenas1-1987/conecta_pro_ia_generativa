from __future__ import annotations

from dataclasses import dataclass

from .marketing_validator import MarketingReport, evaluate_marketing
from .models import DialogueTurn, ScriptSection, StoryboardScene, VideoScript


@dataclass
class OptimizationResult:
    script: VideoScript
    storyboard: list[StoryboardScene]
    changed: list[str]
    estimated_score: int
    iterations: int


def _improve_hook(script: VideoScript) -> tuple[VideoScript, bool]:
    hook = script.hook.strip()
    if "?" in hook and len(hook.split()) >= 6:
        return script, False

    improved = "¿Te ha pasado que necesitas ayuda urgente y nadie responde?"
    return script.model_copy(update={"hook": improved}), True


def _reinforce_cta(script: VideoScript) -> tuple[VideoScript, bool]:
    cta = script.cta.lower()
    if "whatsapp" in cta and "ahora" in cta and "gratis" in cta:
        return script, False

    improved = "Escríbenos ahora por WhatsApp. Contactar es 100% gratis"
    return script.model_copy(update={"cta": improved}), True


def _simplify_sections(script: VideoScript) -> tuple[VideoScript, bool]:
    changed = False
    new_sections = []
    for sec in script.sections:
        words = sec.narration.split()
        if len(words) > 18:
            narration = " ".join(words[:18]).strip()
            if narration and narration[-1] not in ".!?":
                narration += "."
            changed = True
        else:
            narration = sec.narration

        new_sections.append(
            sec.model_copy(
                update={
                    "narration": narration,
                    "onscreen_text": sec.onscreen_text if len(sec.onscreen_text.split()) <= 12 else " ".join(sec.onscreen_text.split()[:12]),
                }
            )
        )

    return script.model_copy(update={"sections": new_sections}), changed


def _enforce_structure(script: VideoScript) -> tuple[VideoScript, bool]:
    sections = list(script.sections)
    if len(sections) < 3:
        return script, False

    changed = False
    titles = [s.title.lower() for s in sections]
    if not any("proble" in t or "dolor" in t for t in titles):
        sections[0] = sections[0].model_copy(update={"title": "Problema", "narration": "Tienes una urgencia y no encuentras un profesional confiable a tiempo."})
        changed = True
    if not any("solu" in t for t in titles):
        mid = min(len(sections) - 1, max(1, len(sections) // 2))
        sections[mid] = sections[mid].model_copy(update={"title": "Solucion", "narration": "ConectaPro IA te conecta por WhatsApp con profesionales disponibles en minutos."})
        changed = True
    if not any("cta" in t or "accion" in t or "paso" in t for t in titles):
        sections[-1] = sections[-1].model_copy(update={"title": "Accion", "narration": "Escríbenos por WhatsApp ahora y encuentra ayuda real."})
        changed = True

    return script.model_copy(update={"sections": sections}), changed


def _sanitize_dialogue(script: VideoScript) -> tuple[VideoScript, bool]:
    if script.style != "dialogo" or not script.dialogue:
        return script, False

    changed = False
    fixed: list[DialogueTurn] = []
    for i, turn in enumerate(script.dialogue):
        line = turn.line
        for bad in ["Persona 1:", "Persona 2:", "Escena", "Cliente:", "Asesor:"]:
            if bad.lower() in line.lower():
                line = line.replace(bad, "").strip()
                changed = True

        speaker = "Cliente" if i % 2 == 0 else "Asesor"
        if turn.speaker != speaker:
            changed = True
        fixed.append(turn.model_copy(update={"speaker": speaker, "line": line}))

    return script.model_copy(update={"dialogue": fixed}), changed


def _quick_rebuild_storyboard(script: VideoScript, storyboard: list[StoryboardScene]) -> list[StoryboardScene]:
    if not storyboard:
        return storyboard

    # Keep visual allocation, refresh text continuity from script order.
    section_texts = [script.hook] + [s.narration for s in script.sections] + [script.cta]
    updated: list[StoryboardScene] = []
    for i, scene in enumerate(storyboard):
        text = section_texts[min(i, len(section_texts) - 1)] if section_texts else scene.body
        updated.append(
            scene.model_copy(
                update={
                    "headline": scene.headline if scene.headline else ("Escena" if i else "Hook"),
                    "body": text,
                }
            )
        )
    return updated


def optimize_marketing(
    *,
    script: VideoScript,
    storyboard: list[StoryboardScene],
    report: MarketingReport,
    objective: str,
    max_iterations: int = 3,
) -> OptimizationResult:
    current_script = script
    current_storyboard = list(storyboard)
    changes: list[str] = []
    best_score = report.score

    for iteration in range(1, max_iterations + 1):
        modified = False

        if report.breakdown.get("hook", 100) < 85:
            current_script, ch = _improve_hook(current_script)
            modified = modified or ch
            if ch:
                changes.append("hook_mejorado")

        if report.breakdown.get("cta", 100) < 85:
            current_script, ch = _reinforce_cta(current_script)
            modified = modified or ch
            if ch:
                changes.append("cta_reforzado")

        if report.breakdown.get("clarity", 100) < 85:
            current_script, ch = _simplify_sections(current_script)
            modified = modified or ch
            if ch:
                changes.append("lenguaje_simplificado")

        if report.breakdown.get("structure", 100) < 85:
            current_script, ch = _enforce_structure(current_script)
            modified = modified or ch
            if ch:
                changes.append("estructura_reordenada")

        current_script, ch = _sanitize_dialogue(current_script)
        modified = modified or ch
        if ch:
            changes.append("dialogo_sanitizado")

        if not modified:
            break

        current_storyboard = _quick_rebuild_storyboard(current_script, current_storyboard)
        new_report = evaluate_marketing(script=current_script, scenes=current_storyboard, objective=objective)
        if new_report.score <= best_score:
            # No gain: stop to avoid loops.
            break

        best_score = new_report.score
        report = new_report

    return OptimizationResult(
        script=current_script,
        storyboard=current_storyboard,
        changed=changes,
        estimated_score=best_score,
        iterations=max_iterations,
    )
