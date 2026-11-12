"""Atomic reservations prevent concurrent image requests exceeding the local cap.

Uncertain API/network failures retain their reservation for reconciliation.
Amounts are operational estimates, not a replacement for the Costs API.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path


class BudgetBlocked(RuntimeError):
    pass


class ImageBudget:
    def __init__(self, path: Path, limit: float, reserve_usd: float = 0.30):
        self.path, self.limit, self.reserve_usd = path, limit, reserve_usd
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS requests (id TEXT PRIMARY KEY, month TEXT, service TEXT, state TEXT, amount REAL, metadata TEXT)")
            db.execute("CREATE TABLE IF NOT EXISTS controls (key TEXT PRIMARY KEY, value TEXT)")

    def connect(self):
        return sqlite3.connect(self.path, timeout=15)

    def reserve(self, service: str) -> str:
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            blocked = db.execute("SELECT value FROM controls WHERE key='quota_blocked'").fetchone()
            if blocked:
                raise BudgetBlocked("openai_quota_blocked: use --resume-after-topup after adding credits")
            total = db.execute("SELECT COALESCE(SUM(amount),0) FROM requests WHERE month=?", (month,)).fetchone()[0]
            if self.limit <= 0 or self.reserve_usd <= 0 or total + self.reserve_usd > self.limit + 1e-9:
                raise BudgetBlocked(f"monthly_image_budget: used/reserved={total:.4f}, limit={self.limit:.2f}")
            key = uuid.uuid4().hex
            db.execute("INSERT INTO requests VALUES (?,?,?,?,?,?)", (key, month, service, "reserved", self.reserve_usd, "{}"))
            return key

    def complete(self, key: str, metadata: dict) -> None:
        # Retain conservative reserved estimate if the response has no known usage schema.
        usage = metadata.get("usage") or {}
        amount = self.reserve_usd
        if metadata.get("model") == "gpt-image-1" and usage.get("output_tokens") is not None:
            details = usage.get("input_tokens_details") or {}
            if "text_tokens" in details and "image_tokens" in details:
                amount = (details["text_tokens"] * 5 + details["image_tokens"] * 10 + usage["output_tokens"] * 40) / 1_000_000
        with self.connect() as db:
            db.execute("UPDATE requests SET state='completed',amount=?,metadata=? WHERE id=?", (amount, json.dumps(metadata), key))

    def failed(self, key: str, error: str) -> None:
        quota = any(x in error for x in ("insufficient_quota", "credit_balance_exhausted"))
        with self.connect() as db:
            if quota:
                db.execute("UPDATE requests SET state='blocked',amount=0 WHERE id=?", (key,))
                db.execute("INSERT OR REPLACE INTO controls VALUES ('quota_blocked',?)", (datetime.now(timezone.utc).isoformat(),))
            else:
                db.execute("UPDATE requests SET state='uncertain' WHERE id=?", (key,))

    def resume(self) -> None:
        with self.connect() as db:
            db.execute("DELETE FROM controls WHERE key='quota_blocked'")

    def import_history(self, logs: Path, estimate: float) -> None:
        with self.connect() as db:
            for path in sorted(logs.glob("image-factory_*.log")):
                content = path.read_text(encoding="utf-8", errors="replace")
                start = content.find("\n{")
                if start < 0:
                    continue
                try:
                    item, _ = json.JSONDecoder().raw_decode(content[start+1:])
                except ValueError:
                    continue
                if item.get("created") and item.get("source") != "reference_seed" and not item.get("budget_request_id"):
                    stamp = path.stem.split("_")[1]
                    db.execute("INSERT OR IGNORE INTO requests VALUES (?,?,?,?,?,?)", (
                        "historical:" + path.name, stamp[:4] + "-" + stamp[4:6],
                        item.get("decision", {}).get("service", {}).get("code", "unknown"),
                        "historical_estimate", estimate, json.dumps({"source_log": path.name})))
