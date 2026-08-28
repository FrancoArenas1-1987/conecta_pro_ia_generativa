param(
  [string]$TaskName = "ConectaProIA_IG_TwiceDaily",
  [string]$PythonExe = "python",
  [string]$WorkDir = "",
  [string]$MorningTime = "09:00",
  [string]$AfternoonTime = "15:00",
  [switch]$ForceRecreate,
  [switch]$DisableLegacyTasks
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($WorkDir)) {
  $WorkDir = Split-Path -Parent $PSScriptRoot
}

$resolvedWorkDir = (Resolve-Path -LiteralPath $WorkDir).Path
$wrapper = Join-Path $resolvedWorkDir "scripts\run_instagram_hourly_wrapper.ps1"
if (-not (Test-Path -LiteralPath $wrapper)) {
  throw "Wrapper no encontrado: $wrapper"
}

try {
  $morning = [datetime]::ParseExact($MorningTime, "HH:mm", $null)
  $afternoon = [datetime]::ParseExact($AfternoonTime, "HH:mm", $null)
}
catch {
  throw "MorningTime y AfternoonTime deben usar formato HH:mm."
}

if ($ForceRecreate) {
  try {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction Stop | Out-Null
  }
  catch {}
}

$execute = "powershell.exe"
$argument = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$wrapper`" -WorkDir `"$resolvedWorkDir`" -PythonExe `"$PythonExe`""
$action = New-ScheduledTaskAction -Execute $execute -Argument $argument -WorkingDirectory $resolvedWorkDir
$morningTrigger = New-ScheduledTaskTrigger -Daily -At $morning
$afternoonTrigger = New-ScheduledTaskTrigger -Daily -At $afternoon
$triggers = @($morningTrigger, $afternoonTrigger)
$settings = New-ScheduledTaskSettingsSet `
  -StartWhenAvailable `
  -AllowStartIfOnBatteries `
  -DontStopIfGoingOnBatteries `
  -MultipleInstances IgnoreNew

Register-ScheduledTask `
  -TaskName $TaskName `
  -Action $action `
  -Trigger $triggers `
  -Settings $settings `
  -Description "Publica automaticamente en Instagram/Facebook todos los dias a las 09:00 y 15:00." `
  -Force | Out-Null

Enable-ScheduledTask -TaskName $TaskName | Out-Null

if ($DisableLegacyTasks) {
  $legacyTaskNames = @(
    "ConectaProIA_IG_AutoHourly",
    "ConectaProIA_IG_Hourly"
  )
  foreach ($legacyName in $legacyTaskNames) {
    try {
      Disable-ScheduledTask -TaskName $legacyName -ErrorAction Stop | Out-Null
      Write-Output ("[DISABLED_LEGACY] " + $legacyName)
    }
    catch {}
  }
}

Write-Output ("[OK] Task creada/actualizada: " + $TaskName)
Write-Output ("[DAILY_AT] " + $MorningTime + ", " + $AfternoonTime)
Write-Output ("[EXEC] " + $execute)
Write-Output ("[ARGS] " + $argument)
