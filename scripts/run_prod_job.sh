#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/conecta-pro-ia-generativa}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
JOB="${1:-}"

cd "$APP_DIR"
mkdir -p logs/prod_jobs

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
log_file="logs/prod_jobs/${JOB:-unknown}_${timestamp}.log"
lock_file="/tmp/conectapro_ig_${JOB:-unknown}.lock"

run_compose() {
  docker compose -f "$COMPOSE_FILE" --env-file .env run --rm social_automation "$@"
}

case "$JOB" in
  image-factory)
    command=(python scripts/instagram_image_factory.py)
    ;;
  autopublish)
    command=(python scripts/run_instagram_autopublish_once.py --use-meta-history)
    ;;
  carousel)
    command=(python scripts/run_instagram_carousel_once.py --publish)
    ;;
  token-refresh)
    command=(python scripts/refresh_meta_token.py)
    ;;
  readiness)
    command=(python scripts/check_automation_readiness.py)
    ;;
  *)
    echo "Usage: $0 {image-factory|autopublish|carousel|token-refresh|readiness}"
    exit 2
    ;;
esac

echo "[job] ${JOB} started at ${timestamp}" | tee "$log_file"
(
  flock -n 9 || {
    echo "[job] skipped: lock active for ${JOB}" | tee -a "$log_file"
    exit 0
  }
  run_compose "${command[@]}" 2>&1 | tee -a "$log_file"
) 9>"$lock_file"
