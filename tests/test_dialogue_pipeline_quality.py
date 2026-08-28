from conecta_video_ai.script_generator import generate_fast_video_script
from conecta_video_ai.models import BrandContext, VisualIdentity, VoiceProfile
from conecta_video_ai.tts_engine import _sanitize_for_voice


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


def test_dialogue_seed_inline_is_cleaned_and_alternated():
    seed = (
        "Persona 1: (preocupado) Se me rompio el calefon / "
        "Persona 2: Usa ConectaProIA por WhatsApp / "
        "Persona 1: ¿Como funciona? / "
        "Persona 2: Es muy facil / "
        "Persona 1: ¿Tiene costo? / "
        "Persona 2: Contactar es gratis"
    )

    script, _ = generate_fast_video_script(
        context=_context(),
        topic="urgencia en casa",
        style="dialogo",
        dialogue_seed=seed,
        duration_seconds=None,
    )

    assert len(script.dialogue) >= 4
    speakers = [t.speaker for t in script.dialogue]
    assert speakers[0] == "Cliente"
    assert speakers[1] == "Asesor"

    for turn in script.dialogue:
        low = turn.line.lower()
        assert "persona 1:" not in low
        assert "persona 2:" not in low
        assert "escena" not in low


def test_voice_sanitize_removes_speaker_labels_and_stage_notes():
    raw = "Persona 1: (triste) Hola, necesito ayuda urgente"
    out = _sanitize_for_voice(raw)
    low = out.lower()

    assert "persona 1" not in low
    assert "triste" not in low
    assert "necesito ayuda" in low
