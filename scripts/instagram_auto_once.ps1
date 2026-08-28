param(
  [switch]$UseMetaHistory = $true,
  [string]$Objective = "captar_clientes",
  [string]$Category = "",
  [string]$PublicImageUrl = "",
  [ValidateSet("auto","user_refresh","system_user")]
  [string]$TokenMode = "auto",
  [int]$MinMinutesBetweenPublish = 50
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$mutexName = "Global\ConectaProIA_IG_Auto_Publish_Lock"
$mutex = New-Object System.Threading.Mutex($false, $mutexName)
$hasLock = $false

function Get-LastPublishedUtc {
  $draftsRoot = Join-Path $root "output\runs\instagram\drafts"
  if (-not (Test-Path $draftsRoot)) {
    return $null
  }

  $latest = $null
  $draftDirs = Get-ChildItem -Path $draftsRoot -Directory -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending
  foreach ($d in $draftDirs) {
    $jsonPath = Join-Path $d.FullName "draft.json"
    if (-not (Test-Path $jsonPath)) {
      continue
    }

    try {
      $obj = Get-Content $jsonPath -Raw | ConvertFrom-Json
      if ($obj.status -notin @("published", "published_with_errors")) {
        continue
      }
      $publishedAt = [string]$obj.published_at
      if ([string]::IsNullOrWhiteSpace($publishedAt)) {
        continue
      }
      $ts = [datetimeoffset]::Parse($publishedAt).ToUniversalTime()
      if ($null -eq $latest -or $ts -gt $latest) {
        $latest = $ts
      }
    }
    catch {
      continue
    }
  }

  return $latest
}

try {
  $hasLock = $mutex.WaitOne(0)
  if (-not $hasLock) {
    Write-Host "Otro proceso de publicacion IG ya esta en ejecucion. Se omite este ciclo para evitar duplicados." -ForegroundColor Yellow
    exit 0
  }

  # Anti-duplicado por ventana temporal.
  $lastPublished = Get-LastPublishedUtc
  if ($lastPublished -ne $null -and $MinMinutesBetweenPublish -gt 0) {
    $now = [datetimeoffset]::UtcNow
    $delta = $now - $lastPublished
    if ($delta.TotalMinutes -lt $MinMinutesBetweenPublish) {
      $remaining = [math]::Ceiling($MinMinutesBetweenPublish - $delta.TotalMinutes)
      Write-Host "Publicacion omitida para evitar duplicados: ultima publicacion hace $([math]::Round($delta.TotalMinutes,1)) min. Espera aprox $remaining min." -ForegroundColor Yellow
      exit 0
    }
  }

  $env:PYTHONPATH = "src"

  $resolvedTokenMode = $TokenMode
  if ($TokenMode -eq "auto") {
    $resolvedTokenMode = (python -c "from conecta_video_ai.settings import load_settings; print((load_settings().meta_token_mode or 'user_refresh').strip().lower())").Trim()
    if (-not $resolvedTokenMode) {
      $resolvedTokenMode = "user_refresh"
    }
  }

  # 1) Token handling according to mode.
  if ($resolvedTokenMode -eq "system_user") {
    Write-Host "Modo token: system_user (se omite refresh automatico)." -ForegroundColor Yellow
  } else {
    python scripts/refresh_meta_token.py | Out-Null
    if ($LASTEXITCODE -ne 0) {
      throw "Fallo refresh de token Meta antes de publicar IG."
    }
  }

  # 2) Execute real IG publish cycle.
  $args = @("-m", "conecta_video_ai.cli", "ig-auto", "--publish", "--real-publish", "--objective", $Objective)
  if ($UseMetaHistory) {
    $args += "--use-meta-history"
  } else {
    $args += "--no-use-meta-history"
  }
  if ($Category) {
    $args += @("--category", $Category)
  }
  if ($PublicImageUrl) {
    $args += @("--public-image-url", $PublicImageUrl)
  }

  python @args
  if ($LASTEXITCODE -ne 0) {
    throw "Fallo ciclo IG real"
  }
}
finally {
  if ($hasLock) {
    $mutex.ReleaseMutex() | Out-Null
  }
  $mutex.Dispose()
}
