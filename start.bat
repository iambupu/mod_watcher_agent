@echo off
chcp 65001 >nul
if /i "%1"=="/stop" goto :stop
if /i "%1"=="/status" goto :status
if /i "%1"=="/debug" goto :normal
:: Default: non-developer friendly launcher.
call "%~dp0start-user.bat"
exit /b %errorlevel%
goto :eof

:normal
:: Developer mode: run frontend dev server with system tray (requires Node.js).
call "%~dp0start-debug.bat"
exit /b %errorlevel%
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
echo [X] Command failed (exit code: %errorlevel%).
echo Press any key to close this window...
pause >nul
exit /b %errorlevel%
