from __future__ import annotations

import json
import os
from pathlib import Path

from conecta_video_ai.pipelines import StudioService
from conecta_video_ai.settings import load_settings


def main() -> None:
    categories = ["sincosto", "proveedores", "contacta_profesional"]

    music_root = Path("config/music/story")
    tracks = sorted([p for p in music_root.glob("*.mp3") if p.is_file()], key=lambda p: p.name.lower())
    if len(tracks) < len(categories):
        raise SystemExit(
            f"Se requieren al menos {len(categories)} pistas en {music_root}, encontradas: {len(tracks)}"
        )

    report: list[dict] = []

    for idx, category in enumerate(categories):
        track = tracks[idx]

        os.environ["INSTAGRAM_ENABLE_OPENAI_IMAGES"] = "true"
        os.environ["INSTAGRAM_REQUIRE_AI_IMAGE"] = "true"
        os.environ["INSTAGRAM_SIMULATE_PUBLISH"] = "false"
        os.environ["INSTAGRAM_CROSSPOST_FACEBOOK"] = "true"
        os.environ["INSTAGRAM_MUSIC_USE_LIBRARY_FIRST"] = "true"
        os.environ["INSTAGRAM_MUSIC_FORCE_TRACK"] = track.name

        settings = load_settings()
        service = StudioService(settings)

        row: dict = {
            "category": category,
            "forced_track": track.name,
            "ok": False,
        }
        try:
            cycle = service.run_instagram_auto_cycle(
                objective=None,
                force_category=category,
                publish=True,
                simulate_publish=False,
                use_meta_history=False,
                public_image_url=None,
            )
            draft = cycle.get("draft") or {}
            row.update(
                {
                    "ok": True,
                    "draft_id": draft.get("draft_id"),
                    "image_source": draft.get("image_source"),
                    "asset_rel_path": draft.get("asset_rel_path"),
                    "video_music_source": draft.get("video_music_source"),
                    "video_music_path": draft.get("video_music_path"),
                    "instagram_channel": draft.get("published_channel"),
                    "instagram_post_id": draft.get("post_id"),
                    "instagram_post_url": draft.get("post_url"),
                    "facebook_publication": draft.get("facebook_publication"),
                    "facebook_story": draft.get("facebook_story"),
                }
            )
        except Exception as exc:  # noqa: BLE001
            row["error"] = str(exc)

        report.append(row)

    out_path = Path("output/runs/instagram/triple_forced_publish_report.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "report_file": str(out_path), "items": report}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
