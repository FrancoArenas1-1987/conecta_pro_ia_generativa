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

from conecta_video_ai.publication_checks import validate_caption, validate_images, DISCLAIMER, FREE_SEARCH, editorial_copy
from conecta_video_ai.campaign_queue import atomic_json
from conecta_video_ai.instagram_graph_publisher import InstagramGraphPublisher
from conecta_video_ai.publish_schedule import publish_window_status
from conecta_video_ai.settings import load_settings
from conecta_video_ai.publication_supply import synchronize_registry, assert_services
from conecta_video_ai.service_images import read_registry, approved_paths, canonical
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
        "categories": ["kinesiologia", "medico_veterinario", "dentista"],
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


def _font_paths(*, bold: bool = False) -> list[Path]:
    filename = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    env_dirs = [Path(x) for x in str(os.getenv("IG_FONT_DIRS") or "").split(os.pathsep) if x.strip()]
    font_dirs = [
        *env_dirs,
        Path("/usr/share/fonts/truetype/dejavu"),
        Path("/usr/share/fonts/truetype/liberation2"),
        Path("/usr/local/share/fonts"),
    ]
    windows_name = "arialbd.ttf" if bold else "arial.ttf"
    segoe_name = "segoeuib.ttf" if bold else "segoeui.ttf"
    return [
        Path(r"C:\Windows\Fonts") / windows_name,
        Path(r"C:\Windows\Fonts") / segoe_name,
        *[font_dir / filename for font_dir in font_dirs],
    ]


def font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    seen: set[str] = set()
    for candidate in _font_paths(bold=bold):
        if not str(candidate):
            continue
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        if not candidate.exists():
            continue
        try:
            return ImageFont.truetype(str(candidate), size=size)
        except OSError:
            continue

    # Last chance: Pillow/fontconfig can resolve these by family name on some Linux images.
    for name in (("DejaVuSans-Bold.ttf", "Arial Bold.ttf") if bold else ("DejaVuSans.ttf", "Arial.ttf")):
        try:
            return ImageFont.truetype(name, size=size)
        except OSError:
            continue
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
    registry = read_registry(INSTAGRAM_STATE_PATH.parent / "catalog" / "service_images.json")
    if registry:
        return {code: [path] for code, path in approved_paths(registry, assets_root).items()}
    raise RuntimeError("No approved service registry; carousel publication blocked")


