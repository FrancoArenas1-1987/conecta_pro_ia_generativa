from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class LayoutBox:
    name: str
    x1: int
    y1: int
    x2: int
    y2: int
    kind: str = "content"

    def intersects(self, other: "LayoutBox", *, gap: int = 0) -> bool:
        return not (
            self.x2 + gap <= other.x1
            or other.x2 + gap <= self.x1
            or self.y2 + gap <= other.y1
            or other.y2 + gap <= self.y1
        )

    def outside(self, width: int, height: int, *, margin: int = 0) -> bool:
        return self.x1 < margin or self.y1 < margin or self.x2 > width - margin or self.y2 > height - margin


class LayoutGuard:
    """Records deterministic layout boxes and rejects unsafe social-media artwork."""

    def __init__(self, *, asset_name: str, width: int, height: int, safe_margin: int = 44) -> None:
        self.asset_name = asset_name
        self.width = int(width)
        self.height = int(height)
        self.safe_margin = int(safe_margin)
        self.boxes: list[LayoutBox] = []

    def add(self, name: str, xy: tuple[int, int, int, int], *, kind: str = "content") -> None:
        x1, y1, x2, y2 = [int(v) for v in xy]
        self.boxes.append(LayoutBox(name=name, x1=x1, y1=y1, x2=x2, y2=y2, kind=kind))

    def validate(self, *, min_gap: int = 8) -> list[str]:
        issues: list[str] = []
        for box in self.boxes:
            if box.outside(self.width, self.height, margin=self.safe_margin):
                issues.append(f"{self.asset_name}: {box.name} fuera de margen seguro")

        for idx, a in enumerate(self.boxes):
            for b in self.boxes[idx + 1 :]:
                if "background" in {a.kind, b.kind}:
                    continue
                if a.intersects(b, gap=min_gap):
                    issues.append(f"{self.asset_name}: {a.name} se superpone con {b.name}")
        return issues

    def to_dict(self) -> dict:
        return {
            "asset_name": self.asset_name,
            "width": self.width,
            "height": self.height,
            "safe_margin": self.safe_margin,
            "boxes": [asdict(box) for box in self.boxes],
            "issues": self.validate(),
        }


def write_manifest(path: Path, guards: Iterable[LayoutGuard]) -> None:
    payload = [guard.to_dict() for guard in guards]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def assert_layouts(guards: Iterable[LayoutGuard]) -> None:
    issues: list[str] = []
    for guard in guards:
        issues.extend(guard.validate())
    if issues:
        raise RuntimeError("Layout guard failed:\n" + "\n".join(f"- {issue}" for issue in issues))
