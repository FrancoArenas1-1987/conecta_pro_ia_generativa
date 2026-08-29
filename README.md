# ConectaProIA Studio Local

Proyecto end-to-end para generar **videos e imagenes** en tu notebook, con QA automatico, optimizacion de marketing, campañas y aprendizaje historico.

## Nivel producto (implementado)

- Generacion local de reels e imagenes (`studio`) + opcion `comfyui`.
- `scene_bible` + `scene_manifest` por cada video.
- `continuity_validator` (consistencia narrativa/visual).
- `marketing_validator` (hook, claridad, CTA, estructura, comprension rapida, objetivo).
- `marketing_optimizer` automatico (mejora hook/CTA/estructura y revalida).
- `variant_generator` (variantes controladas de hook/narrativa/CTA y seleccion de mejor variante).
- `performance_tracker` (historial por video + metricas reales).
- `insights_engine` (ranking de hooks/CTAs/narrativas + recomendaciones accionables).
- `campaign_engine` (genera multiples videos por segmento/objetivo).
- Publicacion social directa:
  - `youtube` (upload + metricas basicas)
  - `tiktok` (publish init/upload/status + consulta)
  - `local_dryrun` (sin publicar, para pruebas)
- Capa Metricool opcional para import de metricas CSV.

## Estructura de salida

- `output/runs/videos/<run_id>/...`
- `output/runs/images/<run_id>/...`
- `output/tracking/performance_records.jsonl`
- `output/tracking/performance_metrics.json`

En cada run de video se guarda:

- `scene_bible.json`
- `scene_manifest.json`
- `marketing_report.json`
- `continuity_report.json`
- `variants_report.json`
- `insights_snapshot.json`
- `post_review.json`
- `metadata.json`

## Requisitos

1. Python 3.10+
2. Ollama instalado
3. Modelo local descargado:

```powershell
ollama pull gemma3:4b
```

## Instalacion

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
Copy-Item .env.example .env
```

## Web local

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_local_web.ps1
```

Abre: `http://127.0.0.1:7860`

Checks utiles:

- `GET /api/social/check`
- `GET /api/social/requirements?channel=youtube`
- `GET /api/social/requirements?channel=tiktok`

## CLI

Video:

```powershell
python -m conecta_video_ai.cli video --topic "reel de conversion para gasfiter en concepcion" --style conversion --objective captar_clientes --variants
```

Imagen:

```powershell
python -m conecta_video_ai.cli image --context "oferta de atencion rapida" --service "kinesiologia"
```

Campana (JSON):

```powershell
python -m conecta_video_ai.cli campaign --config campaign.json
```

`campaign.json` ejemplo:

```json
{
  "name": "campana_servicios_hogar",
  "base_topic": "ConectaProIA resuelve urgencias del hogar",
  "objective": "captar_clientes",
  "tone": "directo",
  "strategy": "conversion",
  "variants_per_segment": 2,
  "segments": [
    {"service": "gasfiter", "comuna": "Santiago", "user_type": "hogar"},
    {"service": "electricista", "comuna": "Concepcion", "user_type": "hogar"}
  ]
}
```

## Publicacion automatica YouTube/TikTok (sin Metricool)

En `.env`:

```env
SOCIAL_PUBLISH_ENABLED=true
SOCIAL_CHANNEL=youtube
YOUTUBE_ACCESS_TOKEN=
YOUTUBE_REFRESH_TOKEN=
YOUTUBE_CLIENT_ID=
YOUTUBE_CLIENT_SECRET=
YOUTUBE_PRIVACY_STATUS=public
```

Para TikTok:

```env
SOCIAL_PUBLISH_ENABLED=true
SOCIAL_CHANNEL=tiktok
TIKTOK_ACCESS_TOKEN=
TIKTOK_REFRESH_TOKEN=
TIKTOK_CLIENT_KEY=
TIKTOK_CLIENT_SECRET=
TIKTOK_PRIVACY_LEVEL=PUBLIC_TO_EVERYONE
```

