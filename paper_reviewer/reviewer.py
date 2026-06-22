"""Prompt construction, LLM invocation, and parsing of {review, opinion} output."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import rules as rules_mod
from . import templates
from .providers import ProviderManager, ProviderError


# Bump this whenever templates.py changes meaningfully so old cached answers
# get invalidated. Cached entries that don't match the current version are ignored.
_CACHE_VERSION = "v6-section-detection"
_CACHE_DIR = Path.home() / ".paper_reviewer_web" / "review_cache"


def _cache_key(paper_text: str, page_count: int = 0, sections: Optional[dict] = None) -> str:
    """Cache key includes paper content, page count, section flags, AND the rules hash.

    A rules edit therefore invalidates all prior cached decisions automatically.
    """
    h = hashlib.sha256()
    h.update(_CACHE_VERSION.encode("utf-8"))
    h.update(b"\x00")
    h.update(rules_mod.rules_hash().encode("utf-8"))
    h.update(b"\x00")
    h.update(f"pages={page_count}".encode("utf-8"))
    h.update(b"\x00")
    if sections:
        h.update(",".join(f"{k}={int(bool(v))}" for k, v in sorted(sections.items())).encode("utf-8"))
    h.update(b"\x00")
    h.update(paper_text.encode("utf-8", errors="ignore"))
    return h.hexdigest()


def _cache_load(key: str) -> Optional[dict]:
    p = _CACHE_DIR / f"{key}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _cache_save(key: str, review: str, opinion: str, provider: str) -> None:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (_CACHE_DIR / f"{key}.json").write_text(
        json.dumps({"review": review, "opinion": opinion, "provider": provider}, indent=2),
        encoding="utf-8",
    )


def clear_cache() -> int:
    """Delete all cached review decisions. Returns number removed."""
    if not _CACHE_DIR.exists():
        return 0
    n = 0
    for p in _CACHE_DIR.glob("*.json"):
        try:
            p.unlink()
            n += 1
        except Exception:
            pass
    return n


def allowed_opinions() -> list[str]:
    """Reject + every configured publisher + 'May be springer', deduped in order."""
    rules = rules_mod.load_rules()
    pub_names = [p.get("name", "").strip() for p in rules.get("publishers", []) if p.get("name")]
    out = ["Reject"] + pub_names + ["May be springer"]
    seen, deduped = set(), []
    for o in out:
        if o.lower() not in seen:
            seen.add(o.lower())
            deduped.append(o)
    return deduped


def build_system_prompt() -> str:
    """Assemble the system prompt at request time so user-edited rules are picked up."""
    allowed = "\n".join(f"- {o}" for o in allowed_opinions())
    return f"""You are a senior reviewer for the ICCCNet2026 conference.
Your only job: read a paper and produce a SHORT review and an OPINION decision.

{templates.STYLE_GUIDE}

PUBLISHER DECISION — follow this EXACT procedure in order. Use objective evidence
(page_count and sections_present that will be provided at the top of the user message)
plus the paper text. Do not use creative judgment.

{rules_mod.format_rules_for_prompt()}

ALLOWED OPINIONS (use EXACTLY one of these strings):
{allowed}

