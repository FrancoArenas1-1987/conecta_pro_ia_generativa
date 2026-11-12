#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/conecta-pro-ia-generativa}"
SERVICE_USER="${SERVICE_USER:-$(whoami)}"
SYSTEMD_DIR="${SYSTEMD_DIR:-/etc/systemd/system}"
PUBLISH_TZ="${PUBLISH_TZ:-America/Santiago}"

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
  local persistent="${4:-true}"
  local schedules=()
  IFS="|" read -r -a schedules <<<"$schedule"
  {
    cat <<EOF
[Unit]
Description=Timer for ${name}

[Timer]
EOF
    for calendar in "${schedules[@]}"; do
      echo "OnCalendar=${calendar}"
    done
    cat <<EOF
RandomizedDelaySec=${randomized_delay}
Persistent=${persistent}

[Install]
WantedBy=timers.target
EOF
  } | sudo tee "${SYSTEMD_DIR}/${name}.timer" >/dev/null
}

install_unit "conectapro-ig-image-factory" "image-factory"
install_timer "conectapro-ig-image-factory" "hourly" "10m"

install_unit "conectapro-ig-autopublish" "autopublish"
autopublish_schedule="Mon *-*-* 14:30:00 ${PUBLISH_TZ}|Mon *-*-* 19:00:00 ${PUBLISH_TZ}|Tue *-*-* 13:30:00 ${PUBLISH_TZ}|Tue *-*-* 18:30:00 ${PUBLISH_TZ}|Wed *-*-* 12:30:00 ${PUBLISH_TZ}|Wed *-*-* 18:30:00 ${PUBLISH_TZ}|Thu *-*-* 12:30:00 ${PUBLISH_TZ}|Thu *-*-* 16:30:00 ${PUBLISH_TZ}|Fri *-*-* 11:30:00 ${PUBLISH_TZ}|Fri *-*-* 16:00:00 ${PUBLISH_TZ}|Sat *-*-* 11:00:00 ${PUBLISH_TZ}|Sat *-*-* 17:00:00 ${PUBLISH_TZ}|Sun *-*-* 13:00:00 ${PUBLISH_TZ}|Sun *-*-* 18:00:00 ${PUBLISH_TZ}"
install_timer "conectapro-ig-autopublish" "${autopublish_schedule}" "10m" "false"

install_unit "conectapro-ig-carousel" "carousel"
install_timer "conectapro-ig-carousel" "*-*-* 12..20:05,20,35,50:00 ${PUBLISH_TZ}" "0" "false"

install_unit "conectapro-meta-token-refresh" "token-refresh"
install_timer "conectapro-meta-token-refresh" "*-*-* 03:30:00" "30m"

sudo systemctl daemon-reload
sudo systemctl enable --now \
  conectapro-ig-image-factory.timer \
  conectapro-ig-autopublish.timer \
  conectapro-ig-carousel.timer \
  conectapro-meta-token-refresh.timer

systemctl list-timers "conectapro-*.timer" --no-pager
