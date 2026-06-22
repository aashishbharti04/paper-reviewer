@echo off
REM Paper Reviewer launcher
cd /d "%~dp0"
python -m paper_reviewer.main
if errorlevel 1 (
    echo.
    echo App exited with an error. Check the messages above.
    pause
)
