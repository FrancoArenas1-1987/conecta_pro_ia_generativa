from pathlib import Path

from conecta_video_ai.models import AssetItem, ScriptSection, VideoScript
from conecta_video_ai.storyboard import build_storyboard


def test_storyboard_duration_is_close_to_target():
    script = VideoScript(
        topic="Prueba WhatsApp",
        hook="Encuentra ayuda profesional por WhatsApp",
        sections=[
            ScriptSection(index=1, title="Paso 1", narration="Explica necesidad por WhatsApp.", onscreen_text="Explica tu necesidad"),
            ScriptSection(index=2, title="Paso 2", narration="Te conectamos con profesional adecuado.", onscreen_text="Te conectamos"),
            ScriptSection(index=3, title="Paso 3", narration="Hablas directo y coordinas detalles.", onscreen_text="Coordinacion directa"),
            ScriptSection(index=4, title="Paso 4", narration="Decides con quien avanzar.", onscreen_text="Tu decides"),
        ],
        cta="Hablar por WhatsApp ahora",
    )
    asset = AssetItem(path=Path("x.jpg"), tags=["kinesiologia"])

    scenes = build_storyboard(script, duration_seconds=45, hero_asset=asset)
    total = sum(s.duration_seconds for s in scenes)

    assert len(scenes) >= 6
    assert 36 <= total <= 54
