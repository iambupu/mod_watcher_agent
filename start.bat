@echo off
chcp 65001 >nul
if /i "%1"=="/stop" goto :stop
if /i "%1"=="/status" goto :status
if /i "%1"=="/debug" goto :normal
:: Default: open browser after services are ready, then keep running in tray.
powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0start.ps1" -Tray
goto :eof

:normal
:: Debug mode: show console windows
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1"
goto :eof

:stop
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" -Stop
goto :eof

:status
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" -Status
goto :eof
