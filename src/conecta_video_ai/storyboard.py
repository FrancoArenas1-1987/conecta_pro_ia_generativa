from __future__ import annotations

from .models import AssetItem, StoryboardScene, VideoScript


def _estimate_seconds(text: str, visual_style: str) -> float:
    words = max(4, len((text or "").split()))
    if visual_style == "dialogo":
        return max(1.1, min(4.2, words / 2.6))
    if visual_style == "conversion":
        return max(1.0, min(1.9, words / 5.0))
    return max(1.4, min(4.6, words / 2.9))


def _split_copy(text: str, max_words: int = 12) -> list[str]:
    words = [w for w in (text or "").split() if w]
    if len(words) <= max_words:
        return [" ".join(words)] if words else []

    chunks: list[str] = []
    for i in range(0, len(words), max_words):
        part = " ".join(words[i : i + max_words]).strip()
        if part:
            chunks.append(part)
    return chunks


def _rebalance_durations(raw: list[float], mins: list[float], target: float) -> list[float]:
    if not raw:
        return []

    total_raw = sum(raw)
    factor = target / total_raw if total_raw > 0 else 1.0
    durations = [max(m, d * factor) for d, m in zip(raw, mins)]

    total = sum(durations)
    if total > target:
        excess = total - target
        for _ in range(36):
            adjustable = [i for i, (d, m) in enumerate(zip(durations, mins)) if d - m > 0.01]
            if not adjustable or excess <= 0.01:
                break

            share = excess / len(adjustable)
            for i in adjustable:
                reducible = max(0.0, durations[i] - mins[i])
                cut = min(reducible, share)
                durations[i] -= cut
                excess -= cut

    total = sum(durations)
    if total < target:
        deficit = target - total
        grow_share = deficit / max(1, len(durations))
        durations = [d + grow_share for d in durations]

    return durations


def _trim_scene_count(scenes: list[StoryboardScene], *, style: str, duration_seconds: int | None) -> list[StoryboardScene]:
    if style == "conversion":
        return scenes

    if duration_seconds:
        if duration_seconds <= 12:
            max_scenes = 8 if style == "dialogo" else 5
        elif duration_seconds <= 25:
            max_scenes = 10 if style == "dialogo" else 7
        elif duration_seconds <= 40:
            max_scenes = 12 if style == "dialogo" else 9
        else:
            max_scenes = 14 if style == "dialogo" else 11
    else:
        max_scenes = 12 if style == "dialogo" else 10

    if len(scenes) <= max_scenes:
        return scenes

    first = scenes[0]
    last = scenes[-1]
    middle = scenes[1:-1]

    keep_middle = max(0, max_scenes - 2)
    if keep_middle <= 0:
        return [first, last]

    if len(middle) <= keep_middle:
        selected_middle = middle
    else:
        step = len(middle) / keep_middle
        selected_middle = []
        pos = 0.0
        for _ in range(keep_middle):
            idx = min(len(middle) - 1, int(pos))
            selected_middle.append(middle[idx])
            pos += step

    return [first] + selected_middle + [last]


def _build_conversion_reel_story(script: VideoScript, hero_asset: AssetItem) -> list[StoryboardScene]:
    # Strict conversion blueprint: 6 blocks, 14 clips, each 1-2s, total ~24.7s.
    stage_specs = [
        ("GANCHO", "¿Te ha fallado un maestro?", 2, 1.0),
        ("DOLOR", "No responde. No llega. Te deja esperando.", 2, 1.5),
        ("FRUSTRACION", "Pierdes tiempo y el problema sigue igual.", 2, 1.5),
        ("SOLUCION", "ConectaProIA por WhatsApp en minutos.", 3, 1.3),
        ("RESULTADO", "Profesional trabajando. Cliente satisfecho.", 4, 1.5),
        (
            "CTA",
            script.sections[-1].onscreen_text if script.sections else "Escríbenos ahora - 100% gratis",
            4,
            1.7,
        ),
    ]

    scenes: list[StoryboardScene] = []
    idx = 1
    for title, text, clips, d in stage_specs:
        for clip_idx in range(clips):
            body = text
            if title == "DOLOR" and clip_idx == 0:
                body = "No responde"
            elif title == "DOLOR" and clip_idx == 1:
                body = "No llega. Te deja esperando"
            elif title == "CTA" and clip_idx == 0:
                body = "Escríbenos ahora - 100% gratis"

            scenes.append(
                StoryboardScene(
                    index=idx,
                    headline=title,
                    body=body,
                    duration_seconds=d,
                    source_image=hero_asset.path,
                    visual_style="conversion",
                )
            )
            idx += 1

    return scenes


