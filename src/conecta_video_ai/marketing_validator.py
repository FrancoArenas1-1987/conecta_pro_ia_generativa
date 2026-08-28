from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .models import StoryboardScene, VideoScript


Objective = Literal["captar_clientes", "captar_proveedores", "branding"]


@dataclass
class MarketingReport:
    passed: bool
    score: int
    breakdown: dict
    issues: list[str]
    recommendations: list[str]


def _score_hook(script: VideoScript) -> tuple[int, list[str]]:
    issues: list[str] = []
    score = 100
    hook = (script.hook or "").strip().lower()

    if len(hook.split()) < 5:
        score -= 30
        issues.append("Hook demasiado corto")

    emotional_words = ["problema", "urgente", "falla", "esperando", "rapido", "hoy", "ahora"]
    if not any(w in hook for w in emotional_words):
        score -= 25
        issues.append("Hook sin tension emocional clara")

    if "?" not in hook and "!" not in hook:
        score -= 15
        issues.append("Hook poco disruptivo")

    return max(0, score), issues


def _score_clarity(script: VideoScript) -> tuple[int, list[str]]:
    issues: list[str] = []
    score = 100

    lines = [script.hook] + [s.narration for s in script.sections] + [script.cta]
    avg_words = sum(len((x or "").split()) for x in lines) / max(1, len(lines))
    if avg_words > 16:
        score -= 25
        issues.append("Lenguaje denso: frases largas")

    full = " ".join(lines).lower()
    if "whatsapp" not in full:
        score -= 35
        issues.append("No explica canal de accion (WhatsApp)")

    if len(script.sections) < 3:
        score -= 30
        issues.append("Estructura insuficiente para comprender en segundos")

    return max(0, score), issues


def _score_cta(script: VideoScript) -> tuple[int, list[str]]:
    issues: list[str] = []
    score = 100
    cta = (script.cta or "").lower()

    if not any(k in cta for k in ["whatsapp", "escribe", "hablar", "contacta", "ahora"]):
        score -= 60
        issues.append("CTA debil o sin accion inmediata")

    if len(cta.split()) < 4:
        score -= 20
        issues.append("CTA demasiado corto")

    if "gratis" not in cta:
        score -= 15
        issues.append("CTA sin incentivo de conversion")

    return max(0, score), issues


def _score_structure(script: VideoScript) -> tuple[int, list[str]]:
    issues: list[str] = []
    score = 100
    full = " ".join([s.title + " " + s.narration for s in script.sections]).lower()

    problem_ok = any(k in full for k in ["problema", "falla", "urgente", "espera", "dolor"]) or "fallado" in (script.hook or "").lower()
    solution_ok = any(k in full for k in ["solucion", "conecta", "whatsapp", "verificado"])
    action_ok = any(k in (script.cta or "").lower() for k in ["ahora", "escribe", "contacta", "whatsapp"])

    if not problem_ok:
        score -= 35
        issues.append("Falta bloque de problema")
    if not solution_ok:
        score -= 35
        issues.append("Falta bloque de solucion")
    if not action_ok:
        score -= 30
        issues.append("Falta bloque de accion")

    return max(0, score), issues


def _score_fast_comprehension(script: VideoScript, scenes: list[StoryboardScene]) -> tuple[int, list[str]]:
    issues: list[str] = []
    score = 100
    total_seconds = sum(max(0.0, s.duration_seconds) for s in scenes)

    if total_seconds > 40:
        score -= 20
        issues.append("Video largo para consumo rapido")

    first_3s = 0.0
    msg_tokens = []
    for s in scenes:
        if first_3s >= 3.0:
            break
        first_3s += max(0.0, s.duration_seconds)
        msg_tokens.append(f"{s.headline} {s.body}".lower())

    early_text = " ".join(msg_tokens)
    if not any(k in early_text for k in ["problema", "falla", "urgente", "maestro", "whatsapp"]):
        score -= 35
        issues.append("Primeros segundos no comunican rapido")

    return max(0, score), issues


def _score_objective_alignment(script: VideoScript, objective: Objective) -> tuple[int, list[str]]:
    issues: list[str] = []
    score = 100
    full = " ".join([script.hook] + [s.narration for s in script.sections] + [script.cta]).lower()

    objective_terms = {
        "captar_clientes": ["necesitas", "problema", "resuelve", "whatsapp", "gratis"],
        "captar_proveedores": ["profesional", "trabajo", "clientes", "registro", "oportunidades"],
        "branding": ["conectapro", "confianza", "marca", "profesionales"],
    }
    hits = sum(1 for t in objective_terms[objective] if t in full)
    if hits <= 1:
        score -= 45
        issues.append("Baja alineacion con objetivo de campana")
    elif hits == 2:
        score -= 20
        issues.append("Alineacion parcial con objetivo")

    return max(0, score), issues


def evaluate_marketing(
    *,
    script: VideoScript,
    scenes: list[StoryboardScene],
    objective: Objective,
) -> MarketingReport:
    weighted: dict[str, tuple[int, int]] = {}
    issues: list[str] = []

    hook_score, hook_issues = _score_hook(script)
    weighted["hook"] = (hook_score, 22)
    issues.extend(hook_issues)

    clarity_score, clarity_issues = _score_clarity(script)
    weighted["clarity"] = (clarity_score, 18)
    issues.extend(clarity_issues)

    cta_score, cta_issues = _score_cta(script)
    weighted["cta"] = (cta_score, 20)
    issues.extend(cta_issues)

    structure_score, structure_issues = _score_structure(script)
    weighted["structure"] = (structure_score, 17)
    issues.extend(structure_issues)

    rapid_score, rapid_issues = _score_fast_comprehension(script, scenes)
    weighted["fast_comprehension"] = (rapid_score, 13)
    issues.extend(rapid_issues)

    objective_score, objective_issues = _score_objective_alignment(script, objective)
    weighted["objective_alignment"] = (objective_score, 10)
    issues.extend(objective_issues)

    total = 0.0
    for value, weight in weighted.values():
        total += value * (weight / 100.0)

    score = max(0, min(100, int(round(total))))
    recs = []
    if hook_score < 80:
        recs.append("Reescribir hook con tension y urgencia en menos de 12 palabras")
    if cta_score < 85:
        recs.append("Reforzar CTA con accion directa + WhatsApp + incentivo")
    if structure_score < 85:
        recs.append("Forzar narrativa problema -> solucion -> accion")
    if objective_score < 85:
        recs.append(f"Ajustar copy para objetivo {objective}")

    return MarketingReport(
        passed=score >= 88 and not issues,
        score=score,
        breakdown={k: v[0] for k, v in weighted.items()},
        issues=issues,
        recommendations=recs,
    )
