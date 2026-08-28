param(
  [string]$TaskName = "ConectaProIA_IG_Weekdays",
  [string]$PythonExe = "python",
  [string]$WorkDir = "",
  [string]$PublishTime = "14:00",
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
  $scheduledTime = [datetime]::ParseExact($PublishTime, "HH:mm", $null)
}
catch {
  throw "PublishTime debe usar formato HH:mm."
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
$trigger = New-ScheduledTaskTrigger `
  -Weekly `
  -WeeksInterval 1 `
  -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday `
  -At $scheduledTime
$settings = New-ScheduledTaskSettingsSet `
  -StartWhenAvailable `
  -AllowStartIfOnBatteries `
  -DontStopIfGoingOnBatteries `
  -MultipleInstances IgnoreNew

Register-ScheduledTask `
  -TaskName $TaskName `
  -Action $action `
  -Trigger $trigger `
  -Settings $settings `
  -Description "Publica en Instagram/Facebook de lunes a viernes a las 14:00." `
  -Force | Out-Null

Enable-ScheduledTask -TaskName $TaskName | Out-Null

if ($DisableLegacyTasks) {
  $legacyTaskNames = @(
    "ConectaProIA_IG_TwiceDaily",
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
Write-Output ("[WEEKDAYS_AT] Monday-Friday " + $PublishTime)
Write-Output ("[EXEC] " + $execute)
Write-Output ("[ARGS] " + $argument)
