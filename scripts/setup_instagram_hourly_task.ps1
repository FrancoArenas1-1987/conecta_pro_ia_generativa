param(
  [string]$TaskName = "ConectaProIA_IG_AutoHourly",
  [string]$PythonExe = "python",
  [string]$WorkDir = "",
  [int]$EveryMinutes = 60,
  [switch]$ForceRecreate
)

$ErrorActionPreference = "Stop"

if ($EveryMinutes -lt 15) {
  throw "EveryMinutes debe ser >= 15"
}

if ([string]::IsNullOrWhiteSpace($WorkDir)) {
  $WorkDir = Split-Path -Parent $PSScriptRoot
}

$resolvedWorkDir = (Resolve-Path -LiteralPath $WorkDir).Path
$wrapper = Join-Path $resolvedWorkDir "scripts\run_instagram_hourly_wrapper.ps1"
if (-not (Test-Path $wrapper)) {
  throw "Wrapper no encontrado: $wrapper"
}

if ($ForceRecreate) {
  try {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction Stop | Out-Null
  } catch {}
}

$execute = "powershell.exe"
$argument = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$wrapper`" -WorkDir `"$resolvedWorkDir`" -PythonExe `"$PythonExe`""

$action = New-ScheduledTaskAction -Execute $execute -Argument $argument -WorkingDirectory $resolvedWorkDir
$trigger = New-ScheduledTaskTrigger `
  -Once `
  -At (Get-Date).AddMinutes(1) `
  -RepetitionInterval (New-TimeSpan -Minutes $EveryMinutes) `
  -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null

Write-Output ("[OK] Task creada/actualizada: " + $TaskName)
Write-Output ("[EVERY_MIN] " + $EveryMinutes)
Write-Output ("[EXEC] " + $execute)
Write-Output ("[ARGS] " + $argument)
