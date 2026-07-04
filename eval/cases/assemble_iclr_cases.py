"""Assemble ICLR 2025 evaluation cases for novelty-vs-OpenReview eval.

Method
------
1. Search OpenReview API v2 (/notes/search) with topic-based queries to find
   ICLR.cc/2025/Conference Official_Review notes containing ``contribution``
   ratings (integer 1-4 scale).
2. For each paper forum, gather all reviews found and compute mean contribution.
3. Rescale 1-4 -> 1-5 via  human_novelty = 1 + (mean_c - 1) * 4/3.
4. Recover paper titles by searching the OpenReview /notes/search API with
   keywords from review summaries; match is accepted only when note.id == forum_id.
5. Search OpenAlex API for each title; extract arXiv ID from DOI
   (``10.48550/arxiv.<id>``); keep only confident matches
   (case-insensitive title similarity >= 0.6 via SequenceMatcher).
6. Write iclr_cases.jsonl alongside this file.

Venue used: ICLR.cc/2025/Conference (ICLR 2025)

Note on the /notes endpoint
----------------------------
The OpenReview v2 ``GET /notes?forum=<id>`` endpoint returns HTTP 403
"Challenge Required" (Cloudflare CAPTCHA) for unauthenticated programmatic
access in 2025.  We therefore rely exclusively on the public
``GET /notes/search?term=<text>`` endpoint, which does not require a challenge.
This means we can only recover reviews whose content matches one of our
topic-based search terms, and only paper submission notes whose title/abstract
text overlaps with the review summary keywords.

Constraints
-----------
* Pure stdlib + httpx (already a project dep).
* No secrets / LLM key required.
* Polite to APIs: 1 s sleep between OpenAlex calls, 0.5 s between OpenReview
  calls, exponential back-off on HTTP 429.
"""

from __future__ import annotations

import json
import re
import time
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path

import httpx

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

OR_SEARCH = "https://api2.openreview.net/notes/search"
OPENALEX_WORKS = "https://api.openalex.org/works"
ICLR_VENUE = "ICLR.cc/2025/Conference"
CASES_PATH = Path(__file__).parent / "iclr_cases.jsonl"

REVIEW_SEARCH_TERMS: list[str] = [
    "ICLR.cc/2025/Conference Official_Review",
    "ICLR 2025 neural network transformer attention contribution",
    "ICLR 2025 diffusion generative model contribution",
    "ICLR 2025 graph neural network contribution",
    "ICLR 2025 optimization gradient descent contribution",
    "ICLR 2025 protein structure biology contribution",
    "ICLR 2025 bayesian inference contribution",
    "ICLR 2025 safety alignment contribution soundness",
    "ICLR 2025 continual learning contribution",
    "ICLR 2025 adversarial robustness contribution",
    "ICLR 2025 knowledge distillation contribution",
    "ICLR 2025 self-supervised learning contribution",
    "ICLR 2025 meta-learning few-shot contribution",
    "ICLR 2025 time series forecasting contribution",
    "ICLR 2025 medical imaging healthcare contribution",
    "ICLR 2025 natural language generation contribution",
    "ICLR 2025 3D generation point cloud contribution",
    "ICLR 2025 efficient training inference contribution",
    "ICLR 2025 multi-task learning contribution soundness",
    "ICLR 2025 model compression pruning contribution",
    "ICLR 2025 explainability interpretability contribution",
    "ICLR 2025 reinforcement learning contribution soundness",
    "ICLR 2025 generalization theory contribution",
    "ICLR 2025 video generation contribution",
    "ICLR 2025 anomaly detection contribution",
    "ICLR 2025 graph learning molecule drug contribution",
    "ICLR 2025 privacy differential privacy contribution",
    "ICLR 2025 world model planning contribution",
]

