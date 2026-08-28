$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$env:PYTHONPATH = "src"
$env:PYTHONIOENCODING = "utf-8"
python .\scripts\check_meta_connection.py
exit $LASTEXITCODE