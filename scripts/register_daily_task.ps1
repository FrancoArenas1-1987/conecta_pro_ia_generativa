param(
  [string]$TaskName = "ConectaProIA_Video_Daily",
  [string]$At = "09:00",
  [string]$WorkingDir = (Get-Location).Path
)

$scriptPath = Join-Path $WorkingDir "scripts\run_batch.ps1"
if (!(Test-Path $scriptPath)) {
  Write-Error "No existe el script: $scriptPath"
  exit 1
}

$arg = "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`""
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arg -WorkingDirectory $WorkingDir
$trigger = New-ScheduledTaskTrigger -Daily -At $At

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Description "Generacion diaria de videos ConectaProIA" -Force | Out-Null
Write-Host "Tarea '$TaskName' registrada a las $At" -ForegroundColor Green
