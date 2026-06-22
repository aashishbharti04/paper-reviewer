"""Persistent paper corpus — every accepted paper is remembered across sessions,
so new uploads can be checked against the entire history (Turnitin "student paper
repository" equivalent).

Storage: a flat directory of JSON files, one per paper, keyed by content SHA.
Index file `corpus_index.json` lets us list entries quickly without scanning
every file. No external database — works fully offline.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable


def _corpus_dir() -> Path:
    if getattr(sys, "frozen", False):
        base = os.environ.get("APPDATA") or str(Path.home())
        d = Path(base) / "PaperReviewer" / "corpus"
    else:
        d = Path.home() / ".paper_reviewer_web" / "corpus"
    d.mkdir(parents=True, exist_ok=True)
    return d


CORPUS_DIR = _corpus_dir()
INDEX_PATH = CORPUS_DIR / "corpus_index.json"


@dataclass
class CorpusEntry:
    sha: str
    filename: str
    paper_id: str
    title: str
    added_at: float
    word_count: int


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()


def _load_index() -> list[dict]:
    if not INDEX_PATH.exists():
        return []
    try:
        return json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_index(index: list[dict]) -> None:
    INDEX_PATH.write_text(json.dumps(index, indent=2), encoding="utf-8")


def add_paper(text: str, *, filename: str = "", paper_id: str = "", title: str = "") -> CorpusEntry | None:
    """Add a paper to the corpus, deduped by content SHA. Returns the new entry,
    or None if the same content was already stored."""
    text = (text or "").strip()
    if len(text) < 200:
        return None
    sha = _sha(text)
    json_path = CORPUS_DIR / f"{sha}.json"
    if json_path.exists():
        # Update metadata (we may have a newer/better title) but don't duplicate.
        existing = json.loads(json_path.read_text(encoding="utf-8"))
        if title and not existing.get("title"):
            existing["title"] = title
            json_path.write_text(json.dumps(existing, ensure_ascii=False), encoding="utf-8")
        return None
    entry = CorpusEntry(
        sha=sha, filename=filename or "", paper_id=paper_id or "",
        title=title or "", added_at=time.time(),
        word_count=len(text.split()),
    )
    json_path.write_text(json.dumps({**asdict(entry), "text": text}, ensure_ascii=False), encoding="utf-8")
    index = _load_index()
    index.append(asdict(entry))
    _save_index(index)
    return entry


def list_corpus() -> list[CorpusEntry]:
    index = _load_index()
    return [CorpusEntry(**e) for e in index]


def load_text(sha: str) -> str:
    p = CORPUS_DIR / f"{sha}.json"
    if not p.exists():
        return ""
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("text", "")
    except Exception:
        return ""


def remove_paper(sha: str) -> bool:
    p = CORPUS_DIR / f"{sha}.json"
    if p.exists():
        p.unlink()
        index = [e for e in _load_index() if e.get("sha") != sha]
        _save_index(index)
        return True
    return False


def clear_corpus() -> int:
    n = 0
    for p in CORPUS_DIR.glob("*.json"):
        if p.name == "corpus_index.json":
            continue
        try:
            p.unlink()
            n += 1
        except Exception:
            pass
    _save_index([])
    return n


# ---------------- Matching against corpus ----------------


def _ngrams(text: str, n: int = 6) -> set[tuple[str, ...]]:
    words = re.findall(r"\w+", (text or "").lower())
    if len(words) < n:
        return set()
    return {tuple(words[i:i + n]) for i in range(len(words) - n + 1)}


@dataclass
class CorpusMatch:
    sha: str
    filename: str
    paper_id: str
    title: str
    overlap_pct: float           # % of the target's 6-word phrases also present in this entry
    matched_snippets: list[str]  # up to 3 example phrases


def find_matches(paper_text: str, *, exclude_sha: str = "", top: int = 5) -> list[CorpusMatch]:
    """Compare against every stored paper. Returns up to `top` highest matches."""
    target_ng = _ngrams(paper_text)
    if not target_ng:
        return []
    target_sha = _sha(paper_text)

    results: list[CorpusMatch] = []
    for entry in list_corpus():
        if entry.sha == exclude_sha or entry.sha == target_sha:
            continue
        other_text = load_text(entry.sha)
        if not other_text:
            continue
        other_ng = _ngrams(other_text)
        if not other_ng:
            continue
        intersection = target_ng & other_ng
        if not intersection:
            continue
        coverage = len(intersection) / len(target_ng)
        # Pick up to 3 phrase snippets for evidence
        snippets = [" ".join(ng) for ng in list(intersection)[:3]]
        results.append(CorpusMatch(
            sha=entry.sha, filename=entry.filename, paper_id=entry.paper_id,
            title=entry.title or "", overlap_pct=round(coverage * 100, 1),
            matched_snippets=snippets,
        ))
    results.sort(key=lambda r: -r.overlap_pct)
    return results[:top]
