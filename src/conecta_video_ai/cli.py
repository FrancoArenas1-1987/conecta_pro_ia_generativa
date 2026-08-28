from __future__ import annotations

import argparse
import json
from pathlib import Path

from .exceptions import ConectaVideoError
from .models import CampaignRequest, ImageRequest, VideoRequest
from .pipelines import StudioService
from .settings import load_settings


def _read_topics(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.strip().startswith("#")]


def _infer_style_from_text(text: str) -> str:
    low = text.lower()
    if any(m in low for m in ["reel", "tiktok", "instagram", "viral", "conversion"]):
        return "conversion"
    markers = ["dialogo", "conversacion", "chat", "dos personas", "hablando", "roleplay"]
    return "dialogo" if any(m in low for m in markers) else "promo"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ConectaProIA Studio: genera imagenes, videos y campanas")
    sub = parser.add_subparsers(dest="command", required=True)

    video = sub.add_parser("video", help="Generar un video")
    video.add_argument("--topic", type=str, help="Tema/contexto del video")
    video.add_argument("--topics-file", type=Path, help="Archivo con temas (1 por linea)")
    video.add_argument("--no-tts", action="store_true")
    video.add_argument("--no-music", action="store_true")
    video.add_argument("--style", choices=["promo", "dialogo", "conversion", "auto"], default="auto")
    video.add_argument("--dialogue-seed", type=str, default=None, help="Dialogo base opcional para orientar la IA")
    video.add_argument("--auto-idea", action="store_true", help="Genera idea/contexto automaticamente")
    video.add_argument("--engine", choices=["studio", "comfyui"], default=None, help="Motor de video")
    video.add_argument("--objective", choices=["captar_clientes", "captar_proveedores", "branding"], default=None)
    video.add_argument(
        "--variants",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Activar exploracion de variantes de hook/narrativa/CTA",
    )
    video.add_argument(
        "--openai-images",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Usar OpenAI para generar imagenes por escena (requiere OPENAI_API_KEY)",
    )

    image = sub.add_parser("image", help="Generar una imagen")
    image.add_argument("--context", required=True, type=str, help="Contexto/brief creativo")
    image.add_argument("--service", required=True, type=str, help="Servicio/profesional objetivo")
    image.add_argument("--width", type=int, default=1080)
    image.add_argument("--height", type=int, default=1350)

    campaign = sub.add_parser("campaign", help="Generar campana de multiples videos")
    campaign.add_argument("--config", type=Path, required=True, help="JSON de campana")

    ig_auto = sub.add_parser("ig-auto", help="Ejecuta 1 ciclo automatico de contenido IG")
    ig_auto.add_argument("--objective", choices=["captar_clientes", "captar_proveedores", "branding"], default=None)
    ig_auto.add_argument("--category", type=str, default=None, help="Categoria forzada (ej: gasfiteria)")
    ig_auto.add_argument(
        "--publish",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Publicar al terminar ciclo",
    )
    ig_auto.add_argument("--real-publish", action="store_true", help="Publicar real en Instagram (requiere URL publica de imagen)")
    ig_auto.add_argument("--public-image-url", type=str, default=None, help="URL publica forzada para publicar imagen del borrador")
    ig_auto.add_argument("--public-video-url", type=str, default=None, help="URL publica forzada para publicar video del borrador")

    ig_auto.add_argument(
        "--use-meta-history",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Usar ultimas publicaciones de IG para rotacion",
    )

    ig_list = sub.add_parser("ig-list", help="Lista borradores IG locales")
    ig_list.add_argument("--limit", type=int, default=20)

    ig_catalog = sub.add_parser("ig-catalog", help="Reconstruye catalogo de categorias desde IG + local")
    ig_assets = sub.add_parser("ig-assets-sync", help="Sincroniza drafts a biblioteca (images/videos) y reindexa catalogo")

    ig_catalog.add_argument(
        "--use-meta-history",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Consultar historial remoto de Instagram",
    )

    ig_plan = sub.add_parser("ig-plan", help="Muestra plan de publicaciones automaticas")
    ig_plan.add_argument("--hours", type=int, default=None)

    ig_publish = sub.add_parser("ig-publish", help="Publica un borrador IG (simulado o real)")
    ig_publish.add_argument("--draft-id", required=True, type=str)
    ig_publish.add_argument("--real", action="store_true", help="Publicar de forma real en Instagram")
    ig_publish.add_argument("--public-image-url", type=str, default=None, help="URL publica forzada para publicar imagen")
    ig_publish.add_argument("--public-video-url", type=str, default=None, help="URL publica forzada para publicar video")

    return parser


