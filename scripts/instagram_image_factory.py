from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import psycopg
import yaml
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
if str(PROJECT_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from conecta_video_ai.exceptions import GenerationError
from conecta_video_ai.pipelines import StudioService
from conecta_video_ai.providers import OpenAIImageProvider
from conecta_video_ai.settings import load_settings
from conecta_video_ai.service_images import reconcile, read_registry, approve_generated, save_registry
from conecta_video_ai.image_budget import ImageBudget, BudgetBlocked
from instagram_layout_guard import LayoutGuard, assert_layouts, write_manifest

W, H = 1080, 1350
SOURCE_SAFE_MARGIN = 56
PHONE = "+56 9 8343 4503"
SITE = "conectaproia.cl"
BRAND = "ConectaProIA"
QUALITY_STANDARD_VERSION = 7
REFERENCE_SEEDS = {
    "electricidad": "electricidad_reparacion_01.png",
}
STATE_DIR = PROJECT_ROOT / "output" / "runs" / "instagram" / "image_factory"
MANIFEST_DIR = STATE_DIR / "manifests"
LOG_PATH = STATE_DIR / "image_factory_log.jsonl"
STATE_PATH = STATE_DIR / "state.json"
REGISTRY_PATH = STATE_DIR.parent / "catalog" / "service_images.json"
LOCK_PATH = Path(tempfile.gettempdir()) / "conectaproia_ig_image_factory.lock"
FONT_DIRS = [
    Path(os.getenv("IG_FONT_DIR", "")),
    Path(r"C:\Windows\Fonts"),
    Path("/usr/share/fonts/truetype/dejavu"),
    Path("/usr/share/fonts/truetype/liberation2"),
]


@dataclass(frozen=True)
class DbService:
    code: str
    name: str
    provider_count: int


@dataclass(frozen=True)
class AssetDecision:
    service: DbService
    action: str
    reason: str
    image_path: str


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_utc_iso(value: str) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def read_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {}
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def write_state_result(result: dict[str, Any]) -> None:
    state = read_state()
    state["last_run_at"] = now_iso()
    state["last_result"] = result
    if bool(result.get("ok")) and bool(result.get("created")):
        state["last_success_at"] = state["last_run_at"]
        state["last_success_result"] = result
    safe_write_json(STATE_PATH, state)


def should_skip_after_recent_success(min_success_interval_hours: int) -> tuple[bool, dict[str, Any] | None]:
    if int(min_success_interval_hours) <= 0:
        return False, None
    state = read_state()
    last_success_at = parse_utc_iso(str(state.get("last_success_at") or ""))
    if last_success_at is None:
        last_result = state.get("last_result") if isinstance(state.get("last_result"), dict) else {}
        if bool(last_result.get("ok")) and bool(last_result.get("created")):
            last_success_at = parse_utc_iso(str(state.get("last_run_at") or ""))
    if last_success_at is None:
        return False, None
    now = datetime.now(timezone.utc)
    next_allowed_at = last_success_at + timedelta(hours=int(min_success_interval_hours))
    if now >= next_allowed_at:
        return False, None
    remaining_minutes = max(1, int((next_allowed_at - now).total_seconds() // 60))
    return True, {
        "ok": True,
        "skipped": True,
        "reason": "recent_success_daily_limit",
        "last_success_at": last_success_at.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "next_allowed_at": next_allowed_at.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "remaining_minutes": remaining_minutes,
        "min_success_interval_hours": int(min_success_interval_hours),
    }


def slugify(text: str, *, fallback: str = "servicio") -> str:
    value = str(text or "").strip().lower()
    replacements = {
        "á": "a",
        "é": "e",
        "í": "i",
        "ó": "o",
        "ú": "u",
        "ñ": "n",
        "ü": "u",
    }
    for src, dst in replacements.items():
        value = value.replace(src, dst)
    value = re.sub(r"[^a-z0-9]+", "_", value).strip("_")
    return value or fallback


def font(name: str, size: int):
    linux_fallbacks = {
        "arial.ttf": "DejaVuSans.ttf",
        "segoeui.ttf": "DejaVuSans.ttf",
        "segoeuib.ttf": "DejaVuSans-Bold.ttf",
    }
    candidates = [name, name.lower(), name.upper()]
    fallback = linux_fallbacks.get(name.lower())
    if fallback:
        candidates.append(fallback)
    for font_dir in [p for p in FONT_DIRS if str(p)]:
        for candidate in candidates:
            path = font_dir / candidate
            if path.exists():
                return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


FONTS = {
    "brand": font("segoeuib.ttf", 42),
    "title": font("segoeuib.ttf", 74),
    "title_small": font("segoeuib.ttf", 62),
    "body": font("segoeui.ttf", 34),
    "body_bold": font("segoeuib.ttf", 35),
    "cta": font("segoeuib.ttf", 44),
    "phone": font("segoeuib.ttf", 52),
    "site": font("segoeuib.ttf", 32),
    "tiny": font("segoeui.ttf", 20),
}


def safe_read_json(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def safe_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def append_log(payload: dict[str, Any]) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": now_iso(), **payload}, ensure_ascii=False) + "\n")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def acquire_lock() -> tuple[bool, str]:
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(LOCK_PATH), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        data = safe_read_json(LOCK_PATH, {})
        raw = str(data.get("acquired_at") or "")
        try:
            acquired = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except Exception:
            acquired = None
        if acquired and datetime.now(timezone.utc) - acquired > timedelta(hours=3):
            try:
                LOCK_PATH.unlink(missing_ok=True)
            except Exception:
                return False, "active_lock_unremovable"
            return acquire_lock()
        return False, "active_lock"
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(json.dumps({"pid": os.getpid(), "acquired_at": now_iso()}, ensure_ascii=False))
    return True, "acquired"


def release_lock() -> None:
    try:
        LOCK_PATH.unlink(missing_ok=True)
    except Exception:
        pass


def db_conninfo_from_env() -> dict[str, str]:
    load_dotenv(PROJECT_ROOT / ".env", override=True)
    required = {
        "host": os.getenv("CP_DB_HOST", "localhost"),
        "port": os.getenv("CP_DB_PORT", "15432"),
        "dbname": os.getenv("CP_DB_NAME", "conectapro"),
        "user": os.getenv("CP_DB_USER", "conectapro"),
        "password": os.getenv("CP_DB_PASSWORD", ""),
    }
    missing = [key for key, value in required.items() if not str(value or "").strip()]
    if missing:
        raise RuntimeError("Faltan variables de DB para image factory: " + ", ".join(f"CP_DB_{m.upper()}" for m in missing))
    return {k: str(v) for k, v in required.items()}


def load_db_services(*, min_providers: int = 1) -> list[DbService]:
    conninfo = db_conninfo_from_env()
    query = """
        select sc.code, sc.name, count(distinct p.id) as provider_count
        from public.service_catalog sc
        join public.provider_services ps on ps.service_code = sc.code and ps.active = true
        join public.providers p
          on p.id = ps.provider_id
         and p.active = true
         and (p.blocked_until is null or p.blocked_until <= now())
        where sc.active = true
        group by sc.code, sc.name
        having count(distinct p.id) >= %s
        order by provider_count desc, sc.name asc
    """
    with psycopg.connect(**conninfo) as conn:
        conn.read_only = True
        with conn.cursor() as cur:
            cur.execute(query, (int(min_providers),))
            return [DbService(code=str(a), name=str(b), provider_count=int(c)) for a, b, c in cur.fetchall()]


def load_yaml_map(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def write_yaml_map(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False, width=1000), encoding="utf-8")


def service_tokens(service: DbService) -> list[str]:
    raw = f"{service.code} {service.name}"
    return [x for x in slugify(raw).split("_") if len(x) >= 3][:10]


def visual_scene_hint(service: DbService) -> str:
    text = f"{service.code} {service.name}".lower()
    if any(x in text for x in ("electric", "enchufe", "tablero", "luz")):
        return (
            "certified electrician actively repairing or inspecting an open electrical outlet or breaker panel, "
            "insulated screwdriver, multimeter, safety gloves, visible wires safely organized, clean Chilean home interior; "
            "medium-wide view with the panel, hands and tools visible; the technician must not be a close-up portrait"
        )
    if any(x in text for x in ("gasfit", "calef", "fuga", "agua")):
        return (
            "professional plumber actively repairing a sink, pipe leak or water heater with visible wrench and fittings, "
            "clean home interior, service action clearly visible, not just a portrait"
        )
    if any(x in text for x in ("comida", "sushi", "pizzeria", "hamburguesa", "sandwich")):
        return "professional local food service scene with appetizing prepared food, clean kitchen or counter, no delivery-app branding"
    if any(x in text for x in ("auto", "mecan", "neumatic", "grua")):
        return "clean automotive workshop with a professional technician using diagnostic tools"
    if any(x in text for x in ("medic", "dent", "fono", "kinesi", "psic", "tens", "enfermer")):
        return "trustworthy healthcare or therapy setting with a professional assisting an adult client, no emergency or invasive procedure"
    if any(x in text for x in ("belleza", "peluquer", "manicure", "cejas", "depil", "maquill")):
        return "refined beauty studio with a skilled professional serving an adult client"
    if any(x in text for x in ("electric", "gasfit", "calef", "reparacion", "pc", "notebook", "celular", "electro")):
        return "professional technician working with tools in a clean home, workshop or service bench"
    if any(x in text for x in ("propiedad", "arquitect", "inmobili", "tasacion")):
        return "modern property or office consultation with a professional advisor and client"
    return "professional local service scene with a real worker or specialist helping an adult client in a clean Chilean setting"


def build_prompt(service: DbService) -> str:
    return (
        "Use case: ads-marketing\n"
        "Asset type: Instagram feed base image for ConectaProIA service marketplace\n"
        f"Primary request: premium photorealistic vertical image representing the service '{service.name}'.\n"
        f"Scene/backdrop: {visual_scene_hint(service)}.\n"
        "Style/medium: high-end commercial editorial photography, realistic faces and hands, polished but natural.\n"
        "Composition/framing: vertical 4:5 composition, clear subject, clean negative space for later Spanish text overlay. "
        "Place the main service action on the right half and keep the left half light and uncluttered. "
        "Keep all meaningful food, people, tools, hands, heads and finished work fully inside the central 80 percent of the image. "
        "Leave calm background padding around every edge; do not crop the subject, plates, tools, hands or faces at any border. "
        "Avoid extreme close-ups and avoid objects touching the top, bottom, left or right image edge. "
        "The service activity, tools, materials or finished result must be visible in the foreground. Avoid generic portrait-only images.\n"
        "Lighting/mood: bright professional lighting, trustworthy, calm, modern.\n"
        "Constraints: no text, no logos, no signs, no readable screens, no phone numbers, no WhatsApp branding, no watermarks, no provider names.\n"
        "Avoid: close-up headshot, cropped hat or face, subject touching image borders, distorted anatomy, extra fingers, clutter, brand marks, documents with readable data, license plates."
    )


def ensure_catalog_entries(service: DbService, *, settings) -> dict[str, Any]:
    changed: dict[str, bool] = {"categories": False, "descriptors": False, "overrides": False}

    categories_path = Path(settings.instagram_categories_path)
    cfg = load_yaml_map(categories_path)
    rows = cfg.setdefault("categories", [])
    if isinstance(rows, list) and not any(isinstance(row, dict) and row.get("id") == service.code for row in rows):
        label = service.name
        rows.append(
            {
                "id": service.code,
                "label": label,
                "objective": "captar_clientes",
                "keywords": service_tokens(service),
                "services": [service.name],
                "image_prompt_templates": [build_prompt(service)],
                "variants": [
                    {
                        "hook": f"¿Necesitas {label}?",
                        "value": "ConectaProIA te conecta por WhatsApp con opciones disponibles.",
                        "proof": "Servicio coordinado con profesionales activos.",
                        "cta": "Escríbenos y te ayudamos a coordinar.",
                        "short_text": label[:70],
                    }
                ],
            }
        )
        write_yaml_map(categories_path, cfg)
        changed["categories"] = True

    descriptors_path = Path(settings.instagram_category_descriptors_path)
    desc = load_yaml_map(descriptors_path)
    desc.setdefault("prompt_framework", {})
    desc_rows = desc.setdefault("categories", [])
    if isinstance(desc_rows, list) and not any(isinstance(row, dict) and row.get("id") == service.code for row in desc_rows):
        desc_rows.append(
            {
                "id": service.code,
                "label": service.name,
                "objective": "captar_clientes",
                "category_context": f"Promocionar coordinación de {service.name} por WhatsApp usando solo contacto oficial de ConectaProIA.",
                "visual_brief": visual_scene_hint(service),
                "keywords": service_tokens(service),
                "services": [service.name],
                "reference_asset_patterns": [f"{service.code}_01.png"],
                "image_prompt_templates": [build_prompt(service)],
                "creative_template": {
                    "subject_profile": "Profesional real del rubro, presentación limpia y confiable.",
                    "scene_profile": visual_scene_hint(service),
                    "color_direction": "Paleta profesional balanceada con acento verde ConectaProIA.",
                    "lighting_direction": "Luz natural o comercial suave, alto nivel de claridad.",
                    "copy_structure": "Servicio + profesionales activos + WhatsApp oficial + web + disclaimer.",
                    "layout_density": "media",
                    "tone_keywords": ["profesional", "confiable", "claro"],
                },
            }
        )
        write_yaml_map(descriptors_path, desc)
        changed["descriptors"] = True

    overrides_path = Path(settings.instagram_asset_overrides_path)
    overrides = load_yaml_map(overrides_path)
    override_rows = overrides.setdefault("overrides", [])
    pattern = f"{service.code}*"
    if isinstance(override_rows, list) and not any(isinstance(row, dict) and row.get("pattern") == pattern for row in override_rows):
        override_rows.append({"pattern": pattern, "category_id": service.code})
        write_yaml_map(overrides_path, overrides)
        changed["overrides"] = True

    return changed


def cover_image(path: Path) -> Image.Image:
    im = Image.open(path).convert("RGB")
    iw, ih = im.size
    cover_scale = max(W / iw, H / ih)
    cover_w, cover_h = int(iw * cover_scale), int(ih * cover_scale)
    bg = im.resize((cover_w, cover_h), Image.Resampling.LANCZOS)
    bg = bg.crop(((cover_w - W) // 2, (cover_h - H) // 2, (cover_w - W) // 2 + W, (cover_h - H) // 2 + H))
    bg = bg.filter(ImageFilter.GaussianBlur(radius=18))
    bg = ImageEnhance.Brightness(bg).enhance(0.94)
    bg = ImageEnhance.Contrast(bg).enhance(0.92)

    contain_scale = min((W - SOURCE_SAFE_MARGIN * 2) / iw, (H - SOURCE_SAFE_MARGIN * 2) / ih)
    nw, nh = int(iw * contain_scale), int(ih * contain_scale)
    fg = im.resize((nw, nh), Image.Resampling.LANCZOS)
    x = W - SOURCE_SAFE_MARGIN - nw
    y = (H - nh) // 2
    bg.paste(fg, (x, y))
    return bg


def text_size(draw: ImageDraw.ImageDraw, text: str, fnt) -> tuple[int, int]:
    box = draw.textbbox((0, 0), text, font=fnt)
    return box[2] - box[0], box[3] - box[1]


def wrap_text(draw: ImageDraw.ImageDraw, text: str, fnt, max_width: int) -> list[str]:
    words = str(text or "").split()
    lines: list[str] = []
    current = ""
    for word in words:
        trial = (current + " " + word).strip()
        if text_size(draw, trial, fnt)[0] <= max_width or not current:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def draw_wrapped(draw, x: int, y: int, text: str, fnt, fill, max_width: int, gap: int = 8) -> int:
    for paragraph in str(text or "").splitlines() or [""]:
        for line in wrap_text(draw, paragraph, fnt, max_width):
            draw.text((x, y), line, font=fnt, fill=fill)
            y += text_size(draw, line, fnt)[1] + gap
    return y


def draw_fitted_text(draw, bounds, text, fnt, fill, *, min_size: int = 16, gap: int = 6):
    """Measure full copy with the actual font and fit it within a fixed region.

    Never truncate copy. Impossible layouts fail during preflight before spending.
    Long words are split by glyph width; Linux fallback fonts are measured too.
    """
    x1, y1, x2, y2 = bounds
    for size in range(fnt.size, min_size - 1, -1):
        fitted = fnt.font_variant(size=size)
        lines = []
        for paragraph in text.splitlines():
            line = ""
            for word in paragraph.split():
                trial = (line + " " + word).strip()
                if text_size(draw, trial, fitted)[0] <= x2 - x1:
                    line = trial
                    continue
                if line:
                    lines.append(line)
                    line = ""
                for char in word:
                    if line and text_size(draw, line + char, fitted)[0] > x2 - x1:
                        lines.append(line)
                        line = ""
                    line += char
            if line:
                lines.append(line)
        measured = [draw.textbbox((0, 0), line, font=fitted, anchor="lt") for line in lines]
        heights = [b[3] - b[1] for b in measured]
        height = sum(heights) + gap * max(0, len(lines) - 1)
        if lines and height <= y2-y1 and all(text_size(draw, line, fitted)[0] <= x2-x1 for line in lines):
            y = y1
            boxes = []
            positions = []
            for line, h, bearing in zip(lines, heights, measured):
                position = (x1 - bearing[0], y - bearing[1])
                positions.append(position)
                boxes.append(draw.textbbox(position, line, font=fitted, anchor="lt"))
                y += h + gap
            actual = (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))
            if actual[0] < x1 or actual[1] < y1 or actual[2] > x2 or actual[3] > y2:
                continue
            y = y1
            for line, h, position in zip(lines, heights, positions):
                draw.text(position, line, font=fitted, fill=fill, anchor="lt")
                y += h + gap
            return actual
    raise RuntimeError(f"Text cannot fit allocated bounds at readable size: {text!r}")


def stable_accent(code: str) -> tuple[int, int, int]:
    palette = [(16, 185, 129), (14, 165, 233), (59, 130, 246), (20, 184, 166), (245, 158, 11), (236, 72, 153)]
    idx = int(hashlib.sha1(code.encode("utf-8")).hexdigest()[:2], 16) % len(palette)
    return palette[idx]


def draw_footer(draw, service: DbService, x: int, y: int, max_width: int, fill) -> tuple[int, int, int, int]:
    text = (
        f"ConectaProIA actúa como intermediario y no presta directamente servicios de {service.name}. "
        "La prestación es responsabilidad del proveedor/profesional."
    )
    return draw_fitted_text(draw, (x, y, x + max_width, 1306), text, FONTS["tiny"], fill, min_size=16, gap=4)



def headline_for_service(service: DbService) -> str:
    mapping = {
        "aire_acondicionado_calefaccion": "climatización",
        "electricidad": "un electricista",
        "gasfiteria": "un gasfiter",
        "kinesiologia": "kinesiología",
        "comida_preparada_restaurante": "comida preparada",
    }
    label = mapping.get(service.code, service.name)
    if len(label) > 28:
        label = "este servicio"
    return "¿Necesitas\n" + label + "?"


def draw_card_icon(draw, *, kind: str, cx: int, cy: int, accent: tuple[int, int, int]) -> None:
    draw.ellipse((cx - 25, cy - 25, cx + 25, cy + 25), fill=accent + (255,))
    white = (255, 255, 255, 255)
    if kind == "fast":
        draw.arc((cx - 13, cy - 13, cx + 13, cy + 13), start=205, end=330, fill=white, width=5)
        draw.line((cx + 8, cy + 8, cx + 15, cy + 15), fill=white, width=5)
        draw.line((cx - 8, cy + 12, cx - 14, cy + 19), fill=white, width=4)
    elif kind == "local":
        draw.ellipse((cx - 11, cy - 16, cx + 11, cy + 6), outline=white, width=5)
        draw.polygon([(cx - 10, cy + 2), (cx + 10, cy + 2), (cx, cy + 20)], fill=white)
        draw.ellipse((cx - 4, cy - 9, cx + 4, cy - 1), fill=accent + (255,))
    else:
        draw.line((cx - 5, cy - 18, cx - 17, cy + 4), fill=white, width=7)
        draw.line((cx - 5, cy - 18, cx + 13, cy - 18), fill=white, width=7)
        draw.line((cx + 13, cy - 18, cx + 2, cy + 4), fill=white, width=7)
        draw.line((cx + 2, cy + 4, cx + 16, cy + 4), fill=white, width=7)
        draw.line((cx + 16, cy + 4, cx - 4, cy + 22), fill=white, width=7)


def draw_site_badge(draw, box: tuple[int, int, int, int], *, fill, text_fill) -> tuple[int, int, int, int]:
    x1, y1, x2, y2 = box
    cy = (y1 + y2) // 2
    draw.rounded_rectangle(box, radius=(y2 - y1) // 2, fill=fill)
    icon_cx = x1 + 31
    draw.ellipse((icon_cx - 12, cy - 12, icon_cx + 12, cy + 12), outline=text_fill, width=3)
    draw.arc((icon_cx - 9, cy - 12, icon_cx + 9, cy + 12), start=80, end=280, fill=text_fill, width=2)
    draw.arc((icon_cx - 9, cy - 12, icon_cx + 9, cy + 12), start=260, end=100, fill=text_fill, width=2)
    draw.line((icon_cx - 12, cy, icon_cx + 12, cy), fill=text_fill, width=2)
    text_x = icon_cx + 24
    bbox = draw.textbbox((0, 0), SITE, font=FONTS["site"])
    text_h = bbox[3] - bbox[1]
    text_y = cy - text_h // 2 - bbox[1] - 1
    draw.text((text_x, text_y), SITE, font=FONTS["site"], fill=text_fill)
    return box


def draw_contact_icon(draw, *, cx: int, cy: int, radius: int, fill, icon_fill) -> tuple[int, int, int, int]:
    box = (cx - radius, cy - radius, cx + radius, cy + radius)
    draw.ellipse(box, fill=fill)
    bubble = (cx - 31, cy - 27, cx + 31, cy + 25)
    draw.rounded_rectangle(bubble, radius=18, outline=icon_fill, width=6)
    draw.polygon([(cx - 18, cy + 20), (cx - 31, cy + 38), (cx - 3, cy + 25)], fill=icon_fill)
    draw.arc((cx - 17, cy - 11, cx + 1, cy + 13), start=110, end=250, fill=icon_fill, width=6)
    draw.arc((cx - 1, cy - 11, cx + 17, cy + 13), start=-70, end=70, fill=icon_fill, width=6)
    draw.line((cx - 10, cy + 9, cx + 11, cy + 18), fill=icon_fill, width=6)
    return box


def draw_info_card(draw, x: int, y: int, title: str, subtitle: str, icon_kind: str, accent) -> tuple[int, int, int, int]:
    card_w, card_h = 468, 96
    draw.rounded_rectangle((x, y, x + card_w, y + card_h), radius=18, fill=(255, 255, 255, 248), outline=(226, 232, 240, 255), width=2)
    draw_card_icon(draw, kind=icon_kind, cx=x + 45, cy=y + 48, accent=accent)
    draw_fitted_text(draw, (x+88, y+18, x+card_w-16, y+52), title, FONTS["body_bold"], (5, 30, 75, 255), min_size=24)
    draw_fitted_text(draw, (x+88, y+60, x+card_w-16, y+82), subtitle, FONTS["tiny"], (51, 65, 85, 255))
    return (x, y, x + card_w, y + card_h)


def compose_premium_reference_asset(*, base_path: Path, output_path: Path, service: DbService) -> LayoutGuard:
    accent = stable_accent(service.code)
    navy = (5, 30, 75, 255)
    green = (0, 178, 105, 255)
    canvas = cover_image(base_path)
    canvas = ImageEnhance.Contrast(canvas).enhance(1.03)
    canvas = ImageEnhance.Color(canvas).enhance(1.04).convert("RGBA")
    draw = ImageDraw.Draw(canvas)
    guard = LayoutGuard(asset_name=output_path.name, width=W, height=H)

    left_w = 610
    draw.rectangle((0, 0, left_w, 930), fill=(255, 255, 255, 246))
    fade = Image.new("RGBA", (140, 930), (255, 255, 255, 0))
    fpx = fade.load()
    for fx in range(140):
        alpha = int(246 * (1 - fx / 140))
        for fy in range(930):
            fpx[fx, fy] = (255, 255, 255, alpha)
    canvas.alpha_composite(fade, (left_w, 0))
    draw.rectangle((0, 0, W, 46), fill=(255, 255, 255, 222))
    draw.rectangle((0, 930, W, H), fill=(244, 248, 252, 245))

    x, y = 64, 70
    draw.ellipse((x, y, x + 58, y + 58), fill=navy)
    draw.text((x + 29, y + 29), "C", font=FONTS["brand"], fill=(255, 255, 255, 255), anchor="mm")
    draw.text((x + 76, y + 4), BRAND, font=FONTS["brand"], fill=navy)
    draw.text((x + 78, y + 54), "Conectamos personas y servicios locales", font=FONTS["tiny"], fill=(51, 65, 85, 255))
    guard.add("brand", (x, y, x + 440, y + 86))

    guard.add("title", draw_fitted_text(draw, (x, 182, x+540, 410), headline_for_service(service), FONTS["title"], navy, min_size=38, gap=10))
    desc = f"Te conectamos por WhatsApp con opciones locales de {service.name}."
    guard.add("description", draw_fitted_text(draw, (x, 432, x+520, 556), desc, FONTS["body"], (51, 65, 85, 255), min_size=24, gap=8))
    y = 580
    guard.add("card_fast", draw_info_card(draw, x, y, "Atención rápida", "por WhatsApp", "fast", green[:3]))
    y += 116
    guard.add("card_options", draw_info_card(draw, x, y, "Opciones locales", "profesionales activos", "local", navy[:3]))
    y += 116
    guard.add("card_service", draw_info_card(draw, x, y, "Servicio disponible", f"{service.provider_count} profesionales activos", "service", accent))

    draw.rounded_rectangle((52, 960, 1028, 1168), radius=20, fill=navy)
    guard.add("cta_panel", (52, 960, 1028, 1168), kind="background")
    guard.add("contact_icon", draw_contact_icon(draw, cx=133, cy=1049, radius=55, fill=green, icon_fill=(255, 255, 255, 255)))
    draw.line((226, 990, 226, 1138), fill=(148, 163, 184, 180), width=2)
    guard.add("cta", draw_fitted_text(draw, (270, 980, 1000, 1025), "Escríbenos al WhatsApp", FONTS["cta"], (255, 255, 255, 255), min_size=32))
    guard.add("phone", draw_fitted_text(draw, (270, 1040, 1000, 1100), PHONE, FONTS["phone"], (255, 255, 255, 255), min_size=38))
    site_box = draw_site_badge(draw, (270, 1120, 610, 1160), fill=green, text_fill=navy)
    guard.add("site", site_box)

    fy = 1188
    labels = ["Contacto directo", "Profesionales locales", "Respuesta WhatsApp", "Intermediario"]
    trust_x = [58, 310, 560, 800]
    for idx, (bx, label) in enumerate(zip(trust_x, labels)):
        draw.ellipse((bx, fy + 8, bx + 24, fy + 32), outline=navy, width=3)
        draw_fitted_text(draw, (bx+36, fy+6, bx+220, fy+44), label, FONTS["tiny"], (30, 41, 59, 255), min_size=16, gap=2)
        guard.add(f"trust_{idx}", (bx, fy, bx + 220, fy + 44))
    guard.add("footer", draw_footer(draw, service, 58, 1248, 960, (71, 85, 105, 230)))

    assert_layouts([guard])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(output_path, "PNG", optimize=True)
    return guard


def compose_asset(*, base_path: Path, output_path: Path, service: DbService) -> LayoutGuard:
    return compose_premium_reference_asset(base_path=base_path, output_path=output_path, service=service)


def preflight_layout(service: DbService, work_dir: Path) -> dict[str, Any]:
    base_path = work_dir / "preflight_base.jpg"
    candidate_path = work_dir / "preflight_candidate.png"
    base_path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (W, H), (235, 238, 242)).save(base_path, "JPEG", quality=92)
    guard = compose_asset(base_path=base_path, output_path=candidate_path, service=service)
    return {
        "ok": True,
        "image_path": str(candidate_path),
        "layout": guard.to_dict(),
    }


def find_reference_seed(service: DbService, assets_root: Path) -> Path | None:
    filename = REFERENCE_SEEDS.get(service.code)
    if not filename:
        return None
    path = assets_root / filename
    return path if path.exists() else None


def existing_manifest_ok(service: DbService, image_path: Path) -> bool:
    manifest_path = MANIFEST_DIR / f"{service.code}.json"
    if not image_path.exists() or not manifest_path.exists():
        return False
    manifest = safe_read_json(manifest_path, {})
    return (
        bool(manifest.get("accepted"))
        and str(manifest.get("service_code")) == service.code
        and str(manifest.get("image_sha256")) == sha256_file(image_path)
        and int(manifest.get("provider_count") or 0) >= 1
    )


def validate_final(
    service: DbService,
    image_path: Path,
    guard: LayoutGuard,
    service_obj: StudioService,
    *,
    source_path: Path | None = None,
) -> dict[str, Any]:
    assert_layouts([guard])
    qc_path = image_path
    if source_path is not None and source_path.exists():
        qc_path = image_path.parent / "_source_qc_proxy.png"
        cover_image(source_path).save(qc_path, "PNG", optimize=True)
    qc = service_obj.instagram_engine._validate_ig_image(image_path=qc_path, image_source="openai_image", format_type="feed")  # noqa: SLF001
    with Image.open(image_path) as img:
        size = list(img.size)
    issues: list[str] = []
    if size != [W, H]:
        issues.append(f"size_invalid:{size}")
    if int(qc.get("score") or 0) < 90 or not bool(qc.get("passed")):
        issues.append("source_image_qc_failed")
    return {
        "ok": not issues,
        "issues": issues,
        "size": size,
        "image_qc": qc,
        "image_qc_path": str(qc_path),
        "layout": guard.to_dict(),
    }


def choose_next_service(services: list[DbService], *, assets_root: Path, force_service: str | None = None, registry: dict | None = None) -> AssetDecision | None:
    force = str(force_service or "").strip()
    for service in services:
        if force and service.code != force:
            continue
        row = (registry or {}).get("services", {}).get(service.code, {})
        # Approvals/review state survive deployments and quality-rule changes.
        if row.get("image") or row.get("status") in {"approved", "needs_review"}:
            continue
        image_path = assets_root / f"{service.code}_01.png"
        if existing_manifest_ok(service, image_path):
            continue
        if not image_path.exists():
            return AssetDecision(service, "create", "missing_image", str(image_path))
        # An existing file is reviewed/adopted, never regenerated automatically.
        continue
    return None


def generate_one(*, force_service: str | None = None, dry_run: bool = False, max_attempts: int = 2, min_providers: int = 1) -> dict[str, Any]:
    settings = load_settings()
    service_obj = StudioService(settings)
    assets_root = Path(settings.instagram_publish_assets_root)
    services = load_db_services(min_providers=min_providers)
    catalog = safe_read_json(settings.instagram_asset_catalog_path, {})
    registry = reconcile(REGISTRY_PATH, services, assets_root, catalog)
    decision = choose_next_service(services, assets_root=assets_root, force_service=force_service, registry=registry)
    if decision is None:
        return {"ok": True, "skipped": True, "reason": "no_pending_services", "db_services": len(services)}

    if dry_run:
        return {"ok": True, "dry_run": True, "decision": asdict(decision), "db_services": len(services)}

    service = decision.service
    work_dir = STATE_DIR / "work" / service.code / datetime.now().strftime("%Y%m%d_%H%M%S")
    accepted_path = assets_root / f"{service.code}_01.png"
    errors: list[dict[str, Any]] = []

    try:
        preflight = preflight_layout(service, work_dir)
    except Exception as exc:  # noqa: BLE001
        result = {
            "ok": False,
            "created": False,
            "decision": asdict(decision),
            "stage": "preflight_layout",
            "error": str(exc),
        }
        append_log(result)
        write_state_result(result)
        return result

    changed = ensure_catalog_entries(service, settings=settings)

    seed_path = find_reference_seed(service, assets_root)
    if seed_path is not None:
        candidate_path = work_dir / "candidate_reference_seed.png"
        try:
            guard = compose_asset(base_path=seed_path, output_path=candidate_path, service=service)
            validation = validate_final(service, candidate_path, guard, service_obj, source_path=seed_path)
            if validation["ok"]:
                accepted_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(candidate_path, accepted_path)
                image_hash = sha256_file(accepted_path)
                manifest = {
                    "accepted": True,
                    "accepted_at": now_iso(),
                    "quality_standard_version": QUALITY_STANDARD_VERSION,
                    "service_code": service.code,
                    "service_name": service.name,
                    "provider_count": service.provider_count,
                    "image_path": str(accepted_path),
                    "image_sha256": image_hash,
                    "prompt": build_prompt(service),
                    "preflight": preflight,
                    "source": "reference_seed",
                    "reference_seed_path": str(seed_path),
                    "catalog_changes": changed,
                    "validation": validation,
                }
                safe_write_json(MANIFEST_DIR / f"{service.code}.json", manifest)
                approve_generated(REGISTRY_PATH, service.code, accepted_path, assets_root)
                write_manifest(STATE_DIR / "layout_manifests" / f"{service.code}.json", [guard])
                sync = service_obj.instagram_engine.sync_asset_catalog()
                result = {
                    "ok": True,
                    "created": True,
                    "decision": asdict(decision),
                    "attempt": 0,
                    "source": "reference_seed",
                    "image_path": str(accepted_path),
                    "manifest_path": str(MANIFEST_DIR / f"{service.code}.json"),
                    "sync": {"ok": bool(sync.get("ok", True)), "total_images": sync.get("asset_catalog", sync).get("total_images")},
                }
                append_log(result)
                write_state_result(result)
                return result
            errors.append({"attempt": 0, "stage": "reference_seed_validate", "validation": validation})
        except Exception as exc:  # noqa: BLE001
            errors.append({"attempt": 0, "stage": "reference_seed_exception", "error": str(exc), "path": str(seed_path)})

    if not (settings.openai_api_key or "").strip():
        raise RuntimeError("OPENAI_API_KEY no configurada; image factory no puede generar imágenes automáticamente")

    provider = OpenAIImageProvider(
        api_key=str(settings.openai_api_key),
        model=str(settings.openai_image_model),
        size=str(settings.openai_image_size),
        quality=str(settings.openai_image_quality),
    )
    budget = ImageBudget(STATE_DIR.parent / "budget" / "image_usage.sqlite3",
                         float(settings.instagram_openai_monthly_budget_usd),
                         float(os.getenv("IG_IMAGE_REQUEST_RESERVATION_USD", "0.30")))

    for attempt in range(1, max(1, int(max_attempts)) + 1):
        base_path = work_dir / f"base_attempt_{attempt}.jpg"
        candidate_path = work_dir / f"candidate_attempt_{attempt}.png"
        reservation = None
        api_completed = False
        try:
            reservation = budget.reserve(service.code)
            provider.generate_image(build_prompt(service), base_path)
            api_completed = True
            budget.complete(reservation, {**provider.last_usage, "image": str(base_path)})
            guard = compose_asset(base_path=base_path, output_path=candidate_path, service=service)
            validation = validate_final(service, candidate_path, guard, service_obj, source_path=base_path)
            if not validation["ok"]:
                errors.append({"attempt": attempt, "stage": "validate", "validation": validation})
                registry = read_registry(REGISTRY_PATH)
                registry["services"][service.code].update(status="needs_review", reason="generated_image_quality_rejected", review_candidate=str(candidate_path))
                save_registry(REGISTRY_PATH, registry)
                break

            accepted_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(candidate_path, accepted_path)
            image_hash = sha256_file(accepted_path)
            manifest = {
                "accepted": True,
                "accepted_at": now_iso(),
                "quality_standard_version": QUALITY_STANDARD_VERSION,
                "service_code": service.code,
                "service_name": service.name,
                "provider_count": service.provider_count,
                "image_path": str(accepted_path),
                "image_sha256": image_hash,
                "prompt": build_prompt(service),
                "preflight": preflight,
                "catalog_changes": changed,
                "validation": validation,
            }
            safe_write_json(MANIFEST_DIR / f"{service.code}.json", manifest)
            approve_generated(REGISTRY_PATH, service.code, accepted_path, assets_root)
            write_manifest(STATE_DIR / "layout_manifests" / f"{service.code}.json", [guard])
            sync = service_obj.instagram_engine.sync_asset_catalog()
            result = {
                "ok": True,
                "created": True,
                "decision": asdict(decision),
                "attempt": attempt,
                "budget_request_id": reservation,
                "image_path": str(accepted_path),
                "manifest_path": str(MANIFEST_DIR / f"{service.code}.json"),
                "sync": {"ok": bool(sync.get("ok", True)), "total_images": sync.get("asset_catalog", sync).get("total_images")},
            }
            append_log(result)
            write_state_result(result)
            return result
        except BudgetBlocked as exc:
            result = {"ok": False, "status": "blocked", "created": False, "reason": str(exc), "decision": asdict(decision)}
            append_log(result)
            write_state_result(result)
            return result
        except Exception as exc:  # noqa: BLE001
            if reservation and not api_completed:
                budget.failed(reservation, str(exc))
            errors.append({"attempt": attempt, "stage": "exception", "error": str(exc)})
            if api_completed:
                # A paid source already exists. Never buy another to fix local
                # composition, disk, validation or catalog errors.
                registry = read_registry(REGISTRY_PATH)
                registry["services"][service.code].update(
                    status="needs_review", reason="post_generation_processing_failed",
                    review_candidate=str(candidate_path), review_source=str(base_path))
                save_registry(REGISTRY_PATH, registry)
                break

    result = {"ok": False, "created": False, "decision": asdict(decision), "errors": errors}
    append_log(result)
    write_state_result(result)
    return result


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env", override=True)
    parser = argparse.ArgumentParser(description="Crea o repara 1 imagen IG por servicio activo en DB.")
    parser.add_argument("--force-service", default=None, help="Service code exacto para forzar.")
    parser.add_argument("--dry-run", action="store_true", help="Sin llamadas pagadas: sincroniza registro/presupuesto y muestra el siguiente faltante.")
    parser.add_argument("--resume-after-topup", action="store_true", help="Clear a recorded quota block after adding credits.")
    parser.add_argument("--max-attempts", type=int, default=int(os.getenv("IG_IMAGE_FACTORY_MAX_ATTEMPTS", "2")))
    parser.add_argument("--min-providers", type=int, default=int(os.getenv("IG_IMAGE_FACTORY_MIN_PROVIDERS", "1")))
    parser.add_argument(
        "--min-success-interval-hours",
        type=int,
        default=int(os.getenv("IG_IMAGE_FACTORY_MIN_SUCCESS_INTERVAL_HOURS", "24")),
        help="Horas minimas entre generaciones exitosas. Si falla, se reintenta en el siguiente ciclo.",
    )
    args = parser.parse_args()

    os.chdir(PROJECT_ROOT)
    locked, note = acquire_lock()
    if not locked:
        payload = {"ok": False, "skipped": True, "reason": note}
        append_log(payload)
        write_state_result(payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    try:
        budget = ImageBudget(STATE_DIR.parent / "budget" / "image_usage.sqlite3",
                             float(os.getenv("INSTAGRAM_OPENAI_MONTHLY_BUDGET_USD", "5")))
        budget.import_history(PROJECT_ROOT / "logs" / "prod_jobs", float(os.getenv("INSTAGRAM_OPENAI_IMAGE_ESTIMATED_COST_USD", "0.25")))
        if args.resume_after_topup:
            budget.resume()
        settings = load_settings()
        reconcile(REGISTRY_PATH, load_db_services(min_providers=int(args.min_providers)),
                  Path(settings.instagram_publish_assets_root), safe_read_json(settings.instagram_asset_catalog_path, {}))
        if not args.force_service and not args.dry_run:
            skipped, payload = should_skip_after_recent_success(int(args.min_success_interval_hours))
            if skipped and payload is not None:
                append_log(payload)
                write_state_result(payload)
                print(json.dumps(payload, ensure_ascii=False, indent=2))
                return
        result = generate_one(
            force_service=args.force_service,
            dry_run=bool(args.dry_run),
            max_attempts=int(args.max_attempts),
            min_providers=int(args.min_providers),
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if not result.get("ok"):
            raise SystemExit(1)
    except Exception as exc:  # noqa: BLE001
        payload = {"ok": False, "error": str(exc)}
        append_log(payload)
        write_state_result(payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        raise SystemExit(1) from exc
    finally:
        release_lock()


if __name__ == "__main__":
    main()
