param(
  [Parameter(Mandatory = $true)]
  [string]$Context,
  [Parameter(Mandatory = $true)]
  [string]$Service,
  [int]$Width = 1080,
  [int]$Height = 1350
)

$env:PYTHONPATH = "src"
python -m conecta_video_ai.cli image --context $Context --service $Service --width $Width --height $Height
