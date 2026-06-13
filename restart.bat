@echo off
REM Stop anything on port 8000, then start the app fresh.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0restart.ps1"
pause
