Write-Host "Creando entorno virtual..." -ForegroundColor Cyan
python -m venv .venv

Write-Host "Activando entorno virtual..." -ForegroundColor Cyan
. .\.venv\Scripts\Activate.ps1

Write-Host "Instalando dependencias..." -ForegroundColor Cyan
python -m pip install --upgrade pip
python -m pip install -e .

if (!(Test-Path ".env")) {
  Copy-Item ".env.example" ".env"
  Write-Host ".env creado desde .env.example" -ForegroundColor Green
}

Write-Host "Recuerda instalar Ollama y el modelo local:" -ForegroundColor Yellow
Write-Host "  ollama pull llama3.1:8b" -ForegroundColor Yellow

Write-Host "Iniciar web local:" -ForegroundColor Green
Write-Host "  powershell -ExecutionPolicy Bypass -File .\scripts\start_local_web.ps1" -ForegroundColor Green
