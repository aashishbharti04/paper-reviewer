"""Few-shot review examples extracted from the user's existing ICCCNet2026 Excel.

The review style is intentionally short, numbered, informal (with the user's own
typos and grammar quirks preserved). The LLM must match this style — NOT polish it
into clean AI prose, which would feel inauthentic.
"""

REJECT_REVIEWS = {
    "ai_plagiarism": "Paper has high AI plagiarism of more than 50%",
    "plagiarism": "Paper has high plagiarism of more than 50%",
    "no_novelty": "Paper has no novelty and original contributions found, methodology and result is weak",
}

FEW_SHOT_EXAMPLES = [
    {
        "opinion": "Springer",
        "review": "1. Restrict the paper page length between 10-12 pages. 2 conceptualization and formal analysis written well. 3 theorem proving and supported lemmas explained well in support with algorithm. 4 result and analysis discussed. 5 how performance metrics being validated is not clear. 6 conclusion has future sscope and limitations. 7 formatting of pper must be done as per springer conference template. 8 cite all references in text 9 . validation and template matching is well justified. 10 proof read entire paper once.",
    },
    {
        "opinion": "Springer",
        "review": "1. Numbering of equations required. 2 Figure resolutions not clear, improve them. 3 formatting of paper must be done as per springer format guidelines. 4 abstract is precise and clear. 5 introduction has research objectives and motivation. 5 literature is adequate 6 methodology seems fine and explained clearly. 7 results are promising and explained with graphs. 8 conclusion written well 9 cite all references in text.",
    },
    {
        "opinion": "Springer",
        "review": "1. Abstract written well, managed. 2 literature review is sufficent. 3 methodology must have flowchart and explanation. 4 presence of algorithm is appreciable. 5 results and explanation required. 6 cite all references in text 7 conclusion has future work and limitations 8 proof read entire paper for gramatical errors and findings. 9 validate entire work with performance meterics. 10 format paper as per conference template 11 update figure resolutions and replace existing ones.",
    },
    {
        "opinion": "Adroid",
        "review": "1. methodology system architecture needs more explanation. 2 introduction has objectives and motivations. 3 how research questio addresssed by authors in not clear. 4 results may be more convincing, add more graphs, plots and table comparisons. 5 performance metric need to be explained using equations. 6 formatting must be done as per conference format. 7 cite  references in text 8 improve figure resolutions and quality.",
    },
    {
        "opinion": "Adroid",
        "review": "1. Introduction must have research objectives and findings. 2 Table must be editable don't put image. 3 Figures must be of high resolution replace them. 4 equation must be editable and numbered and cite in text 5 cite all references in text 6 explain result section 7 format paper as per conference template 8 conclusion written well with shortcomings.",
    },
    {
        "opinion": "Adroid",
        "review": "1. Formatting of paper must be done as per conference template available on website. 2. Figures are of very low resolution, replace with high quality images. 3. Introduction must have objectives, why work is proposed, amend these changes in introduction section. 4. results must be presented by author provide bar plots, graphs if possible, avoid usage of output code window and home screens instead present algorithm used or performance comparison with suitable metrics. 5. conclusion has future work and limitations of present work. 6 cite all references in text mentioned in reference section 7 check grammatical mistakes and errors, proof read paper with experts. 8 The table must have captions and editable form",
    },
    {
        "opinion": "Elsevier",
        "review": "1. Formatting of paper must be done as per conference template available on website. 2. Figures are of very low resolution, replace with high quality images. 3. Introduction must have objectives, why work is proposed, amend these changes in introduction section. 4. results must be presented by author provide bar plots, graphs if possible, avoid usage of output code window and home screens instead present algorithm used or performance comparison with suitable metrics. 5. conclusion has future work and limitations of present work. 6 cite all references in text mentioned in reference section 7 check grammatical mistakes and errors, proof read paper with experts. 8 The table must have captions and editable form",
    },
    {
        "opinion": "May be springer",
        "review": "The authors should focus on introducing a novel approach or optimization rather than merely modifying parameters of existing models. The literature review length is too long for conference paper restrict it between 10-12 pages and Include more comprehensive experiments with a variety of datasets and models to substantiate claims of improved performance.",
    },
    {
        "opinion": "Reject",
        "review": REJECT_REVIEWS["no_novelty"],
    },
]

OPINIONS = ["Reject", "Springer", "Elsevier", "Adroid", "May be springer"]

