from __future__ import annotations

import re
from dataclasses import dataclass

from .models import StoryboardScene, VideoScript


@dataclass
class ContinuityReport:
    passed: bool
    score: int
    issues: list[str]
    checks: dict


def _tok(text: str) -> set[str]:
    cleaned = re.sub(r"[^a-zA-Z0-9áéíóúÁÉÍÓÚñÑ ]+", " ", (text or "").lower())
    return {p for p in cleaned.split() if len(p) >= 3}


def validate_continuity(
    *,
    scene_bible: dict,
    scene_manifest: dict,
    script: VideoScript,
    scenes: list[StoryboardScene],
) -> ContinuityReport:
    issues: list[str] = []
    score = 100

    hard = ((scene_bible or {}).get("constraints") or {}).get("hard") or {}
    soft = ((scene_bible or {}).get("constraints") or {}).get("soft") or {}

    expected_style = hard.get("style")
    if expected_style and script.style != expected_style:
        score -= 16
        issues.append(f"Style inconsistente: script={script.style} bible={expected_style}")

    if hard.get("cta_whatsapp_required", False):
        cta_low = (script.cta or "").lower()
        if "whatsapp" not in cta_low:
            score -= 15
            issues.append("CTA no menciona WhatsApp")

    scene_count = len(scenes)
    if scene_count < 4:
        score -= 18
        issues.append("Muy pocas escenas para narrativa profesional")

    if scene_manifest.get("scene_count") != scene_count:
        score -= 8
        issues.append("scene_manifest scene_count no coincide")

    if scene_count:
        first_scene = scenes[0]
        hook_tokens = _tok(script.hook)
        first_tokens = _tok(first_scene.headline + " " + first_scene.body)
        overlap = len(hook_tokens.intersection(first_tokens)) / max(1, len(hook_tokens))
        if overlap < 0.25:
            score -= 10
            issues.append("Hook no se refleja claramente en primera escena")

    # Scene order and arc coherence.
    arc = scene_bible.get("story_arc") or []
    if arc and scene_count:
        expected_beats = [str(b.get("beat", "")).lower() for b in arc]
        text_flow = [f"{s.headline} {s.body}".lower() for s in scenes]
        hit = 0
        for beat in expected_beats:
            if any(beat[:5] in t for t in text_flow):
                hit += 1
        ratio = hit / max(1, len(expected_beats))
        if ratio < 0.45:
            score -= 12
            issues.append("Narrativa no sigue el story arc definido")

    # Duration continuity.
    min_d, max_d = (soft.get("scene_duration_range") or [1.0, 5.0])
    bad_durations = [s.duration_seconds for s in scenes if s.duration_seconds < float(min_d) or s.duration_seconds > float(max_d)]
    if bad_durations:
        penalty = min(18, 2 * len(bad_durations))
        score -= penalty
        issues.append(f"Duraciones fuera de rango esperado ({len(bad_durations)} escenas)")

    # Asset continuity / visual consistency signal.
    asset_refs = [str(s.source_image or s.source_video or "") for s in scenes]
    unique_assets = len({a for a in asset_refs if a})
    if scene_count >= 6 and unique_assets < 3:
        score -= 12
        issues.append("Baja variedad visual entre escenas")

    # Dialogue coherence.
    if script.style == "dialogo" and script.dialogue:
        speakers = [t.speaker.strip().lower() for t in script.dialogue if t.speaker.strip()]
        unique_speakers = len(set(speakers))
        if unique_speakers < 2:
            score -= 14
            issues.append("Dialogo sin variedad de speaker")

    checks = {
        "scene_count": scene_count,
        "unique_assets": unique_assets,
        "expected_style": expected_style,
        "hook_first_scene_overlap": round(overlap if scene_count else 0.0, 2),
    }
    score = max(0, min(100, score))
    return ContinuityReport(
        passed=score >= 85 and not issues,
        score=score,
        issues=issues,
        checks=checks,
    )
