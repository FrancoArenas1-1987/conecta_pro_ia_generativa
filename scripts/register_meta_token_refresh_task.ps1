param(
  [string]$TaskName = "ConectaProIA_MetaToken_Refresh",
  [string]$WorkingDir = "",
  [int]$EveryHours = 24
)

$ErrorActionPreference = "Stop"

if ($EveryHours -lt 1) {
  throw "EveryHours debe ser >= 1"
}

if ([string]::IsNullOrWhiteSpace($WorkingDir)) {
  $WorkingDir = Split-Path -Parent $PSScriptRoot
}

$resolvedWorkingDir = (Resolve-Path -LiteralPath $WorkingDir).Path
$scriptPath = Join-Path $resolvedWorkingDir "scripts\refresh_meta_token.ps1"
if (!(Test-Path -LiteralPath $scriptPath)) {
  throw "No existe script: $scriptPath"
}

$arg = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$scriptPath`""
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arg -WorkingDirectory $resolvedWorkingDir

$start = (Get-Date).AddMinutes(2)
$interval = New-TimeSpan -Hours $EveryHours
$duration = New-TimeSpan -Days 3650
$trigger = New-ScheduledTaskTrigger -Once -At $start -RepetitionInterval $interval -RepetitionDuration $duration

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Description "Renovacion automatica token Meta (ConectaProIA)" -Force | Out-Null
Write-Host "Tarea '$TaskName' registrada cada $EveryHours horas." -ForegroundColor Green
