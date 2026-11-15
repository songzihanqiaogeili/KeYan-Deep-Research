@echo off
chcp 65001 >nul
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-scientific.ps1" -OpenBrowser
echo.
echo Workbench stopped. Keep this window open while using the app.
pause
