param(
  [string]$TaskName = "ConectaProIA_IG_DailyBestTimes",
  [string]$PythonExe = "python",
  [string]$WorkDir = "",
  [string]$MondayTime = "14:30",
  [string]$MondayTime2 = "19:00",
  [string]$TuesdayTime = "13:30",
  [string]$TuesdayTime2 = "18:30",
  [string]$WednesdayTime = "18:30",
  [string]$WednesdayTime2 = "12:30",
  [string]$ThursdayTime = "12:30",
  [string]$ThursdayTime2 = "16:30",
  [string]$FridayTime = "11:30",
  [string]$FridayTime2 = "16:00",
  [string]$SaturdayTime = "11:00",
  [string]$SaturdayTime2 = "17:00",
  [string]$SundayTime = "18:00",
  [string]$SundayTime2 = "13:00",
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

$schedule = @(
  @{ Day = "Monday"; Time = $MondayTime },
  @{ Day = "Monday"; Time = $MondayTime2 },
  @{ Day = "Tuesday"; Time = $TuesdayTime },
  @{ Day = "Tuesday"; Time = $TuesdayTime2 },
  @{ Day = "Wednesday"; Time = $WednesdayTime },
  @{ Day = "Wednesday"; Time = $WednesdayTime2 },
  @{ Day = "Thursday"; Time = $ThursdayTime },
  @{ Day = "Thursday"; Time = $ThursdayTime2 },
  @{ Day = "Friday"; Time = $FridayTime },
  @{ Day = "Friday"; Time = $FridayTime2 },
  @{ Day = "Saturday"; Time = $SaturdayTime },
  @{ Day = "Saturday"; Time = $SaturdayTime2 },
  @{ Day = "Sunday"; Time = $SundayTime }
  @{ Day = "Sunday"; Time = $SundayTime2 }
)

$triggers = @()
foreach ($slot in $schedule) {
  try {
    $scheduledTime = [datetime]::ParseExact($slot.Time, "HH:mm", $null)
  }
  catch {
    throw ("Horario invalido para " + $slot.Day + ": " + $slot.Time + ". Usa formato HH:mm.")
  }

  $triggers += New-ScheduledTaskTrigger -Weekly -DaysOfWeek $slot.Day -At $scheduledTime
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
$settings = New-ScheduledTaskSettingsSet `
  -StartWhenAvailable `
  -AllowStartIfOnBatteries `
  -DontStopIfGoingOnBatteries `
  -MultipleInstances IgnoreNew

$description = "Publica automaticamente en Instagram/Facebook dos veces al dia en horarios recomendados por ventana de audiencia."

Register-ScheduledTask `
  -TaskName $TaskName `
  -Action $action `
  -Trigger $triggers `
  -Settings $settings `
  -Description $description `
  -Force | Out-Null

Enable-ScheduledTask -TaskName $TaskName | Out-Null

if ($DisableLegacyTasks) {
  $legacyTaskNames = @(
    "ConectaProIA_IG_AutoHourly",
    "ConectaProIA_IG_Hourly",
    "ConectaProIA_IG_Weekdays",
    "ConectaProIA_IG_TwiceDaily"
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
foreach ($slot in $schedule) {
  Write-Output ("[DAILY_AT] " + $slot.Day + " " + $slot.Time)
}
Write-Output ("[EXEC] " + $execute)
Write-Output ("[ARGS] " + $argument)
