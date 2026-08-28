from __future__ import annotations

from pathlib import Path

import numpy as np

from .models import BrandContext, StoryboardScene, VideoScript


def _tokenize(text: str) -> set[str]:
    clean = "".join(ch.lower() if ch.isalnum() else " " for ch in text)
    return {t for t in clean.split() if len(t) >= 3}


def _semantic_overlap(a: set[str], b: set[str]) -> bool:
    if a.intersection(b):
        return True

    concept_groups = [
        {"gasfiter", "gasfiteria", "plomeria", "plomero", "calefon", "fuga"},
        {"electricista", "electricidad", "tablero", "enchufe", "cable", "luz"},
        {"abogado", "legal", "juridico", "contrato", "demanda"},
        {"kinesiologia", "kine", "rehabilitacion", "terapia", "dolor"},
        {"servicio", "servicios", "profesional", "profesionales", "tecnico", "especialista"},
        {"whatsapp", "mensaje", "chat", "celular", "movil"},
        {"comofunciona", "paso", "pasos", "proceso", "flujo", "como"},
        {"gratis", "sincosto", "costo", "sin"},
    ]

    for group in concept_groups:
        if a.intersection(group) and b.intersection(group):
            return True

    return False


def _check_dialogue_alternation(script: VideoScript) -> bool:
    if script.style != "dialogo":
        return True
    if len(script.dialogue) < 6:
        return False
    prev = None
    switches = 0
    for turn in script.dialogue:
        s = turn.speaker.strip().lower()
        if prev is not None and s != prev:
            switches += 1
        prev = s
    return switches >= max(3, len(script.dialogue) // 2)


def _estimate_visual_dynamics(video_path: Path, samples: int = 12) -> float:
    from moviepy.editor import VideoFileClip

    clip = VideoFileClip(str(video_path))
    try:
        if clip.duration <= 0:
            return 0.0

        times = np.linspace(0, max(0.01, clip.duration - 0.01), num=max(3, samples))
        frames = [clip.get_frame(float(t)).astype(np.float32) for t in times]

        deltas: list[float] = []
        for i in range(1, len(frames)):
            delta = np.mean(np.abs(frames[i] - frames[i - 1]))
            deltas.append(float(delta))

        return float(np.mean(deltas)) if deltas else 0.0
    finally:
        clip.close()


def review_generated_video(
    *,
    video_path: Path,
    script: VideoScript,
    scenes: list[StoryboardScene],
    topic: str,
    target_seconds: int | None,
    expect_audio: bool,
    context: BrandContext,
    min_score: int,
) -> dict:
    from moviepy.editor import VideoFileClip

    issues: list[str] = []
    strengths: list[str] = []
    score = 100

    if not video_path.exists() or video_path.stat().st_size == 0:
        return {
            "passed": False,
            "score": 0,
            "issues": ["Video file missing or empty"],
            "strengths": [],
            "checks": {},
            "recommendations": ["Regenerar video"],
        }

    clip = VideoFileClip(str(video_path))
    try:
        duration = float(clip.duration or 0.0)
        width, height = clip.size
        has_audio = clip.audio is not None and (clip.audio.duration or 0) > 0
    finally:
        clip.close()

    checks: dict[str, object] = {
        "duration": round(duration, 2),
        "size": [width, height],
        "has_audio": has_audio,
        "style": script.style,
        "dialogue_turns": len(script.dialogue),
        "scene_count": len(scenes),
    }

    # Technical checks.
    if width >= height:
        score -= 12
        issues.append("Formato no vertical para redes (esperado 9:16)")
    else:
        strengths.append("Formato vertical correcto")

    if target_seconds and target_seconds > 0:
        if abs(duration - target_seconds) > target_seconds * 0.25:
            score -= 12
            issues.append(f"Duracion desviada: {round(duration,2)}s vs objetivo {target_seconds}s")
        else:
            strengths.append("Duracion cercana al objetivo")
    else:
        strengths.append("Duracion coherente con storyline")

    if expect_audio and not has_audio:
        score -= 20
        issues.append("No incluye audio")
    elif expect_audio and has_audio:
        strengths.append("Incluye audio")

    # Content checks.
    full_text = " ".join(
        [script.hook, script.cta]
        + [f"{s.title} {s.narration} {s.onscreen_text}" for s in script.sections]
        + [f"{d.speaker} {d.line}" for d in script.dialogue]
    ).lower()

    if "whatsapp" not in full_text:
        score -= 10
        issues.append("No menciona WhatsApp")
    else:
        strengths.append("Mensaje WhatsApp presente")

    cta_low = script.cta.lower()
    brand_cta_low = context.call_to_action.lower()
    cta_action_ok = any(k in cta_low for k in ["whatsapp", "escribe", "hablar", "contacta", "ahora"])
    if brand_cta_low not in cta_low and not cta_action_ok:
        score -= 8
        issues.append("CTA final no coincide con CTA de marca")
    else:
        strengths.append("CTA alineado a marca")

    if script.style == "dialogo":
        if not _check_dialogue_alternation(script):
            score -= 12
            issues.append("Dialogo poco natural (pocos turnos o alternancia baja)")
        else:
            strengths.append("Dialogo con alternancia natural")

    if script.style == "dialogo":
        bad_line_hits = 0
        for turn in script.dialogue:
            low_line = turn.line.lower()
            if any(tok in low_line for tok in ["persona 1:", "persona 2:", "cliente:", "asesor:", "escena "]):
                bad_line_hits += 1
        if bad_line_hits > 0:
            score -= min(14, 3 * bad_line_hits)
            issues.append("Dialogo contiene etiquetas internas (persona/escena) en lineas narradas")
        else:
            strengths.append("Dialogo limpio sin etiquetas narradas")
    if script.style == "conversion":
        max_conversion_seconds = 30 if context.whatsapp_qr_path else 25
        if duration < 20 or duration > max_conversion_seconds:
            score -= 18
            issues.append(f"Reel conversion fuera de rango 20-{max_conversion_seconds}s")
        else:
            strengths.append(f"Duracion conversion en rango 20-{max_conversion_seconds}s")

        bad_scene_durations = [s.duration_seconds for s in scenes if s.duration_seconds < 1.0 or s.duration_seconds > 2.0]
        if bad_scene_durations:
            score -= 16
            issues.append("Hay clips fuera del rango 1-2s")
        else:
            strengths.append("Todos los clips estan entre 1-2s")

        if "te ha fallado un maestro" not in full_text:
            score -= 8
            issues.append("Falta gancho inicial esperado")
        else:
            strengths.append("Gancho inicial presente")
    # Visual relevance checks.
    unique_assets = len({str(s.source_image) for s in scenes if s.source_image})
    checks["unique_assets"] = unique_assets

    min_assets = 3 if script.style == "dialogo" else 2
    if unique_assets < min_assets:
        score -= 12
        issues.append(f"Poca variedad visual ({unique_assets} assets)")
    else:
        strengths.append("Variedad visual aceptable")

    # Relevance based on topic + script semantics + section copy.
    expected_tokens = _tokenize(topic + " " + full_text + " " + " ".join(context.key_messages))

    relevance_hits = 0
    for scene in scenes:
        if not scene.source_image:
            continue
        tags = _tokenize(str(scene.source_image))
        scene_tokens = _tokenize(f"{scene.headline} {scene.body} {scene.speaker or ''}")
        if _semantic_overlap(tags, expected_tokens.union(scene_tokens)):
            relevance_hits += 1

    relevance_ratio = relevance_hits / max(1, len(scenes))
    checks["asset_topic_relevance_ratio"] = round(relevance_ratio, 2)

    if relevance_ratio < 0.22:
        score -= 10
        issues.append("Imagenes poco relacionadas con el tema del reel")
    else:
        strengths.append("Imagenes mayormente relacionadas al tema")

    # Dynamic feel check.
    try:
        dynamics = _estimate_visual_dynamics(video_path)
        checks["visual_dynamics"] = round(dynamics, 2)
        if dynamics < 1.8:
            score -= 10
            issues.append("Video visualmente poco dinamico")
        else:
            strengths.append("Dinamica visual adecuada")
    except Exception:
        checks["visual_dynamics"] = None

    # Marketing-risk language checks.
    risky_claims = ["garantizado", "100%", "sin riesgo"]
    if script.style == "conversion" and "100% gratis" in full_text:
        risky_claims = [term for term in risky_claims if term != "100%"]
    risky_hits = [term for term in risky_claims if term in full_text]
    if risky_hits:
        score -= 8
        issues.append(f"Claim riesgoso para marketing: {', '.join(risky_hits)}")

    score = max(0, min(100, score))
    passed = score >= min_score and len(issues) == 0

    recommendations: list[str] = []
    issues_text = " | ".join(issues).lower()
    if "variedad visual" in issues_text:
        recommendations.append("Agregar assets mas variados por escena")
    if "poco relacionadas" in issues_text or "relacionadas" in issues_text:
        recommendations.append("Usar imagenes mas alineadas al servicio o problema principal del reel")
    if "dialogo poco natural" in issues_text:
        recommendations.append("Pedir dialogo mas corto, claro y con alternancia estricta")
    if "claim riesgoso" in issues_text:
        recommendations.append("Evitar terminos absolutos como 'garantizado' o '100%'")
    if "duracion desviada" in issues_text:
        recommendations.append("Ajustar duracion objetivo o reducir cantidad de escenas")
    if "no incluye audio" in issues_text:
        recommendations.append("Activar TTS o adjuntar pista de voz")
    if not recommendations and passed:
        recommendations.append("Apto para publicacion en redes")
    elif not recommendations and not passed:
        recommendations.append("Revisar post_review.json y regenerar con contexto mas especifico")

    return {
        "passed": passed,
        "score": score,
        "issues": issues,
        "strengths": strengths,
        "checks": checks,
        "recommendations": recommendations,
    }







