@echo off
chcp 65001 >nul
if /i "%1"=="/stop" goto :stop
if /i "%1"=="/status" goto :status

:: Non-developer mode: static frontend hosted by backend, no Node.js required.
powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0start.ps1" -Tray
goto :eof

:stop
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" -Stop
goto :eof

:status
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" -Status
goto :eof
