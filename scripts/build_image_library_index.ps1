param(
  [string]$LibraryRoot = "C:\Franco\conectapro_rrss\biblioteca_ia\raw",
  [string]$OutputFile = "C:\Franco\conectapro_rrss\biblioteca_ia\catalog.json"
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path -LiteralPath $LibraryRoot)) {
  throw "Library root not found: $LibraryRoot"
}

$items = Get-ChildItem -LiteralPath $LibraryRoot -File | Where-Object {
  $_.Extension -match '^(\.png|\.jpg|\.jpeg|\.webp)$'
} | Sort-Object Name | ForEach-Object {
  $name = $_.BaseName.ToLowerInvariant()
  $tokens = ($name -replace '[^a-z0-9_]', '_').Split('_') | Where-Object { $_ -and $_.Length -gt 1 }

  $category = if ($name -like 'problema*') { 'problema' }
  elseif ($name -like 'descubrimiento*' -or $name -like 'contacto*') { 'descubrimiento' }
  elseif ($name -like 'profesional*' -or $name -like 'profesionales*') { 'profesionales' }
  elseif ($name -like 'resultado*') { 'resultado' }
  elseif ($name -like 'fondo*') { 'fondo' }
  else { 'general' }

  [pscustomobject]@{
    file = $_.Name
    path = $_.FullName
    category = $category
    tags = @($tokens)
    bytes = $_.Length
    updated_at = $_.LastWriteTime.ToString('s')
  }
}

$catalog = [pscustomobject]@{
  generated_at = (Get-Date).ToString('s')
  root = (Resolve-Path -LiteralPath $LibraryRoot).Path
  total = @($items).Count
  items = @($items)
}

$catalog | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $OutputFile -Encoding UTF8
Write-Host "Catalog generated:" $OutputFile