def choose_theme(grouped: dict[str, list[Path]], *, force_theme: str | None = None) -> dict[str, Any]:
    state = read_json(STATE_PATH, {})
    recent = list(state.get("recent_themes") or []) if isinstance(state, dict) else []
    dynamic_theme = build_recent_services_theme(grouped)
    canonical_themes = [{**theme, "categories": list(dict.fromkeys(canonical(c) for c in theme["categories"]))} for theme in THEMES]
    candidates = [dynamic_theme, *canonical_themes] if dynamic_theme is not None else canonical_themes
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
    if scored[0][1] < 3:
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
    service_names = ", ".join(editorial_copy(x.label) for x in services)
    whatsapp_phone = extract_whatsapp_phone(whatsapp_url)
    hashtags_list = ["#conectaproia", "#profesionales", "#whatsapp", "#chile", *theme["hashtags"]]
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
            editorial_copy(theme["caption_intro"]),
            "",
            f"En este carrusel: {service_names}.",
            "ConectaProIA te ayuda a encontrar contactos en Chile.",
            FREE_SEARCH,
            DISCLAIMER,
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
    if STATE_PATH.with_name("carousel_pending.json").exists():
        return True, {"ok": False, "skipped": True, "reason": "carousel_requires_manual_reconciliation"}
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
    caption = str(manifest.get("caption") or "")
    content_qc = validate_caption(caption, whatsapp_url=settings.instagram_whatsapp_client_url)
    slides = [Path(x) for x in manifest.get("slides") or []]
    if len(slides) != 5:
        raise RuntimeError("Carousel requires a cover, three services and a CTA")
    media_qc = validate_images(slides, size=(W, H))
    approved = load_assets(Path(manifest["assets_root"]))
    allowed_categories = {canonical(c) for c in manifest.get("theme", {}).get("categories", [])}
    for service in manifest.get("services", []):
        code = canonical(service["category_id"])
        source = Path(service["image_path"]).resolve()
        if code not in allowed_categories or source not in {p.resolve() for p in approved.get(code, [])}:
            raise RuntimeError("Carousel source is unapproved or outside its theme")
    if len(manifest.get("services", [])) != 3:
        raise RuntimeError("Carousel must contain exactly three approved services")
    supply_check = assert_services([s["category_id"] for s in manifest["services"]])
    manifest["supply_check"] = supply_check
    pending = STATE_PATH.with_name("carousel_pending.json")
    if pending.exists():
        raise RuntimeError("Carousel has an unresolved publication; manual reconciliation required")
    publisher = InstagramGraphPublisher(settings)
    identity = publisher.inspect_page_identity()
    if identity.get("linked_instagram_user_id") != publisher.ig_user_id:
        raise RuntimeError("Carousel Instagram destination does not match its Facebook page")
    run_dir = slides[0].parent
    journal = {"run_id": manifest.get("run_id"), "manifest": str(run_dir / "manifest.json"),
               "status": "staging", "created_at": now_iso(), "deliveries": {}}
    def save():
        manifest["publication_journal"] = journal
        atomic_json(pending, journal)
        atomic_json(run_dir / "manifest.json", manifest)
    save()
    try:
        public_urls = [publisher.stage_local_image_for_public_url(image_path=p, caption=caption) for p in slides]
        results = {}
        jobs = [("instagram", lambda: publisher.publish_carousel_post(image_urls=public_urls, caption=caption))]
        if bool(settings.instagram_crosspost_facebook):
            jobs.append(("facebook", lambda: publisher.publish_facebook_multi_photo(image_urls=public_urls, caption=caption)))
        for channel, send in jobs:
            journal["status"] = "publishing"
            journal["deliveries"][channel] = {"status": "sending"}
            save()
            receipt = send()
            if not receipt.get("post_id"):
                raise RuntimeError("Carousel publisher returned no publication id")
            results[channel] = receipt
            journal["deliveries"][channel] = {"status": "published", "receipt": receipt}
            save()
        result = {"ok": True, "status": "published", "published_at": now_iso(),
                  "public_urls": public_urls, "instagram": results["instagram"],
                  "facebook": results.get("facebook", {"status": "skipped"}),
                  "content_qc": content_qc, "media_qc": media_qc}
        manifest.update(result)
        journal["status"] = "published"
        save()
        state = read_json(STATE_PATH, {})
        recent = list(state.get("recent_themes") or [])
        recent.append((manifest.get("theme") or {}).get("id"))
        state.update(last_published_at=result["published_at"], last_run_id=manifest.get("run_id"),
                     last_theme=(manifest.get("theme") or {}).get("id"), last_result=result,
                     recent_themes=recent[-12:])
        atomic_json(STATE_PATH, state)
        pending.unlink()
        return result
    except Exception:
        journal["status"] = "requires_review" if journal["deliveries"] else "failed_before_publish"
        save()
        if not journal["deliveries"]:
            pending.unlink()
        raise


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
        settings = load_settings()
        schedule_status = publish_window_status(
            enabled=bool(settings.instagram_publish_time_window_enabled),
            timezone_name=str(settings.instagram_publish_timezone),
            allowed_windows=str(settings.instagram_publish_allowed_windows),
        )
        if not bool(schedule_status.get("allowed", False)):
            print(
                json.dumps(
                    {
                        "ok": True,
                        "skipped": True,
                        "reason": str(schedule_status.get("reason") or "publish_time_window_closed"),
                        "schedule": schedule_status,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return
        skipped, payload = should_skip(int(args.interval_hours), force=bool(args.force))
        if skipped and payload is not None:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return
    if args.publish:
        synchronize_registry(INSTAGRAM_STATE_PATH.parent / "catalog/service_images.json")
    manifest = build_carousel(force_theme=args.theme)
    if not args.publish:
        print(json.dumps({"ok": True, "published": False, "preview_dir": str(Path(manifest["slides"][0]).parent), "manifest": manifest}, ensure_ascii=False, indent=2))
        return
    result = publish_carousel(manifest)
    print(json.dumps({"ok": True, "preview_dir": str(Path(manifest["slides"][0]).parent), "publication": result}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
