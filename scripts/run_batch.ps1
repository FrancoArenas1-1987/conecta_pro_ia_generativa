param(
  [string]$TopicsFile = "config/topics_seed.txt",
  [switch]$NoTTS,
  [string]$Style = "auto",
  [string]$Objective = "captar_clientes"
)

if (!(Test-Path $TopicsFile)) {
  Write-Error "No existe el archivo de temas: $TopicsFile"
  exit 1
}

$env:PYTHONPATH = "src"
$args = @("-m", "conecta_video_ai.cli", "video", "--topics-file", $TopicsFile, "--style", $Style, "--objective", $Objective)
if ($NoTTS) { $args += "--no-tts" }

python @args
