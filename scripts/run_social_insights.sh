#!/usr/bin/env bash
set -euo pipefail
APP_DIR="${APP_DIR:-/opt/conecta-pro-ia-generativa}"
cd "$APP_DIR"
mkdir -p logs/prod_jobs
log_file="logs/prod_jobs/insights_$(date -u +%Y%m%dT%H%M%SZ).log"
(
  flock -n 9 || exit 0
  docker compose -f docker-compose.prod.yml --env-file .env run --rm social_automation python scripts/collect_social_insights.py "$@" 2>&1 | tee "$log_file"
) 9>/tmp/conectapro_social_insights.lock
