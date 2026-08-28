from __future__ import annotations

import math
import shutil
import tempfile
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

if not hasattr(Image, "ANTIALIAS"):
    Image.ANTIALIAS = Image.Resampling.LANCZOS

from .exceptions import RenderError
from .models import StoryboardScene

_VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}


def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "C:/Windows/Fonts/bahnschrift.ttf",
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


def _fit_contain(image: Image.Image, width: int, height: int, pad_x: int, pad_y: int) -> Image.Image:
    max_w = max(100, width - 2 * pad_x)
    max_h = max(100, height - 2 * pad_y)

    src_w, src_h = image.size
    scale = min(max_w / src_w, max_h / src_h)
    new_w = max(1, int(src_w * scale))
    new_h = max(1, int(src_h * scale))
    return image.resize((new_w, new_h), Image.Resampling.LANCZOS)


def _make_rounded_mask(size: tuple[int, int], radius: int) -> Image.Image:
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((0, 0, size[0], size[1]), radius=radius, fill=255)
    return mask


def _render_base_background(scene: StoryboardScene, out_file: Path, width: int, height: int) -> None:
    if scene.source_image and scene.source_image.exists():
        source = Image.open(scene.source_image).convert("RGB")
    else:
        source = Image.new("RGB", (width, height), "#101827")

    bg = _fit_cover(source, width, height)
    bg = bg.filter(ImageFilter.GaussianBlur(radius=16))
    bg = ImageEnhance.Brightness(bg).enhance(0.48)

    canvas = bg.convert("RGBA")
    src_ratio = source.width / max(1, source.height)
    dst_ratio = width / max(1, height)
    ratio_gap = abs(src_ratio - dst_ratio) / max(0.01, dst_ratio)

    if ratio_gap > 0.20:
        fg = _fit_contain(source, width, height, pad_x=int(width * 0.07), pad_y=int(height * 0.14)).convert("RGBA")

        shadow = Image.new("RGBA", (fg.width + 24, fg.height + 24), (0, 0, 0, 0))
        draw_shadow = ImageDraw.Draw(shadow)
        draw_shadow.rounded_rectangle((0, 0, shadow.width - 1, shadow.height - 1), radius=36, fill=(0, 0, 0, 130))
        shadow = shadow.filter(ImageFilter.GaussianBlur(radius=8))

        x = (width - fg.width) // 2
        y = (height - fg.height) // 2
        canvas.alpha_composite(shadow, (x - 12, y - 8))

        card = Image.new("RGBA", fg.size, (255, 255, 255, 0))
        rounded = _make_rounded_mask(fg.size, radius=34)
        card.paste(fg, (0, 0), rounded)
        canvas.alpha_composite(card, (x, y))
    else:
        fg = _fit_cover(source, width, height).convert("RGBA")
        fg = ImageEnhance.Brightness(fg).enhance(0.92)
        canvas.alpha_composite(fg, (0, 0))

    shade = Image.new("RGBA", (width, height), (6, 12, 24, 55))
    canvas = Image.alpha_composite(canvas, shade)
    canvas.convert("RGB").save(out_file, quality=95)


def _candidate_logo_paths(logo_candidates: list[str] | None) -> list[Path]:
    ordered: list[Path] = []
    seen: set[str] = set()

    def _add(path: Path) -> None:
        key = str(path).lower()
        if key not in seen:
            seen.add(key)
            ordered.append(path)

    for candidate in logo_candidates or []:
        raw = (candidate or "").strip()
        if raw:
            _add(Path(raw))

    defaults = [
        Path(r"C:\Franco\conectapro_rrss\portada_facebook.png"),
        Path(r"C:\Franco\conectapro_rrss\perfil_facebook.png"),
        Path(r"C:\Franco\conectapro_rrss\publicacion_clientes.png"),
    ]
    for item in defaults:
        _add(item)

    return ordered


def _trim_near_white(image: Image.Image, threshold: int = 245) -> Image.Image:
    rgb = image.convert("RGB")
    masks = [ch.point(lambda v: 255 if v < threshold else 0) for ch in rgb.split()]
    mask = masks[0]
    for part in masks[1:]:
        mask = ImageChops.lighter(mask, part)

    bbox = mask.getbbox()
    if bbox:
        return image.crop(bbox)
    return image


def _trim_edges(image: Image.Image) -> Image.Image:
    bg = Image.new(image.mode, image.size, image.getpixel((0, 0)))
    diff = ImageChops.difference(image, bg)
    bbox = diff.getbbox()
    if bbox:
        return image.crop(bbox)
    return image


