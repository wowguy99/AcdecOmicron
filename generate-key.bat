@echo off
REM Owner-only: generate product keys for recipients (GUI).
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo Virtualenv not found. Create .venv and install backend dependencies first.
    pause
    exit /b 1
)
start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0tools\make_key_gui.py"
