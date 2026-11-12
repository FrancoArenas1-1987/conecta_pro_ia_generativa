"""Read-only operational report; never generates, publishes or contacts providers."""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from conecta_video_ai.service_images import read_registry


def report(root=ROOT):
    instagram = root / "output/runs/instagram"
    registry = read_registry(instagram / "catalog/service_images.json")
    rows = registry.get("services", {})
    result = {"checked_at": datetime.now(timezone.utc).isoformat(),
              "images": dict(Counter(r.get("status", "unknown") for r in rows.values() if r.get("active"))),
              "needs_review": [code for code,r in rows.items() if r.get("active") and r.get("status") == "needs_review"],
              "jobs": {}}
    for job in ("image-factory", "autopublish", "carousel", "token-refresh"):
        files = sorted((root / "logs/prod_jobs").glob(job+"_*.log"))
        if not files:
            continue
        content = files[-1].read_text(errors="replace")
        start = content.find("\n{")
        try:
            payload, _ = json.JSONDecoder().raw_decode(content[start+1:])
            result["jobs"][job] = {"log": files[-1].name, "ok": payload.get("ok"),
                                    "status": payload.get("status") or ("skipped" if payload.get("skipped") else "succeeded" if payload.get("ok") else "failed"),
                                    "reason": payload.get("reason")}
        except ValueError:
            result["jobs"][job] = {"log": files[-1].name, "status": "unparsed_or_running"}
    budget = instagram / "budget/image_usage.sqlite3"
    if budget.exists():
        with sqlite3.connect(budget.resolve().as_uri()+"?mode=ro", uri=True) as db:
            month = datetime.now(timezone.utc).strftime("%Y-%m")
            result["image_budget"] = {"month": month, "estimated_or_reserved_usd": db.execute("SELECT COALESCE(SUM(amount),0) FROM requests WHERE month=?", (month,)).fetchone()[0],
                                       "quota_blocked": bool(db.execute("SELECT 1 FROM controls WHERE key='quota_blocked'").fetchone())}
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", action="store_true")
    args = parser.parse_args()
    result = report()
    if args.database:
        import psycopg
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
        with psycopg.connect(host=os.getenv("CP_DB_HOST", "127.0.0.1"), port=os.getenv("CP_DB_PORT", "5432"),
                              dbname=os.getenv("CP_DB_NAME"), user=os.getenv("CP_DB_USER"), password=os.getenv("CP_DB_PASSWORD"),
                              connect_timeout=5, options="-c default_transaction_read_only=on -c statement_timeout=10000") as db:
            with db.cursor() as cur:
                cur.execute("SELECT job_type,status,count(*),max(created_at) FROM worker_runs WHERE created_at >= now()-interval '7 days' GROUP BY 1,2")
                result["workers_7d"] = cur.fetchall()
                cur.execute("SELECT status,count(*) FROM provider_import_candidates GROUP BY status")
                result["candidates"] = dict(cur.fetchall())
                cur.execute("SELECT count(*) FROM inbound_messages WHERE processed_at IS NULL")
                result["pending_messages"] = cur.fetchone()[0]
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
