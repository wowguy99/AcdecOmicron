@echo off
REM Build the Windows installer (Setup.exe). Requires Inno Setup 6.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build.ps1" %*
pause
