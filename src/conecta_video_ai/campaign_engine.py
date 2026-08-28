from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class CampaignDefinition:
    name: str
    objective: str
    segments: list[dict]
    tone: str = "directo"
    strategy: str = "conversion"
    variants_per_segment: int = 2


@dataclass
class CampaignRunResult:
    campaign_name: str
    objective: str
    generated_runs: list[dict]
    summary: dict


def _segment_prompt(segment: dict, base_topic: str, objective: str, tone: str) -> str:
    service = segment.get("service", "servicio general")
    comuna = segment.get("comuna", "tu comuna")
    user_type = segment.get("user_type", "hogar")
    return (
        f"{base_topic}. Objetivo: {objective}. Segmento: {user_type} en {comuna}. "
        f"Servicio foco: {service}. Tono: {tone}."
    )


def run_campaign(
    *,
    campaign: CampaignDefinition,
    base_topic: str,
    generate_video_fn,
    insights: dict | None = None,
) -> CampaignRunResult:
    runs: list[dict] = []
    insights = insights or {}
    recommendations = insights.get("recommendations", [])

    for segment in campaign.segments:
        for i in range(campaign.variants_per_segment):
            topic = _segment_prompt(segment, base_topic, campaign.objective, campaign.tone)
            if recommendations:
                topic += f" Recomendacion insight: {recommendations[0]}"

            output = generate_video_fn(
                topic=topic,
                style="conversion" if campaign.strategy == "conversion" else "promo",
                objective=campaign.objective,
                auto_idea=False,
            )
            runs.append(
                {
                    "segment": segment,
                    "variant_index": i + 1,
                    "run_id": output.run_id,
                    "file": str(output.main_file),
                }
            )

    summary = {
        "segments": len(campaign.segments),
        "variants_per_segment": campaign.variants_per_segment,
        "total_videos": len(runs),
    }

    return CampaignRunResult(
        campaign_name=campaign.name,
        objective=campaign.objective,
        generated_runs=runs,
        summary=summary,
    )


def campaign_from_payload(payload: dict[str, Any]) -> CampaignDefinition:
    name = str(payload.get("name", "campana_conectapro")).strip() or "campana_conectapro"
    objective = str(payload.get("objective", "captar_clientes")).strip() or "captar_clientes"
    tone = str(payload.get("tone", "directo")).strip() or "directo"
    strategy = str(payload.get("strategy", "conversion")).strip() or "conversion"
    variants_per_segment = int(payload.get("variants_per_segment", 2) or 2)

    segments = payload.get("segments") or [
        {"service": "gasfiter", "comuna": "Santiago", "user_type": "hogar"},
        {"service": "electricista", "comuna": "Concepcion", "user_type": "hogar"},
    ]
    if not isinstance(segments, list) or not segments:
        raise ValueError("Campaign segments invalid")

    return CampaignDefinition(
        name=name,
        objective=objective,
        segments=segments,
        tone=tone,
        strategy=strategy,
        variants_per_segment=max(1, min(5, variants_per_segment)),
    )