Si `SOCIAL_PUBLISH_ENABLED=false`, se usa `local_dryrun` (no publica, pero guarda todo el pipeline).

## Metricool opcional

Si quieres, puedes complementar con CSV exportado desde Metricool para retroalimentar performance histórico.

## OpenAI opcional

Puedes activar imagen por escena y TTS OpenAI con `OPENAI_API_KEY` para subir calidad visual/voz.

## Flujo Publicar Manual (Web)

Ahora el sistema deja los videos en cola para revision y publicacion manual.

- Ir a la pestaña **Publicar**.
- Revisar preview.
- Elegir canal (`youtube` o `tiktok`).
- Click en **Publicar**.

Variables clave en `.env`:

```env
SOCIAL_PUBLISH_ENABLED=true
AUTO_PUBLISH_ON_GENERATE=false
SOCIAL_CHANNEL=youtube
```

Si quieres publicar automaticamente al generar:

```env
AUTO_PUBLISH_ON_GENERATE=true
```

## Automatizacion IG por categorias (nuevo)

Ahora el sistema puede crear borradores de publicaciones Instagram en forma automatica, con rotacion por categoria para no repetir siempre el mismo tipo de mensaje.

Archivos generados por ciclo:

- `output/runs/instagram/drafts/<draft_id>/image.*`
- `output/runs/instagram/drafts/<draft_id>/caption.txt`
- `output/runs/instagram/drafts/<draft_id>/short_text.txt`
- `output/runs/instagram/drafts/<draft_id>/draft.json`
- Catalogo: `output/runs/instagram/catalog/publication_catalog.json`

Categorias base: `config/instagram_publication_categories.yaml`

Comandos CLI:

```powershell
python -m conecta_video_ai.cli ig-auto --publish --use-meta-history
python -m conecta_video_ai.cli ig-list --limit 30
python -m conecta_video_ai.cli ig-catalog --use-meta-history
python -m conecta_video_ai.cli ig-publish --draft-id <draft_id>
```

En la web (`http://127.0.0.1:7860`) usa la pestaña **IG Auto**.
Tambien tienes galeria directa en:

- `http://127.0.0.1:7860/instagram/gallery`

## Programacion diaria recomendada

Ejecuta 1 ciclo manual:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\instagram_auto_once.ps1
```

Runner recomendado para produccion estable (real publish + guardias de cadencia/antispam):

```powershell
python scripts/run_instagram_autopublish_once.py --use-meta-history
```

Nota: este runner valida la ventana horaria local antes de generar o publicar. Por defecto solo publica entre `11:00-20:30` en `America/Santiago`, configurable con `INSTAGRAM_PUBLISH_TIMEZONE` e `INSTAGRAM_PUBLISH_ALLOWED_WINDOWS`.

Registrar tarea diaria en Windows, hasta dos publicaciones por dia en horarios recomendados:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup_instagram_daily_best_times_task.ps1 -DisableLegacyTasks
```

Horarios por defecto:

- Lunes: 14:30 y 19:00
- Martes: 13:30 y 18:30
- Miercoles: 12:30 y 18:30
- Jueves: 12:30 y 16:30
- Viernes: 11:30 y 16:00
- Sabado: 11:00 y 17:00
- Domingo: 13:00 y 18:00

La tarea diaria ejecuta sincronizacion ligera de biblioteca central antes del ciclo de publicacion.

La automatizacion estable ahora incluye:

- guardia de ventana horaria local (`INSTAGRAM_PUBLISH_ALLOWED_WINDOWS`)
- guardia de intervalo minimo de publicacion (`INSTAGRAM_POST_INTERVAL_MINUTES`)
- cooldown anti-spam por error Meta 368
- fallback automatico de video a imagen cuando corresponde
- preflight de targets (fanpage/IG) antes de publicar
- sincronizacion automatica de biblioteca central en cada ciclo
- tarea de mantenimiento de biblioteca central (correccion completa) registrada por `register_full_automation.ps1`

