from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


@dataclass
class InsightReport:
    generated_at: str
    top_variants: list[dict]
    hook_ranking: list[dict]
    narrative_ranking: list[dict]
    cta_ranking: list[dict]
    trend_warnings: list[str]
    recommendations: list[str]


def _parse_iso(value: str) -> datetime | None:
    try:
        if value.endswith("Z"):
            value = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _avg(values: list[float]) -> float:
    return sum(values) / max(1, len(values))


def _build_bucket_scores(rows: list[dict], key: str) -> list[dict]:
    bucket = defaultdict(list)
    for row in rows:
        k = row.get(key)
        if not k:
            continue
        bucket[str(k)].append(float(row.get("composite_score", 0)))

    ranking = []
    for k, vals in bucket.items():
        ranking.append({"name": k, "count": len(vals), "avg_score": round(_avg(vals), 2)})
    ranking.sort(key=lambda x: (x["avg_score"], x["count"]), reverse=True)
    return ranking


def _composite(row: dict, performance_score: int | None) -> float:
    marketing = float(row.get("marketing_score", 0))
    continuity = float(row.get("continuity_score", 0))
    quality = float(row.get("quality_score", 0))
    perf = float(performance_score or 0)

    if perf > 0:
        return marketing * 0.30 + continuity * 0.20 + quality * 0.20 + perf * 0.30
    return marketing * 0.45 + continuity * 0.30 + quality * 0.25


def generate_insights(*, history_rows: list[dict], metrics_by_run: dict) -> InsightReport:
    enriched = []
    for row in history_rows:
        run_id = str(row.get("run_id", ""))
        perf = metrics_by_run.get(run_id, {}).get("performance_score") if run_id else None
        comp = _composite(row, perf)
        item = dict(row)
        item["performance_score"] = perf
        item["composite_score"] = round(comp, 2)
        enriched.append(item)

    enriched.sort(key=lambda x: x.get("composite_score", 0), reverse=True)

    top_variants = [
        {
            "run_id": r.get("run_id"),
            "variant_id": r.get("variant_id"),
            "objective": r.get("objective"),
            "score": r.get("composite_score"),
        }
        for r in enriched[:10]
    ]

    hook_ranking = _build_bucket_scores(enriched, "hook")
    narrative_ranking = _build_bucket_scores(enriched, "narrative")
    cta_ranking = _build_bucket_scores(enriched, "cta")

    trend_warnings: list[str] = []
    recommendations: list[str] = []

    now = datetime.now(timezone.utc)
    recent_cutoff = now - timedelta(days=14)
    recent = []
    older = []
    for row in enriched:
        dt = _parse_iso(str(row.get("published_at", "")))
        if dt is None:
            continue
        if dt >= recent_cutoff:
            recent.append(row)
        else:
            older.append(row)

    if recent and older:
        recent_avg = _avg([r.get("composite_score", 0) for r in recent])
        older_avg = _avg([r.get("composite_score", 0) for r in older])
        if recent_avg < older_avg - 8:
            trend_warnings.append("Rendimiento reciente en baja vs histórico")
            recommendations.append("Priorizar hooks y CTA del top histórico en próximas variantes")

    if hook_ranking:
        recommendations.append(f"Reutilizar hook ganador: {hook_ranking[0]['name']}")
    if cta_ranking:
        recommendations.append(f"Reutilizar CTA ganador: {cta_ranking[0]['name']}")
    if not recommendations:
        recommendations.append("Aún no hay suficiente histórico para insights robustos")

    return InsightReport(
        generated_at=now.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        top_variants=top_variants,
        hook_ranking=hook_ranking,
        narrative_ranking=narrative_ranking,
        cta_ranking=cta_ranking,
        trend_warnings=trend_warnings,
        recommendations=recommendations,
    )


