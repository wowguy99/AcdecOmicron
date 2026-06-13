@echo off
REM Double-click this file to start the AcDec Flashcard Generator.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1"
pause