OUTPUT FORMAT (strict JSON, nothing else, no markdown fences):
{{"review": "<the review text>", "opinion": "<one of the allowed opinions>"}}
"""


# Backwards compat alias used by older callers (recomputed each access)
class _SystemPromptProxy(str):
    def __new__(cls):
        return super().__new__(cls, build_system_prompt())

SYSTEM_PROMPT = build_system_prompt()


def _format_examples() -> str:
    lines = ["Examples of past reviews in the exact required style:\n"]
    for i, ex in enumerate(templates.FEW_SHOT_EXAMPLES, 1):
        lines.append(f"EXAMPLE {i} (opinion = {ex['opinion']}):")
        lines.append(ex["review"])
        lines.append("")
    return "\n".join(lines)


def build_user_prompt(
    paper_text: str,
    title_hint: str = "",
    *,
    page_count: int = 0,
    sections: Optional[dict[str, bool]] = None,
) -> str:
    title_line = f"Paper title (extracted): {title_hint}\n\n" if title_hint else ""
    evidence = []
    if page_count:
        evidence.append(f"page_count: {page_count}")
    if sections:
        present = [k for k, v in sections.items() if v]
        missing = [k for k, v in sections.items() if not v]
        evidence.append("sections_present: " + ", ".join(present) if present else "sections_present: (none detected)")
        evidence.append("sections_missing: " + ", ".join(missing) if missing else "sections_missing: (none)")
    evidence_block = ("EVIDENCE FOR YOUR DECISION:\n" + "\n".join(evidence) + "\n\n") if evidence else ""

    return (
        _format_examples()
        + "\n---\n\n"
        + title_line
        + evidence_block
        + "Paper text (truncated):\n"
        + paper_text
        + "\n\n---\n"
        + "Apply the PUBLISHER DECISION procedure step by step. The page_count and sections evidence is OBJECTIVE — use it. "
        + "Produce the JSON for THIS paper now. Remember: terse numbered points in the review, no AI-prose, "
        + "opinion must be EXACTLY one of the allowed strings, AND the review MUST end with a 'Decision: ... Reason: ...' line that names the specific rules that matched (or the specific missing requirement if rejected)."
    )


@dataclass
class ReviewResult:
    review: str
    opinion: str
    provider: str
    raw: str = ""


def _strip_fences(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    return s


def _parse_json(text: str) -> tuple[str, str]:
    text = _strip_fences(text)
    # Try direct
    try:
        d = json.loads(text)
        return d["review"], d["opinion"]
    except Exception:
        pass
    # Try to find first {...} block
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try:
            d = json.loads(m.group(0))
            return d["review"], d["opinion"]
        except Exception:
            pass
    # FALLBACK: model returned plain text (no JSON). This is common with smaller
    # models. Recover the opinion from a "Decision: <opinion>" line and use the
    # whole text as the review.
    review, opinion = _parse_loose(text)
    if opinion:
        return review, opinion
    raise ValueError(f"Could not parse opinion from model output:\n{text[:400]}")


def _parse_loose(text: str) -> tuple[str, str]:
    """Best-effort extraction when the model ignored the JSON instruction."""
    review = text.strip()
    opinion = ""
    # 1. Look for an explicit "Decision: <opinion>" line
    m = re.search(r"Decision\s*:\s*([A-Za-z ]+?)\s*(?:\.|\n|$)", text, re.IGNORECASE)
    if m:
        opinion = m.group(1).strip()
    if not opinion:
        # 2. Scan for any known opinion keyword, preferring the last occurrence.
        #    Use the live configured opinions so a new publisher is matched too.
        try:
            candidates = list(dict.fromkeys(allowed_opinions() + ["Springer", "IEEE", "ACM", "Adroid"]))
        except Exception:
            candidates = ["May be springer", "Reject", "Springer", "Elsevier", "IEEE", "ACM", "Adroid"]
        last_pos, last_op = -1, ""
        low = text.lower()
        for c in candidates:
            p = low.rfind(c.lower())
            if p > last_pos:
                last_pos, last_op = p, c
        opinion = last_op
    return review, opinion


def _normalize_opinion(op: str) -> str:
    op = op.strip()
    low = op.lower().strip()
    mapping = {
        "reject": "Reject",
        "springer": "Springer",
        "elsevier": "Elsevier",
        "adroid": "Adroid",
        "android": "Adroid",
        "ieee": "IEEE",
        "acm": "ACM",
        "may be springer": "May be springer",
        "maybe springer": "May be springer",
        "may be": "May be springer",
    }
    return mapping.get(low, op)


def review_paper(
    manager: ProviderManager,
    paper_text: str,
    *,
    title_hint: str = "",
    force_reject_reason: Optional[str] = None,
    use_cache: bool = True,
    page_count: int = 0,
    sections: Optional[dict[str, bool]] = None,
) -> ReviewResult:
    """Review a paper.

    - If force_reject_reason is set ('ai', 'plag', 'novelty'), skip the LLM entirely.
    - Otherwise, check the content-hash cache first so the *same paper text* always
      returns the *same review and opinion*. Without this, re-reviewing the same paper
      could land in a different publisher bucket because the LLM is non-deterministic.
    """
    if force_reject_reason:
        body = {
            "ai": templates.REJECT_REVIEWS["ai_plagiarism"],
            "plag": templates.REJECT_REVIEWS["plagiarism"],
            "novelty": templates.REJECT_REVIEWS["no_novelty"],
        }.get(force_reject_reason, templates.REJECT_REVIEWS["no_novelty"])
        reason = {
            "ai": "user flagged the paper as having >50% AI-generated content (manual plagiarism filter).",
            "plag": "user flagged the paper as having >50% plagiarism (manual plagiarism filter).",
            "novelty": "user flagged the paper as having no original contribution; methodology and result are weak.",
        }.get(force_reject_reason, "user flagged the paper for rejection.")
        review_text = f"{body}\nDecision: Reject. Reason: {reason}"
        return ReviewResult(review=review_text, opinion="Reject", provider="(rule)")

    cache_key = _cache_key(paper_text, page_count, sections) if use_cache else None
    if cache_key:
        hit = _cache_load(cache_key)
        if hit and hit.get("opinion"):
            return ReviewResult(
                review=hit["review"], opinion=hit["opinion"],
                provider=f"cache ({hit.get('provider','?')})", raw="",
            )

    user_prompt = build_user_prompt(paper_text, title_hint, page_count=page_count, sections=sections)
    # Rebuild the system prompt each call so live rule edits take effect immediately.
    provider_name, raw = manager.call(build_system_prompt(), user_prompt, json_mode=True)
    review, opinion = _parse_json(raw)
    opinion = _normalize_opinion(opinion)
    review = review.strip()

    if cache_key:
        _cache_save(cache_key, review, opinion, provider_name)

    return ReviewResult(review=review, opinion=opinion, provider=provider_name, raw=raw)
