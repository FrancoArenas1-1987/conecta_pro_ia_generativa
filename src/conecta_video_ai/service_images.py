"""Persistent, canonical service -> primary image registry. No generation here."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ALIASES = {"legal": "abogado", "veterinarios": "medico_veterinario",
           "desarrollo_software": "desarrollo_web", "traductores_ingles_espanol": "traductor"}


def canonical(code: str) -> str:
    return ALIASES.get(code, code)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_registry(path: Path) -> dict:
    if not path.exists():
        return {}
    # Fail closed on corruption: never silently discard approvals.
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data.get("services"), dict):
        raise ValueError("Invalid service image registry")
    return data


def save_registry(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def approved_paths(registry: dict, assets_root: Path) -> dict[str, Path]:
    result = {}
    for code, row in registry.get("services", {}).items():
        if row.get("status") != "approved" or not row.get("active") or row.get("provider_count", 0) < 1:
            continue
        path = (assets_root / row["image"]).resolve()
        if not path.is_relative_to(assets_root.resolve()):
            raise ValueError("Image outside assets root")
        if path.is_file() and digest(path) == row.get("sha256"):
            result[code] = path
    return result


def reconcile(path: Path, services: list, assets_root: Path, catalog: dict) -> dict:
    data = read_registry(path) or {"version": 1, "services": {}}
    live = {s.code: s for s in services}
    for code, row in data["services"].items():
        row["active"] = code in live
        row["provider_count"] = live[code].provider_count if code in live else 0
    for code, service in live.items():
        row = data["services"].setdefault(code, {})
        row.update(name=service.name, active=True, provider_count=service.provider_count)
        if row.get("image"):
            image = assets_root / row["image"]
            if not image.is_file() or digest(image) != row.get("sha256"):
                row.update(status="needs_review", reason="approved_file_missing_or_changed")
            continue
        candidates = [a for a in catalog.get("items", [])
                      if canonical(str(a.get("category_id", ""))) == code
                      and a.get("media_type", "image") == "image" and not a.get("excluded")
                      and (assets_root / a.get("rel_path", "")).is_file()]
        candidates.sort(key=lambda a: (not bool(a.get("quality_passed")),
                                      a.get("rel_path") != f"{code}_01.png", a.get("rel_path", "")))
        if candidates:
            asset = candidates[0]
            image = assets_root / asset["rel_path"]
            row.update(image=asset["rel_path"], sha256=digest(image),
                       status="approved" if asset.get("quality_passed") else "needs_review",
                       approval_source="existing_catalog_quality_check",
                       reason="; ".join(asset.get("quality_issues") or []))
        else:
            row.setdefault("status", "missing")
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    save_registry(path, data)
    return data


def approve_generated(path: Path, code: str, image: Path, assets_root: Path) -> None:
    data = read_registry(path)
    row = data["services"][code]
    row.update(image=image.resolve().relative_to(assets_root.resolve()).as_posix(),
               sha256=digest(image), status="approved", approval_source="factory_quality_check",
               approved_at=datetime.now(timezone.utc).isoformat(), reason="")
    save_registry(path, data)
