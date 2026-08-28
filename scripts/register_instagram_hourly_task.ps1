param(
  [string]$TaskName = "ConectaProIA_IG_AutoHourly",
  [string]$WorkingDir = "",
  [int]$EveryMinutes = 60
)

$ErrorActionPreference = "Stop"

if ($EveryMinutes -lt 15) {
  throw "EveryMinutes debe ser >= 15"
}

if ([string]::IsNullOrWhiteSpace($WorkingDir)) {
  $WorkingDir = Split-Path -Parent $PSScriptRoot
}

$resolvedWorkingDir = (Resolve-Path -LiteralPath $WorkingDir).Path
$scriptPath = Join-Path $resolvedWorkingDir "scripts\setup_instagram_hourly_task.ps1"
if (!(Test-Path -LiteralPath $scriptPath)) {
  throw "No existe script: $scriptPath"
}

& powershell -NoProfile -ExecutionPolicy Bypass -File $scriptPath -TaskName $TaskName -WorkDir $resolvedWorkingDir -EveryMinutes $EveryMinutes -ForceRecreate

Write-Host "Tarea '$TaskName' registrada cada $EveryMinutes minutos (wrapper robusto)." -ForegroundColor Green
