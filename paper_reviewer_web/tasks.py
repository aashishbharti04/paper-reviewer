"""In-memory single-user job state for the web dashboard.

The web app is local single-user, so a module-level singleton works. If we ever
go multi-user this becomes a dict keyed by session ID.
"""

from __future__ import annotations

import queue
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class PaperItem:
    id: str
    filename: str
    server_path: str          # absolute path on server's temp dir
    paper_id: str = ""
    force_reject: str = ""    # "" | "ai" | "plag" | "novelty"
    status: str = "pending"   # pending | reading | reviewing | preview | done | skipped | error | cancelled
    opinion: str = ""
    review: str = ""
    provider: str = ""
    error: str = ""
    ai_score: float = -1.0    # -1 = not yet checked
    dup_score: float = -1.0   # session + persistent corpus
    web_score: float = -1.0   # only set by deep web check
    similarity_index: float = -1.0  # max(dup, web)
    plag_flagged: str = ""    # "" | "ai" | "plag"
    plag_evidence: list[str] = field(default_factory=list)
    last_report: dict = field(default_factory=dict)


@dataclass
class JobState:
    items: list[PaperItem] = field(default_factory=list)
    cmt_path: str = ""
    cmt_count: int = 0
    excel_path: str = ""
    preview_enabled: bool = True
    running: bool = False
    cancelled: bool = False

    # SSE event queue
    events: queue.Queue = field(default_factory=queue.Queue)

    # Preview synchronization
    preview_lock: threading.Lock = field(default_factory=threading.Lock)
    preview_event: threading.Event = field(default_factory=threading.Event)
    preview_response: dict = field(default_factory=dict)
    pending_preview_id: str = ""

    def push(self, event_type: str, data: dict | None = None) -> None:
        self.events.put({"type": event_type, "data": data or {}, "ts": time.time()})

    def reset(self) -> None:
        # keep cmt + excel + preview_enabled
        self.items = []
        self.running = False
        self.cancelled = False
        self.preview_event.clear()
        self.preview_response = {}
        self.pending_preview_id = ""
        # drain event queue
        try:
            while True:
                self.events.get_nowait()
        except queue.Empty:
            pass


STATE = JobState()


def upload_dir() -> Path:
    d = Path.home() / ".paper_reviewer_web" / "uploads"
    d.mkdir(parents=True, exist_ok=True)
    return d


def new_paper_id() -> str:
    return uuid.uuid4().hex[:12]
