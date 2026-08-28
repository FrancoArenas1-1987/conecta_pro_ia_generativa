param(
  [string]$WorkDir = "",
  [string]$PythonExe = "python"
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($WorkDir)) {
  $WorkDir = Split-Path -Parent $PSScriptRoot
}

$resolvedWorkDir = (Resolve-Path -LiteralPath $WorkDir).Path
$runner = Join-Path $resolvedWorkDir "scripts\sync_instagram_media_library.py"
if (-not (Test-Path -LiteralPath $runner)) {
  throw "Runner de mantenimiento no encontrado: $runner"
}

Set-Location $resolvedWorkDir
$env:PYTHONPATH = "src"
& $PythonExe $runner