def run(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    settings = load_settings()
    service = StudioService(settings)

    try:
        if args.command == "video":
            enable_tts = settings.enable_tts and not args.no_tts
            enable_music = settings.enable_background_music and not args.no_music
            engine = args.engine or settings.video_engine

            topics: list[str] = []
            if args.topic:
                topics = [args.topic]
            elif args.topics_file:
                topics = _read_topics(args.topics_file)
            elif args.auto_idea:
                topics = [""]
            else:
                parser.error("video requiere --topic o --topics-file o --auto-idea")

            for topic in topics:
                style = args.style
                if style == "auto":
                    style = _infer_style_from_text(f"{topic} {args.dialogue_seed or ''}")

                output = service.create_video(
                    VideoRequest(
                        topic=topic,
                        duration_seconds=None,
                        enable_tts=enable_tts,
                        enable_music=enable_music,
                        style=style,
                        dialogue_seed=args.dialogue_seed,
                        auto_idea=args.auto_idea,
                        use_openai_images=args.openai_images,
                        engine=engine,
                        objective=args.objective,
                        enable_variant_exploration=bool(args.variants),
                    )
                )
                print(f"[OK] Video: {output.main_file}")

            return 0

        if args.command == "campaign":
            payload = json.loads(args.config.read_text(encoding="utf-8-sig"))
            if not isinstance(payload, dict):
                raise ConectaVideoError("El archivo de campana debe contener un objeto JSON")

            result = service.create_campaign(payload)
            print(f"[OK] Campana: {result.campaign_name} | Videos: {result.summary.get('total_videos')}")
            for item in result.generated_runs:
                print(f"  - {item.get('run_id')}: {item.get('file')}")
            return 0

        if args.command == "ig-catalog":
            catalog = service.build_instagram_catalog(use_meta_history=bool(args.use_meta_history))
            print(json.dumps(catalog, ensure_ascii=False, indent=2))
            return 0

        if args.command == "ig-assets-sync":
            report = service.sync_instagram_assets()
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0

        if args.command == "ig-list":
            rows = service.list_instagram_drafts(limit=max(1, args.limit))
            print(json.dumps({"count": len(rows), "items": rows}, ensure_ascii=False, indent=2))
            return 0

        if args.command == "ig-plan":
            plan = service.get_instagram_plan(horizon_hours=args.hours)
            print(json.dumps(plan, ensure_ascii=False, indent=2))
            return 0
        if args.command == "ig-auto":
            result = service.run_instagram_auto_cycle(
                objective=args.objective,
                force_category=args.category,
                publish=bool(args.publish),
                simulate_publish=not bool(args.real_publish),
                use_meta_history=bool(args.use_meta_history),
                public_image_url=args.public_image_url,
                public_video_url=args.public_video_url,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0

        if args.command == "ig-publish":
            draft = service.publish_instagram_draft(
                draft_id=args.draft_id,
                simulate=not bool(args.real),
                public_image_url=args.public_image_url,
                public_video_url=args.public_video_url,
            )
            print(json.dumps({"ok": True, "draft": draft}, ensure_ascii=False, indent=2))
            return 0

        output = service.create_image(
            ImageRequest(
                context=args.context,
                service=args.service,
                width=args.width,
                height=args.height,
            )
        )
        print(f"[OK] Image: {output.main_file}")
        return 0

    except ConectaVideoError as exc:
        print(f"[ERROR] {exc}")
        return 1


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()






