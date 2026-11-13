from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, request, send_file
import yaml

from .exceptions import ConectaVideoError
from .meta_connector import MetaConnectorError, MetaCredentials, MetaGraphClient
from .models import ImageRequest, VideoRequest
from .pipelines import StudioService
from .settings import load_settings
from .social_connectors import connector_blueprint

app = Flask(__name__)
settings = load_settings()
service = StudioService(settings)
ROOT = Path(__file__).resolve().parents[2]
INDEX_FILE = ROOT / "web" / "index.html"
INSTAGRAM_GALLERY_FILE = ROOT / "web" / "instagram_gallery.html"


def _reload_runtime() -> None:
    global settings, service
    settings = load_settings()
    service = StudioService(settings)


def _infer_style_from_text(text: str) -> str:
    low = text.lower()
    if any(m in low for m in ["reel", "tiktok", "instagram", "viral", "conversion"]):
        return "conversion"
    markers = ["dialogo", "conversacion", "chat", "dos personas", "hablando", "roleplay"]
    return "dialogo" if any(m in low for m in markers) else "promo"


def _descriptor_state_path() -> Path:
    return settings.output_root / "instagram" / "catalog" / "descriptor_bootstrap_state.json"


def _descriptor_assets_root() -> Path:
    return settings.output_root / "instagram" / "publish_assets"


def _ensure_descriptor_file() -> Path:
    path = settings.instagram_category_descriptors_path
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("prompt_framework: {}\ncategories: []\n", encoding="utf-8")
    return path


