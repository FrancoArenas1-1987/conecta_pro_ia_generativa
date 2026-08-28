from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from conecta_video_ai.instagram_graph_publisher import InstagramGraphPublisher
from conecta_video_ai.settings import load_settings
from conecta_video_ai.whatsapp_links import extract_whatsapp_phone, normalize_whatsapp_click_url

W, H = 1080, 1350
OUTPUT_ROOT = PROJECT_ROOT / "output" / "runs" / "instagram" / "carousels"
STATE_PATH = PROJECT_ROOT / "output" / "runs" / "instagram" / "carousel_state.json"
INSTAGRAM_STATE_PATH = PROJECT_ROOT / "output" / "runs" / "instagram" / "state.json"


@dataclass(frozen=True)
class ServiceSlide:
    category_id: str
    label: str
    title: str
    body: str
    image_path: Path


THEMES: list[dict[str, Any]] = [
    {
        "id": "hogar",
        "title": "Servicios utiles para tu hogar",
        "subtitle": "Coordina opciones por WhatsApp en todo Chile.",
        "categories": ["electricidad", "gasfiteria", "aire_acondicionado_calefaccion"],
        "caption_intro": "Tres necesidades comunes del hogar, en un solo lugar.",
        "hashtags": ["#servicioshogar", "#electricidad", "#gasfiteria", "#climatizacion"],
    },
    {
        "id": "salud_mascotas",
        "title": "Cuidado para personas y mascotas",
        "subtitle": "Encuentra orientacion y opciones disponibles por WhatsApp.",
        "categories": ["kinesiologia", "medico_veterinario", "veterinarios"],
        "caption_intro": "Salud, recuperacion y cuidado de mascotas con una coordinacion simple.",
        "hashtags": ["#kinesiologia", "#veterinaria", "#cuidadodemascotas"],
    },
    {
        "id": "comida_local",
        "title": "Comida local para resolver el dia",
        "subtitle": "Opciones para pedir, coordinar o cotizar por WhatsApp.",
        "categories": ["comida_pizzeria", "comida_sushi", "comida_sandwiches_completos"],
        "caption_intro": "Ideas simples para comer rico sin perder tiempo buscando.",
        "hashtags": ["#comidalocal", "#pizzeria", "#sushi", "#sandwiches"],
    },
    {
        "id": "profesionales",
        "title": "Apoyo profesional cuando lo necesitas",
        "subtitle": "Legal, traduccion y software con contacto directo.",
        "categories": ["legal", "traductores_ingles_espanol", "desarrollo_software"],
        "caption_intro": "Servicios profesionales para avanzar con menos friccion.",
        "hashtags": ["#serviciosprofesionales", "#legal", "#traduccion", "#software"],
    },
]

RECENT_SERVICES_THEME_ID = "servicios_recientes"

