param(
  [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$envPath = Join-Path $ProjectRoot ".env"
if (!(Test-Path $envPath)) {
  Write-Error "No existe .env en $ProjectRoot"
}

$apiKey = $null
Get-Content $envPath | ForEach-Object {
  $line = $_.Trim()
  if ($line -and -not $line.StartsWith("#") -and $line.StartsWith("OPENAI_API_KEY=")) {
    $apiKey = $line.Substring("OPENAI_API_KEY=".Length).Trim()
  }
}

if ([string]::IsNullOrWhiteSpace($apiKey)) {
  Write-Error "OPENAI_API_KEY esta vacia en .env"
}

$env:OPENAI_API_KEY = $apiKey
python -c "import os,sys; from openai import OpenAI; key=os.getenv('OPENAI_API_KEY','').strip();
if not key: print('ERROR: OPENAI_API_KEY empty'); sys.exit(3)

try:
 c=OpenAI(api_key=key); m=c.models.list(); _=next(iter(m.data), None); print('OK: OPENAI_API_KEY valida')
except Exception as e:
 print(f'ERROR: API key invalida o sin permisos: {e}'); sys.exit(4)"
