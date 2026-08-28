param(
    [int]$KeepEnvBackups = 5
)

$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $root

Write-Host "[cleanup] Root: $root"

$dirsToRemove = @(
    ".pytest_cache",
    "src/conecta_video_ai_local.egg-info"
)

foreach ($rel in $dirsToRemove) {
    $target = Join-Path $root $rel
    if (Test-Path -LiteralPath $target) {
        Remove-Item -LiteralPath $target -Recurse -Force
        Write-Host "[cleanup] Removed $rel"
    }
}

Get-ChildItem -Path $root -Recurse -Directory -Force |
    Where-Object { $_.Name -eq "__pycache__" } |
    ForEach-Object {
        Remove-Item -LiteralPath $_.FullName -Recurse -Force
        Write-Host "[cleanup] Removed $($_.FullName)"
    }

$envBackups = Get-ChildItem -Path $root -File -Filter ".env.bak_*" |
    Sort-Object LastWriteTime -Descending

if ($envBackups.Count -gt $KeepEnvBackups) {
    $toDelete = $envBackups | Select-Object -Skip $KeepEnvBackups
    foreach ($file in $toDelete) {
        Remove-Item -LiteralPath $file.FullName -Force
        Write-Host "[cleanup] Removed backup $($file.Name)"
    }
}

Write-Host "[cleanup] Done"
