# Paper Reviewer (ICCCNet2026)

A desktop / web tool for conference paper screening. It ingests submitted papers
(PDF / DOCX), assigns a publisher bucket from a configurable rules engine, runs
AI-text and plagiarism checks, generates a review, and appends the result to a
Microsoft CMT–style Excel sheet.

There are three ways to run it:

- **Web dashboard** (recommended) — a FastAPI app you open in your browser.
- **Native desktop** — the same web app wrapped in an Edge app-mode window, shipped as a Windows installer.
- **Legacy Tkinter desktop** — the original drag-and-drop UI.

## Download (Windows)

Grab the latest **`PaperReviewer-Setup.exe`** from the
[Releases page](../../releases/latest) and run it. No Python required.

## Run from source

```bash
# 1. Install Python 3.10+  (https://www.python.org/downloads/)
# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure providers (see below)
copy config.json.example config.json   # Windows
# cp config.json.example config.json    # macOS / Linux

# 4. Start the web dashboard
python -m paper_reviewer_web.app
```

Then open <http://localhost:8765>. On Windows you can also just double-click
`run_web.bat` (web) or `run_desktop.bat` (Edge app window).

## Configuration

Provider keys live in `config.json`, which is **git-ignored** so your keys are
never committed. Copy `config.json.example` to `config.json` and fill in your
own keys, or set them later from the app's **Settings** tab.

Supported LLM providers (any one is enough; the app falls back in order):

| Provider   | Free key                          |
|------------|-----------------------------------|
| Groq       | <https://console.groq.com>        |
| OpenRouter | <https://openrouter.ai>           |
| Ollama     | local — <https://ollama.com> (`ollama pull llama3.1`) |

## Project layout

```
paper_reviewer/         Core engine (rules, extraction, plagiarism, providers, Excel I/O)
paper_reviewer_web/     FastAPI dashboard (app.py, templates, static)
desktop_app.py          Edge app-mode launcher for the web dashboard
app.py / app_web.py     PyInstaller entry points
publisher_rules.json    Editable publisher-bucket rules
installer.iss           Inno Setup script for the Windows installer
```

## Notes

- This app processes paper submissions locally and writes to a shared Excel
  sheet (`reviews_output.xlsx`). It has no authentication and is intended for a
  single reviewer / trusted machine, not public hosting.
- The first 7 columns of the output sheet follow the Microsoft CMT export schema
  and are preserved on every append.