SERVICE_COPY: dict[str, tuple[str, str, str]] = {
    "aire_acondicionado_calefaccion": (
        "Climatizacion",
        "Aire acondicionado y calefaccion",
        "Instalacion, mantencion o reparacion segun tu necesidad.",
    ),
    "comida_pizzeria": ("Pizzeria", "Pizza local", "Opciones para pedir o coordinar por WhatsApp."),
    "comida_preparada_restaurante": (
        "Comida preparada",
        "Restaurantes y comida diaria",
        "Alternativas para resolver almuerzo, cena o pedidos.",
    ),
    "comida_sandwiches_completos": (
        "Sandwiches",
        "Sandwiches y completos",
        "Comida rapida, practica y cercana.",
    ),
    "comida_sushi": ("Sushi", "Sushi y rolls", "Opciones para cotizar o pedir en tu zona."),
    "desarrollo_software": (
        "Software",
        "Sitios y sistemas",
        "Apoyo para automatizar, ordenar o crear herramientas digitales.",
    ),
    "electricidad": (
        "Electricidad",
        "Electricistas y reparaciones",
        "Fallas, enchufes, luces y urgencias del hogar.",
    ),
    "gasfiteria": (
        "Gasfiteria",
        "Fugas y reparaciones",
        "Filtraciones, calefon, llaves y mantenciones.",
    ),
    "kinesiologia": (
        "Kinesiologia",
        "Apoyo kinesico",
        "Rehabilitacion, domicilio y necesidades puntuales.",
    ),
    "legal": ("Legal", "Asesoria legal", "Contratos, dudas y orientacion practica."),
    "medico_veterinario": (
        "Medico veterinario",
        "Atencion para mascotas",
        "Controles, vacunas y orientacion segun sintomas.",
    ),
    "traductores_ingles_espanol": (
        "Traduccion",
        "Ingles y espanol",
        "Textos, documentos y contenido bilingue.",
    ),
    "veterinarios": (
        "Veterinarios",
        "Cuidado animal",
        "Opciones para controles y necesidades de tu mascota.",
    ),
}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_utc(value: str) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def read_json(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        Path(r"C:\Windows\Fonts\arialbd.ttf") if bold else Path(r"C:\Windows\Fonts\arial.ttf"),
        Path(r"C:\Windows\Fonts\segoeuib.ttf") if bold else Path(r"C:\Windows\Fonts\segoeui.ttf"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default()


def wrap_text(draw: ImageDraw.ImageDraw, text: str, fnt: ImageFont.ImageFont, max_width: int) -> list[str]:
    words = str(text or "").split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = word if not current else f"{current} {word}"
        bbox = draw.textbbox((0, 0), candidate, font=fnt)
        if bbox[2] - bbox[0] <= max_width:
            current = candidate
            continue
        if current:
            lines.append(current)
        current = word
    if current:
        lines.append(current)
    return lines


def draw_wrapped(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    fnt: ImageFont.ImageFont,
    *,
    fill: tuple[int, int, int] | tuple[int, int, int, int],
    max_width: int,
    line_gap: int,
) -> int:
    x, y = xy
    for line in wrap_text(draw, text, fnt, max_width):
        draw.text((x, y), line, font=fnt, fill=fill)
        bbox = draw.textbbox((x, y), line, font=fnt)
        y = bbox[3] + line_gap
    return y


def fit_cover(path: Path, size: tuple[int, int] = (W, H)) -> Image.Image:
    with Image.open(path) as img:
        image = img.convert("RGB")
    src_w, src_h = image.size
    dst_w, dst_h = size
    scale = max(dst_w / src_w, dst_h / src_h)
    resized = image.resize((int(src_w * scale), int(src_h * scale)), Image.Resampling.LANCZOS)
    left = max(0, (resized.width - dst_w) // 2)
    top = max(0, (resized.height - dst_h) // 2)
    return resized.crop((left, top, left + dst_w, top + dst_h))


def overlay(base: Image.Image, alpha: int = 120) -> Image.Image:
    dark = Image.new("RGBA", base.size, (14, 21, 28, alpha))
    return Image.alpha_composite(base.convert("RGBA"), dark)


def detect_category(path: Path, *, assets_root: Path | None = None) -> str:
    if assets_root is not None:
        try:
            rel_parts = path.resolve().relative_to(assets_root.resolve()).parts
        except Exception:
            rel_parts = ()
        if len(rel_parts) >= 3 and rel_parts[1].lower() in {"images", "videos", "audios"}:
            return rel_parts[0]

    name = path.stem.lower()
    checks = [
        "aire_acondicionado_calefaccion",
        "comida_sandwiches_completos",
        "comida_preparada_restaurante",
        "traductores_ingles_espanol",
        "medico_veterinario",
        "desarrollo_software",
        "comida_pizzeria",
        "comida_sushi",
        "electricidad",
        "gasfiteria",
        "kinesiologia",
        "veterinarios",
        "legal",
    ]
    for category in checks:
        if name.startswith(category):
            return category
    return name.split("_01", 1)[0]


def load_assets(assets_root: Path) -> dict[str, list[Path]]:
    grouped: dict[str, list[Path]] = {}
    for path in sorted(assets_root.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
            continue
        grouped.setdefault(detect_category(path, assets_root=assets_root), []).append(path)
    for paths in grouped.values():
        paths.sort(key=lambda p: (p.stat().st_mtime_ns, p.name.lower()), reverse=True)
    return grouped


def choose_theme(grouped: dict[str, list[Path]], *, force_theme: str | None = None) -> dict[str, Any]:
    state = read_json(STATE_PATH, {})
    recent = list(state.get("recent_themes") or []) if isinstance(state, dict) else []
    dynamic_theme = build_recent_services_theme(grouped)
    candidates = [dynamic_theme, *THEMES] if dynamic_theme is not None else THEMES
    if force_theme:
        candidates = [theme for theme in candidates if theme["id"] == force_theme]
    if not candidates:
        raise RuntimeError(f"Tema desconocido: {force_theme}")

    scored: list[tuple[int, int, int, int, dict[str, Any]]] = []
    for idx, theme in enumerate(candidates):
        available = sum(1 for cat in theme["categories"] if grouped.get(cat))
        recent_penalty = recent.index(theme["id"]) + 1 if theme["id"] in recent else 0
        fresh_bonus = 1 if theme["id"] == RECENT_SERVICES_THEME_ID and recent_penalty == 0 else 0
        scored.append((fresh_bonus, min(available, 3), -recent_penalty, -idx, theme | {"_index": idx}))
    scored.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
    best = scored[0][4]
    if scored[0][1] < 2:
        raise RuntimeError("No hay suficientes imagenes para armar un carrusel coherente")
    return best


def build_recent_services_theme(grouped: dict[str, list[Path]]) -> dict[str, Any] | None:
    newest_by_category: list[tuple[int, str]] = []
    for category, images in grouped.items():
        if not images:
            continue
        newest = max((p.stat().st_mtime_ns for p in images if p.exists()), default=0)
        if newest:
            newest_by_category.append((newest, category))
    newest_by_category.sort(reverse=True)
    categories = [category for _mtime, category in newest_by_category[:3]]
    if len(categories) < 3:
        return None
    return {
        "id": RECENT_SERVICES_THEME_ID,
        "title": "Servicios recientes disponibles",
        "subtitle": "Nuevas opciones para coordinar por WhatsApp.",
        "categories": categories,
        "caption_intro": "Nuevos servicios activos para resolver necesidades reales.",
        "hashtags": ["#servicioslocales", "#conectaproia", "#whatsapp"],
    }


def default_service_copy(category: str) -> tuple[str, str, str]:
    label = category.replace("_", " ").title()
    return (
        label,
        label,
        "Opciones disponibles para coordinar por WhatsApp.",
    )


def choose_services(theme: dict[str, Any], grouped: dict[str, list[Path]], *, count: int = 3) -> list[ServiceSlide]:
    services: list[ServiceSlide] = []
    for category in theme["categories"]:
        images = grouped.get(category) or []
        if not images:
            continue
        label, title, body = SERVICE_COPY.get(category, default_service_copy(category))
        services.append(ServiceSlide(category, label, title, body, images[0]))
    if len(services) < count:
        used = {x.category_id for x in services}
        for category, images in sorted(grouped.items()):
            if category in used or not images:
                continue
            label, title, body = SERVICE_COPY.get(category, default_service_copy(category))
            services.append(ServiceSlide(category, label, title, body, images[0]))
            if len(services) >= count:
                break
    return services[:count]


def save_jpg(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(path, "JPEG", quality=92, optimize=True)


def render_cover(theme: dict[str, Any], services: list[ServiceSlide], output: Path) -> None:
    img = Image.new("RGBA", (W, H), (18, 31, 39, 255))
    draw = ImageDraw.Draw(img)
    draw.rectangle((72, 82, 1008, 118), fill=(117, 222, 188, 255))
    draw.text((72, 156), "ConectaProIA", font=font(44, bold=True), fill=(255, 255, 255, 255))
    y = draw_wrapped(
        draw,
        (72, 320),
        str(theme["title"]),
        font(76, bold=True),
        fill=(255, 255, 255, 255),
        max_width=880,
        line_gap=12,
    )
    draw_wrapped(
        draw,
        (72, y + 24),
        str(theme["subtitle"]),
        font(38),
        fill=(235, 244, 247, 255),
        max_width=860,
        line_gap=10,
    )
    thumb_y = 790
    thumb_w = 292
    thumb_h = 330
    gap = 26
    for idx, service in enumerate(services[:3]):
        thumb = fit_cover(service.image_path, (thumb_w, thumb_h)).convert("RGBA")
        x = 72 + idx * (thumb_w + gap)
        img.alpha_composite(thumb, (x, thumb_y))
        draw.rectangle((x, thumb_y, x + thumb_w, thumb_y + thumb_h), outline=(255, 255, 255, 190), width=3)
        draw.text((x, thumb_y + thumb_h + 18), service.label, font=font(28, bold=True), fill=(255, 255, 255, 255))
    draw.rectangle((72, 1210, 1008, 1284), fill=(255, 255, 255, 235))
    draw.text((108, 1230), "Desliza para ver opciones", font=font(34, bold=True), fill=(19, 35, 45, 255))
    save_jpg(img, output)


def render_service(slide: ServiceSlide, index: int, output: Path) -> None:
    save_jpg(fit_cover(slide.image_path), output)


def render_cta(theme: dict[str, Any], services: list[ServiceSlide], output: Path) -> None:
    img = Image.new("RGBA", (W, H), (18, 31, 39, 255))
    draw = ImageDraw.Draw(img)
    for idx, service in enumerate(services[:3]):
        thumb = fit_cover(service.image_path, (260, 260)).convert("RGBA")
        x = 72 + idx * 318
        img.alpha_composite(thumb, (x, 110))
        draw.rectangle((x, 110, x + 260, 370), outline=(255, 255, 255, 180), width=3)
    draw.text((72, 470), "ConectaProIA", font=font(44, bold=True), fill=(117, 222, 188, 255))
    y = draw_wrapped(
        draw,
        (72, 610),
        "Necesitas ayuda para encontrar opciones?",
        font(66, bold=True),
        fill=(255, 255, 255, 255),
        max_width=900,
        line_gap=12,
    )
    draw_wrapped(
        draw,
        (72, y + 28),
        "Escribenos por WhatsApp y cuentanos que necesitas.",
        font(38),
        fill=(235, 244, 247, 255),
        max_width=860,
        line_gap=10,
    )
    draw.rectangle((72, 1086, 1008, 1238), fill=(255, 255, 255, 238))
    draw.text((112, 1122), "WhatsApp: +56 9 8343 4503", font=font(34, bold=True), fill=(19, 35, 45, 255))
    draw.text((112, 1184), "conectaproia.cl", font=font(34), fill=(19, 35, 45, 255))
    save_jpg(img, output)


def build_caption(theme: dict[str, Any], services: list[ServiceSlide], *, whatsapp_url: str) -> str:
    service_names = ", ".join(x.label for x in services)
    whatsapp_phone = extract_whatsapp_phone(whatsapp_url)
    hashtags_list = ["#conectaproia", "#profesionalesconfiables", "#whatsapp", "#chile", *theme["hashtags"]]
    seen_tags: set[str] = set()
    clean_tags: list[str] = []
    for tag in hashtags_list:
        key = str(tag).strip().lower()
        if key and key not in seen_tags:
            seen_tags.add(key)
            clean_tags.append(str(tag).strip())
    hashtags = " ".join(clean_tags)
    return "\n".join(
        [
            str(theme["caption_intro"]),
            "",
            f"En este carrusel: {service_names}.",
            "ConectaProIA te ayuda a coordinar opciones disponibles en Chile.",
            "",
            f"WhatsApp: {whatsapp_phone or whatsapp_url}",
            f"Link directo: {whatsapp_url}",
            "Web: https://conectaproia.cl",
            "",
            hashtags,
        ]
    )


def build_carousel(*, force_theme: str | None = None) -> dict[str, Any]:
    settings = load_settings()
    whatsapp_url = normalize_whatsapp_click_url(settings.instagram_whatsapp_client_url)
    assets_root = Path(settings.instagram_publish_assets_root)
    if not assets_root.is_absolute():
        assets_root = PROJECT_ROOT / assets_root
    grouped = load_assets(assets_root)
    theme = choose_theme(grouped, force_theme=force_theme)
    services = choose_services(theme, grouped)
    if len(services) < 3:
        raise RuntimeError("No hay servicios suficientes para carrusel de 5 slides")

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S") + f"_{theme['id']}"
    run_dir = OUTPUT_ROOT / run_id
    slide_paths = [
        run_dir / "slide_01_cover.jpg",
        run_dir / "slide_02_service.jpg",
        run_dir / "slide_03_service.jpg",
        run_dir / "slide_04_service.jpg",
        run_dir / "slide_05_cta.jpg",
    ]
    render_cover(theme, services, slide_paths[0])
    for idx, service in enumerate(services[:3], start=2):
        render_service(service, idx - 1, slide_paths[idx - 1])
    render_cta(theme, services, slide_paths[4])

    caption = build_caption(theme, services, whatsapp_url=whatsapp_url)
    (run_dir / "caption.txt").write_text(caption, encoding="utf-8")
    manifest = {
        "run_id": run_id,
        "created_at": now_iso(),
        "status": "draft",
        "theme": {k: v for k, v in theme.items() if not k.startswith("_")},
        "services": [
            {
                **asdict(service),
                "image_path": str(service.image_path),
            }
            for service in services
        ],
        "slides": [str(path) for path in slide_paths],
        "caption": caption,
        "assets_root": str(assets_root),
        "whatsapp_url": whatsapp_url,
    }
    write_json(run_dir / "manifest.json", manifest)
    return manifest


def should_skip(interval_hours: int, *, force: bool = False) -> tuple[bool, dict[str, Any] | None]:
    if force or interval_hours <= 0:
        return False, None
    state = read_json(STATE_PATH, {})
    last_at = parse_utc(str((state or {}).get("last_published_at") or ""))
    if last_at is None:
        return False, None
    next_allowed = last_at + timedelta(hours=interval_hours)
    now = datetime.now(timezone.utc)
    if now >= next_allowed:
        return False, None
    return True, {
        "ok": True,
        "skipped": True,
        "reason": "carousel_interval_guard_active",
        "last_published_at": last_at.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "next_allowed_at": next_allowed.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "remaining_minutes": max(1, int((next_allowed - now).total_seconds() // 60)),
    }


def publish_carousel(manifest: dict[str, Any]) -> dict[str, Any]:
    settings = load_settings()
    publisher = InstagramGraphPublisher(settings)
    slides = [Path(x) for x in manifest.get("slides") or []]
    public_urls = [
        publisher.stage_local_image_for_public_url(image_path=slide, caption=str(manifest.get("caption") or ""))
        for slide in slides
    ]
    ig = publisher.publish_carousel_post(image_urls=public_urls, caption=str(manifest.get("caption") or ""))
    fb: dict[str, Any] = {"status": "skipped", "reason": "instagram_crosspost_facebook_disabled"}
    if bool(settings.instagram_crosspost_facebook):
        fb = publisher.publish_facebook_multi_photo(image_urls=public_urls, caption=str(manifest.get("caption") or ""))
    result = {
        "ok": True,
        "status": "published",
        "published_at": now_iso(),
        "public_urls": public_urls,
        "instagram": ig,
        "facebook": fb,
    }
    run_dir = Path(str(manifest["slides"][0])).parent
    manifest.update(result)
    write_json(run_dir / "manifest.json", manifest)
    state = read_json(STATE_PATH, {})
    state.update(
        {
            "last_published_at": result["published_at"],
            "last_run_id": manifest.get("run_id"),
            "last_theme": (manifest.get("theme") or {}).get("id"),
            "last_result": result,
            "recent_themes": [*((state.get("recent_themes") or []) if isinstance(state, dict) else [])],
        }
    )
    theme_id = str((manifest.get("theme") or {}).get("id") or "")
    recent = [theme_id, *[x for x in state.get("recent_themes", []) if x != theme_id]][:8]
    state["recent_themes"] = recent
    write_json(STATE_PATH, state)

    ig_state = read_json(INSTAGRAM_STATE_PATH, {})
    if isinstance(ig_state, dict):
        ig_state["last_sequence_published_at"] = result["published_at"]
        write_json(INSTAGRAM_STATE_PATH, ig_state)
    return result


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env", override=True)
    parser = argparse.ArgumentParser(description="Genera/publica un carrusel IG/FB desde imagenes_ig.")
    parser.add_argument("--publish", action="store_true", help="Publica en IG/FB. Sin esto solo genera preview local.")
    parser.add_argument("--force", action="store_true", help="Ignora guardia de intervalo entre carruseles.")
    parser.add_argument("--theme", default=None, help="Tema exacto: hogar, salud_mascotas, comida_local, profesionales.")
    parser.add_argument(
        "--interval-hours",
        type=int,
        default=int(os.getenv("IG_CAROUSEL_INTERVAL_HOURS", "48")),
        help="Horas minimas entre carruseles publicados.",
    )
    args = parser.parse_args()

    os.chdir(PROJECT_ROOT)
    if args.publish:
        skipped, payload = should_skip(int(args.interval_hours), force=bool(args.force))
        if skipped and payload is not None:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return
    manifest = build_carousel(force_theme=args.theme)
    if not args.publish:
        print(json.dumps({"ok": True, "published": False, "preview_dir": str(Path(manifest["slides"][0]).parent), "manifest": manifest}, ensure_ascii=False, indent=2))
        return
    result = publish_carousel(manifest)
    print(json.dumps({"ok": True, "preview_dir": str(Path(manifest["slides"][0]).parent), "publication": result}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
