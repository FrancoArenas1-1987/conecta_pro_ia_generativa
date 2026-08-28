param(
  [string]$WorkDir = "",
  [string]$PythonExe = "python",
  [switch]$SkipLibrarySync
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($WorkDir)) {
  $WorkDir = Split-Path -Parent $PSScriptRoot
}

$resolvedWorkDir = (Resolve-Path -LiteralPath $WorkDir).Path
$runner = Join-Path $resolvedWorkDir "scripts\run_instagram_autopublish_once.py"
if (-not $SkipLibrarySync) {
  $syncRunner = Join-Path $resolvedWorkDir "scripts\sync_instagram_media_library.py"
  if (Test-Path -LiteralPath $syncRunner) {
    Set-Location $resolvedWorkDir
    $env:PYTHONPATH = "src"
    # Fast sync each hourly cycle; full repair runs in separate maintenance task.
    & $PythonExe $syncRunner "--skip-repair"
  }
}
if (-not (Test-Path -LiteralPath $runner)) {
  throw "Runner no encontrado: $runner"
}

Set-Location $resolvedWorkDir
$env:PYTHONPATH = "src"
& $PythonExe $runner "--use-meta-history"
