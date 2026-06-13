@echo off
REM Double-click to build AcDecFlashcards-Setup.exe (see packaging\output\).
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0packaging\build.ps1" %*
pause
