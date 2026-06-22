"""Editable publisher acceptance rules.

The defaults below come from the official Springer Nature and Elsevier author
guidelines (see Pubrica + Springer Nature Templates & Style Files Guide,
elsevier.com author guides). The user can edit, add, or delete rules from
the Settings page; edits are persisted to publisher_rules.json next to the
project root (or %APPDATA%\\PaperReviewer when running as a frozen .exe).

A paper is assigned to a publisher when its text matches at least `min_matches`
of that publisher's rules. If multiple publishers tie, the tie_break_order
in `global_settings` decides.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any


# ----- Default rules (editable in the UI; can be restored from here) -----


DEFAULT_PUBLISHERS: list[dict[str, Any]] = [
    {
        "name": "Springer",
        "description": "Springer Nature LNCS / Journal — official template",
        "min_matches": 6,
        "rules": [
            "Font: 10-point Times New Roman (or Computer Modern for LaTeX)",
            "Spacing: 1.5 or double, margins at least 2.5 cm / 1 inch on all sides",
            "No manual page numbers, running heads, or footers",
            "Max 3 heading levels using decimal numbering (1, 1.1, 1.1.1)",
            "Title in concise title case",
            "Author block: full names, institutional affiliations, emails (ORCID encouraged)",
            "Abstract: 150-250 words",
            "Keywords: 4-6 keywords directly beneath the abstract",
            "Declarations section: Conflict of Interest and Ethical Approval before references",
            "Data Availability and Author Contributions statements above the references",
            "Equations created with Word Equation Editor or MathType (NOT pasted as images)",
            "Tables built as native Word tables (NOT embedded Excel screenshots)",
            "Figures submitted as high-resolution TIFF / EPS / embedded high-quality PDF, named logically",
            "In-text citations use name-year format, e.g. (Author, 2024)",
            "Reference list is alphabetical with full journal names (no abbreviations)",
        ],
    },
    {
        "name": "Elsevier",
        "description": "Elsevier journal / ScienceDirect — Your Paper Your Way final format",
        "min_matches": 5,
        "rules": [
            "Single-column layout (not two-column for final production)",
            "Font: Times New Roman or Arial, 11-12 pt",
            "Margins: 2.5 cm / 1 inch on all sides",
            "Double-spaced throughout (including abstract, footnotes, references)",
            "Continuous line numbering in the left margin from the title page",
            "Page numbers on every page including references and figures",
            "Title: concise and informative, avoid abbreviations",
            "Author block: full names, affiliations, corresponding author email",
            "Abstract: concise factual summary of 150-250 words",
            "Keywords: 4-6 keywords/phrases for indexing",
            "Highlights bullet points (optional but supported)",
            "Max 3 heading levels using decimal numbering with trailing dot (1., 1.1., 1.1.1.)",
            "Equations entered as editable text (NOT static images)",
            "Acronyms defined on first use and used consistently",
            "Figures NOT embedded in body; placement indicated like [Insert Figure 1 here]",
            "Figures uploaded as separate high-resolution source files (TIFF or EPS preferred)",
            "Tables as editable text with NO vertical lines",
            "Figure and table captions provided as a separate list at the end",
            "In-text citations use author, year format e.g. (Smith, 2026)",
        ],
    },
    {
        "name": "IEEE",
        "description": "IEEE conference / journal — official two-column template",
        "min_matches": 4,
        "rules": [
            "Two-column body layout (inferable from short line lengths)",
            "Font: Times New Roman 10 pt body on US Letter page size",
            "Title in large font, author names and affiliations centered below",
            "Abstract begins with bold/italic 'Abstract—' (em-dash), single paragraph",
            "Keywords line written as 'Index Terms—' after the abstract",
            "Section headings use Roman numerals in caps: 'I. INTRODUCTION', 'II. RELATED WORK'",
            "Subsections lettered: 'A.', 'B.', 'C.'",
            "In-text citations are bracket-numbered: [1], [2], [3]-[5]",
            "Reference list in IEEE style: '[1] A. Author, \"Title,\" Journal, vol. x, no. y, pp. z, Year.'",
            "Figures and tables numbered (Fig. 1, TABLE I) with captions",
        ],
    },
    {
        "name": "Adroid",
        "description": "Default conference-proceedings bucket — applied when no Springer / Elsevier / IEEE template signals are detected",
        "min_matches": 2,
        "rules": [
            "Paper has the minimum required sections (abstract, introduction, methodology, results, conclusion, references)",
            "Page count is in the 6-20 page range (acceptable for conference proceedings)",
            "Generic conference paper format, no strong Springer or Elsevier template signals",
        ],
    },
]


DEFAULT_GLOBAL: dict[str, Any] = {
    "reject_if_pages_below": 4,
    "reject_if_pages_above": 25,
    "ideal_pages_min": 12,
    "ideal_pages_max": 14,
    "acceptable_pages_min": 8,
    "acceptable_pages_max": 15,
    "required_sections": ["abstract", "introduction", "methodology", "results", "conclusion", "references"],
    "tie_break_order": ["Reject", "Springer", "Elsevier", "IEEE", "May be springer", "Adroid"],
    "maybe_springer_when": "Some Springer cues present (2-3 matches) but novelty is weak, lit review too long, or experiments thin",
    "plagiarism": {
        "auto_check_before_review": True,
        "auto_flag_reject_if_over": True,
        "ai_threshold": 50,
        "dup_threshold": 50,
        # placeholders for future paid integrations — leave blank to disable
        "gptzero_api_key": "",
        "copyleaks_api_key": "",
    },
}


# ----- File location -----


def _rules_path() -> Path:
    """Where publisher_rules.json lives.

    Same logic as providers config — user-writeable in frozen mode, project-local in dev.
    """
    if getattr(sys, "frozen", False):
        base = os.environ.get("APPDATA") or str(Path.home())
        d = Path(base) / "PaperReviewer"
        d.mkdir(parents=True, exist_ok=True)
        return d / "publisher_rules.json"
    return Path(__file__).resolve().parent.parent / "publisher_rules.json"


RULES_PATH = _rules_path()


# ----- Load / save -----


def _merge_defaults(loaded: dict) -> dict:
    """Add any missing default keys to a user-saved rules file. Preserves edits."""
    g = loaded.setdefault("global", {})
    for k, v in DEFAULT_GLOBAL.items():
        if k not in g:
            g[k] = json.loads(json.dumps(v))  # deep copy
        elif isinstance(v, dict) and isinstance(g[k], dict):
            # merge nested dicts (e.g. plagiarism subsection)
            for sub_k, sub_v in v.items():
                if sub_k not in g[k]:
                    g[k][sub_k] = sub_v

    # Add any NEW default publishers (by name) that the saved file predates.
    # Preserves the user's existing/edited publishers; only appends missing ones.
    pubs = loaded.setdefault("publishers", [])
    existing_names = {p.get("name", "").lower() for p in pubs}
    for dp in DEFAULT_PUBLISHERS:
        if dp.get("name", "").lower() not in existing_names:
            # insert before the default 'Adroid' fallback if present, else append
            new_pub = json.loads(json.dumps(dp))
            adroid_idx = next((i for i, p in enumerate(pubs) if p.get("name", "").lower() == "adroid"), None)
            if adroid_idx is not None:
                pubs.insert(adroid_idx, new_pub)
            else:
                pubs.append(new_pub)

    # Ensure every publisher appears in tie_break_order (append missing ones before
    # the final fallback so newly-added publishers still have a defined priority).
    tbo = g.setdefault("tie_break_order", list(DEFAULT_GLOBAL["tie_break_order"]))
    tbo_lower = {x.lower() for x in tbo}
    for p in pubs:
        name = p.get("name", "")
        if name and name.lower() not in tbo_lower:
            insert_at = len(tbo) - 1 if tbo else 0  # before the last (fallback) entry
            tbo.insert(max(0, insert_at), name)
            tbo_lower.add(name.lower())
    return loaded


def load_rules() -> dict[str, Any]:
    """Return the current rules dict. Falls back to defaults if file missing/corrupt."""
    if RULES_PATH.exists():
        try:
            data = json.loads(RULES_PATH.read_text(encoding="utf-8"))
            # Basic schema validation — ensure required keys
            if "publishers" not in data or "global" not in data:
                raise ValueError("missing keys")
            return _merge_defaults(data)
        except Exception:
            pass
    return {"publishers": [dict(p) for p in DEFAULT_PUBLISHERS], "global": dict(DEFAULT_GLOBAL)}


def save_rules(data: dict[str, Any]) -> None:
    """Persist user-edited rules. Caller is responsible for validation."""
    RULES_PATH.parent.mkdir(parents=True, exist_ok=True)
    RULES_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def restore_defaults() -> dict[str, Any]:
    """Wipe user edits, return to defaults."""
    fresh = {"publishers": [dict(p) for p in DEFAULT_PUBLISHERS], "global": dict(DEFAULT_GLOBAL)}
    save_rules(fresh)
    return fresh


def rules_hash(rules: dict[str, Any] | None = None) -> str:
    """Stable hash of the rules — used by the review cache so a rule change invalidates."""
    if rules is None:
        rules = load_rules()
    blob = json.dumps(rules, sort_keys=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


# ----- Format for the LLM prompt -----


def format_rules_for_prompt(rules: dict[str, Any] | None = None) -> str:
    """Render the current rules into the text that gets injected into the system prompt."""
    if rules is None:
        rules = load_rules()
    g = rules.get("global", DEFAULT_GLOBAL)
    pubs = rules.get("publishers", DEFAULT_PUBLISHERS)

    parts: list[str] = []
    parts.append("STEP 0 — Hard rejection check. Return \"Reject\" if ANY are true:")
    parts.append(f"   * Any of these required sections is missing: {', '.join(g.get('required_sections', []))}")
    parts.append(f"   * page_count < {g.get('reject_if_pages_below', 4)} (too short)")
    parts.append(f"   * page_count > {g.get('reject_if_pages_above', 25)} (out of conference scope)")
    parts.append( "   * No novel contribution AND methodology + results are both weak")
    parts.append( "   * Paper is only a literature survey, no original method or experiments")
    parts.append("")

    parts.append("STEP 1 — Universal quality (use for the WRITTEN review text, not the bucket):")
    parts.append(
        f"   * Ideal page count: {g.get('ideal_pages_min', 12)}-{g.get('ideal_pages_max', 14)}, "
        f"acceptable: {g.get('acceptable_pages_min', 8)}-{g.get('acceptable_pages_max', 15)}"
    )
    parts.append(f"   * Required sections to flag if missing: {', '.join(g.get('required_sections', []))}")
    parts.append( "   * Figures / tables / equations must be numbered, captioned, editable (not images)")
    parts.append( "   * References must be cited in text, complete, recent")
    parts.append("")

    step = 2
    for pub in pubs:
        if pub.get("name", "").lower() in ("may be springer",):  # synthetic bucket, no direct rules
            continue
        name = pub.get("name", "Unknown")
        desc = pub.get("description", "")
        min_m = pub.get("min_matches", 3)
        rules_list = pub.get("rules", [])
        parts.append(f"STEP {step} — {name.upper()} bucket. {desc}")
        parts.append(f"   The paper must match at least {min_m} of these rules to be assigned to \"{name}\":")
        for r in rules_list:
            parts.append(f"     - {r}")
        parts.append(f"   Decision: if matches >= {min_m} AND no Step-0 failure -> opinion = \"{name}\".")
        parts.append("")
        step += 1

    parts.append(f"STEP {step} — MAY BE SPRINGER (borderline). {g.get('maybe_springer_when', '')}")
    parts.append( "   -> opinion = \"May be springer\"")
    parts.append("")

    parts.append("TIE-BREAK: When 50/50, prefer the EARLIER bucket in this order:")
    parts.append(f"   {' > '.join(g.get('tie_break_order', []))}")
    parts.append("")
    parts.append("DETERMINISM: identical paper content + identical rules MUST give identical opinion.")

    return "\n".join(parts)
