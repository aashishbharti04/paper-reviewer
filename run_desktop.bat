@echo off
REM Launch Paper Reviewer as a native desktop window (runs from source).
cd /d "%~dp0"
python desktop_app.py
if errorlevel 1 (
    echo.
    echo Desktop app exited with an error. See messages above.
    pause
)
