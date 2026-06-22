"""Offline plagiarism + AI-text detection.

Two scores per paper:

1. ai_score (0-100): heuristic estimate that the paper was LLM-generated.
   Looks at LLM-favourite phrase density, sentence-length uniformity, and
   formal-language ratio. Not as accurate as paid tools (GPTZero, Sapling)
   but works offline with zero API calls.

2. dup_score (0-100): maximum n-gram overlap with any other paper in the
   corpus (typically the other papers uploaded in the same session). Catches
   resubmissions / verbatim copies.

Third-party integrations:
- GPTZero: LIVE. If a key is set, detect_ai_score() calls the real GPTZero
  /v2/predict/text endpoint and falls back to the heuristic on any error.
- Copyleaks: NOT supported in local mode. The Copyleaks plagiarism scan is
  asynchronous and webhook-based — results are POSTed back to a public callback
  URL that a desktop/localhost app cannot receive. The built-in web (DuckDuckGo)
  + persistent-corpus check fills this role locally. The key is stored for a
  future hosted deployment where a public webhook endpoint is available.
"""

from __future__ import annotations

import html
import random
import re
import statistics
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Iterable, Optional

from . import corpus as corpus_mod


# ---------------- AI detection heuristic ----------------

# These are phrases / words that LLM writing reaches for far more often than
# human academic writers do. Each hit adds to the AI score. Tuned conservatively
# to avoid flagging good-faith academic prose.
_AI_PHRASES = [
    # generic LLM tells
    "delve into", "delves into", "delving into",
    "leveraging", "leverages", "leveraged",
    "harness", "harnessing", "harnesses",
    "seamless", "seamlessly",
    "tapestry", "treasure trove",
    "navigate the complexities", "navigating the complexities",
    "embark on", "embarking on", "embarks on",
    "in today's world", "in the realm of", "in the world of",
    "shed light on", "sheds light on",
    "underscore", "underscores", "underscored",
    "myriad of", "a myriad",
    "paramount", "pivotal", "intricate",
    # formal sentence starters that LLMs over-use
    "moreover,", "furthermore,", "additionally,",
    "in conclusion,", "in summary,",
    "it is important to note", "it is worth noting", "it should be emphasized",
    "it is crucial to", "it is essential to",
    "on the one hand", "on the other hand",
    # academic-AI tells
    "comprehensive analysis", "comprehensive overview",
    "extensive experiments demonstrate", "experimental results demonstrate",
    "our contributions can be summarized as follows",
    "this paper presents a novel",
    "in light of these findings",
]

# Words rarely seen in human academic writing but loved by LLMs (single-word signal)
_AI_SINGLETONS = {"realm", "tapestry", "leveraging", "harnessing", "seamlessly", "myriad",
                  "pivotal", "paramount", "intricacies", "facet", "facets"}


