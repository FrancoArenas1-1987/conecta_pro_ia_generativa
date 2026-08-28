from __future__ import annotations

import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFont

from .models import ImageCreative


def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _fit_cover(image: Image.Image, width: int, height: int) -> Image.Image:
    src_w, src_h = image.size
    src_ratio = src_w / src_h
    dst_ratio = width / height

    if src_ratio > dst_ratio:
        new_h = height
        new_w = int(new_h * src_ratio)
    else:
        new_w = width
        new_h = int(new_w / src_ratio)

    resized = image.resize((new_w, new_h), Image.Resampling.LANCZOS)
    left = (new_w - width) // 2
    top = (new_h - height) // 2
    return resized.crop((left, top, left + width, top + height))


def render_social_image(
    creative: ImageCreative,
    source_image: Path,
    output_path: Path,
    width: int,
    height: int,
    primary_color: str,
    accent_color: str,
    text_color: str,
) -> None:
    img = Image.open(source_image).convert("RGB")
    canvas = _fit_cover(img, width, height)

    # Slight darkening to improve text legibility.
    canvas = ImageEnhance.Brightness(canvas).enhance(0.62)

    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw_overlay = ImageDraw.Draw(overlay)
    draw_overlay.rectangle((0, int(height * 0.55), width, height), fill=(0, 0, 0, 155))
    draw_overlay.rectangle((0, 0, width, 12), fill=_hex_to_rgba(accent_color, 230))

    combined = Image.alpha_composite(canvas.convert("RGBA"), overlay)
    draw = ImageDraw.Draw(combined)

    title_font = _load_font(76, bold=True)
    sub_font = _load_font(42)
    cta_font = _load_font(44, bold=True)

    title = textwrap.fill(creative.headline.upper(), width=18)
    sub = textwrap.fill(creative.subheadline, width=28)

    draw.multiline_text((64, 96), title, fill=text_color, font=title_font, spacing=10)
    draw.multiline_text((64, int(height * 0.62)), sub, fill=text_color, font=sub_font, spacing=8)

    cta_text = creative.call_to_action.upper()
    cta_w = draw.textlength(cta_text, font=cta_font)
    cta_box = (64, height - 150, int(64 + cta_w + 42), height - 78)
    draw.rounded_rectangle(cta_box, radius=14, fill=primary_color)
    draw.text((84, height - 139), cta_text, fill=text_color, font=cta_font)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    combined.convert("RGB").save(output_path, quality=95)


def _hex_to_rgba(value: str, alpha: int) -> tuple[int, int, int, int]:
    clean = value.lstrip("#")
    if len(clean) != 6:
        return (0, 0, 0, alpha)
    return (int(clean[0:2], 16), int(clean[2:4], 16), int(clean[4:6], 16), alpha)
