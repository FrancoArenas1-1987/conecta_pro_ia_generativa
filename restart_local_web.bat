@echo off
setlocal
cd /d %~dp0
powershell -ExecutionPolicy Bypass -File ".\scripts\restart_local_web.ps1"
endlocal
