#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/conecta-pro-ia-generativa}"
SERVICE_USER="${SERVICE_USER:-$(whoami)}"
SYSTEMD_DIR="${SYSTEMD_DIR:-/etc/systemd/system}"

install_unit() {
  local name="$1"
  local job="$2"
  sudo tee "${SYSTEMD_DIR}/${name}.service" >/dev/null <<EOF
[Unit]
Description=ConectaPro IA Generativa ${job}
Requires=docker.service
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=${SERVICE_USER}
WorkingDirectory=${APP_DIR}
Environment=APP_DIR=${APP_DIR}
ExecStart=${APP_DIR}/scripts/run_prod_job.sh ${job}
EOF
}

install_timer() {
  local name="$1"
  local schedule="$2"
  local randomized_delay="${3:-5m}"
  sudo tee "${SYSTEMD_DIR}/${name}.timer" >/dev/null <<EOF
[Unit]
Description=Timer for ${name}

[Timer]
OnCalendar=${schedule}
RandomizedDelaySec=${randomized_delay}
Persistent=true

[Install]
WantedBy=timers.target
EOF
}

install_unit "conectapro-ig-image-factory" "image-factory"
install_timer "conectapro-ig-image-factory" "hourly" "10m"

install_unit "conectapro-ig-autopublish" "autopublish"
install_timer "conectapro-ig-autopublish" "*-*-* *:15:00" "10m"

install_unit "conectapro-ig-carousel" "carousel"
install_timer "conectapro-ig-carousel" "Mon,Wed,Fri,Sun *-*-* 12:05:00" "20m"

install_unit "conectapro-meta-token-refresh" "token-refresh"
install_timer "conectapro-meta-token-refresh" "*-*-* 03:30:00" "30m"

sudo systemctl daemon-reload
sudo systemctl enable --now \
  conectapro-ig-image-factory.timer \
  conectapro-ig-autopublish.timer \
  conectapro-ig-carousel.timer \
  conectapro-meta-token-refresh.timer

systemctl list-timers "conectapro-*.timer" --no-pager