## Sincronizar Biblioteca Central IG (imagenes, videos y audio)

Para unificar historial de drafts en una sola biblioteca por categoria:

```powershell
python .\scripts\sync_instagram_media_library.py
```

Solo auditoria (sin cambios):

```powershell
python .\scripts\sync_instagram_media_library.py --audit-only
```

La biblioteca central queda en `output/runs/instagram/publish_assets/<categoria>/{images,videos,audios}`.

## Limpieza rapida de workspace

Para eliminar cache/artefactos legacy y mantener solo backups recientes de `.env`:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\cleanup_workspace.ps1 -KeepEnvBackups 3
```

## Musica para stories/reels (biblioteca local)

- Carpeta usada por el motor IG: `config/music/story`
- Prioridad: si hay pistas en esa carpeta, se usan antes de la musica sintetica local.
- Fuente actual cargada: Mixkit (royalty-free stock music).

### Branding y contexto de publicaciones IG

El motor IG ahora genera cada publicación con:

- imagen de base (idealmente IA)
- branding estructural en la imagen (logo + WhatsApp + web)
- caption y short_text congruentes al objetivo
- plan horario de publicaciones con contexto por orden

Archivo de planificación:

- `output/runs/instagram/catalog/publication_plan.json`

Flags relevantes:

```env
INSTAGRAM_ENABLE_OPENAI_IMAGES=false
INSTAGRAM_REQUIRE_AI_IMAGE=false
INSTAGRAM_BRANDING_REQUIRED=true
INSTAGRAM_WHATSAPP_CLIENT_URL=https://api.whatsapp.com/send?phone=56983434503
INSTAGRAM_WHATSAPP_PROVIDER_URL=https://api.whatsapp.com/send?phone=56961903199
INSTAGRAM_PUBLISH_MEDIA_MODE=auto
INSTAGRAM_PUBLISH_QUALITY_GATE_ENABLED=false
INSTAGRAM_PUBLISH_QUALITY_MIN_SCORE=90
INSTAGRAM_PUBLISH_REQUIRE_VIDEO_QC=true
INSTAGRAM_PUBLISH_AUTO_VIDEO_FALLBACK_ENABLED=true
INSTAGRAM_PUBLISH_VIDEO_FAILURE_COOLDOWN_MINUTES=360
INSTAGRAM_PUBLISH_PREFLIGHT_TARGETS_ENABLED=true
INSTAGRAM_PUBLISH_PREFLIGHT_TARGETS_STRICT=false
INSTAGRAM_ANTISPAM_COOLDOWN_MINUTES=120
INSTAGRAM_OPENAI_USE_INTERLEAVING=false
```

En produccion estable, la fabrica dedicada `scripts/instagram_image_factory.py` genera imagenes premium con OpenAI, aplica branding/QC y actualiza `imagenes_ig`. Por eso el publicador puede mantener `INSTAGRAM_ENABLE_OPENAI_IMAGES=false` y publicar desde la biblioteca curada.

## Renovacion automatica token Meta

Se agrego renovacion automatica de token para no depender de cambio manual.

1) Ejecutar renovacion una vez:

```powershell
python scripts/refresh_meta_token.py
```

Tambien disponible en 1 click:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\refresh_meta_token.ps1
```

Que actualiza en `.env`:

- `META_USER_ACCESS_TOKEN` (token usuario largo renovado)
- `META_USER_TOKEN_EXPIRES_AT` (fecha UTC de expiracion)
- `META_ACCESS_TOKEN` (token de pagina para Graph)
- `META_PAGE_ID`
- `META_INSTAGRAM_USER_ID` (si aplica)

2) Programar renovacion automatica (recomendado cada 24h):

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\register_meta_token_refresh_task.ps1
```

La tarea crea backup del `.env` antes de escribir cambios.
