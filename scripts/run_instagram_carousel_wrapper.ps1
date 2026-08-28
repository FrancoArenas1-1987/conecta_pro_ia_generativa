param(
  [string]$WorkDir = "",
  [string]$PythonExe = "python",
  [switch]$Publish,
  [switch]$Force,
  [string]$Theme = "",
  [int]$IntervalHours = 48
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($WorkDir)) {
  $WorkDir = Split-Path -Parent $PSScriptRoot
}

$resolvedWorkDir = (Resolve-Path -LiteralPath $WorkDir).Path
Set-Location $resolvedWorkDir
$env:PYTHONPATH = "src"

$logDir = Join-Path $resolvedWorkDir "output\runs\instagram\carousels"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$lastLog = Join-Path $logDir "wrapper_last.log"

$argsList = @("scripts\run_instagram_carousel_once.py", "--interval-hours", [string]$IntervalHours)
if ($Publish) {
  $argsList += "--publish"
}
if ($Force) {
  $argsList += "--force"
}
if (-not [string]::IsNullOrWhiteSpace($Theme)) {
  $argsList += @("--theme", $Theme)
}

& $PythonExe @argsList *>&1 | Tee-Object -FilePath $lastLog
exit $LASTEXITCODE