def _extract_logo_region(image: Image.Image, path: Path) -> Image.Image:
    w, h = image.size
    name = path.name.lower()

    if "portada" in name and w > h:
        box = (int(w * 0.01), int(h * 0.18), int(w * 0.45), int(h * 0.39))
    elif "perfil" in name:
        box = (int(w * 0.16), int(h * 0.08), int(w * 0.84), int(h * 0.40))
    elif "publicacion" in name:
        box = (int(w * 0.08), int(h * 0.30), int(w * 0.88), int(h * 0.56))
    else:
        ratio = w / max(1, h)
        if ratio > 1.3:
            box = (int(w * 0.02), int(h * 0.06), int(w * 0.46), int(h * 0.30))
        elif ratio < 0.9:
            box = (int(w * 0.12), int(h * 0.12), int(w * 0.88), int(h * 0.38))
        else:
            box = (int(w * 0.10), int(h * 0.08), int(w * 0.90), int(h * 0.34))

    crop = image.crop(box).convert("RGBA")
    crop = _trim_near_white(crop, threshold=242)
    crop = _trim_edges(crop)
    boosted = ImageOps.autocontrast(crop.convert("RGB"), cutoff=1)
    return boosted.convert("RGBA")


def _resolve_logo_image(logo_candidates: list[str] | None) -> Image.Image | None:
    for path in _candidate_logo_paths(logo_candidates):
        if not path.exists() or path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
            continue
        try:
            src = Image.open(path).convert("RGB")
            logo = _extract_logo_region(src, path)
            if logo.width >= 120 and logo.height >= 40:
                return logo
        except Exception:
            continue
    return None


def _resolve_qr_path(qr_code_path: str | None) -> Path | None:
    candidates: list[Path] = []
    if qr_code_path and qr_code_path.strip():
        candidates.append(Path(qr_code_path.strip()))
    candidates.append(Path(r"C:\Franco\conectapro_rrss\qr_conectapro_reel.png"))

    for path in candidates:
        if path.exists() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
            return path
    return None


def _render_qr_badge(out_file: Path, qr_path: Path, accent_color: str) -> None:
    size = 210
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=24, fill=(6, 14, 24, 224), outline=_hex_to_rgba(accent_color, 240), width=3)

    qr = Image.open(qr_path).convert("RGBA")
    qr = _trim_edges(qr)
    qr = _fit_contain(qr, size, size, pad_x=16, pad_y=16)

    x = (size - qr.width) // 2
    y = (size - qr.height) // 2
    img.alpha_composite(qr, (x, y))
    img.save(out_file)


