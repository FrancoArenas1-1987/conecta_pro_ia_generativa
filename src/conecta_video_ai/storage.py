from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


def slugify(value: str) -> str:
    clean = "".join(ch.lower() if ch.isalnum() else "-" for ch in value)
    while "--" in clean:
        clean = clean.replace("--", "-")
    return clean.strip("-")[:60] or "item"


def create_run_dir(output_root: Path, prefix: str) -> tuple[str, Path]:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_run_id = f"{ts}_{slugify(prefix)}"
    for suffix in range(100):
        run_id = base_run_id if suffix == 0 else f"{base_run_id}-{suffix:02d}"
        run_dir = output_root / run_id
        try:
            run_dir.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            continue
        return run_id, run_dir
    raise FileExistsError(f"No se pudo crear run dir unico para {base_run_id}")


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
