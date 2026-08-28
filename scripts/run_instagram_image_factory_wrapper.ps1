param(
  [string]$WorkDir = "",
  [string]$PythonExe = "python",
  [string]$ExtraArgs = ""
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($WorkDir)) {
  $WorkDir = Split-Path -Parent $PSScriptRoot
}

$resolvedWorkDir = (Resolve-Path -LiteralPath $WorkDir).Path
Set-Location $resolvedWorkDir

$logDir = Join-Path $resolvedWorkDir "output\runs\instagram\image_factory"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$lastLog = Join-Path $logDir "wrapper_last.log"

$argsList = @("scripts\run_instagram_image_factory_once.py")
if (-not [string]::IsNullOrWhiteSpace($ExtraArgs)) {
  $argsList += ($ExtraArgs -split " ")
}

& $PythonExe @argsList *>&1 | Tee-Object -FilePath $lastLog
exit $LASTEXITCODE
