"""Build reviewed advertising assets locally; never calls AI or publishing APIs."""
from __future__ import annotations
import argparse
from functools import lru_cache
import hashlib
import html
import json
from pathlib import Path
import subprocess
import sys

import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from conecta_video_ai.publication_checks import FREE_SEARCH, DISCLAIMER, caption_digest, validate_caption

OUT = ROOT / "output/advertising/fresco_2026_11_12"
FF = imageio_ffmpeg.get_ffmpeg_exe()
CONTACT = "https://wa.me/56983434503"
W, H = 1080, 1920
SPECS = [
    {
        "id": "como_buscar_video_v1", "title": "Cómo buscar un servicio",
        "angle": "educacion", "palette": ["#F6F4E9", "#083F33", "#AAE300"],
        "music": "mixkit-corporate-drive-493.mp3",
        "intro": "Empieza por tu necesidad y tu comuna. ConectaProIA te ayuda a encontrar contactos de profesionales y servicios.",
        "scenes": [
            ["¿Buscas un\nprofesional?", "Empieza por contarnos\nqué necesitas."],
            ["Tu comuna\nimporta.", "Indica dónde necesitas\nel servicio."],
            ["Revisa los\ncontactos.", "Consulta disponibilidad y valores\ncon cada profesional."],
            ["Buscar contactos\nes gratis.", "Tú eliges con quién conversar."]
        ]
    },
    {
        "id": "preguntas_antes_contratar_video_v1", "title": "Tres preguntas antes de contratar",
        "angle": "consejos", "palette": ["#101C31", "#FFF7E9", "#9DF3C6"],
        "music": "mixkit-stylish-energy-614.mp3",
        "intro": "Antes de contratar, pregunta por el valor, qué incluye el servicio y la disponibilidad. Guarda esta lista y decide con información. Encuentra contactos con ConectaProIA.",
        "scenes": [
            ["Antes de\ncontratar...", "Tres preguntas para decidir\ncon información."],
            ["¿Cuál es\nel valor?", "Pregunta también qué incluye\nel servicio."],
            ["¿Hay\ndisponibilidad?", "Acuerda fecha, horario\ny condiciones directamente."],
            ["Busca contactos.\nTú decides.", "ConectaProIA te ayuda\na encontrar a quién consultar."]
        ]
    },
    {
        "id": "buscar_sin_costo_video_v1", "title": "Qué es gratis y qué se contrata",
        "angle": "propuesta_de_valor", "palette": ["#F8DED0", "#153E37", "#FF653E"],
        "music": "mixkit-upbeat-groove-897.mp3",
        "intro": "Buscar contactos y contratar un servicio son pasos distintos. ConectaProIA te ayuda a encontrar a quién consultar; acuerda el trabajo directamente con cada profesional.",
        "scenes": [
            ["El servicio\ntiene su valor.", "Cada profesional define\nsus precios y condiciones."],
            ["Buscar contactos\nes gratis.", "ConectaProIA te ayuda\na encontrar a quién consultar."],
            ["Tu próximo\ncontacto.", "Cuéntanos qué necesitas\ny en qué comuna buscas."]
        ]
    }
]
IMAGE_SPECS = [
    ("empieza_por_tu_comuna_v1", "Empieza por tu comuna", "educacion",
     OUT / "empieza_por_tu_comuna_v1.png",
     "¿Cómo empezar? Cuéntanos qué servicio necesitas, indica tu comuna y revisa los contactos disponibles con ConectaProIA.", True),
    ("antes_de_contratar_v1", "Antes de contratar, pregunta esto", "consejos",
     OUT / "antes_de_contratar_v1.png",
     "Tres preguntas para decidir con información: ¿cuál es el valor?, ¿qué incluye? y ¿hay disponibilidad? Guarda esta lista y encuentra contactos con ConectaProIA.", True),
    ("muchos_pendientes_v1", "Un lugar para tus pendientes", "vida_cotidiana",
     OUT / "muchos_pendientes_v1.png",
     "Tu hogar, tus mascotas, tu trabajo o una mudanza: las necesidades cambian. ConectaProIA te ayuda a buscar contactos según tu necesidad y comuna.", True),
    ("profesional_casa_imagen_v1", "Un profesional para tu casa", "hogar",
     ROOT / "output/imagegen/campana_guia/01_profesional_para_tu_casa.png",
     "¿Buscas un profesional o un servicio para tu hogar? Cuéntanos qué necesitas y en qué comuna buscas atención. ConectaProIA te ayuda a encontrar contactos.", False),
    ("muchos_servicios_imagen_v1", "Muchos servicios, un lugar", "variedad",
     ROOT / "output/imagegen/campana_guia/02_muchos_servicios.png",
     "Hay distintas necesidades en tu día a día. Busca contactos de profesionales y servicios con ConectaProIA y consulta las opciones disponibles para tu comuna.", False),
    ("guia_siglo_xxi_imagen_v1", "La guía de servicios del siglo XXI", "marca",
     ROOT / "output/imagegen/campana_guia/03_guia_siglo_xxi.png",
     "Una guía de contactos para el día a día. ConectaProIA te ayuda a encontrar profesionales y servicios según lo que necesitas y dónde buscas atención.", False)
]


