from pathlib import Path

from conecta_video_ai.models import BrandContext, ImageCreative, ScriptSection, VideoScript, VisualIdentity, VoiceProfile
from conecta_video_ai.quality import evaluate_image_creative, evaluate_video_script


def _context() -> BrandContext:
    return BrandContext(
        company_name="ConectaProIA",
        tagline="Conexion confiable por WhatsApp",
        mission="Mision",
        positioning={"core_value": "x", "differentiation": ["y"]},
        brand_promises=["No compartimos datos"],
        audience=["personas"],
        voice=VoiceProfile(tone="claro", style=["simple"], avoid=["promesas absolutas"]),
        key_messages=["WhatsApp"],
        legal_safety=["intermediario"],
        service_scope="Biobio",
        call_to_action="Hablar por WhatsApp ahora",
        visual_identity=VisualIdentity(
            primary_color="#0B132B",
            secondary_color="#1C2541",
            accent_color="#5BC0BE",
            text_color="#FFFFFF",
        ),
    )


def test_video_quality_passes_with_valid_script():
    script = VideoScript(
        topic="Conecta por WhatsApp",
        hook="Encuentra ayuda confiable por WhatsApp en minutos",
        sections=[
            ScriptSection(index=1, title="Paso 1", narration="Escribe por WhatsApp lo que necesitas en detalle.", onscreen_text="Escribe por WhatsApp"),
            ScriptSection(index=2, title="Paso 2", narration="Recibe opciones de profesionales verificados para tu caso.", onscreen_text="Recibe opciones"),
            ScriptSection(index=3, title="Paso 3", narration="Habla directo con el profesional y coordina condiciones.", onscreen_text="Habla directo"),
            ScriptSection(index=4, title="Paso 4", narration="Elige con tranquilidad la opcion que mas te conviene.", onscreen_text="Elige tu opcion"),
        ],
        cta="Hablar por WhatsApp ahora",
    )
    report = evaluate_video_script(script, _context())
    assert report.score >= 85


def test_image_quality_detects_long_copy():
    creative = ImageCreative(
        headline="Headline extremadamente largo para fallar la validacion profesional del sistema",
        subheadline="Texto de apoyo muy largo tambien para forzar errores y validar reglas de calidad automaticas",
        call_to_action="Hablar por WhatsApp ahora mismo por favor",
        service_focus="kinesiologia",
    )
    report = evaluate_image_creative(creative, _context())
    assert report.passed is False
    assert report.issues
