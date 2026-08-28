from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass
class MetricoolRow:
    date: str
    network: str
    post_id: str
    clicks: int
    impressions: int
    engagement: float


class MetricoolCSVImporter:
    """Importa métricas exportadas desde Metricool (CSV) para alimentar performance_tracker."""

    @staticmethod
    def parse_csv(path: Path) -> list[MetricoolRow]:
        rows: list[MetricoolRow] = []
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for r in reader:
                post_id = str(r.get("post_id") or r.get("Post ID") or r.get("id") or "").strip()
                if not post_id:
                    continue
                rows.append(
                    MetricoolRow(
                        date=str(r.get("date") or r.get("Date") or "").strip(),
                        network=str(r.get("network") or r.get("Network") or "").strip(),
                        post_id=post_id,
                        clicks=int(float(r.get("clicks") or r.get("Clicks") or 0)),
                        impressions=int(float(r.get("impressions") or r.get("Impressions") or 0)),
                        engagement=float(r.get("engagement") or r.get("Engagement") or 0.0),
                    )
                )
        return rows

    @staticmethod
    def attach_to_runs(rows: Iterable[MetricoolRow], post_to_run: dict[str, str]) -> dict[str, dict]:
        mapped: dict[str, dict] = {}
        for row in rows:
            run_id = post_to_run.get(row.post_id)
            if not run_id:
                continue
            mapped[run_id] = {
                "clicks": row.clicks,
                "impressions": row.impressions,
                "engagement": row.engagement,
            }
        return mapped


class SocialConnectorError(RuntimeError):
    pass


class ConnectorConfig:
    def __init__(self, channel: str, required_env: list[str]) -> None:
        self.channel = channel
        self.required_env = required_env

    def validate(self, env: dict[str, str]) -> tuple[bool, list[str]]:
        missing = [k for k in self.required_env if not env.get(k)]
        return len(missing) == 0, missing


def connector_blueprint(channel: str) -> ConnectorConfig:
    """Retorna requisitos de configuracion para publicar en cada canal.

    Nota: La publicacion real usa adapters en performance_tracker (dry-run por defecto).
    """

    c = (channel or "").strip().lower()
    if c in {"instagram", "facebook", "meta"}:
        return ConnectorConfig(channel="meta", required_env=["META_APP_ID", "META_APP_SECRET", "META_PAGE_ID", "META_ACCESS_TOKEN"])
    if c in {"tiktok"}:
        return ConnectorConfig(channel="tiktok", required_env=["TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET", "TIKTOK_ACCESS_TOKEN"])
    if c in {"youtube"}:
        return ConnectorConfig(channel="youtube", required_env=["YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN"])
    if c in {"metricool"}:
        return ConnectorConfig(channel="metricool", required_env=["METRICOOL_API_KEY"])
    return ConnectorConfig(channel="local_dryrun", required_env=[])