TITLE_STOPWORDS = frozenset(
    {
        "with", "from", "that", "they", "which", "their", "have", "been", "into",
        "such", "also", "more", "when", "while", "through", "these", "those",
        "some", "than", "both", "each", "very", "well", "first", "show", "work",
        "using", "used", "based", "approach", "method", "model", "models",
        "training", "learning", "neural", "network", "deep", "data", "task",
        "tasks", "achieve", "performance", "existing", "results", "state",
        "improve", "better", "high", "good", "large", "small",
    }
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _backoff_get(
    client: httpx.Client,
    url: str,
    params: dict,
    base_sleep: float = 2.0,
    attempts: int = 6,
) -> httpx.Response | None:
    """GET with exponential back-off on 429; returns None after exhaustion."""
    wait = base_sleep
    for _ in range(attempts):
        try:
            r = client.get(url, params=params)
        except httpx.TransportError:
            return None
        if r.status_code == 429:
            time.sleep(wait)
            wait = min(wait * 2, 60)
            continue
        return r
    return None


def _get_value(obj: object) -> object:
    """Unwrap ``{'value': x}`` dicts from OpenReview API."""
    if isinstance(obj, dict):
        return obj.get("value", obj)
    return obj


# ---------------------------------------------------------------------------
# Step 1: collect ICLR 2025 reviews
# ---------------------------------------------------------------------------


def collect_reviews(client: httpx.Client) -> dict[str, list[dict]]:
    """Return ``{forum_id: [review_note, ...]}`` for ICLR 2025 reviews."""
    reviews_by_forum: dict[str, list[dict]] = defaultdict(list)
    seen_ids: set[str] = set()

    for term in REVIEW_SEARCH_TERMS:
        r = _backoff_get(client, OR_SEARCH, {"term": term, "limit": 25})
        if r is None or r.status_code != 200:
            time.sleep(1)
            continue
        for note in r.json().get("notes", []):
            note_id = note.get("id", "")
            if note_id in seen_ids:
                continue
            invitations = note.get("invitations", [])
            content = note.get("content", {})
            is_iclr25_review = any(
                ICLR_VENUE in inv and "Official_Review" in inv for inv in invitations
            )
            if is_iclr25_review and "contribution" in content:
                seen_ids.add(note_id)
                reviews_by_forum[note.get("forum", "")].append(note)
        time.sleep(0.5)

    print(
        f"  Collected {len(seen_ids)} review notes across {len(reviews_by_forum)} forums"
    )
    return dict(reviews_by_forum)


# ---------------------------------------------------------------------------
# Step 2 & 3: score computation
# ---------------------------------------------------------------------------


def compute_human_novelty(contribs: list[int]) -> float:
    """Mean contribution rescaled 1-4 -> 1-5."""
    mean_c = sum(contribs) / len(contribs)
    return round(1.0 + (mean_c - 1.0) * 4.0 / 3.0, 3)


# ---------------------------------------------------------------------------
# Step 4: recover paper titles from OpenReview
# ---------------------------------------------------------------------------


def extract_key_terms(summary: str) -> str:
    """Pull discriminative terms from a reviewer summary for title search."""
    text = re.sub(
        r"\b(this paper|the paper|the authors?|presents?|proposes?|introduces?|"
        r"studies?|provides?|investigates?|demonstrates?|explore|examines?|"
        r"analyzes?)\b",
        "",
        summary,
        flags=re.IGNORECASE,
    )
    words = re.findall(r"[A-Za-z][A-Za-z\-]{3,}", text)
    keywords = [w for w in words if w.lower() not in TITLE_STOPWORDS]
    return " ".join(keywords[:10])


def find_paper_title(client: httpx.Client, forum_id: str, summary: str) -> str | None:
    """Search OpenReview for the submission note whose ``id == forum_id``."""
    if not summary or len(summary) < 20:
        return None
    keywords = extract_key_terms(summary)
    if not keywords:
        return None
    r = _backoff_get(client, OR_SEARCH, {"term": keywords, "limit": 10})
    if r is None or r.status_code != 200:
        return None
    for note in r.json().get("notes", []):
        if note.get("id") != forum_id:
            continue
        title = _get_value(note.get("content", {}).get("title", ""))
        if isinstance(title, str) and title:
            return title
    return None


# ---------------------------------------------------------------------------
# Step 5: arXiv matching via OpenAlex
# ---------------------------------------------------------------------------


def _title_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def search_arxiv_via_openalex(client: httpx.Client, title: str) -> str | None:
    """Return arXiv ID (e.g. '2406.12345') using OpenAlex title search.

    OpenAlex indexes ICLR 2025 papers and exposes arXiv IDs via the DOI field
    (``10.48550/arxiv.<id>``).  We use this instead of the arXiv API directly
    because the arXiv export API has strict rate limits that commonly trigger
    HTTP 429 / 503 during bulk queries.
    """
    time.sleep(1)  # OpenAlex polite rate-limit pause
    r = _backoff_get(
        client,
        OPENALEX_WORKS,
        {
            "filter": f"title.search:{title}",
            "select": "id,title,ids,doi,primary_location",
            "per_page": 5,
        },
        base_sleep=5.0,
    )
    if r is None or r.status_code != 200:
        return None

    best: dict | None = None
    best_sim = 0.0
    for p in r.json().get("results", []):
        sim = _title_similarity(title, p.get("title") or "")
        if sim > best_sim:
            best_sim = sim
            best = p

    if best is None or best_sim < 0.60:
        return None

    # Try DOI field first (most reliable for arXiv preprints)
    doi = best.get("doi") or ""
    m = re.search(r"arxiv[./](\d{4}\.\d{4,5})", doi, re.IGNORECASE)
    if m:
        return m.group(1)

    # Try ids dict
    arxiv_url = (best.get("ids") or {}).get("arxiv", "") or ""
    m = re.search(r"(\d{4}\.\d{4,5})", arxiv_url)
    if m:
        return m.group(1)

    # Try primary_location landing page
    pl = best.get("primary_location") or {}
    url = pl.get("landing_page_url") or ""
    m = re.search(r"arxiv\.org/abs/(\d{4}\.\d{4,5})", url)
    if m:
        return m.group(1)

    return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    cases: list[dict] = []

    with httpx.Client(
        timeout=60,
        headers={"User-Agent": "papergraph-eval/1.0 (mailto:papergraph@example.com)"},
    ) as client:
        # --- Step 1: collect reviews ---
        print("Collecting ICLR 2025 reviews from OpenReview API v2 …")
        reviews_by_forum = collect_reviews(client)

        # --- Steps 2 & 3: compute scores ---
        forum_scores: list[tuple[str, float, list[int]]] = []
        for forum_id, review_notes in reviews_by_forum.items():
            contribs = []
            for note in review_notes:
                c = _get_value(note.get("content", {}).get("contribution"))
                if isinstance(c, int) and 1 <= c <= 4:
                    contribs.append(c)
            if not contribs:
                continue
            human_novelty = compute_human_novelty(contribs)
            forum_scores.append((forum_id, human_novelty, contribs))

        # Sort for diversity sampling (low -> high novelty)
        forum_scores.sort(key=lambda x: x[1])

        # Build summary lookup
        summary_by_forum: dict[str, str] = {}
        for forum_id, review_notes in reviews_by_forum.items():
            for note in review_notes:
                s = _get_value(note.get("content", {}).get("summary", ""))
                if isinstance(s, str) and len(s) > 30:
                    summary_by_forum[forum_id] = s
                    break

        # --- Step 4: recover titles ---
        print("Recovering paper titles from OpenReview …")
        forum_titles: dict[str, str] = {}
        for forum_id, _hn, _c in forum_scores:
            summary = summary_by_forum.get(forum_id, "")
            title = find_paper_title(client, forum_id, summary)
            if title:
                forum_titles[forum_id] = title
            time.sleep(0.5)

        print(f"  Found titles for {len(forum_titles)}/{len(forum_scores)} forums")

        # --- Step 5: arXiv matching via OpenAlex ---
        print("Matching titles to arXiv via OpenAlex …")
        for forum_id, human_novelty, _contribs in forum_scores:
            title = forum_titles.get(forum_id)
            if not title:
                continue
            arxiv_id = search_arxiv_via_openalex(client, title)
            if not arxiv_id:
                continue
            cases.append(
                {
                    "arxiv_id": arxiv_id,
                    "title": title,
                    "human_novelty": human_novelty,
                    "openreview_forum": forum_id,
                }
            )
            print(
                f"  [{len(cases):3d}] arxiv={arxiv_id}  hn={human_novelty:.2f}"
                f"  {title[:55]}"
            )
            if len(cases) >= 25:
                break

    print(f"\nTotal cases assembled: {len(cases)}")

    # --- Write JSONL ---
    CASES_PATH.write_text(
        "\n".join(json.dumps(c, ensure_ascii=False) for c in cases) + "\n",
        encoding="utf-8",
    )
    print(f"Written to {CASES_PATH}")


if __name__ == "__main__":
    main()
