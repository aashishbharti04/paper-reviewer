"""Native desktop launcher for Paper Reviewer.

Runs the FastAPI dashboard in-process and shows it in a CHROMELESS app window
(Microsoft Edge / Chrome in --app mode). This gives a real standalone desktop
window — no tabs, no address bar — while reusing the full web UI (rules,
plagiarism, check page, originality report).

No extra Python dependencies: Edge ships with Windows 10/11, and --app mode
with a dedicated --user-data-dir gives a process whose lifetime matches the
window, so closing the window shuts the app down cleanly.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

import uvicorn

from paper_reviewer_web.app import app


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_for_server(port: int, timeout: float = 20.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/items", timeout=0.5)
            return True
        except Exception:
            time.sleep(0.15)
    return False


def _find_browser() -> str | None:
    candidates = [
        os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
    ]
    for c in candidates:
        if c and os.path.exists(c):
            return c
    return None


def _open_window_then_exit(port: int):
    """Wait for the server, open the chromeless app window, and when the window
    is closed, force-quit the whole process (which stops uvicorn on the main thread)."""
    if not _wait_for_server(port):
        # Server never came up — exit so we don't hang.
        os._exit(1)

    url = f"http://127.0.0.1:{port}"
    browser = _find_browser()

    if not browser:
        import webbrowser
        webbrowser.open(url)
        return  # leave uvicorn running; user closes the console to quit

    # Fresh profile each launch so Edge never restores a stale "last session"
    # pointing at a previous (now-dead) port — which is exactly what shows the
    # ERR_CONNECTION_REFUSED page.
    import shutil
    profile = os.path.join(tempfile.gettempdir(), "PaperReviewerAppProfile")
    shutil.rmtree(profile, ignore_errors=True)
    args = [
        browser,
        f"--app={url}",
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-session-crashed-bubble",
        "--hide-crash-restore-bubble",
        "--window-size=1280,860",
    ]
    try:
        proc = subprocess.Popen(args)
        proc.wait()        # blocks until the app window is closed
    except Exception:
        pass
    os._exit(0)            # window closed -> tear everything down


def main():
    env_port = os.environ.get("PAPER_REVIEWER_PORT")
    port = int(env_port) if env_port and env_port.isdigit() else _free_port()
    # Open the window from a background thread; run uvicorn on the MAIN thread
    # (uvicorn must install signal handlers on the main thread, which fails in a
    # worker thread inside a frozen exe and silently kills the server).
    if os.environ.get("PAPER_REVIEWER_NO_WINDOW") != "1":
        threading.Thread(target=_open_window_then_exit, args=(port,), daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
