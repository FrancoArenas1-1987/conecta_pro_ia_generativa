#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/conecta-pro-ia-generativa}"
BRANCH="${BRANCH:-main}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
RUN_READINESS_CHECK="${RUN_READINESS_CHECK:-1}"
INSTALL_TIMERS="${INSTALL_TIMERS:-1}"

cd "$APP_DIR"

git config --global --add safe.directory "$APP_DIR"

if [[ ! -w "$APP_DIR" ]]; then
  echo "[deploy] ERROR: $APP_DIR is not writable by $(whoami). Fix owner with: sudo chown -R $(whoami):$(whoami) $APP_DIR"
  exit 1
fi

if [[ ! -f ".env" ]]; then
  echo "[deploy] ERROR: missing $APP_DIR/.env. Create it from .env.example with production credentials."
  exit 1
fi

mkdir -p output logs imagenes_ig

echo "[deploy] Fetching latest code ($BRANCH)..."
git fetch origin "$BRANCH"
git checkout "$BRANCH"
git reset --hard "origin/$BRANCH"

echo "[deploy] Building production image..."
docker compose -f "$COMPOSE_FILE" --env-file .env build social_automation

if [[ "$RUN_READINESS_CHECK" == "1" ]]; then
  echo "[deploy] Running automation readiness check..."
  docker compose -f "$COMPOSE_FILE" --env-file .env run --rm social_automation python scripts/check_automation_readiness.py
fi

if [[ "$INSTALL_TIMERS" == "1" ]]; then
  echo "[deploy] Installing/updating systemd timers..."
  bash scripts/install_systemd_timers.sh
fi

echo "[deploy] OK: production automation updated."
