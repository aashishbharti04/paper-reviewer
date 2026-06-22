"""Native desktop launcher for Paper Reviewer.

Runs the FastAPI dashboard in-process and shows it in a CHROMELESS app window
(Microsoft Edge / Chrome in --app mode). This gives a real standalone desktop
window — no tabs, no address bar — while reusing the full web UI (rules,
plagiarism, check page, originality report).

No extra Python dependencies: Edge ships with Windows 10/11, and --app mode
with a dedicated --user-data-dir gives a process whose lifetime matches the
window, so closing the window shuts the app down cleanly.

Robustness (why this file is more than a one-liner):
  * Single-instance: if a healthy server is already running (lock file +
    /api/items probe), a second launch just opens a window pointing at the
    existing port and exits — it never starts a competing server. This prevents
    the classic ERR_CONNECTION_REFUSED where a double-launch tears down the
    first server's port out from under its window.
  * Quick-exit guard: if the Edge child process exits almost immediately it
    means the window was handed off to another Edge process rather than truly
    closed, so we DON'T kill the server — we keep it alive.
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


def _state_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    d = Path(base) / "PaperReviewer"
    d.mkdir(parents=True, exist_ok=True)
    return d


LOCK_FILE = _state_dir() / "app.lock"
APP_PROFILE = os.path.join(tempfile.gettempdir(), "PaperReviewerAppProfile")


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _server_healthy(port: int, timeout: float = 0.6) -> bool:
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/api/items", timeout=timeout)
        return True
    except Exception:
        return False


def _read_lock_port() -> int | None:
    try:
        return int(LOCK_FILE.read_text(encoding="utf-8").strip())
    except Exception:
        return None


def _write_lock(port: int) -> None:
    try:
        LOCK_FILE.write_text(str(port), encoding="utf-8")
    except Exception:
        pass


def _wait_for_server(port: int, timeout: float = 20.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _server_healthy(port, timeout=0.5):
            return True
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


def _edge_args(browser: str, url: str) -> list[str]:
    return [
        browser,
        f"--app={url}",
        f"--user-data-dir={APP_PROFILE}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-session-crashed-bubble",
        "--hide-crash-restore-bubble",
        "--window-size=1280,860",
    ]


def _open_existing_window(port: int) -> None:
    """Second-launch path: a server is already running — just surface a window
    pointing at it, then let this process exit without starting/stopping anything."""
    url = f"http://127.0.0.1:{port}"
    browser = _find_browser()
    if not browser:
        import webbrowser
        webbrowser.open(url)
        return
    try:
        # Same profile -> Edge focuses/reopens the existing app window.
        subprocess.Popen(_edge_args(browser, url))
    except Exception:
        import webbrowser
        webbrowser.open(url)


def _open_window_then_exit(port: int):
    """Wait for the server, open the chromeless app window, and when the window is
    genuinely closed, force-quit the whole process (stopping uvicorn on the main
    thread). Guards against Edge handing the window off (quick child exit)."""
    if not _wait_for_server(port):
        os._exit(1)  # server never came up — don't hang

    url = f"http://127.0.0.1:{port}"
    browser = _find_browser()

    if not browser:
        import webbrowser
        webbrowser.open(url)
        return  # leave uvicorn running; user closes the console to quit

    # Fresh profile each launch so Edge never restores a stale "last session"
    # pointing at a previous (now-dead) port.
    import shutil
    shutil.rmtree(APP_PROFILE, ignore_errors=True)

    while True:
        start = time.time()
        try:
            proc = subprocess.Popen(_edge_args(browser, url))
            proc.wait()  # blocks until this Edge process ends
        except Exception:
            break
        elapsed = time.time() - start
        # If Edge returned almost instantly, the window was handed off to another
        # Edge process rather than closed by the user. Keep the server alive: wait
        # until the window is truly gone (the URL keeps loading) before exiting.
        if elapsed < 4.0:
            # Give the handed-off window a moment, then watch the server: as long
            # as the user keeps the window open the server should keep serving.
            # We simply stop micromanaging and let the process live; exit only when
            # the machine/user kills it. Re-loop would spin, so break to a wait.
            _idle_until_killed()
            break
        else:
            break
    os._exit(0)  # window closed -> tear everything down


def _idle_until_killed() -> None:
    """Block forever (used after an Edge handoff) so uvicorn keeps serving the
    handed-off window. The process is torn down when the user quits via the
    console window or Task Manager."""
    while True:
        time.sleep(3600)


def main():
    env_port = os.environ.get("PAPER_REVIEWER_PORT")

    # ---- Single-instance guard -------------------------------------------------
    # If another copy is already serving, don't start a second server (which would
    # grab a different port and leave windows pointing at dead ports). Just show a
    # window for the running instance and quit.
    if os.environ.get("PAPER_REVIEWER_NO_WINDOW") != "1":
        existing = int(env_port) if env_port and env_port.isdigit() else _read_lock_port()
        if existing and _server_healthy(existing):
            _open_existing_window(existing)
            return
    # ---------------------------------------------------------------------------

    port = int(env_port) if env_port and env_port.isdigit() else _free_port()
    _write_lock(port)

    # Open the window from a background thread; run uvicorn on the MAIN thread
    # (uvicorn must install signal handlers on the main thread, which fails in a
    # worker thread inside a frozen exe and silently kills the server).
    if os.environ.get("PAPER_REVIEWER_NO_WINDOW") != "1":
        threading.Thread(target=_open_window_then_exit, args=(port,), daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