def detect_ai_score_gptzero(text: str, api_key: str) -> tuple[float, list[str]]:
    """Use the real GPTZero API for AI detection. Returns (score 0-100, evidence).

    Raises on any failure so the caller can fall back to the local heuristic.
    """
    import json
    payload = json.dumps({"document": text[:50000], "multilingual": False}).encode("utf-8")
    req = urllib.request.Request(
        "https://api.gptzero.me/v2/predict/text",
        data=payload,
        headers={
            "x-api-key": api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read().decode("utf-8", errors="ignore"))
    docs = data.get("documents") or []
    if not docs:
        raise ValueError("GPTZero returned no documents")
    doc = docs[0]
    # Prefer class_probabilities.ai, fall back to average/completely_generated_prob
    prob = None
    cp = doc.get("class_probabilities") or {}
    if "ai" in cp:
        prob = cp["ai"]
    elif doc.get("completely_generated_prob") is not None:
        prob = doc["completely_generated_prob"]
    elif doc.get("average_generated_prob") is not None:
        prob = doc["average_generated_prob"]
    if prob is None:
        raise ValueError("GPTZero response missing probability fields")
    score = round(float(prob) * 100, 1)
    predicted = doc.get("predicted_class", "?")
    return score, [f"GPTZero API: predicted_class='{predicted}', AI probability {score}%"]


def detect_ai_score(text: str, *, gptzero_api_key: str = "") -> tuple[float, list[str]]:
    """Return (score 0-100, list of evidence strings).

    If a GPTZero API key is provided, use the real service; on any failure,
    transparently fall back to the local heuristic.
    """
    if gptzero_api_key:
        try:
            return detect_ai_score_gptzero(text, gptzero_api_key)
        except Exception as e:
            # fall through to heuristic, but note the failure
            heuristic_score, heuristic_ev = _detect_ai_score_heuristic(text)
            heuristic_ev.insert(0, f"(GPTZero API failed: {str(e)[:120]} — used local heuristic)")
            return heuristic_score, heuristic_ev
    return _detect_ai_score_heuristic(text)


def _detect_ai_score_heuristic(text: str) -> tuple[float, list[str]]:
    """Offline heuristic AI-text estimate."""
    if not text or len(text) < 200:
        return 0.0, ["text too short to analyze"]

    lower = text.lower()
    words = re.findall(r"[a-zA-Z']+", lower)
    word_count = max(1, len(words))
    evidence: list[str] = []

    # 1. AI-phrase density (per 1000 words)
    phrase_hits = []
    for p in _AI_PHRASES:
        n = lower.count(p)
        if n:
            phrase_hits.append((p, n))
    phrase_density = sum(n for _, n in phrase_hits) / (word_count / 1000)
    if phrase_hits:
        top = sorted(phrase_hits, key=lambda x: -x[1])[:4]
        evidence.append("LLM-favourite phrases: " + ", ".join(f"'{p}'×{n}" for p, n in top))

    # 2. Singleton word density
    singleton_hits = sum(1 for w in words if w in _AI_SINGLETONS)
    singleton_density = singleton_hits / (word_count / 1000)
    if singleton_hits >= 3:
        evidence.append(f"{singleton_hits} occurrences of LLM-favourite single words (realm/tapestry/myriad/…)")

    # 3. Sentence-length uniformity. Humans vary sentence length; LLMs are flatter.
    sentences = [s.strip() for s in re.split(r"[.!?]+", text) if len(s.split()) >= 4]
    sent_lengths = [len(s.split()) for s in sentences]
    sent_uniformity_score = 0.0
    if len(sent_lengths) >= 8:
        mean = statistics.mean(sent_lengths)
        stdev = statistics.pstdev(sent_lengths) if len(sent_lengths) > 1 else 0
        cv = stdev / mean if mean > 0 else 0.0
        # Human academic CV typically 0.45-0.7; AI 0.25-0.40
        if cv < 0.45:
            sent_uniformity_score = (0.45 - cv) * 100  # 0-45 ish
            evidence.append(f"sentence-length variance is low (CV={cv:.2f}) — typical of AI text")

    # Combine — capped at 100
    raw = phrase_density * 12 + singleton_density * 8 + sent_uniformity_score * 0.9
    score = max(0.0, min(100.0, raw))

    if not evidence:
        evidence.append("no strong AI-text signals detected")

    return round(score, 1), evidence


# ---------------- Duplicate / verbatim plagiarism ----------------


def _ngrams(text: str, n: int = 6) -> set[tuple[str, ...]]:
    words = re.findall(r"\w+", (text or "").lower())
    if len(words) < n:
        return set()
    return {tuple(words[i:i + n]) for i in range(len(words) - n + 1)}


def detect_duplicate_score(
    paper_text: str, corpus: Iterable[tuple[str, str]],
) -> tuple[float, list[str]]:
    """Return (max-overlap percent, evidence list) against a corpus.

    Each corpus entry is (label, text) — label is shown in evidence on a hit.
    """
    target = _ngrams(paper_text)
    if not target:
        return 0.0, ["paper too short for n-gram analysis"]

    best_score = 0.0
    best_label = ""
    n_compared = 0
    for label, other in corpus:
        if not other:
            continue
        other_ng = _ngrams(other)
        if not other_ng:
            continue
        n_compared += 1
        intersection = len(target & other_ng)
        coverage = intersection / len(target)  # what % of target's n-grams appear in `other`
        if coverage > best_score:
            best_score = coverage
            best_label = label

    if n_compared == 0:
        return 0.0, ["no other papers in corpus to compare against"]

    score = round(best_score * 100, 1)
    if score >= 5:
        evidence = [f"≈{score}% 6-word phrase overlap with {best_label}"]
    else:
        evidence = [f"{score}% maximum overlap across {n_compared} other paper(s) — no significant duplication"]
    return score, evidence


# ---------------- Web similarity (DuckDuckGo HTML scrape) ----------------


def _pick_spicy_sentences(text: str, n: int = 6) -> list[str]:
    """Pick distinctive sentences to search the web for. Prefer long ones with
    specific nouns / numbers / multi-word entities, avoid generic openers."""
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    sentences = [s for s in sentences if 80 <= len(s) <= 300 and len(s.split()) >= 12]
    # Filter out obvious boilerplate
    boilerplate = re.compile(r"\b(?:abstract|keywords?|introduction|references|conclusion)\b", re.I)
    sentences = [s for s in sentences if not boilerplate.search(s[:30])]
    if not sentences:
        return []
    random.seed(hash(text) & 0xFFFFFFFF)
    return random.sample(sentences, k=min(n, len(sentences)))


def _ddg_search(query: str, *, timeout: int = 8) -> list[str]:
    """Return raw HTML snippets from DuckDuckGo's HTML endpoint. Best-effort."""
    url = "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode("utf-8", errors="ignore")
    except Exception:
        return []
    snippets = re.findall(r'class="result__snippet"[^>]*>(.+?)</a>', body, flags=re.DOTALL)
    cleaned = [html.unescape(re.sub(r"<[^>]+>", " ", s)) for s in snippets]
    return [re.sub(r"\s+", " ", s).strip() for s in cleaned[:6]]


def detect_web_similarity(text: str, *, max_queries: int = 6) -> tuple[float, list[dict], list[str]]:
    """Search the web for distinctive sentences from the paper.

    Returns (score 0-100, matches list, evidence list). A "match" is when a search
    result snippet contains >= 70% of the query sentence's 4-grams.
    """
    queries = _pick_spicy_sentences(text, n=max_queries)
    if not queries:
        return 0.0, [], ["paper too short or too generic to search"]

    matches: list[dict] = []
    hits = 0
    for q in queries:
        snippets = _ddg_search(q)
        if not snippets:
            continue
        q_4grams = _ngrams(q, n=4)
        if not q_4grams:
            continue
        for sn in snippets:
            sn_4grams = _ngrams(sn, n=4)
            if not sn_4grams:
                continue
            overlap = len(q_4grams & sn_4grams) / len(q_4grams)
            if overlap >= 0.7:
                hits += 1
                matches.append({
                    "query": q[:160],
                    "matched_snippet": sn[:240],
                    "overlap_pct": round(overlap * 100, 1),
                })
                break  # one hit per query is enough

    score = round((hits / len(queries)) * 100, 1)
    evidence = [
        f"{hits} of {len(queries)} sampled sentences matched online sources",
    ] if matches else [f"checked {len(queries)} sentences — no online matches"]
    return score, matches, evidence


# ---------------- Public result type ----------------


@dataclass
class PlagiarismResult:
    ai_score: float = 0.0
    dup_score: float = 0.0           # internal corpus overlap
    web_score: float = 0.0           # web similarity (only set when deep check runs)
    ai_evidence: list[str] = field(default_factory=list)
    dup_evidence: list[str] = field(default_factory=list)
    web_evidence: list[str] = field(default_factory=list)
    web_matches: list[dict] = field(default_factory=list)
    corpus_matches: list[dict] = field(default_factory=list)
    flagged: Optional[str] = None  # "ai" | "plag" | None
    flagged_reason: str = ""

    @property
    def similarity_index(self) -> float:
        """Combined similarity — max of corpus and web (Turnitin-style)."""
        return round(max(self.dup_score, self.web_score), 1)

    def to_dict(self) -> dict:
        return {
            "ai_score": self.ai_score,
            "dup_score": self.dup_score,
            "web_score": self.web_score,
            "similarity_index": self.similarity_index,
            "ai_evidence": self.ai_evidence,
            "dup_evidence": self.dup_evidence,
            "web_evidence": self.web_evidence,
            "web_matches": self.web_matches,
            "corpus_matches": self.corpus_matches,
            "flagged": self.flagged,
            "flagged_reason": self.flagged_reason,
        }


def check_paper(
    paper_text: str,
    session_corpus: Iterable[tuple[str, str]] = (),
    *,
    ai_threshold: float = 50.0,
    dup_threshold: float = 50.0,
    deep_web_check: bool = False,
    exclude_corpus_sha: str = "",
    gptzero_api_key: str = "",
) -> PlagiarismResult:
    """Run all checks. `session_corpus` is the other in-flight uploads in this
    job; the persistent corpus (from corpus_mod) is also queried automatically.
    `deep_web_check=True` adds DuckDuckGo similarity (slow, network-dependent).
    If `gptzero_api_key` is set, AI detection uses the real GPTZero service.
    """
    ai_score, ai_ev = detect_ai_score(paper_text, gptzero_api_key=gptzero_api_key)

    # In-session corpus (current batch)
    sess_score, sess_ev = detect_duplicate_score(paper_text, session_corpus)

    # Persistent corpus (every paper ever added)
    persistent_matches = corpus_mod.find_matches(paper_text, exclude_sha=exclude_corpus_sha, top=5)
    persistent_score = persistent_matches[0].overlap_pct if persistent_matches else 0.0
    persistent_ev = (
        [f"top match: {persistent_matches[0].filename or persistent_matches[0].sha[:10]} "
         f"({persistent_matches[0].overlap_pct}% overlap)"]
        if persistent_matches else
        [f"no significant overlap with {len(corpus_mod.list_corpus())} stored papers"]
    )

    dup_score = max(sess_score, persistent_score)
    dup_ev = list(sess_ev) + persistent_ev
    corpus_matches_dicts = [
        {"label": m.filename or m.sha[:10], "paper_id": m.paper_id,
         "title": m.title, "overlap_pct": m.overlap_pct,
         "snippets": m.matched_snippets}
        for m in persistent_matches
    ]

    result = PlagiarismResult(
        ai_score=ai_score, dup_score=dup_score,
        ai_evidence=ai_ev, dup_evidence=dup_ev,
        corpus_matches=corpus_matches_dicts,
    )

    if deep_web_check:
        web_score, web_matches, web_ev = detect_web_similarity(paper_text)
        result.web_score = web_score
        result.web_matches = web_matches
        result.web_evidence = web_ev

    # Apply thresholds — AI takes priority over plagiarism
    overall_plag = max(result.dup_score, result.web_score)
    if ai_score >= ai_threshold:
        result.flagged = "ai"
        result.flagged_reason = f"AI score {ai_score}% is at or above the {ai_threshold}% threshold."
    elif overall_plag >= dup_threshold:
        result.flagged = "plag"
        result.flagged_reason = (
            f"Similarity {overall_plag}% is at or above the {dup_threshold}% threshold "
            f"(corpus {result.dup_score}%, web {result.web_score}%)."
        )
    return result
