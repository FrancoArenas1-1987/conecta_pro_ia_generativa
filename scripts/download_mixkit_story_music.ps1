param(
    [string]$OutputDir = "config/music/story"
)

$ErrorActionPreference = "Stop"

New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null

$tracks = @(
    @{ id = 130; name = "mixkit-tech-house-vibes-130.mp3" },
    @{ id = 32;  name = "mixkit-driving-ambition-32.mp3" },
    @{ id = 623; name = "mixkit-deep-urban-623.mp3" },
    @{ id = 738; name = "mixkit-hip-hop-02-738.mp3" },
    @{ id = 580; name = "mixkit-pop-rhythm-580.mp3" },
    @{ id = 132; name = "mixkit-trailer-sport-132.mp3" },
    @{ id = 897; name = "mixkit-upbeat-groove-897.mp3" },
    @{ id = 493; name = "mixkit-corporate-drive-493.mp3" },
    @{ id = 614; name = "mixkit-stylish-energy-614.mp3" },
    @{ id = 400; name = "mixkit-electro-pulse-400.mp3" }
)

$headers = @{
    "User-Agent" = "Mozilla/5.0"
    "Referer"    = "https://mixkit.co/free-stock-music/"
}

foreach ($t in $tracks) {
    $url = "https://assets.mixkit.co/music/$($t.id)/$($t.id).mp3"
    $out = Join-Path $OutputDir $t.name
    try {
        Invoke-WebRequest -Uri $url -Headers $headers -OutFile $out -TimeoutSec 90
        $size = (Get-Item $out).Length
        Write-Host "[OK] $($t.name) ($size bytes)"
    }
    catch {
        Write-Warning "No se pudo descargar $($t.name): $($_.Exception.Message)"
    }
}

Write-Host "[done] Mixkit sync complete -> $OutputDir"
