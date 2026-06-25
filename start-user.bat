@echo off
chcp 65001 >nul
if /i "%1"=="/stop" goto :stop
if /i "%1"=="/status" goto :status
if /i "%1"=="/bg" goto :bg

:: Non-developer mode (foreground): show startup/install logs and errors.
set "MW_WAIT_FOR_KEY_IN_BAT=1"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" -Tray
set "MW_WAIT_FOR_KEY_IN_BAT="
if errorlevel 1 goto :failed
echo.
echo Press any key to close this window and keep running in tray mode...
pause >nul
goto :eof

:bg
:: Optional background mode for silent tray startup.
powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0start.ps1" -Tray -DetachedTray
if errorlevel 1 goto :failed
goto :eof

:stop
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" -Stop
if errorlevel 1 goto :failed
goto :eof

:status
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" -Status
goto :eof

:failed
echo.
echo [X] Startup failed (exit code: %errorlevel%).
echo Press any key to close this window...
pause >nul
exit /b %errorlevel%