def caption(intro):
    text = f"{intro}\n\n{FREE_SEARCH}\n\nCuéntanos qué necesitas y en qué comuna buscas atención.\nWhatsApp: {CONTACT}\n\n{DISCLAIMER}\n\n#ConectaProIA #Servicios #Chile"
    validate_caption(text, whatsapp_url=CONTACT)
    return text


@lru_cache
def font(size, bold=True):
    candidates = [Path("C:/Windows/Fonts") / ("seguibl.ttf" if bold else "segoeui.ttf"),
                  Path("/usr/share/fonts/truetype/dejavu") / ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf")]
    for p in candidates:
        if p.exists():
            return ImageFont.truetype(str(p), size)
    raise RuntimeError("No supported font installed")


def draw_fit(draw, text, x, y, *, size, color, max_width=900, max_height=400, bold=True, spacing=14):
    for n in range(size, 23, -1):
        f = font(n, bold)
        box = draw.multiline_textbbox((x, y), text, font=f, spacing=spacing)
        if box[2] - x <= max_width and box[3] - y <= max_height:
            draw.multiline_text((x, y), text, fill=color, font=f, spacing=spacing)
            return
    raise ValueError("Advertising text exceeds safe layout region: " + text)


def render_scene(spec, index, target):
    bg, ink, accent = spec["palette"]
    im = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(im)
    d.ellipse((770, -150, 1320, 400), fill=accent)
    d.rounded_rectangle((90, 221, 133, 264), radius=12, fill=accent)
    draw_fit(d, "ConectaProIA", 153, 208, size=48, color=ink, max_height=80)
    draw_fit(d, "CONTACTOS PARA TU DÍA A DÍA", 90, 320, size=29, color=ink, max_height=70)
    head, body = spec["scenes"][index]
    draw_fit(d, head, 90, 440, size=88, color=ink, max_height=350, spacing=20)
    d.rounded_rectangle((90, 810, 990, 1170), radius=44, fill=accent)
    draw_fit(d, f"0{index+1}", 130, 840, size=64, color="#102E28", max_height=100)
    draw_fit(d, body, 130, 960, size=39, color="#102E28", max_width=820, max_height=180)
    draw_fit(d, "BUSCAR CONTACTOS ES GRATIS", 90, 1270, size=38, color=ink, max_height=90)
    d.rounded_rectangle((90, 1380, 990, 1490), radius=30, fill=ink)
    draw_fit(d, "ESCRÍBENOS POR WHATSAPP", 130, 1404, size=38, color=bg, max_width=820, max_height=80)
    draw_fit(d, "+56 9 8343 4503", 90, 1540, size=57, color=ink, max_height=90)
    draw_fit(d, "conectaproia.cl", 90, 1630, size=37, color=ink, bold=False, max_height=60)
    draw_fit(d, "El servicio contratado lo cobra\ncada profesional.", 90, 1705, size=29, color=ink, bold=False, max_height=100)
    n = len(spec["scenes"])
    width = 900 / n
    for i in range(n):
        d.rounded_rectangle((90 + i*width, 1830, 90 + (i+1)*width-18, 1838), radius=4,
                            fill=ink if i <= index else accent)
    im.save(target)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def encode_video(spec, folder):
    frames = []
    for i in range(len(spec["scenes"])):
        p = folder / f"{spec['id']}_scene_{i+1}.png"
        render_scene(spec, i, p)
        frames.append(p)
    import numpy as np
    from moviepy.editor import VideoClip, AudioFileClip
    from moviepy.audio.fx.all import audio_loop
    duration, transition = 4.4, .4
    stride = duration-transition
    total = round(duration*len(frames) - transition*(len(frames)-1), 3)
    arrays = [np.asarray(Image.open(p).convert("RGB")) for p in frames]
    def make_frame(t):
        index = min(int(t/stride), len(arrays)-1)
        local = t-index*stride
        if index == 0 or local >= transition:
            return arrays[index]
        progress = max(0, min(1, local/transition))
        if index == 1:
            shift = round(W*progress)
            return np.concatenate([arrays[index-1][:,shift:], arrays[index][:,:shift]], axis=1)
        return (arrays[index-1].astype(np.float32)*(1-progress) + arrays[index].astype(np.float32)*progress).astype(np.uint8)
    target = folder / (spec["id"] + ".mp4")
    music = AudioFileClip(str(ROOT/"config/music/story"/spec["music"]))
    bed = audio_loop(music, duration=total).volumex(.38).audio_fadein(.4).audio_fadeout(1.2)
    video = VideoClip(make_frame, duration=total).set_audio(bed)
    video.write_videofile(str(target), fps=30, codec="libx264", audio_codec="aac", audio_fps=48000,
                         audio_bitrate="192k", bitrate="5000k", preset="veryfast", threads=4,
                         temp_audiofile=str(folder/(spec["id"]+"_audio.m4a")), logger=None,
                         ffmpeg_params=["-pix_fmt","yuv420p","-g","60","-keyint_min","60",
                                        "-sc_threshold","0","-movflags","+faststart","-use_editlist","0"])
    video.close()
    music.close()
    normalize_video_music(target, total)
    cover = folder / (spec["id"] + "_cover.jpg")
    subprocess.run([FF, "-y", "-v", "error", "-i", str(frames[0]), "-q:v", "2", str(cover)], check=True)
    return target, cover, total


def normalize_video_music(target, total):
    normalized = target.with_name(target.stem+"_normalized.mp4")
    subprocess.run([FF, "-y", "-v", "error", "-i", str(target), "-map", "0:v:0", "-map", "0:a:0",
                    "-c:v", "copy", "-af", "loudnorm=I=-18:TP=-1.5:LRA=8",
                    "-c:a", "aac", "-ar", "48000", "-ac", "2", "-b:a", "192k", "-t", str(total),
                    "-movflags", "+faststart", "-use_editlist", "0", str(normalized)], check=True)
    normalized.replace(target)


def convert_image(source, target, *, story=False):
    # Delivery-format conversion only: retain the complete artwork without cropping.
    width, height = (1080, 1920) if story else (1080, 1350)
    filters = f"scale=1080:1350:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=0xF6F4E9,setsar=1"
    subprocess.run([FF, "-y", "-v", "error", "-i", str(source), "-vf", filters,
                    "-frames:v", "1", "-q:v", "2", str(target)], check=True)


def make_entry(code, title, angle, text, **assets):
    return dict(campaign_id=code, title=title, angle=angle, caption=text,
                caption_sha256=caption_digest(text), approval_status="pending_review",
                enabled=False, repeat_after_days=14, **assets)


def gallery(entries, target):
    cards = []
    for e in entries:
        media = (f'<video controls preload="metadata" poster="{html.escape(e["cover"])}" src="{html.escape(e["video"])}"></video>'
                 if e["media_type"] == "video" else f'<img loading="lazy" src="{html.escape(e["image"])}" alt="{html.escape(e["title"])}">')
        story = f'<a href="{html.escape(e["story_image"])}">Versión Story</a>' if e.get("story_image") else ""
        cards.append(f'<article><h2>{html.escape(e["title"])}</h2><p>{html.escape(e["angle"])} · {e["media_type"]}</p>{media}{story}<details><summary>Texto de publicación</summary><p class="caption">{html.escape(e["caption"])}</p></details></article>')
    document = '<!doctype html><html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>ConectaProIA · Biblioteca de publicidad</title><style>body{background:#f6f4e9;color:#163f35;font:16px system-ui;margin:0;padding:32px}main{max-width:1440px;margin:auto}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(290px,1fr));gap:24px}article{background:white;padding:20px;border-radius:20px}img,video{width:100%;max-height:620px;object-fit:contain;background:#e8e9e2;border-radius:12px}.caption{white-space:pre-wrap}h1{font-size:38px}a{color:#005d44}</style><main><h1>Publicidad con distintos ángulos</h1><p>Imágenes de campaña y videos con música. Cada pieza incluye su texto, contacto y condiciones del servicio.</p><div class="grid">' + "".join(cards) + "</div></main></html>"
    target.write_text(document, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--images-only", action="store_true")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    entries = []
    for code, title, angle, source, intro, stories in IMAGE_SPECS:
        if not source.is_file():
            raise FileNotFoundError(source)
        feed, story = OUT/(code+"_feed.jpg"), OUT/(code+"_story.jpg")
        convert_image(source, feed)
        values = dict(media_type="image", image=feed.name, sha256=digest(feed), publish_stories=stories)
        if stories:
            convert_image(source, story, story=True)
            values.update(story_image=story.name, story_sha256=digest(story))
        entries.append(make_entry(code, title, angle, caption(intro), **values))
        print("Image prepared:", code, flush=True)
    if not args.images_only:
        for spec in SPECS:
            video, cover, duration = encode_video(spec, OUT)
            entries.append(make_entry(spec["id"], spec["title"], spec["angle"], caption(spec["intro"]),
                                     media_type="video", video=video.name, cover=cover.name,
                                     duration_seconds=duration, sha256=digest(video), cover_sha256=digest(cover),
                                     publish_stories=True, music=spec["music"]))
            print("Video prepared:", spec["id"], flush=True)
    manifest = {"schema_version": 2, "enabled": False, "min_interval_hours": 24,
                "repeat_after_days": 14, "entries": entries}
    (OUT/"manifest.review.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT/"video_storyboards.json").write_text(json.dumps(SPECS, ensure_ascii=False, indent=2), encoding="utf-8")
    gallery(entries, OUT/"revisar.html")
    print("Review gallery:", OUT/"revisar.html", flush=True)


if __name__ == "__main__":
    main()
