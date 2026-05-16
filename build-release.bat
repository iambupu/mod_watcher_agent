@echo off
chcp 65001 >nul
setlocal

:: Developer helper: build a non-developer release zip under ./release/
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\build_release.ps1"

endlocal

