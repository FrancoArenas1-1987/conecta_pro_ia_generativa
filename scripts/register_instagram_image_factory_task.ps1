param(
  [string]$TaskName = "ConectaProIA_IG_ImageFactoryHourly",
  [string]$PythonExe = "python",
  [string]$WorkDir = "",
  [int]$EveryHours = 1,
  [switch]$ForceRecreate
)

$ErrorActionPreference = "Stop"

if ($EveryHours -lt 1) {
  throw "EveryHours debe ser >= 1"
}

if ([string]::IsNullOrWhiteSpace($WorkDir)) {
  $WorkDir = Split-Path -Parent $PSScriptRoot
}

$resolvedWorkDir = (Resolve-Path -LiteralPath $WorkDir).Path
$wrapper = Join-Path $resolvedWorkDir "scripts\run_instagram_image_factory_wrapper.ps1"
if (-not (Test-Path -LiteralPath $wrapper)) {
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
  -At (Get-Date).AddMinutes(5) `
  -RepetitionInterval (New-TimeSpan -Hours $EveryHours) `
  -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null

Write-Output ("[OK] Task creada/actualizada: " + $TaskName)
Write-Output ("[EVERY_HOURS] " + $EveryHours)
Write-Output ("[EXEC] " + $execute)
Write-Output ("[ARGS] " + $argument)
