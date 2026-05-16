@echo off
chcp 65001 >nul
if /i "%1"=="/stop" goto :stop
if /i "%1"=="/status" goto :status

:: Developer mode: backend on 7500, Vite frontend on 7501, with system tray.
powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0start.ps1" -DevMode -Tray
goto :eof

:stop
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" -Stop
goto :eof

:status
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" -Status
goto :eof