def _load_descriptors_yaml(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    parsed = yaml.safe_load(text) or {}
    if not isinstance(parsed, dict):
        parsed = {}
    categories = parsed.get("categories")
    if not isinstance(categories, list):
        parsed["categories"] = []
    return parsed


def _load_descriptor_bootstrap_state() -> dict[str, Any]:
    path = _descriptor_state_path()
    fallback = {"generated": {}, "skipped": {}}
    if not path.exists():
        return fallback
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback
    if not isinstance(raw, dict):
        return fallback
    generated = raw.get("generated")
    skipped = raw.get("skipped")
    raw["generated"] = generated if isinstance(generated, dict) else {}
    raw["skipped"] = skipped if isinstance(skipped, dict) else {}
    return raw


def _list_from_payload(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    if isinstance(value, str):
        return [part.strip() for part in value.replace(";", ",").split(",") if part.strip()]
    return []


def _discover_asset_categories() -> list[str]:
    root = _descriptor_assets_root()
    if not root.exists() or not root.is_dir():
        return []
    out: list[str] = []
    for child in root.iterdir():
        if child.is_dir():
            out.append(child.name.strip())
    return sorted([x for x in out if x], key=lambda x: x.lower())


def _descriptor_confidence(row: dict[str, Any]) -> int:
    score = 0
    if str(row.get("label") or "").strip():
        score += 12
    if str(row.get("objective") or "").strip() in {"captar_clientes", "captar_proveedores", "branding"}:
        score += 12
    if str(row.get("category_context") or "").strip():
        score += 10
    if str(row.get("visual_brief") or "").strip():
        score += 10
    keywords = [str(x).strip() for x in (row.get("keywords") or []) if str(x).strip()]
    services = [str(x).strip() for x in (row.get("services") or []) if str(x).strip()]
    if len(keywords) >= 3:
        score += 12
    elif keywords:
        score += 6
    if len(services) >= 2:
        score += 12
    elif services:
        score += 6

    template = row.get("creative_template") if isinstance(row.get("creative_template"), dict) else {}
    if template:
        score += 10
    if int(template.get("min_info_elements") or 0) >= 8:
        score += 5

    analysis = row.get("analysis") if isinstance(row.get("analysis"), dict) else {}
    composition = analysis.get("composition") if isinstance(analysis.get("composition"), dict) else {}
    ocr = analysis.get("ocr") if isinstance(analysis.get("ocr"), dict) else {}
    semantic_tags = [str(x).strip() for x in (analysis.get("semantic_tags") or []) if str(x).strip()]
    if composition.get("safe_text_zone") and composition.get("focal_zone"):
        score += 5
    if bool(ocr.get("available", False)):
        score += 8
    elif str(ocr.get("engine") or "").strip() and str(ocr.get("engine") or "").strip() != "none":
        score += 4
    if len(semantic_tags) >= 5:
        score += 4
    return max(0, min(100, score))


def _default_descripcion_es(row: dict[str, Any]) -> str:
    current = str(row.get("descripcion_es") or "").strip()
    if current:
        return current
    label = str(row.get("label") or row.get("id") or "Categoria").strip()
    context = str(row.get("category_context") or "").strip()
    services = [str(x).strip() for x in (row.get("services") or []) if str(x).strip()]
    services_part = ", ".join(services[:3]) if services else "servicios profesionales"
    if context:
        return f"{label}: {context} Servicios clave: {services_part}."
    return f"{label}: categoria orientada a generar publicaciones consistentes para {services_part}."


def _descriptor_audit_row(
    row: dict[str, Any],
    *,
    generated_map: dict[str, Any],
    skipped_map: dict[str, Any],
) -> dict[str, Any]:
    cat_id = str(row.get("id") or "").strip()
    analysis = row.get("analysis") if isinstance(row.get("analysis"), dict) else {}
    composition = analysis.get("composition") if isinstance(analysis.get("composition"), dict) else {}
    ocr = analysis.get("ocr") if isinstance(analysis.get("ocr"), dict) else {}
    semantic_tags = [str(x).strip() for x in (analysis.get("semantic_tags") or []) if str(x).strip()]
    ref_patterns = [str(x).strip() for x in (row.get("reference_asset_patterns") or []) if str(x).strip()]

    generated = generated_map.get(cat_id) if isinstance(generated_map.get(cat_id), dict) else {}
    skipped = skipped_map.get(cat_id) if isinstance(skipped_map.get(cat_id), dict) else {}
    origin = "auto_generado" if generated else "manual_existente"
    if skipped:
        origin = "pendiente_revision"

    ocr_engine = str(ocr.get("engine") or "none").strip() or "none"
    ocr_available = bool(ocr.get("available", False))
    ocr_used = ocr_engine != "none"

    return {
        "id": cat_id,
        "label": str(row.get("label") or cat_id).strip(),
        "objective": str(row.get("objective") or "").strip(),
        "descripcion_es": _default_descripcion_es(row),
        "category_context": str(row.get("category_context") or "").strip(),
        "visual_brief": str(row.get("visual_brief") or "").strip(),
        "keywords": [str(x).strip() for x in (row.get("keywords") or []) if str(x).strip()],
        "services": [str(x).strip() for x in (row.get("services") or []) if str(x).strip()],
        "image_prompt_templates": [str(x).strip() for x in (row.get("image_prompt_templates") or []) if str(x).strip()][:3],
        "variants": [x for x in (row.get("variants") or []) if isinstance(x, dict)][:2],
        "reference_asset_patterns": ref_patterns,
        "origin": origin,
        "generated_at": str(generated.get("generated_at") or "").strip(),
        "generated_reference": str(generated.get("reference") or "").strip(),
        "skipped_reason": str(skipped.get("reason") or "").strip(),
        "ocr": {
            "used": ocr_used,
            "engine": ocr_engine,
            "available": ocr_available,
            "error": str(ocr.get("error") or "").strip(),
            "line_preview": [str(x).strip() for x in (ocr.get("line_preview") or []) if str(x).strip()][:5],
        },
        "semantic_tags": semantic_tags[:12],
        "composition": {
            "safe_text_zone": str(composition.get("safe_text_zone") or "").strip(),
            "focal_zone": str(composition.get("focal_zone") or "").strip(),
            "vertical_focus": str(composition.get("vertical_focus") or "").strip(),
            "content_density": str(composition.get("content_density") or "").strip(),
            "edge_margin_risk": bool(composition.get("edge_margin_risk", False)),
        },
        "confidence": _descriptor_confidence(row),
    }


@app.get("/")
def index():
    return send_file(INDEX_FILE)


@app.get("/instagram/gallery")
def instagram_gallery():
    return send_file(INSTAGRAM_GALLERY_FILE)


@app.get("/health")
def health():
    return jsonify({"ok": True, "service": "conectaproia-studio-local"})


@app.post("/api/generate")
def api_generate():
    payload = request.get_json(force=True) or {}
    mode = str(payload.get("mode", "")).strip().lower()
    context = str(payload.get("context", "")).strip()

    try:
        if mode == "video":
            enable_tts = bool(payload.get("enable_tts", settings.enable_tts))
            enable_music = bool(payload.get("enable_music", settings.enable_background_music))
            requested_style = str(payload.get("style", "auto")).strip().lower() or "auto"
            dialogue_seed = str(payload.get("dialogue_seed", "")).strip() or None
            auto_idea = bool(payload.get("auto_idea", False))
            use_openai_images = payload.get("use_openai_images", None)
            if use_openai_images is not None:
                use_openai_images = bool(use_openai_images)
            engine = str(payload.get("engine", settings.video_engine)).strip().lower() or settings.video_engine
            objective = str(payload.get("objective", "")).strip().lower() or None
            if objective not in {None, "captar_clientes", "captar_proveedores", "branding"}:
                objective = None
            variants = bool(payload.get("enable_variant_exploration", True))

            if not context and not auto_idea:
                return jsonify({"error": "Ingresa contexto o activa 'auto idea'"}), 400

            if requested_style not in {"promo", "dialogo", "conversion", "auto"}:
                requested_style = "auto"

            if engine not in {"studio", "comfyui"}:
                return jsonify({"error": "Engine invalido. Usa 'studio' o 'comfyui'"}), 400

            resolved_style = requested_style if requested_style != "auto" else _infer_style_from_text(f"{context} {dialogue_seed or ''}")

            duration_raw = payload.get("duration", None)
            duration_seconds = None
            if duration_raw not in (None, "", 0, "0"):
                duration_seconds = int(duration_raw)

            output = service.create_video(
                VideoRequest(
                    topic=context,
                    duration_seconds=duration_seconds,
                    enable_tts=enable_tts,
                    enable_music=enable_music,
                    style=resolved_style,
                    dialogue_seed=dialogue_seed,
                    auto_idea=auto_idea,
                    use_openai_images=use_openai_images,
                    engine=engine,
                    objective=objective,
                    enable_variant_exploration=variants,
                )
            )
        elif mode == "image":
            if not context:
                return jsonify({"error": "El campo contexto es obligatorio para imagen"}), 400

            service_name = str(payload.get("service", "")).strip()
            if not service_name:
                return jsonify({"error": "El campo servicio es obligatorio para imagen"}), 400
            output = service.create_image(ImageRequest(context=context, service=service_name))
        else:
            return jsonify({"error": "Modo invalido. Usa 'video' o 'image'"}), 400

        rel = output.main_file.resolve().relative_to(settings.output_root.resolve())
        file_url = f"/generated/{rel.as_posix()}"
        return jsonify({"ok": True, "run_id": output.run_id, "type": output.type, "file_url": file_url})
    except ConectaVideoError as exc:
        return jsonify({"error": str(exc)}), 500


@app.post("/api/campaign")
def api_campaign():
    payload = request.get_json(force=True) or {}
    try:
        result = service.create_campaign(payload)
        return jsonify(
            {
                "ok": True,
                "campaign_name": result.campaign_name,
                "objective": result.objective,
                "summary": result.summary,
                "runs": result.generated_runs,
            }
        )
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.get("/api/insights")
def api_insights():
    history = service.tracker.load_history()
    metrics = service.tracker.load_metrics()
    from .insights_engine import generate_insights

    rep = generate_insights(history_rows=history, metrics_by_run=metrics)
    return jsonify(
        {
            "generated_at": rep.generated_at,
            "top_variants": rep.top_variants,
            "hook_ranking": rep.hook_ranking,
            "narrative_ranking": rep.narrative_ranking,
            "cta_ranking": rep.cta_ranking,
            "trend_warnings": rep.trend_warnings,
            "recommendations": rep.recommendations,
        }
    )


@app.get("/api/instagram/status")
def api_instagram_status():
    try:
        status = service.instagram_status()
        return jsonify(status)
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.get("/api/instagram/catalog")
def api_instagram_catalog():
    use_meta_history = str(request.args.get("use_meta_history", "true")).strip().lower() != "false"
    try:
        catalog = service.build_instagram_catalog(use_meta_history=use_meta_history)
        return jsonify({"ok": True, "catalog": catalog})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.get("/api/instagram/plan")
def api_instagram_plan():
    try:
        plan = service.get_instagram_plan()
        return jsonify({"ok": True, "plan": plan})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500

@app.get("/api/instagram/drafts")
def api_instagram_drafts():
    limit = int(request.args.get("limit", "40") or "40")
    limit = max(1, min(limit, 300))
    try:
        drafts = service.list_instagram_drafts(limit=limit)
        return jsonify({"ok": True, "count": len(drafts), "items": drafts})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.post("/api/instagram/auto-once")
def api_instagram_auto_once():
    payload = request.get_json(force=True) or {}
    objective = str(payload.get("objective", "")).strip().lower() or None
    if objective not in {None, "captar_clientes", "captar_proveedores", "branding"}:
        objective = None

    category = str(payload.get("category", "")).strip() or None
    publish = bool(payload.get("publish", True))
    simulate_publish = bool(payload.get("simulate_publish", True))
    use_meta_history = bool(payload.get("use_meta_history", True))
    public_image_url = str(payload.get("public_image_url", "")).strip() or None
    public_video_url = str(payload.get("public_video_url", "")).strip() or None

    try:
        result = service.run_instagram_auto_cycle(
            objective=objective,
            force_category=category,
            publish=publish,
            simulate_publish=simulate_publish,
            use_meta_history=use_meta_history,
            public_image_url=public_image_url,
            public_video_url=public_video_url,
        )
        return jsonify(result)
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.post("/api/instagram/drafts/<draft_id>/publish")
def api_instagram_publish_draft(draft_id: str):
    payload = request.get_json(force=True) or {}
    simulate = bool(payload.get("simulate", True))
    public_image_url = str(payload.get("public_image_url", "")).strip() or None
    public_video_url = str(payload.get("public_video_url", "")).strip() or None
    try:
        result = service.publish_instagram_draft(
            draft_id=draft_id,
            simulate=simulate,
            public_image_url=public_image_url,
            public_video_url=public_video_url,
        )
        return jsonify({"ok": True, "draft": result})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.get("/api/instagram/descriptors")
def api_instagram_descriptors_get():
    path = _ensure_descriptor_file()
    text = path.read_text(encoding="utf-8")
    return jsonify({"ok": True, "path": str(path), "content": text})


@app.post("/api/instagram/descriptors")
def api_instagram_descriptors_save():
    payload = request.get_json(force=True) or {}
    content = str(payload.get("content", "") or "")
    if not content.strip():
        return jsonify({"ok": False, "error": "Contenido vacio"}), 400

    try:
        parsed = yaml.safe_load(content) or {}
    except Exception as exc:
        return jsonify({"ok": False, "error": f"YAML invalido: {exc}"}), 400

    if not isinstance(parsed, dict):
        return jsonify({"ok": False, "error": "El YAML debe ser un objeto/mapa"}), 400
    categories = parsed.get("categories")
    if not isinstance(categories, list):
        return jsonify({"ok": False, "error": "El YAML debe incluir 'categories' como lista"}), 400

    seen: set[str] = set()
    for row in categories:
        if not isinstance(row, dict):
            return jsonify({"ok": False, "error": "Cada item de categories debe ser objeto"}), 400
        cat_id = str(row.get("id") or "").strip()
        if not cat_id:
            return jsonify({"ok": False, "error": "Cada categoria debe tener id"}), 400
        if cat_id in seen:
            return jsonify({"ok": False, "error": f"id duplicado: {cat_id}"}), 400
        seen.add(cat_id)

    path = _ensure_descriptor_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    _reload_runtime()
    return jsonify({"ok": True, "path": str(path), "count": len(categories)})


@app.get("/api/instagram/descriptors/audit")
def api_instagram_descriptors_audit():
    path = _ensure_descriptor_file()
    cfg = _load_descriptors_yaml(path)
    rows = [row for row in (cfg.get("categories") or []) if isinstance(row, dict)]
    state = _load_descriptor_bootstrap_state()
    generated_map = state.get("generated") if isinstance(state.get("generated"), dict) else {}
    skipped_map = state.get("skipped") if isinstance(state.get("skipped"), dict) else {}

    descriptors: list[dict[str, Any]] = []
    known_ids: set[str] = set()
    for row in rows:
        cat_id = str(row.get("id") or "").strip()
        if not cat_id:
            continue
        known_ids.add(cat_id)
        descriptors.append(_descriptor_audit_row(row, generated_map=generated_map, skipped_map=skipped_map))

    asset_ids = set(_discover_asset_categories())
    pending_ids = sorted(asset_ids - known_ids)
    pending_new = []
    for cat_id in pending_ids:
        skipped = skipped_map.get(cat_id) if isinstance(skipped_map.get(cat_id), dict) else {}
        pending_new.append(
            {
                "id": cat_id,
                "status": "pendiente_descriptor",
                "reason": str(skipped.get("reason") or "descriptor_missing").strip(),
                "seen_at": str(skipped.get("seen_at") or "").strip(),
            }
        )

    descriptors.sort(key=lambda x: (x.get("id") or "").lower())
    return jsonify(
        {
            "ok": True,
            "path": str(path),
            "state_path": str(_descriptor_state_path()),
            "summary": {
                "total_descriptors": len(descriptors),
                "auto_generated": sum(1 for row in descriptors if row.get("origin") == "auto_generado"),
                "manual_existing": sum(1 for row in descriptors if row.get("origin") == "manual_existente"),
                "pending_review": sum(1 for row in descriptors if row.get("origin") == "pendiente_revision"),
                "new_detected_without_descriptor": len(pending_new),
            },
            "categories": descriptors,
            "pending_new_categories": pending_new,
        }
    )


@app.post("/api/instagram/descriptors/category/<category_id>")
def api_instagram_descriptors_category_save(category_id: str):
    cat_id = str(category_id or "").strip()
    if not cat_id:
        return jsonify({"ok": False, "error": "category_id vacio"}), 400

    payload = request.get_json(force=True) or {}
    path = _ensure_descriptor_file()
    cfg = _load_descriptors_yaml(path)
    categories = [row for row in (cfg.get("categories") or []) if isinstance(row, dict)]

    target: dict[str, Any] | None = None
    for row in categories:
        if str(row.get("id") or "").strip() == cat_id:
            target = row
            break
    if target is None:
        return jsonify({"ok": False, "error": f"No existe categoria: {cat_id}"}), 404

    label = str(payload.get("label") or target.get("label") or "").strip()
    objective = str(payload.get("objective") or target.get("objective") or "").strip().lower()
    category_context = str(payload.get("category_context") or target.get("category_context") or "").strip()
    visual_brief = str(payload.get("visual_brief") or target.get("visual_brief") or "").strip()
    descripcion_es = str(payload.get("descripcion_es") or target.get("descripcion_es") or "").strip()
    keywords = _list_from_payload(payload.get("keywords"))
    services = _list_from_payload(payload.get("services"))
    image_prompt_template = str(payload.get("image_prompt_template") or "").strip()

    if objective not in {"captar_clientes", "captar_proveedores", "branding"}:
        return jsonify({"ok": False, "error": "objective invalido"}), 400
    if not label:
        return jsonify({"ok": False, "error": "label vacio"}), 400
    if not category_context:
        return jsonify({"ok": False, "error": "category_context vacio"}), 400
    if not keywords:
        keywords = [str(x).strip() for x in (target.get("keywords") or []) if str(x).strip()]
    if not services:
        services = [str(x).strip() for x in (target.get("services") or []) if str(x).strip()]
    if not keywords:
        return jsonify({"ok": False, "error": "keywords vacio"}), 400
    if not services:
        return jsonify({"ok": False, "error": "services vacio"}), 400

    target["label"] = label
    target["objective"] = objective
    target["category_context"] = category_context
    target["visual_brief"] = visual_brief
    target["descripcion_es"] = descripcion_es
    target["keywords"] = keywords
    target["services"] = services

    templates = target.get("image_prompt_templates")
    if not isinstance(templates, list):
        templates = []
    templates = [str(x).strip() for x in templates if str(x).strip()]
    if image_prompt_template:
        if templates:
            templates[0] = image_prompt_template
        else:
            templates = [image_prompt_template]
    if templates:
        target["image_prompt_templates"] = templates

    variant_payload = payload.get("variant") if isinstance(payload.get("variant"), dict) else {}
    if variant_payload:
        variants = target.get("variants")
        if not isinstance(variants, list) or not variants or not isinstance(variants[0], dict):
            variants = [{}]
        first = dict(variants[0])
        for key in ["hook", "value", "proof", "cta", "short_text"]:
            value = str(variant_payload.get(key) or first.get(key) or "").strip()
            if value:
                first[key] = value
        variants[0] = first
        target["variants"] = variants

    cfg["categories"] = categories
    path.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
    _reload_runtime()
    return jsonify({"ok": True, "id": cat_id, "path": str(path)})


@app.get("/api/videos/queue")
def api_videos_queue():
    ready_only = str(request.args.get("ready_only", "true")).strip().lower() != "false"
    items = service.list_video_publish_queue(ready_only=ready_only)
    return jsonify({"ok": True, "count": len(items), "items": items})


@app.post("/api/videos/publish")
def api_video_publish():
    payload = request.get_json(force=True) or {}
    run_id = str(payload.get("run_id", "")).strip()
    channel = str(payload.get("channel", "")).strip().lower() or None
    force = bool(payload.get("force", False))

    if not run_id:
        return jsonify({"error": "run_id es obligatorio"}), 400

    try:
        result = service.publish_video_run(run_id=run_id, channel=channel, force=force)
        return jsonify(result)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.get("/api/social/check")
def api_social_check():
    channel = settings.social_channel
    cfg = connector_blueprint(channel)
    missing = [k for k in cfg.required_env if not os.getenv(k)]
    return jsonify(
        {
            "enabled": bool(settings.social_publish_enabled),
            "channel": cfg.channel,
            "auto_publish_on_generate": bool(settings.auto_publish_on_generate),
            "required_env": cfg.required_env,
            "missing_env": missing,
            "ready": (not settings.social_publish_enabled) or len(missing) == 0,
        }
    )


@app.get("/api/social/requirements")
def api_social_requirements():
    channel = str(request.args.get("channel", "local_dryrun"))
    cfg = connector_blueprint(channel)
    return jsonify({"channel": cfg.channel, "required_env": cfg.required_env})


@app.get("/api/meta/check")
def api_meta_check():
    missing = []
    if not (settings.meta_access_token or "").strip():
        missing.append("META_ACCESS_TOKEN")
    if not (settings.meta_page_id or "").strip():
        missing.append("META_PAGE_ID")

    if missing:
        return jsonify(
            {
                "ok": False,
                "ready": False,
                "missing_env": missing,
                "message": "Completa variables Meta en .env para validar Instagram/Facebook",
            }
        ), 400

    media_limit = int(request.args.get("limit", "5") or "5")
    media_limit = max(1, min(media_limit, 25))

    try:
        client = MetaGraphClient(
            MetaCredentials(
                app_id=settings.meta_app_id or "",
                app_secret=settings.meta_app_secret or "",
                access_token=settings.meta_access_token or "",
                page_id=settings.meta_page_id or "",
                instagram_user_id=settings.meta_instagram_user_id,
                graph_version=settings.meta_graph_version,
            )
        )
        report = client.inspect_account(media_limit=media_limit)
        report["ready"] = True
        return jsonify(report)
    except MetaConnectorError as exc:
        return jsonify({"ok": False, "ready": False, "error": str(exc)}), 500


@app.get("/generated/<path:subpath>")
def generated_file(subpath: str):
    target = (settings.output_root / subpath).resolve()
    root = settings.output_root.resolve()
    if root not in target.parents and target != root:
        return jsonify({"error": "Acceso denegado"}), 403
    private_reports = (root / "instagram" / "analytics").resolve()
    if target == private_reports or private_reports in target.parents:
        return jsonify({"error": "Archivo no encontrado"}), 404
    if not target.exists():
        return jsonify({"error": "Archivo no encontrado"}), 404
    return send_file(target)


def main() -> None:
    app.run(host="127.0.0.1", port=7860, debug=False)


if __name__ == "__main__":
    main()




