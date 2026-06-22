@echo off
REM Launch the Paper Reviewer web dashboard.
cd /d "%~dp0"
python -m paper_reviewer_web.app
if errorlevel 1 (
    echo.
    echo Web app exited with an error. See messages above.
    pause
)
