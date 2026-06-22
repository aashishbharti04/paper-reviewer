@echo off
REM Build PaperReviewer.exe (NATIVE DESKTOP app) with PyInstaller.
REM Output: dist\PaperReviewer\PaperReviewer.exe + supporting files
REM Running the exe starts the local server and opens a chromeless desktop window.
REM (To build the browser-tab version instead, change app_web.py at the bottom.)

setlocal
cd /d "%~dp0"

echo === Installing PyInstaller (if not already) ===
python -m pip install --upgrade pyinstaller
if errorlevel 1 (
    echo PyInstaller install failed.
    pause
    exit /b 1
)

echo.
echo === Cleaning previous build artifacts ===
if exist build rmdir /s /q build
if exist dist  rmdir /s /q dist
if exist PaperReviewer.spec del PaperReviewer.spec

echo.
echo === Building executable (web dashboard) ===
python -m PyInstaller ^
  --name PaperReviewer ^
  --console ^
  --noconfirm ^
  --clean ^
  --add-data "paper_reviewer_web/templates;paper_reviewer_web/templates" ^
  --add-data "paper_reviewer_web/static;paper_reviewer_web/static" ^
  --collect-all uvicorn ^
  --collect-all fastapi ^
  --collect-all starlette ^
  --collect-all anyio ^
  --collect-all pymupdf ^
  --collect-submodules paper_reviewer ^
  --collect-submodules paper_reviewer_web ^
  --collect-submodules openpyxl ^
  --collect-submodules docx ^
  --hidden-import paper_reviewer_web.app ^
  --hidden-import paper_reviewer_web.tasks ^
  --hidden-import uvicorn.logging ^
  --hidden-import uvicorn.loops.auto ^
  --hidden-import uvicorn.protocols.http.auto ^
  --hidden-import uvicorn.protocols.websockets.auto ^
  --hidden-import uvicorn.lifespan.on ^
  desktop_app.py

if errorlevel 1 (
    echo.
    echo Build failed. See errors above.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo Build complete.
echo   Executable: dist\PaperReviewer\PaperReviewer.exe
echo   Running it opens Paper Reviewer in its own desktop window.
echo.
echo Settings, rules, corpus all save to: %%APPDATA%%\PaperReviewer
echo ============================================================
pause
