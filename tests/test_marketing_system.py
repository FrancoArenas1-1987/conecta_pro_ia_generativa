from pathlib import Path

from conecta_video_ai.continuity_validator import validate_continuity
from conecta_video_ai.marketing_optimizer import optimize_marketing
from conecta_video_ai.marketing_validator import evaluate_marketing
from conecta_video_ai.models import (
    BrandContext,
    ScriptSection,
    StoryboardScene,
    VideoScript,
    VisualIdentity,
    VoiceProfile,
)
from conecta_video_ai.performance_tracker import PerformanceRecord, PerformanceTracker
from conecta_video_ai.scene_bible import build_scene_bible, build_scene_manifest
from conecta_video_ai.variant_generator import generate_variants, select_best_variant


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
        whatsapp_url="https://wa.me/56983434503",
        visual_identity=VisualIdentity(
            primary_color="#0B132B",
            secondary_color="#1C2541",
            accent_color="#5BC0BE",
            text_color="#FFFFFF",
        ),
    )


def _script() -> VideoScript:
    return VideoScript(
        topic="calefon roto",
        style="conversion",
        hook="¿Te ha fallado un maestro justo hoy?",
        sections=[
            ScriptSection(index=1, title="Problema", narration="No responde y te deja esperando.", onscreen_text="No responde"),
            ScriptSection(index=2, title="Solucion", narration="ConectaProIA por WhatsApp en minutos.", onscreen_text="Conecta por WhatsApp"),
            ScriptSection(index=3, title="Resultado", narration="Llega el profesional y resuelve rapido.", onscreen_text="Problema resuelto"),
        ],
        cta="Escríbenos ahora por WhatsApp. Contactar es 100% gratis",
    )


def _scenes() -> list[StoryboardScene]:
    return [
        StoryboardScene(index=1, headline="Hook", body="¿Te ha fallado un maestro?", duration_seconds=1.2, source_image=Path("a.jpg"), visual_style="conversion"),
        StoryboardScene(index=2, headline="Problema", body="No responde", duration_seconds=1.3, source_image=Path("b.jpg"), visual_style="conversion"),
        StoryboardScene(index=3, headline="Solucion", body="WhatsApp y profesionales", duration_seconds=1.4, source_image=Path("c.jpg"), visual_style="conversion"),
        StoryboardScene(index=4, headline="CTA", body="Escribe ahora", duration_seconds=1.5, source_image=Path("d.jpg"), visual_style="conversion"),
    ]


def test_marketing_validator_and_optimizer_improves_score():
    script = _script().model_copy(update={"hook": "Ayuda", "cta": "Contacta"})
    scenes = _scenes()
    report = evaluate_marketing(script=script, scenes=scenes, objective="captar_clientes")
    assert report.score < 88

    optimized = optimize_marketing(
        script=script,
        storyboard=scenes,
        report=report,
        objective="captar_clientes",
        max_iterations=2,
    )
    improved = evaluate_marketing(script=optimized.script, scenes=optimized.storyboard, objective="captar_clientes")
    assert improved.score >= report.score


def test_scene_bible_and_continuity_validator_passes_on_consistent_data():
    script = _script()
    scenes = _scenes()
    bible = build_scene_bible(context=_context(), topic=script.topic, style=script.style, objective="captar_clientes", script=script)
    manifest = build_scene_manifest(script=script, scenes=scenes, run_id="run1")
    rep = validate_continuity(scene_bible=bible, scene_manifest=manifest, script=script, scenes=scenes)
    assert rep.score >= 70


def test_variant_generation_and_selection():
    script = _script()
    variants = generate_variants(base_script=script, objective="captar_clientes", max_variants=6)
    assert len(variants) == 6

    selected = select_best_variant(
        variants=variants,
        objective="captar_clientes",
        storyboard_factory=lambda s: _scenes(),
    )
    assert selected.selected.variant_id
    assert selected.ranking


def test_performance_tracker_registers_records(tmp_path: Path):
    tracker = PerformanceTracker(tmp_path)
    tracker.register_video(
        PerformanceRecord(
            run_id="run-1",
            variant_id="v1",
            hook="hook",
            narrative="directa",
            cta="cta",
            objective="captar_clientes",
            marketing_score=90,
            continuity_score=88,
            quality_score=91,
            published_at="2026-04-04T10:00:00Z",
            channel="local",
        )
    )
    metrics = tracker.register_metrics(run_id="run-1", clicks=10, whatsapp_messages=4, engagement=0.3, impressions=100)
    assert metrics["performance_score"] >= 0
    assert tracker.load_history()
