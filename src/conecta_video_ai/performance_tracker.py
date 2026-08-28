from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from .social_connectors import MetricoolCSVImporter


@dataclass
class PerformanceRecord:
    run_id: str
    variant_id: str
    hook: str
    narrative: str
    cta: str
    objective: str
    marketing_score: int
    continuity_score: int
    quality_score: int
    published_at: str
    channel: str
    post_id: str | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _safe_read_json(path: Path, fallback):
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


class PerformanceTracker:
    def __init__(self, storage_root: Path) -> None:
        self.storage_root = storage_root
        self.storage_root.mkdir(parents=True, exist_ok=True)
        self.records_file = self.storage_root / "performance_records.jsonl"
        self.metrics_file = self.storage_root / "performance_metrics.json"

    def register_video(self, record: PerformanceRecord) -> None:
        row = {
            "run_id": record.run_id,
            "variant_id": record.variant_id,
            "hook": record.hook,
            "narrative": record.narrative,
            "cta": record.cta,
            "objective": record.objective,
            "marketing_score": record.marketing_score,
            "continuity_score": record.continuity_score,
            "quality_score": record.quality_score,
            "published_at": record.published_at,
            "channel": record.channel,
            "post_id": record.post_id,
        }
        with self.records_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def register_metrics(
        self,
        *,
        run_id: str,
        clicks: int = 0,
        whatsapp_messages: int = 0,
        engagement: float = 0.0,
        impressions: int = 0,
    ) -> dict:
        metrics = _safe_read_json(self.metrics_file, {})
        metrics[run_id] = {
            "clicks": int(clicks),
            "whatsapp_messages": int(whatsapp_messages),
            "engagement": float(engagement),
            "impressions": int(impressions),
            "updated_at": _now_iso(),
            "performance_score": self.compute_performance_score(
                clicks=clicks,
                whatsapp_messages=whatsapp_messages,
                engagement=engagement,
                impressions=impressions,
            ),
        }
        self.metrics_file.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
        return metrics[run_id]

    @staticmethod
    def compute_performance_score(
        *,
        clicks: int,
        whatsapp_messages: int,
        engagement: float,
        impressions: int,
    ) -> int:
        ctr = (clicks / impressions) if impressions > 0 else 0.0
        lead_rate = (whatsapp_messages / max(1, clicks))
        engagement_norm = max(0.0, min(1.0, engagement))

        score = (ctr * 35.0) + (lead_rate * 40.0) + (engagement_norm * 25.0)
        return int(max(0, min(100, round(score * 100 if score <= 1.0 else score))))

    def load_history(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        if not self.records_file.exists():
            return rows
        for line in self.records_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
        return rows

    def load_metrics(self) -> dict:
        return _safe_read_json(self.metrics_file, {})

    def import_metricool_csv(self, *, csv_path: Path, post_to_run: dict[str, str]) -> dict:
        rows = MetricoolCSVImporter.parse_csv(csv_path)
        mapped = MetricoolCSVImporter.attach_to_runs(rows, post_to_run)
        for run_id, item in mapped.items():
            self.register_metrics(
                run_id=run_id,
                clicks=int(item.get("clicks", 0)),
                engagement=float(item.get("engagement", 0.0)),
                impressions=int(item.get("impressions", 0)),
            )
        return {"imported_rows": len(rows), "mapped_runs": len(mapped)}


class SocialPublisherAdapter:
    """Base adapter for optional social network publishing integration.

    Implementations can publish and pull metrics from each platform.
    """

    channel_name = "generic"

    def publish_video(self, *, video_path: Path, caption: str, tags: list[str] | None = None) -> dict:
        raise NotImplementedError

    def fetch_post_metrics(self, *, post_id: str) -> dict:
        raise NotImplementedError


class LocalDryRunPublisher(SocialPublisherAdapter):
    channel_name = "local_dryrun"

    def publish_video(self, *, video_path: Path, caption: str, tags: list[str] | None = None) -> dict:
        return {
            "channel": self.channel_name,
            "post_id": f"dryrun-{video_path.stem}",
            "published_at": _now_iso(),
            "caption": caption,
            "tags": tags or [],
        }

    def fetch_post_metrics(self, *, post_id: str) -> dict:
        return {
            "post_id": post_id,
            "clicks": 0,
            "whatsapp_messages": 0,
            "engagement": 0.0,
            "impressions": 0,
        }

