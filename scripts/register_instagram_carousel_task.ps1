param(
  [string]$TaskName = "ConectaProIA_IG_Carousel_Every2Days",
  [string]$WorkDir = "",
  [string]$PythonExe = "python",
  [string]$At = "12:45",
  [int]$DaysInterval = 1,
  [int]$GuardHours = 48,
  [switch]$ForceRecreate
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($WorkDir)) {
  $WorkDir = Split-Path -Parent $PSScriptRoot
}

$resolvedWorkDir = (Resolve-Path -LiteralPath $WorkDir).Path
$wrapper = Join-Path $resolvedWorkDir "scripts\run_instagram_carousel_wrapper.ps1"
if (-not (Test-Path -LiteralPath $wrapper)) {
  throw "Wrapper no encontrado: $wrapper"
}

$time = [datetime]::ParseExact($At, "HH:mm", $null)
$trigger = New-ScheduledTaskTrigger -Daily -At $time
$trigger.DaysInterval = [Math]::Max(1, $DaysInterval)

$arguments = @(
  "-NoProfile",
  "-ExecutionPolicy", "Bypass",
  "-WindowStyle", "Hidden",
  "-File", "`"$wrapper`"",
  "-WorkDir", "`"$resolvedWorkDir`"",
  "-PythonExe", "`"$PythonExe`"",
  "-Publish",
  "-IntervalHours", "$GuardHours"
) -join " "

$action = New-ScheduledTaskAction `
  -Execute "powershell.exe" `
  -Argument $arguments `
  -WorkingDirectory $resolvedWorkDir

$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
  -MultipleInstances IgnoreNew `
  -StartWhenAvailable `
  -AllowStartIfOnBatteries `
  -DontStopIfGoingOnBatteries `
  -ExecutionTimeLimit (New-TimeSpan -Minutes 20)

if ($ForceRecreate) {
  Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue | Out-Null
}

Register-ScheduledTask `
  -TaskName $TaskName `
  -Action $action `
  -Trigger $trigger `
  -Principal $principal `
  -Settings $settings `
  -Description "Evalua carrusel IG/FB ConectaProIA cada $DaysInterval dia(s) y publica solo si la guardia interna de $GuardHours horas lo permite." `
  -Force | Out-Null

Enable-ScheduledTask -TaskName $TaskName | Out-Null

Write-Output ("[OK] Task creada/actualizada: " + $TaskName)
Write-Output ("[OK] Frecuencia de evaluacion: cada " + $DaysInterval + " dia(s) a las " + $At + ", guardia de publicacion " + $GuardHours + "h")
