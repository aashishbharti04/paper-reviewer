@echo off
REM Paper Reviewer — one-click install of Python dependencies
setlocal

cd /d "%~dp0"

echo Checking Python...
python --version
if errorlevel 1 (
    echo.
    echo Python is not installed or not on PATH.
    echo Install Python 3.10+ from https://www.python.org/downloads/ and re-run this script.
    pause
    exit /b 1
)

echo.
echo Installing required packages...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo Install failed. See the error messages above.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo Install complete.
echo Next steps:
echo   1. Run  run.bat  to start the app.
echo   2. Open the Settings tab, enable a provider and add your API key,
echo      then click Test to verify it works.
echo      - Groq free key:    https://console.groq.com
echo      - OpenRouter free:  https://openrouter.ai
echo      - Ollama local:     https://ollama.com  (then: ollama pull llama3.1)
echo ============================================================
pause
