# Despliegue productivo en VPS

Este proyecto corre independiente de `conectapro-platform`. GitHub actualiza el codigo en el VPS y systemd ejecuta los jobs automaticos.

## 1. GitHub

Configura el repositorio:

```powershell
git remote add origin https://github.com/FrancoArenas1-1987/conecta_pro_ia_generativa.git
git branch -M main
git push -u origin main
```

Secrets requeridos en GitHub Actions:

- `PROD_HOST`: IP o host del VPS.
- `PROD_PORT`: puerto SSH, normalmente `22`.
- `PROD_USER`: usuario Linux que administra el proyecto.
- `PROD_SSH_KEY`: llave privada SSH.
- `PROD_APP_DIR`: `/opt/conecta-pro-ia-generativa`.

Variables opcionales del repositorio:

- `RUN_READINESS_CHECK`: `1` por defecto.
- `INSTALL_TIMERS`: `1` por defecto.

## 2. VPS

Instala Docker y clona el repo:

```bash
sudo apt update
sudo apt install -y ca-certificates curl gnupg git
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /usr/share/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker $USER
```

Reingresa por SSH y luego:

```bash
sudo mkdir -p /opt/conecta-pro-ia-generativa
sudo chown -R $USER:$USER /opt/conecta-pro-ia-generativa
git clone https://github.com/FrancoArenas1-1987/conecta_pro_ia_generativa.git /opt/conecta-pro-ia-generativa
cd /opt/conecta-pro-ia-generativa
cp .env.example .env
nano .env
```

Variables minimas de produccion:

```env
CP_DB_HOST=127.0.0.1
CP_DB_PORT=5432
CP_DB_NAME=conectapro
CP_DB_USER=conectapro
CP_DB_PASSWORD=<misma-password-postgres-de-conectapro-platform>
OPENAI_API_KEY=...
META_APP_ID=...
META_APP_SECRET=...
META_ACCESS_TOKEN=...
META_USER_ACCESS_TOKEN=...
META_USER_TOKEN_EXPIRES_AT=...
META_PAGE_ID=...
META_INSTAGRAM_USER_ID=...
INSTAGRAM_SIMULATE_PUBLISH=false
INSTAGRAM_ENABLE_OPENAI_IMAGES=false
INSTAGRAM_REQUIRE_AI_IMAGE=false
INSTAGRAM_WHATSAPP_CLIENT_URL=https://api.whatsapp.com/send?phone=56983434503
INSTAGRAM_WHATSAPP_PROVIDER_URL=https://api.whatsapp.com/send?phone=56961903199
```

El compose usa `network_mode: host` porque en Linux permite que el contenedor independiente conecte a la DB publicada por `conectapro-platform` en `127.0.0.1:5432`, sin mezclar repos ni servicios.

La generacion de imagenes premium queda a cargo de `scripts/instagram_image_factory.py`. Por eso en produccion conviene mantener `INSTAGRAM_ENABLE_OPENAI_IMAGES=false`: el publicador no regenera imagenes inline, sino que publica desde `imagenes_ig`, donde la fabrica va agregando/actualizando assets con QC.

Usa `IG_IMAGE_FACTORY_MAX_ATTEMPTS=1` para controlar gasto. El layout productivo encaja la imagen base con margen seguro y valida una version proxy sin textos para no gastar reintentos por falsos positivos del branding/footer.

Primer deploy manual:

```bash
bash scripts/deploy_prod.sh
```

## 3. Jobs automaticos

El deploy instala estos timers:

- `conectapro-ig-image-factory.timer`: genera o repara imagenes.
- `conectapro-ig-autopublish.timer`: publica feed/story con guardias internas.
- `conectapro-ig-carousel.timer`: publica carruseles con imagenes nuevas.
- `conectapro-meta-token-refresh.timer`: renueva tokens Meta.

Comandos utiles:

```bash
systemctl list-timers "conectapro-*.timer"
journalctl -u conectapro-ig-autopublish.service -n 100 --no-pager
tail -n 100 logs/prod_jobs/autopublish_*.log
docker compose -f docker-compose.prod.yml --env-file .env run --rm social_automation python scripts/check_automation_readiness.py
```

## 4. Ejecucion manual

```bash
./scripts/run_prod_job.sh image-factory
./scripts/run_prod_job.sh autopublish
./scripts/run_prod_job.sh carousel
./scripts/run_prod_job.sh token-refresh
```
