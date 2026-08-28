param(
  [Parameter(Mandatory = $true)]
  [string]$Topic,
  [switch]$NoTTS,
  [string]$Style = "auto",
  [string]$Objective = "captar_clientes"
)

$env:PYTHONPATH = "src"
$args = @("-m", "conecta_video_ai.cli", "video", "--topic", $Topic, "--style", $Style, "--objective", $Objective)
if ($NoTTS) { $args += "--no-tts" }

python @args
