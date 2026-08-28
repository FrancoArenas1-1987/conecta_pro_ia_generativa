$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$env:PYTHONPATH = "src"
$logDir = Join-Path $root "output\runs\meta_token_refresh"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$lastLog = Join-Path $logDir "wrapper_last.log"

python scripts/refresh_meta_token.py *>&1 | Tee-Object -FilePath $lastLog
exit $LASTEXITCODE