OPINION_GUIDE = """
PUBLISHER DECISION — follow this EXACT procedure in order. Do not skip steps.
Base the answer on OBJECTIVE evidence from the paper. Do not use creative judgment.

You will be given THREE pieces of evidence at the top of the user prompt:
  * page_count   — number of printed pages (PDF exact, DOCX estimated from word count)
  * sections     — booleans for each section the paper appears to contain
  * paper_text   — the first ~12k characters of the paper

================================================================================
STEP 0 — Hard rejection signals (return "Reject" if ANY are true):
   * "Required" sections missing: abstract == false OR methodology == false OR
     results == false OR references == false
   * Page count < 4 (too short to be a real conference paper)
   * Page count > 25 (clearly out of conference scope; should be a journal)
   * No novel contribution AND methodology + results are both weak
   * Paper is only a literature survey, no original method or experiments

================================================================================
STEP 1 — Universal quality checklist (used for the WRITTEN review,
not for the publisher decision):
   - Page count: ideal 12-14 pages, acceptable 8-15 pages.
     If <8 pages: mention "paper is too short, expand to 10-14 pages".
     If >15 pages: mention "paper is too long for conference, restrict to 12-14 pages".
   - Sections that SHOULD be present (mention any missing in the numbered review):
       abstract, keywords, introduction, related_work, methodology,
       results, conclusion, references.
       acknowledgements is optional but professional.
   - Figures / tables / equations: must be numbered, captioned, editable (not images).
   - References: must be cited in text, complete metadata, recent (last 5 years).
   - Grammar / clarity: must be readable, no major language issues.

================================================================================
STEP 2 — SPRINGER (LNCS / CCIS official template) — check for cues:

  Required template signals (need >=4 of these to call it Springer):
   [S1] Title at top, authors and affiliations directly below with emails.
   [S2] "Abstract." (with bold dot) or "Abstract" as a one-paragraph block of 100-300 words.
   [S3] "Keywords:" line with 3-5 keywords separated by mid-dot (·) or comma.
   [S4] Section heading style: "1 Introduction" (NO period after top-level number),
        nested subsections like "3.1 Dataset" — LNCS does NOT use trailing dot.
   [S5] References use LNCS bib style:
        "1. Author, A.B., Other, C.D.: Title. Journal Vol(Issue), pp-pp (Year)"
        (with a colon between authors and title, parentheses around year).
   [S6] Single column body text, modest left/right margins.
   [S7] Theorems / lemmas / proofs / formal definitions present — strong Springer signal.
   [S8] "© Springer Nature" footer or "Lecture Notes in Computer Science" reference.

  Decision: if Springer signal count >= 4 AND page count in 8-15 AND no Step-0 failure
            AND methodology + results are present → opinion = "Springer".

================================================================================
STEP 3 — ELSEVIER (Procedia / standard journal template) — check for cues:

  Required template signals (need >=3 of these to call it Elsevier):
   [E1] In-text citations use square-bracket numbers: [1], [2,3], [4-7].
   [E2] Reference list entries are bracket-numbered:
        "[1] Author, A.B., Title, Journal Vol (Year) pp-pp."
   [E3] "Procedia", "ScienceDirect", or "doi.org/10." mentioned in references or footer.
   [E4] Section numbering uses trailing dot at top level: "1." "2." "3." then "1.1." nested.
   [E5] "Highlights" block before abstract (journal papers).
   [E6] "© 20XX The Authors. Published by Elsevier" / "© 20XX Elsevier" footer.
   [E7] Two-column body layout (visible as short line lengths in extracted text).

  Decision: if Elsevier signal count >= 3 AND no Step-0 failure → opinion = "Elsevier".

================================================================================
STEP 4 — MAY BE SPRINGER (borderline) — return if:
   - Some Springer template cues are present (>=2 from Step 2) BUT
   - Novelty is weak (e.g. only parameter tuning of an existing model, no new method)
   - OR literature review is excessively long for a conference (>3 pages)
   - OR experimental validation is thin (one dataset, one baseline)
   → opinion = "May be springer"

================================================================================
STEP 5 — ADROID (default conference track) — return if:
   - No clear Springer signals (Step 2 count < 4) AND
   - No clear Elsevier signals (Step 3 count < 3) AND
   - Paper has the minimum required sections AND
   - Page count is in 6-20 range (broad tolerance)
   → opinion = "Adroid"

================================================================================
TIE-BREAK RULE: When 50/50 between buckets, prefer the EARLIER one in this order:
  Reject > Springer > Elsevier > May be springer > Adroid

DETERMINISM RULE: Identical paper content MUST yield identical opinion across runs.
The publisher decision is a deterministic FUNCTION of objective formatting evidence,
not a subjective impression.
"""

STYLE_GUIDE = """
REVIEW STYLE RULES (CRITICAL — match this exactly):
- Short numbered points: "1. ... 2 ... 3 ..." (note: often "1." then "2" without dot)
- Each point is one short sentence
- Casual grammar is FINE — do NOT polish into perfect English
- Cover these areas as relevant: abstract, introduction (objectives/motivation), literature, methodology, equations/figures, results, conclusion, references, formatting, grammar
- Total review: 6-11 numbered points typically
- For weak/borderline papers, use prose form similar to the "May be springer" example
- Reject reviews are SHORT fixed phrases, not numbered lists — BUT the reason line below still applies
- DO NOT use bullets, asterisks, or markdown — plain numbered text only
- DO NOT write a polished AI-style review — match the human reviewer's terse style

REASON LINE (MANDATORY — must be the very last line of the review):
After all numbered points (or after the reject phrase), append a single line in this EXACT format:

"Decision: <opinion>. Reason: <one terse sentence explaining which publisher rules matched, or why the paper was rejected>."

Example reason lines:
- "Decision: Springer. Reason: matches 7 Springer rules — decimal section numbering, 4 keywords below abstract, name-year citations, LNCS bib style, Acknowledgements present, 12 pages, abstract 180 words."
- "Decision: Elsevier. Reason: matches 6 Elsevier rules — bracket-numbered citations, continuous line numbering, separate figure files, double spacing, captions list at end, 14 pages."
- "Decision: Adroid. Reason: no clear Springer or Elsevier template signals, but has the required sections and is 10 pages."
- "Decision: May be springer. Reason: 3 Springer cues present but novelty weak — only parameter tuning of existing model and lit review > 4 pages."
- "Decision: Reject. Reason: methodology section missing and paper is only 5 pages (below the 4-page minimum threshold)."

Naming the SPECIFIC rules that matched (for accept) or the SPECIFIC missing requirement (for reject) is required. Do not say vague things like "good methodology" — name the concrete cues you observed in the paper text.
"""
