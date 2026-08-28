from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from typing import Callable

from .marketing_validator import MarketingReport, evaluate_marketing
from .models import StoryboardScene, VideoScript


@dataclass
class Variant:
    variant_id: str
    hook_template: str
    narrative_template: str
    cta_template: str
    script: VideoScript


@dataclass
class VariantSelection:
    selected: Variant
    report: MarketingReport
    ranking: list[dict]


HOOK_LIBRARY = {
    "captar_clientes": [
        "¿Te ha fallado un maestro justo cuando más lo necesitas?",
        "Tu urgencia no puede esperar. ¿Quién te responde hoy?",
        "Cuando nadie llega, tu problema sigue creciendo.",
    ],
    "captar_proveedores": [
        "¿Eres profesional y te faltan clientes serios?",
        "Tu oficio merece más oportunidades reales.",
        "Deja de depender del boca a boca: activa tu flujo de clientes.",
    ],
    "branding": [
        "Conecta Pro IA: confianza real cuando necesitas ayuda.",
        "La forma más simple de conectar con profesionales.",
        "Resuelve más rápido con una experiencia moderna y humana.",
    ],
}

NARRATIVE_LIBRARY = {
    "directa": ["Problema", "Solucion", "Resultado", "Accion"],
    "emocional": ["Dolor", "Frustracion", "Alivio", "Accion"],
}

CTA_LIBRARY = {
    "captar_clientes": [
        "Escríbenos ahora por WhatsApp. Contactar es 100% gratis",
        "Conecta YA por WhatsApp y encuentra ayuda en minutos",
    ],
    "captar_proveedores": [
        "Regístrate hoy y recibe nuevos clientes por WhatsApp",
        "Únete ahora y activa oportunidades reales en tu comuna",
    ],
    "branding": [
        "Conoce Conecta Pro IA y comienza por WhatsApp ahora",
        "Habla con nosotros por WhatsApp y descubre cómo funciona",
    ],
}


def _apply_narrative_template(script: VideoScript, narrative_template: str) -> VideoScript:
    if len(script.sections) < 2:
        return script

    titles = NARRATIVE_LIBRARY[narrative_template]
    new_sections = []
    for i, section in enumerate(script.sections):
        new_title = titles[min(i, len(titles) - 1)]
        new_sections.append(section.model_copy(update={"title": new_title}))

    return script.model_copy(update={"sections": new_sections})


def generate_variants(
    *,
    base_script: VideoScript,
    objective: str,
    max_variants: int = 12,
) -> list[Variant]:
    hooks = HOOK_LIBRARY.get(objective, HOOK_LIBRARY["branding"])[:3]
    narratives = list(NARRATIVE_LIBRARY.keys())[:2]
    ctas = CTA_LIBRARY.get(objective, CTA_LIBRARY["branding"])[:2]

    variants: list[Variant] = []
    idx = 1
    for hook, narrative, cta in product(hooks, narratives, ctas):
        if len(variants) >= max_variants:
            break

        script = base_script.model_copy(update={"hook": hook, "cta": cta})
        script = _apply_narrative_template(script, narrative)

        variants.append(
            Variant(
                variant_id=f"v{idx:02d}_{narrative}",
                hook_template=hook,
                narrative_template=narrative,
                cta_template=cta,
                script=script,
            )
        )
        idx += 1

    return variants


def select_best_variant(
    *,
    variants: list[Variant],
    objective: str,
    storyboard_factory: Callable[[VideoScript], list[StoryboardScene]],
) -> VariantSelection:
    best_variant = variants[0]
    best_report = MarketingReport(passed=False, score=0, breakdown={}, issues=[], recommendations=[])
    ranking: list[dict] = []

    for variant in variants:
        scenes = storyboard_factory(variant.script)
        report = evaluate_marketing(script=variant.script, scenes=scenes, objective=objective)
        ranking.append(
            {
                "variant_id": variant.variant_id,
                "score": report.score,
                "hook": variant.hook_template,
                "narrative": variant.narrative_template,
                "cta": variant.cta_template,
                "issues": report.issues,
            }
        )
        if report.score > best_report.score:
            best_variant = variant
            best_report = report

    ranking.sort(key=lambda x: x["score"], reverse=True)
    return VariantSelection(selected=best_variant, report=best_report, ranking=ranking)
