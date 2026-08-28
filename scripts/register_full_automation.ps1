param(
  [string]$WorkingDir = "",
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
  [int]$ImageFactoryEveryHours = 1,
  [int]$LibraryMaintenanceEveryHours = 24,
  [int]$TokenEveryHours = 24,
  [string]$CarouselTime = "12:45",
  [int]$CarouselGuardHours = 48,
  [string]$RunSmokeNow = "false"
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($WorkingDir)) {
  $WorkingDir = Split-Path -Parent $PSScriptRoot
}
$resolvedWorkingDir = (Resolve-Path -LiteralPath $WorkingDir).Path
Set-Location $resolvedWorkingDir

$runSmoke = @("1", "true", "yes", "si", "on") -contains ($RunSmokeNow.ToLowerInvariant())

Write-Host "Registrando tarea de refresh token..." -ForegroundColor Cyan
& ".\scripts\register_meta_token_refresh_task.ps1" -WorkingDir $resolvedWorkingDir -EveryHours $TokenEveryHours

Write-Host "Registrando tarea de publicacion IG automatica..." -ForegroundColor Cyan
& ".\scripts\setup_instagram_daily_best_times_task.ps1" `
  -TaskName "ConectaProIA_IG_DailyBestTimes" `
  -WorkDir $resolvedWorkingDir `
  -MondayTime $MondayTime `
  -MondayTime2 $MondayTime2 `
  -TuesdayTime $TuesdayTime `
  -TuesdayTime2 $TuesdayTime2 `
  -WednesdayTime $WednesdayTime `
  -WednesdayTime2 $WednesdayTime2 `
  -ThursdayTime $ThursdayTime `
  -ThursdayTime2 $ThursdayTime2 `
  -FridayTime $FridayTime `
  -FridayTime2 $FridayTime2 `
  -SaturdayTime $SaturdayTime `
  -SaturdayTime2 $SaturdayTime2 `
  -SundayTime $SundayTime `
  -SundayTime2 $SundayTime2 `
  -ForceRecreate `
  -DisableLegacyTasks

Write-Host "Registrando mantenimiento de biblioteca central IG..." -ForegroundColor Cyan
& ".\scripts\register_instagram_library_maintenance_task.ps1" -TaskName "ConectaProIA_IG_Library_Maintenance" -WorkDir $resolvedWorkingDir -EveryHours $LibraryMaintenanceEveryHours -ForceRecreate

Write-Host "Registrando fabrica horaria de imagenes IG con limite diario por exito..." -ForegroundColor Cyan
& ".\scripts\register_instagram_image_factory_task.ps1" -TaskName "ConectaProIA_IG_ImageFactoryHourly" -WorkDir $resolvedWorkingDir -EveryHours $ImageFactoryEveryHours -ForceRecreate

Write-Host "Registrando carrusel IG/FB con evaluacion diaria y guardia interna..." -ForegroundColor Cyan
& ".\scripts\register_instagram_carousel_task.ps1" `
  -TaskName "ConectaProIA_IG_Carousel_Every2Days" `
  -WorkDir $resolvedWorkingDir `
  -At $CarouselTime `
  -DaysInterval 1 `
  -GuardHours $CarouselGuardHours `
  -ForceRecreate

$taskNames = @(
  "ConectaProIA_IG_DailyBestTimes",
  "ConectaProIA_IG_ImageFactoryHourly",
  "ConectaProIA_IG_Library_Maintenance",
  "ConectaProIA_IG_Carousel_Every2Days",
  "ConectaProIA_MetaToken_Refresh"
)
foreach ($taskName in $taskNames) {
  Enable-ScheduledTask -TaskName $taskName | Out-Null
}

if ($runSmoke) {
  Write-Host "Ejecutando smoke test de ciclo IG real (1 vez)..." -ForegroundColor Cyan
  & ".\scripts\run_instagram_hourly_wrapper.ps1" -WorkDir $resolvedWorkingDir
}

Write-Host "Automatizacion completa registrada." -ForegroundColor Green