def _render_qr_endcard(
    out_file: Path,
    width: int,
    height: int,
    accent_color: str,
    text_color: str,
    qr_path: Path,
    brand_name: str,
    logo_candidates: list[str] | None,
) -> None:
    canvas = Image.new("RGBA", (width, height), (8, 16, 28, 255))
    draw = ImageDraw.Draw(canvas)

    # Dynamic background to avoid a flat ending frame.
    draw.ellipse((-220, -120, int(width * 0.62), int(height * 0.36)), fill=_hex_to_rgba(accent_color, 72))
    draw.ellipse((int(width * 0.56), int(height * 0.60), width + 220, height + 160), fill=(22, 42, 68, 180))

    title = "CONECTA YA"
    title_font = _load_font(126, bold=True)
    bbox = draw.textbbox((0, 0), title, font=title_font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    tx = (width - tw) // 2
    ty = int(height * 0.07)
    draw.text((tx + 3, ty + 3), title, font=title_font, fill=(0, 0, 0, 165))
    draw.text((tx, ty), title, font=title_font, fill=text_color)

    logo = _resolve_logo_image(logo_candidates)
    if logo is not None:
        logo_area = _fit_contain(logo.convert("RGBA"), width, height, pad_x=int(width * 0.23), pad_y=int(height * 0.80))
        lx = (width - logo_area.width) // 2
        ly = int(height * 0.21)
        canvas.alpha_composite(logo_area, (lx, ly))
    else:
        label = " ".join((brand_name or "ConectaProIA").split()).upper()
        font = _load_font(54, bold=True)
        lb = draw.textbbox((0, 0), label, font=font)
        lw = lb[2] - lb[0]
        draw.text(((width - lw) // 2, int(height * 0.24)), label, font=font, fill=text_color)

    qr = Image.open(qr_path).convert("RGBA")
    qr = _trim_edges(qr)
    qr_size = int(min(width * 0.62, height * 0.44))
    qr = _fit_contain(qr, qr_size, qr_size, pad_x=0, pad_y=0)

    card_size = max(qr.width, qr.height) + 90
    card_x = (width - card_size) // 2
    card_y = int(height * 0.43)
    draw.rounded_rectangle(
        (card_x, card_y, card_x + card_size, card_y + card_size),
        radius=44,
        fill=(255, 255, 255, 248),
        outline=_hex_to_rgba(accent_color, 245),
        width=8,
    )

    qx = card_x + (card_size - qr.width) // 2
    qy = card_y + (card_size - qr.height) // 2
    canvas.alpha_composite(qr, (qx, qy))

    hint = "Escanea y habla por WhatsApp"
    hint_font = _load_font(50, bold=True)
    hb = draw.textbbox((0, 0), hint, font=hint_font)
    hw = hb[2] - hb[0]
    hy = min(height - 120, card_y + card_size + 28)
    draw.text(((width - hw) // 2, hy), hint, font=hint_font, fill=text_color)

    canvas.convert("RGB").save(out_file, quality=95)


def _render_logo_badge(
    out_file: Path,
    brand_name: str,
    accent_color: str,
    text_color: str,
    logo_candidates: list[str] | None = None,
) -> None:
    w, h = 460, 132
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    draw.rounded_rectangle((0, 0, w - 1, h - 1), radius=26, fill=(8, 16, 28, 220), outline=_hex_to_rgba(accent_color, 240), width=3)
    draw.rectangle((0, 0, w - 1, 10), fill=_hex_to_rgba(accent_color, 255))

    logo_image = _resolve_logo_image(logo_candidates)
    if logo_image is not None:
        area = _fit_contain(logo_image.convert("RGBA"), w, h, pad_x=18, pad_y=20)
        x = (w - area.width) // 2
        y = (h - area.height) // 2 + 2
        img.alpha_composite(area, (x, y))
    else:
        label = " ".join((brand_name or "ConectaProIA").split()).upper()
        font = _load_font(40, bold=True)
        bbox = draw.textbbox((0, 0), label, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        draw.text(((w - tw) // 2, (h - th) // 2 + 6), label, font=font, fill=text_color)

    img.save(out_file)

def _draw_conversion_text(draw: ImageDraw.ImageDraw, scene: StoryboardScene, width: int, height: int, text_color: str) -> None:
    text = (scene.body or scene.headline or "").strip()
    text = text.replace("\\n", "\n")

    # Build lines for strong readability.
    words = text.split()
    lines: list[str] = []
    line = ""
    max_words = 4
    for w in words:
        cand = (line + " " + w).strip()
        if len(cand.split()) <= max_words:
            line = cand
        else:
            lines.append(line)
            line = w
    if line:
        lines.append(line)

    display = "\n".join(lines[:4])

    font = _load_font(72, bold=True)
    if len(display) > 80:
        font = _load_font(60, bold=True)

    pad = 36
    text_box = (pad, int(height * 0.58), width - pad, height - 36)
    draw.rounded_rectangle(text_box, radius=26, fill=(5, 10, 20, 190), outline=(255, 255, 255, 40), width=2)

    tx = text_box[0] + 24
    ty = text_box[1] + 20
    # fake stroke/shadow
    draw.multiline_text((tx + 2, ty + 2), display, font=font, fill=(0, 0, 0, 210), spacing=8)
    draw.multiline_text((tx, ty), display, font=font, fill=text_color, spacing=8)


def _render_overlay(
    scene: StoryboardScene,
    out_file: Path,
    width: int,
    height: int,
    text_color: str,
    accent_color: str,
    show_text: bool,
) -> None:
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))

    # User preference: no text boxes or captions on final video.
    if not show_text:
        overlay.save(out_file)
        return

    draw = ImageDraw.Draw(overlay)
    if scene.visual_style == "conversion":
        _draw_conversion_text(draw, scene, width, height, text_color)
    else:
        cap_h = 300
        cap_left = 36
        cap_right = width - 36
        cap_bottom = height - 36
        cap_top = cap_bottom - cap_h
        draw.rounded_rectangle((cap_left, cap_top, cap_right, cap_bottom), radius=30, fill=(7, 14, 24, 185), outline=(255, 255, 255, 45), width=2)
        draw.rectangle((cap_left, cap_top, cap_right, cap_top + 10), fill=_hex_to_rgba(accent_color, 255))

        title_font = _load_font(46, bold=True)
        body_font = _load_font(40)
        draw.text((60, cap_top + 44), (scene.headline or "").upper(), font=title_font, fill=text_color)
        draw.text((60, cap_top + 128), scene.body or "", font=body_font, fill=text_color)

    overlay.save(out_file)

def _is_video_file(path: Path | None) -> bool:
    return bool(path and path.suffix.lower() in _VIDEO_EXTENSIONS)


def mux_audio_track(video_path: Path, output_path: Path, audio_path: Path | None = None) -> Path:
    if not video_path.exists() or video_path.stat().st_size == 0:
        raise RenderError(f"Video base invalido: {video_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    if audio_path is None or not audio_path.exists() or audio_path.stat().st_size == 0:
        shutil.copy2(video_path, output_path)
        return output_path

    from moviepy.editor import AudioFileClip, VideoFileClip

    video_clip = VideoFileClip(str(video_path))
    audio_clip = AudioFileClip(str(audio_path))
    try:
        final = video_clip.set_audio(audio_clip.set_duration(video_clip.duration))
        final.write_videofile(str(output_path), codec="libx264", audio_codec="aac", verbose=False, logger=None)
        final.close()
    finally:
        audio_clip.close()
        video_clip.close()

    return output_path


def _apply_cinematic_motion(clip, duration: float, width: int, height: int, style: str, idx: int):
    from moviepy.editor import CompositeVideoClip

    # Deterministic motion profile per scene to keep outputs stable.
    seed = abs(hash(f"{style}-{idx}"))

    if style == "conversion":
        overscan = 1.26
        zoom_delta = 0.06
    elif style == "promo":
        overscan = 1.18
        zoom_delta = 0.04
    else:
        overscan = 1.12
        zoom_delta = 0.025

    base_scale = max(width / max(1.0, clip.w), height / max(1.0, clip.h))
    scale = max(base_scale, overscan)

    moving = clip.resize(scale)
    max_dx = max(0.0, float(moving.w - width))
    max_dy = max(0.0, float(moving.h - height))

    def _ratio(part: int) -> float:
        return 0.08 + (((seed // (part + 1)) % 84) / 100.0)

    x0 = max_dx * _ratio(3)
    y0 = max_dy * _ratio(7)
    x1 = max_dx * _ratio(11)
    y1 = max_dy * _ratio(17)

    if style == "dialogo":
        # Softer movement for dialogue pieces.
        x1 = x0 + (x1 - x0) * 0.45
        y1 = y0 + (y1 - y0) * 0.45

    def _ease(r: float) -> float:
        return 0.5 - 0.5 * math.cos(math.pi * r)

    def _pos(t: float) -> tuple[float, float]:
        r = 0.0 if duration <= 0 else max(0.0, min(1.0, t / duration))
        e = _ease(r)
        x = x0 + (x1 - x0) * e
        y = y0 + (y1 - y0) * e
        return (-x, -y)

    if zoom_delta > 0:
        moving = moving.resize(lambda t: 1.0 + zoom_delta * (0.0 if duration <= 0 else max(0.0, min(1.0, t / duration))))

    motion = moving.set_position(_pos)
    return CompositeVideoClip([motion], size=(width, height)).set_duration(duration)


def _build_scene_clip(
    scene: StoryboardScene,
    idx: int,
    temp_dir: Path,
    width: int,
    height: int,
    text_color: str,
    accent_color: str,
    show_text: bool,
    logo_badge_path: Path | None,
):
    from moviepy.editor import CompositeVideoClip, ImageClip, VideoFileClip, vfx

    duration = max(1.0, scene.duration_seconds)

    if _is_video_file(scene.source_video) and scene.source_video and scene.source_video.exists():
        src = VideoFileClip(str(scene.source_video))
        if src.duration <= 0:
            src.close()
            raise RenderError(f"Video asset invalido: {scene.source_video}")

        if src.duration < duration:
            base_raw = src.fx(vfx.loop, duration=duration)
        else:
            start_max = max(0.0, src.duration - duration)
            start = (abs(hash(f"{scene.index}-{scene.headline}")) % 1000) / 1000.0 * start_max
            base_raw = src.subclip(start, start + duration)

        base_raw = base_raw.fx(vfx.colorx, 0.96)
        base = _apply_cinematic_motion(base_raw, duration, width, height, scene.visual_style, idx)
    else:
        bg_image = temp_dir / f"scene_bg_{idx:02d}.jpg"
        _render_base_background(scene, bg_image, width, height)
        base_raw = ImageClip(str(bg_image)).set_duration(duration)
        base = _apply_cinematic_motion(base_raw, duration, width, height, scene.visual_style, idx)

    layers = [base]

    if show_text:
        overlay_png = temp_dir / f"scene_ov_{idx:02d}.png"
        _render_overlay(scene, overlay_png, width, height, text_color, accent_color, show_text=show_text)
        overlay_clip = (
            ImageClip(str(overlay_png))
            .set_duration(duration)
            .set_position(("center", "center"))
            .crossfadein(0.06)
            .crossfadeout(0.08)
        )
        layers.append(overlay_clip)

    if logo_badge_path and logo_badge_path.exists() and logo_badge_path.stat().st_size > 0:
        logo_w, logo_h = 460, 132
        logo_x = width - logo_w - 24
        logo_y = 22
        logo_clip = (
            ImageClip(str(logo_badge_path))
            .set_duration(duration)
            .set_position((logo_x, logo_y))
            .resize(lambda t: 0.97 + 0.05 * math.sin((t / max(duration, 0.001)) * math.pi))
            .crossfadein(0.12)
            .crossfadeout(0.10)
        )
        layers.append(logo_clip)

    return CompositeVideoClip(layers, size=(width, height)).set_duration(duration)

def render_video(
    scenes: list[StoryboardScene],
    output_path: Path,
    fps: int,
    width: int,
    height: int,
    text_color: str,
    accent_color: str,
    audio_path: Path | None = None,
    show_text: bool = False,
    brand_name: str = "ConectaProIA",
    logo_candidates: list[str] | None = None,
    qr_code_path: str | None = None,
) -> None:
    if not scenes:
        raise RenderError("No scenes available for rendering")

    from moviepy.editor import AudioClip, AudioFileClip, ImageClip, concatenate_audioclips, concatenate_videoclips

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="conecta_scenes_") as temp_dir_raw:
        temp_dir = Path(temp_dir_raw)

        logo_badge_path = temp_dir / "logo_badge.png"
        _render_logo_badge(
            logo_badge_path,
            brand_name=brand_name,
            accent_color=accent_color,
            text_color=text_color,
            logo_candidates=logo_candidates,
        )

        qr_path = _resolve_qr_path(qr_code_path)

        clips = []
        for i, scene in enumerate(scenes, start=1):
            clip = _build_scene_clip(
                scene=scene,
                idx=i,
                temp_dir=temp_dir,
                width=width,
                height=height,
                text_color=text_color,
                accent_color=accent_color,
                show_text=show_text,
                logo_badge_path=logo_badge_path,
            )
            if i > 1:
                clip = clip.crossfadein(0.06)
            clips.append(clip)

        if qr_path is not None:
            endcard_png = temp_dir / "qr_endcard.jpg"
            _render_qr_endcard(
                out_file=endcard_png,
                width=width,
                height=height,
                accent_color=accent_color,
                text_color=text_color,
                qr_path=qr_path,
                brand_name=brand_name,
                logo_candidates=logo_candidates,
            )
            endcard_clip = ImageClip(str(endcard_png)).set_duration(4.2).crossfadein(0.16)
            clips.append(endcard_clip)

        final_clip = concatenate_videoclips(clips, method="compose", padding=-0.04)

        if audio_path and audio_path.exists() and audio_path.stat().st_size > 0:
            audio_clip = AudioFileClip(str(audio_path))
            if audio_clip.duration > 0:
                if audio_clip.duration >= final_clip.duration:
                    final_audio = audio_clip.subclip(0, final_clip.duration)
                else:
                    gap = max(0.0, final_clip.duration - audio_clip.duration)
                    silence = AudioClip(lambda t: 0.0, duration=gap, fps=44100)
                    final_audio = concatenate_audioclips([audio_clip, silence])
                final_clip = final_clip.set_audio(final_audio)

        final_clip.write_videofile(
            str(output_path),
            fps=fps,
            codec="libx264",
            audio_codec="aac",
            verbose=False,
            logger=None,
        )

        try:
            final_clip.close()
        except Exception:
            pass

        for clip in clips:
            try:
                clip.close()
            except Exception:
                pass

def _hex_to_rgba(value: str, alpha: int) -> tuple[int, int, int, int]:
    clean = value.lstrip("#")
    if len(clean) != 6:
        return (0, 0, 0, alpha)
    return (int(clean[0:2], 16), int(clean[2:4], 16), int(clean[4:6], 16), alpha)