def build_storyboard(script: VideoScript, duration_seconds: int | None, hero_asset: AssetItem) -> list[StoryboardScene]:
    scenes: list[StoryboardScene] = []

    if script.style == "conversion":
        scenes = _build_conversion_reel_story(script, hero_asset)
        target = 24.0
    elif script.style == "dialogo" and script.dialogue:
        scenes.append(
            StoryboardScene(
                index=1,
                headline=script.hook,
                body="Conversacion natural entre dos personas",
                duration_seconds=1.6,
                source_image=hero_asset.path,
                visual_style="dialogo",
            )
        )

        idx = 2
        for turn in script.dialogue:
            chunks = _split_copy(turn.line, max_words=14)
            if not chunks:
                chunks = [turn.line]

            for chunk in chunks:
                scenes.append(
                    StoryboardScene(
                        index=idx,
                        headline=turn.speaker,
                        body=chunk,
                        duration_seconds=_estimate_seconds(chunk, "dialogo"),
                        source_image=hero_asset.path,
                        speaker=turn.speaker,
                        visual_style="dialogo",
                    )
                )
                idx += 1

        scenes.append(
            StoryboardScene(
                index=idx,
                headline="Siguiente paso",
                body=script.cta,
                duration_seconds=1.8,
                source_image=hero_asset.path,
                visual_style="dialogo",
            )
        )
        target = float(duration_seconds) if duration_seconds else None

    else:
        scenes.append(
            StoryboardScene(
                index=1,
                headline=script.hook,
                body=script.topic,
                duration_seconds=1.9,
                source_image=hero_asset.path,
                visual_style="promo",
            )
        )

        idx = 2
        for section in script.sections:
            headline = section.title or "Momento"
            primary_line = section.narration or section.onscreen_text
            chunks = _split_copy(primary_line, max_words=13)
            if not chunks:
                chunks = [primary_line]

            for chunk in chunks:
                scenes.append(
                    StoryboardScene(
                        index=idx,
                        headline=headline,
                        body=chunk,
                        duration_seconds=_estimate_seconds(chunk, "promo"),
                        source_image=hero_asset.path,
                        visual_style="promo",
                    )
                )
                idx += 1

        scenes.append(
            StoryboardScene(
                index=idx,
                headline="Siguiente paso",
                body=script.cta,
                duration_seconds=2.0,
                source_image=hero_asset.path,
                visual_style="promo",
            )
        )
        target = float(duration_seconds) if duration_seconds else None

    scenes = _trim_scene_count(scenes, style=script.style, duration_seconds=duration_seconds)

    if script.style == "conversion":
        mins = [1.0 for _ in scenes]
        maxs = [2.0 for _ in scenes]
        raw = [s.duration_seconds for s in scenes]
        balanced = _rebalance_durations(raw, mins, target if target else sum(raw))
        balanced = [min(maxs[i], max(mins[i], d)) for i, d in enumerate(balanced)]
    else:
        mins = [1.0 if s.visual_style == "dialogo" else 1.3 for s in scenes]
        raw = [s.duration_seconds for s in scenes]
        if target:
            balanced = _rebalance_durations(raw, mins, float(target))
        else:
            balanced = [max(m, d) for d, m in zip(raw, mins)]

    normalized: list[StoryboardScene] = []
    for idx, (scene, dur) in enumerate(zip(scenes, balanced), start=1):
        normalized.append(
            StoryboardScene(
                index=idx,
                headline=scene.headline,
                body=scene.body,
                duration_seconds=round(dur, 2),
                source_image=scene.source_image,
                source_video=scene.source_video,
                speaker=scene.speaker,
                visual_style=scene.visual_style,
            )
        )

    return normalized
