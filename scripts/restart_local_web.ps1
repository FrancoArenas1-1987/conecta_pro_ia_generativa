param(
    [int]$Port = 7860
)

$ErrorActionPreference = "SilentlyContinue"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Host "[ConectaProIA] Reiniciando servidor local en puerto $Port..."

# Intento principal: Get-NetTCPConnection (si esta disponible en el sistema)
$listenerPids = @()
try {
    $listenerPids = Get-NetTCPConnection -LocalPort $Port -State Listen | Select-Object -ExpandProperty OwningProcess -Unique
} catch {
    $listenerPids = @()
}

# Fallback: netstat
if (-not $listenerPids -or $listenerPids.Count -eq 0) {
    $netstatLines = netstat -ano | Select-String ":$Port"
    foreach ($line in $netstatLines) {
        $parts = ($line.ToString() -split "\s+") | Where-Object { $_ -ne "" }
        if ($parts.Count -ge 5) {
            $pid = 0
            if ([int]::TryParse($parts[-1], [ref]$pid)) {
                if ($pid -gt 0) {
                    $listenerPids += $pid
                }
            }
        }
    }
    $listenerPids = $listenerPids | Select-Object -Unique
}

if ($listenerPids.Count -gt 0) {
    foreach ($pid in $listenerPids) {
        Write-Host "[ConectaProIA] Cerrando proceso PID $pid en puerto $Port..."
        Stop-Process -Id $pid -Force
    }
    Start-Sleep -Milliseconds 600
} else {
    Write-Host "[ConectaProIA] No habia servidor activo en puerto $Port."
}

$env:PYTHONPATH = "src"
Write-Host "[ConectaProIA] Iniciando servidor web..."
python -m conecta_video_ai.webapp
