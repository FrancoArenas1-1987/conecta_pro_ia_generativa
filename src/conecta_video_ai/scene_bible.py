from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .models import BrandContext, StoryboardScene, VideoScript


Objective = Literal["captar_clientes", "captar_proveedores", "branding"]


@dataclass(frozen=True)
class ConstraintSet:
    hard: dict
    soft: dict


def resolve_objective(style: str, objective: str | None) -> Objective:
    if objective in {"captar_clientes", "captar_proveedores", "branding"}:
        return objective
    if style == "conversion":
        return "captar_clientes"
    return "branding"


def _default_constraints(style: str, objective: Objective, context: BrandContext) -> ConstraintSet:
    hard = {
        "format": "vertical_9_16",
        "brand_name": context.company_name,
        "cta_whatsapp_required": True,
        "logo_required": True,
        "avoid_claims": context.voice.avoid + ["garantizado", "sin riesgo"],
        "style": style,
        "objective": objective,
    }
    soft = {
        "pace_target": "alto" if style == "conversion" else "medio",
        "emotional_tone": "urgencia_confiable" if objective == "captar_clientes" else "confianza_profesional",
        "narrative_shape": ["problema", "solucion", "accion"],
        "scene_duration_range": [1.0, 2.0] if style == "conversion" else [1.0, 5.0],
    }
    return ConstraintSet(hard=hard, soft=soft)


def _story_arc(style: str, objective: Objective) -> list[dict]:
    if style == "conversion":
        return [
            {"beat": "hook", "goal": "detener scroll"},
            {"beat": "problema", "goal": "identificacion"},
            {"beat": "frustracion", "goal": "subir tension"},
            {"beat": "solucion", "goal": "mostrar producto"},
            {"beat": "resultado", "goal": "prueba visual"},
            {"beat": "cta", "goal": "accion inmediata"},
        ]
    if objective == "captar_proveedores":
        return [
            {"beat": "hook", "goal": "atraer profesionales"},
            {"beat": "problema", "goal": "falta de clientes"},
            {"beat": "solucion", "goal": "flujo de oportunidades"},
            {"beat": "credibilidad", "goal": "confianza plataforma"},
            {"beat": "cta", "goal": "registro inmediato"},
        ]
    return [
        {"beat": "hook", "goal": "recordacion"},
        {"beat": "problema", "goal": "contexto"},
        {"beat": "solucion", "goal": "propuesta de valor"},
        {"beat": "resultado", "goal": "beneficio claro"},
        {"beat": "cta", "goal": "accion"},
    ]


def build_scene_bible(
    *,
    context: BrandContext,
    topic: str,
    style: str,
    objective: Objective,
    script: VideoScript,
) -> dict:
    constraints = _default_constraints(style, objective, context)
    cast: list[dict] = []
    if script.style == "dialogo" and script.dialogue:
        speakers = []
        for turn in script.dialogue:
            speaker = turn.speaker.strip()
            if speaker and speaker not in speakers:
                speakers.append(speaker)
        for i, speaker in enumerate(speakers, start=1):
            cast.append(
                {
                    "id": f"speaker_{i}",
                    "name": speaker,
                    "role": "asesor" if "asesor" in speaker.lower() else "cliente",
                    "wardrobe": "casual_profesional",
                }
            )

    return {
        "version": "1.0",
        "topic": topic,
        "style": style,
        "objective": objective,
        "brand": {
            "name": context.company_name,
            "tagline": context.tagline,
            "cta": context.call_to_action,
            "whatsapp_url": context.whatsapp_url,
            "website_url": context.website_url,
        },
        "constraints": {
            "hard": constraints.hard,
            "soft": constraints.soft,
        },
        "story_arc": _story_arc(style, objective),
        "cast": cast,
    }


def build_scene_manifest(*, script: VideoScript, scenes: list[StoryboardScene], run_id: str) -> dict:
    scene_items = []
    for scene in scenes:
        scene_items.append(
            {
                "index": scene.index,
                "headline": scene.headline,
                "body": scene.body,
                "speaker": scene.speaker,
                "duration_seconds": scene.duration_seconds,
                "visual_style": scene.visual_style,
                "source_image": str(scene.source_image) if scene.source_image else None,
                "source_video": str(scene.source_video) if scene.source_video else None,
            }
        )

    return {
        "run_id": run_id,
        "style": script.style,
        "hook": script.hook,
        "cta": script.cta,
        "scene_count": len(scene_items),
        "scenes": scene_items,
    }
