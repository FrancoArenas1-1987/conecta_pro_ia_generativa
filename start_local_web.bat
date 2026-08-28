@echo off
setlocal
cd /d %~dp0
set PYTHONPATH=src
python -m conecta_video_ai.webapp
endlocal
