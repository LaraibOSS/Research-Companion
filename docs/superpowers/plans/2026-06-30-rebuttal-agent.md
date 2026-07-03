# Rebuttal Assistant Implementation Plan (Plan 3 of 5)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or superpowers:executing-plans. Checkbox steps.

**Goal:** The approved rebuttal design as a `papergraph/rebuttal/` package + `RebuttalAgent` + `papergraph rebuttal` CLI: paste reviews → segment into concerns → classify → retrieve grounding passages → draft point-by-point replies (tone-controlled) → verify every quoted span → revision changelog + cross-reviewer dedup.

**Architecture:** Pure deterministic units (segment/retrieve/verify/dedup/report) wrap two mockable LLM steps (classify, draft) reached only via an injected callable. Same seam pattern as NoveltyAgent (`_llm`). Two-phase editing: `--emit-segments` writes segments JSON for author correction; `--segments` resumes from it.

**Tech Stack:** Python 3.10, existing prompts-SHA pattern, `refcheck.matching.title_similarity` for dedup, `store.load_text` for fulltext.

## Global Constraints
- Python ≥ 3.10, ruff `E,F,I,B,UP,SIM` line 110 (zip needs `strict=`). TDD: fail→watch→implement→pass; RED/GREEN in report.
- No network/LLM in tests; LLM injected. Sync-in-async via `asyncio.to_thread`.
- Commit ONLY named files per task. NEVER `git add -A`/`.`/`-a`.
- Baseline at plan start: **155 passed** (plus any Plan-2 final-review fix deltas — use the suite count you observe before Task 1 as baseline; each task's expected count is baseline + cumulative new tests).
- Tones: `deferential | balanced | firm` (default `balanced`).

---

### Task 1: Data models

**Files:** Create `papergraph/rebuttal/__init__.py`, `papergraph/rebuttal/models.py` · Test `tests/test_rebuttal_models.py`

**Interfaces (produced):**
```python
@dataclass Concern:   concern_id: str; reviewer: str; text: str; kind: str = ""   # kind set by classifier
@dataclass Passage:   location: str; text: str; score: float
@dataclass ResponseDraft: concern_id: str; reply: str; cited_passages: list[Passage]
                          verified: bool; unverified_spans: list[str]; planned_revision: str = ""
@dataclass RebuttalReport: drafts: list[ResponseDraft]; changelog: list[str]
                           groups: list[list[str]]  # concern_id groups from dedup
```
All with `to_dict()` (JSON-safe; Passage list serialized inline). `concerns_to_json(list[Concern]) -> str` and `concerns_from_json(str) -> list[Concern]` for the two-phase edit flow.

- [ ] **Step 1: failing test**

```python
# tests/test_rebuttal_models.py
"""Tests for rebuttal data models and segment JSON round-trip."""
from __future__ import annotations

import json

from papergraph.rebuttal.models import (
    Concern, Passage, RebuttalReport, ResponseDraft,
    concerns_from_json, concerns_to_json,
)


def test_concern_json_roundtrip():
    cs = [Concern(concern_id="R1.1", reviewer="R1", text="Missing baseline."),
          Concern(concern_id="R2.1", reviewer="R2", text="Unclear notation.", kind="clarification")]
    blob = concerns_to_json(cs)
    back = concerns_from_json(blob)
    assert back == cs
    assert json.loads(blob)[0]["concern_id"] == "R1.1"


def test_report_to_dict_json_safe():
    draft = ResponseDraft(
        concern_id="R1.1", reply="We thank R1...",
        cited_passages=[Passage(location="para 3", text="we compare against X", score=0.8)],
        verified=True, unverified_spans=[], planned_revision="add baseline Y",
    )
    report = RebuttalReport(drafts=[draft], changelog=["add baseline Y"], groups=[["R1.1"]])
    d = report.to_dict()
    json.dumps(d)
    assert d["drafts"][0]["cited_passages"][0]["location"] == "para 3"
```

- [ ] **Step 2: run, watch fail** — `python -m pytest tests/test_rebuttal_models.py -q` → `ModuleNotFoundError: No module named 'papergraph.rebuttal'`
- [ ] **Step 3: implement**

```python
# papergraph/rebuttal/__init__.py
"""Rebuttal assistant: grounded point-by-point responses to reviewer concerns."""
```

```python
# papergraph/rebuttal/models.py
"""Data models for the rebuttal pipeline. All JSON-safe via to_dict/asdict."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field


@dataclass
class Concern:
    concern_id: str
    reviewer: str
    text: str
    kind: str = ""


@dataclass
class Passage:
    location: str
    text: str
    score: float


@dataclass
class ResponseDraft:
    concern_id: str
    reply: str
    cited_passages: list[Passage] = field(default_factory=list)
    verified: bool = False
    unverified_spans: list[str] = field(default_factory=list)
    planned_revision: str = ""


@dataclass
class RebuttalReport:
    drafts: list[ResponseDraft] = field(default_factory=list)
    changelog: list[str] = field(default_factory=list)
    groups: list[list[str]] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def concerns_to_json(concerns: list[Concern]) -> str:
    return json.dumps([asdict(c) for c in concerns], indent=2, ensure_ascii=False)


def concerns_from_json(blob: str) -> list[Concern]:
    return [Concern(**d) for d in json.loads(blob)]
```

- [ ] **Step 4: run, watch pass** — `2 passed`
- [ ] **Step 5: commit** — `git add papergraph/rebuttal/__init__.py papergraph/rebuttal/models.py tests/test_rebuttal_models.py` · msg `feat(rebuttal): data models and segments JSON round-trip`

---

### Task 2: Segmentation (heuristics)

**Files:** Create `papergraph/rebuttal/segment.py` · Test `tests/test_rebuttal_segment.py`

**Interfaces:** `segment_reviews(text: str) -> list[Concern]`. Rules: lines matching `Reviewer <X>` / `# Reviewer <X>` / `== Reviewer <X> ==` (case-insensitive) switch current reviewer (default `R1`); within a reviewer, numbered items (`1.`, `2)`, `-`, `*` at line start) start new concerns; otherwise blank-line-separated paragraphs are concerns; concern_ids are `R<n>.<k>` in encounter order; whitespace-collapsed text; segments shorter than 20 chars are merged into the previous concern (trailing fragments).

- [ ] **Step 1: failing test**

```python
# tests/test_rebuttal_segment.py
"""Tests for reviewer-comment segmentation heuristics."""
from __future__ import annotations

from papergraph.rebuttal.segment import segment_reviews

REVIEW = """Reviewer 1

1. The paper is missing a comparison against baseline X entirely.
2) Notation in section 3 is unclear and inconsistent throughout.

Reviewer 2

- The claimed novelty overlaps with He et al. substantially here.

The evaluation section needs statistical significance tests included.
"""


def test_segment_numbered_and_bulleted_and_paragraphs():
    concerns = segment_reviews(REVIEW)
    ids = [c.concern_id for c in concerns]
    assert ids == ["R1.1", "R1.2", "R2.1", "R2.2"]
    assert concerns[0].reviewer == "R1"
    assert "baseline X" in concerns[0].text
    assert concerns[2].reviewer == "R2"
    assert "He et al." in concerns[2].text
    assert "significance tests" in concerns[3].text


def test_segment_no_headers_defaults_single_reviewer():
    concerns = segment_reviews("First concern paragraph is long enough to count.\n\n"
                               "Second concern paragraph is also long enough here.")
    assert [c.concern_id for c in concerns] == ["R1.1", "R1.2"]


def test_segment_short_fragment_merges_into_previous():
    concerns = segment_reviews("1. A sufficiently long first concern sentence here.\n\nOk.")
    assert len(concerns) == 1
    assert "Ok." in concerns[0].text


def test_segment_empty_input():
    assert segment_reviews("   \n\n ") == []
```

- [ ] **Step 2: run, watch fail** — `ModuleNotFoundError: papergraph.rebuttal.segment`
- [ ] **Step 3: implement**

```python
# papergraph/rebuttal/segment.py
"""Split raw reviewer text into individual Concern items (deterministic heuristics)."""
from __future__ import annotations

import re

from papergraph.rebuttal.models import Concern

_REVIEWER_RE = re.compile(r"^\s*(?:[#=\s]*)reviewer\s+(\w+)", re.IGNORECASE)
_ITEM_RE = re.compile(r"^\s*(?:\d+[.)]|[-*])\s+")
_MIN_LEN = 20


def segment_reviews(text: str) -> list[Concern]:
    concerns: list[Concern] = []
    reviewer_n = 0
    reviewer = "R1"
    counter = 0
    buf: list[str] = []

    def flush():
        nonlocal counter
        body = re.sub(r"\s+", " ", " ".join(buf)).strip()
        buf.clear()
        if not body:
            return
        if len(body) < _MIN_LEN and concerns:
            concerns[-1].text += " " + body
            return
        counter += 1
        concerns.append(Concern(concern_id=f"{reviewer}.{counter}", reviewer=reviewer, text=body))

    for line in text.splitlines():
        m = _REVIEWER_RE.match(line)
        if m:
            flush()
            reviewer_n += 1
            reviewer = f"R{reviewer_n}"
            counter = 0
            continue
        if _ITEM_RE.match(line):
            flush()
            buf.append(_ITEM_RE.sub("", line))
        elif not line.strip():
            flush()
        else:
            buf.append(line)
    flush()
    return concerns
```

- [ ] **Step 4: run, watch pass** — `4 passed`
- [ ] **Step 5: commit** — `git add papergraph/rebuttal/segment.py tests/test_rebuttal_segment.py` · msg `feat(rebuttal): deterministic reviewer-comment segmentation`

---

### Task 3: Quote verification

**Files:** Create `papergraph/rebuttal/verify.py` · Test `tests/test_rebuttal_verify.py`

**Interfaces:** `verify_quote(quote: str, fulltext: str) -> tuple[bool, str]` — (matched, "exact"|"normalized"|"") — normalization = lowercase + whitespace collapse. `verify_reply_quotes(reply: str, fulltext: str) -> list[str]` — returns the list of double-quoted spans (`"..."`) in the reply that do NOT appear in fulltext (the unverified spans); spans under 15 chars are ignored (too generic to check).

- [ ] **Step 1: failing test**

```python
# tests/test_rebuttal_verify.py
"""Tests for rebuttal quote verification against paper fulltext."""
from __future__ import annotations

from papergraph.rebuttal.verify import verify_quote, verify_reply_quotes

TEXT = "In Section 4.2 we compare against BaselineX on three datasets."


def test_verify_quote_exact():
    assert verify_quote("we compare against BaselineX", TEXT) == (True, "exact")


def test_verify_quote_normalized():
    ok, how = verify_quote("WE   compare against baselinex", TEXT)
    assert ok and how == "normalized"


def test_verify_quote_miss():
    assert verify_quote("we outperform everything", TEXT) == (False, "")


def test_verify_reply_quotes_flags_only_unverified_long_spans():
    reply = ('As stated, "we compare against BaselineX on three datasets" already; '
             'we never claim "a fabricated span that is definitely not present" and '
             'short "ok" spans are ignored.')
    bad = verify_reply_quotes(reply, TEXT)
    assert bad == ["a fabricated span that is definitely not present"]
```

- [ ] **Step 2: run, watch fail** — `ModuleNotFoundError: papergraph.rebuttal.verify`
- [ ] **Step 3: implement**

```python
# papergraph/rebuttal/verify.py
"""Verify that spans a draft attributes to the paper actually appear in it."""
from __future__ import annotations

import re

_MIN_SPAN = 15


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower()).strip()


def verify_quote(quote: str, fulltext: str) -> tuple[bool, str]:
    if not quote or not fulltext:
        return False, ""
    if quote in fulltext:
        return True, "exact"
    if _norm(quote) in _norm(fulltext):
        return True, "normalized"
    return False, ""


def verify_reply_quotes(reply: str, fulltext: str) -> list[str]:
    spans = re.findall(r'"([^"]+)"', reply)
    return [s for s in spans if len(s) >= _MIN_SPAN and not verify_quote(s, fulltext)[0]]
```

- [ ] **Step 4: run, watch pass** — `4 passed`
- [ ] **Step 5: commit** — `git add papergraph/rebuttal/verify.py tests/test_rebuttal_verify.py` · msg `feat(rebuttal): quote verification against paper fulltext`

---

### Task 4: Passage retrieval

**Files:** Create `papergraph/rebuttal/retrieve.py` · Test `tests/test_rebuttal_retrieve.py`

**Interfaces:** `retrieve_passages(concern_text: str, fulltext: str, k: int = 3) -> list[Passage]` — split fulltext into paragraphs (blank-line); score each = |shared lowercase word tokens len≥4 between concern and paragraph| / (1 + log(1+len(paragraph words))); return top-k with score>0, `location=f"para {i}"` (1-based), ordered by score desc then i.

- [ ] **Step 1: failing test**

```python
# tests/test_rebuttal_retrieve.py
"""Tests for grounding-passage retrieval (term overlap, deterministic)."""
from __future__ import annotations

from papergraph.rebuttal.retrieve import retrieve_passages

FULLTEXT = """Introduction paragraph about graphs and knowledge.

We evaluate baseline comparison methods against BaselineX with three datasets carefully.

Unrelated paragraph about typography and fonts entirely.
"""


def test_retrieve_ranks_matching_paragraph_first():
    ps = retrieve_passages("Missing baseline comparison against BaselineX", FULLTEXT, k=2)
    assert ps and ps[0].location == "para 2"
    assert "BaselineX" in ps[0].text
    assert ps[0].score > 0


def test_retrieve_returns_empty_when_no_overlap():
    assert retrieve_passages("quantum entanglement spectroscopy", FULLTEXT) == []


def test_retrieve_k_limits():
    ps = retrieve_passages("paragraph about graphs typography datasets", FULLTEXT, k=1)
    assert len(ps) == 1
```

- [ ] **Step 2: run, watch fail** — `ModuleNotFoundError: papergraph.rebuttal.retrieve`
- [ ] **Step 3: implement**

```python
# papergraph/rebuttal/retrieve.py
"""Retrieve the paper passages most relevant to a reviewer concern (no LLM)."""
from __future__ import annotations

import math
import re

from papergraph.rebuttal.models import Passage


def _tokens(s: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", s.lower()) if len(t) >= 4}


def retrieve_passages(concern_text: str, fulltext: str, k: int = 3) -> list[Passage]:
    concern_toks = _tokens(concern_text)
    if not concern_toks:
        return []
    out: list[Passage] = []
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", fulltext) if p.strip()]
    for i, para in enumerate(paragraphs, 1):
        para_toks = _tokens(para)
        shared = concern_toks & para_toks
        if not shared:
            continue
        score = len(shared) / (1 + math.log(1 + len(para.split())))
        out.append(Passage(location=f"para {i}", text=para, score=round(score, 4)))
    out.sort(key=lambda p: (-p.score, p.location))
    return out[:k]
```

- [ ] **Step 4: run, watch pass** — `3 passed`
- [ ] **Step 5: commit** — `git add papergraph/rebuttal/retrieve.py tests/test_rebuttal_retrieve.py` · msg `feat(rebuttal): deterministic passage retrieval for grounding`

---

### Task 5: Cross-reviewer dedup

**Files:** Create `papergraph/rebuttal/dedup.py` · Test `tests/test_rebuttal_dedup.py`

**Interfaces:** `group_concerns(concerns: list[Concern], threshold: float = 0.55) -> list[list[str]]` — greedy grouping by `refcheck.matching.title_similarity` on concern text; each group is concern_ids in encounter order; singletons included; a concern joins the first existing group whose FIRST member's similarity ≥ threshold.

- [ ] **Step 1: failing test**

```python
# tests/test_rebuttal_dedup.py
"""Tests for cross-reviewer concern grouping."""
from __future__ import annotations

from papergraph.rebuttal.dedup import group_concerns
from papergraph.rebuttal.models import Concern


def _c(cid, text):
    return Concern(concern_id=cid, reviewer=cid.split(".")[0], text=text)


def test_similar_concerns_grouped_across_reviewers():
    concerns = [
        _c("R1.1", "The paper is missing a baseline comparison against X"),
        _c("R2.1", "Missing baseline comparison against method X in evaluation"),
        _c("R2.2", "Figures are far too small to read"),
    ]
    groups = group_concerns(concerns)
    assert ["R1.1", "R2.1"] in groups
    assert ["R2.2"] in groups


def test_all_distinct_yields_singletons():
    concerns = [_c("R1.1", "alpha beta gamma delta"), _c("R1.2", "completely different topic entirely")]
    assert group_concerns(concerns) == [["R1.1"], ["R1.2"]]
```

- [ ] **Step 2: run, watch fail** — `ModuleNotFoundError: papergraph.rebuttal.dedup`
- [ ] **Step 3: implement**

```python
# papergraph/rebuttal/dedup.py
"""Group near-duplicate concerns raised by different reviewers."""
from __future__ import annotations

from papergraph.rebuttal.models import Concern
from papergraph.refcheck.matching import title_similarity


def group_concerns(concerns: list[Concern], threshold: float = 0.55) -> list[list[str]]:
    groups: list[list[Concern]] = []
    for c in concerns:
        for g in groups:
            if title_similarity(c.text, g[0].text) >= threshold:
                g.append(c)
                break
        else:
            groups.append([c])
    return [[c.concern_id for c in g] for g in groups]
```

- [ ] **Step 4: run, watch pass** — `2 passed`
- [ ] **Step 5: commit** — `git add papergraph/rebuttal/dedup.py tests/test_rebuttal_dedup.py` · msg `feat(rebuttal): cross-reviewer concern grouping`

---

### Task 6: Rebuttal prompts

**Files:** Modify `papergraph/prompts.py` (append) · Test `tests/test_rebuttal_prompts.py`

**Interfaces:** `CLASSIFY_CONCERN_PROMPT` (placeholder `{concern}`) → JSON `{"kind": "factual_error|misunderstanding|valid_weakness|clarification"}`. `REBUTTAL_DRAFT_PROMPT` (placeholders `{concern}`, `{kind}`, `{passages}`, `{tone}`) → JSON `{"reply": str, "planned_revision": str}`; instructs: quote the paper ONLY via the provided passages, wrap verbatim paper text in double quotes, be `{tone}`. `format_classify_prompt(concern)`, `format_rebuttal_prompt(concern, kind, passages, tone)`, `rebuttal_prompt_sha256()` (sha over both).

- [ ] **Step 1: failing test**

```python
# tests/test_rebuttal_prompts.py
"""Tests for rebuttal classify/draft prompts."""
from __future__ import annotations

from papergraph import prompts


def test_classify_prompt_formats_and_lists_kinds():
    p = prompts.format_classify_prompt("Missing baseline")
    assert "Missing baseline" in p and "{concern}" not in p
    for kind in ("factual_error", "misunderstanding", "valid_weakness", "clarification"):
        assert kind in p


def test_rebuttal_prompt_formats_all_placeholders():
    p = prompts.format_rebuttal_prompt("c", "valid_weakness", "para 1: text", "firm")
    assert "{concern}" not in p and "{passages}" not in p and "{tone}" not in p and "{kind}" not in p
    assert "firm" in p and "para 1: text" in p


def test_rebuttal_sha_stable():
    assert prompts.rebuttal_prompt_sha256() == prompts.rebuttal_prompt_sha256()
```

- [ ] **Step 2: run, watch fail** — `AttributeError`
- [ ] **Step 3: implement** — append to `papergraph/prompts.py`:

```python
# ---------------------------------------------------------------------------
# Rebuttal prompts (rebuttal/draft.py). SHA-cached.
# ---------------------------------------------------------------------------

CLASSIFY_CONCERN_PROMPT = """Classify this peer-review concern into exactly one kind.

Concern:
{concern}

Kinds:
- factual_error: the reviewer states something factually wrong about the paper
- misunderstanding: the paper already addresses this but the reviewer missed it
- valid_weakness: a genuine limitation the authors should concede
- clarification: a question or request for more detail

Return ONLY valid JSON: {{"kind": "factual_error|misunderstanding|valid_weakness|clarification"}}
"""

REBUTTAL_DRAFT_PROMPT = """Draft a point-by-point rebuttal reply to one reviewer concern.

Concern ({kind}):
{concern}

Relevant passages from OUR paper (the only paper text you may quote):
{passages}

Tone: {tone}. Be professional and specific.

Rules:
- If you reference our paper's text verbatim, wrap it in double quotes and copy it
  EXACTLY from the passages above. Never invent paper text.
- If the concern is a valid_weakness, concede honestly and state a concrete revision.
- End with what we will change in the revision (or "No change needed" plus why).

Return ONLY valid JSON: {{"reply": "...", "planned_revision": "..."}}
"""


def format_classify_prompt(concern: str) -> str:
    return CLASSIFY_CONCERN_PROMPT.format(concern=concern)


def format_rebuttal_prompt(concern: str, kind: str, passages: str, tone: str) -> str:
    return REBUTTAL_DRAFT_PROMPT.format(concern=concern, kind=kind, passages=passages, tone=tone)


def rebuttal_prompt_sha256() -> str:
    both = CLASSIFY_CONCERN_PROMPT + REBUTTAL_DRAFT_PROMPT
    return hashlib.sha256(both.encode("utf-8")).hexdigest()
```

- [ ] **Step 4: run, watch pass** — `3 passed`
- [ ] **Step 5: commit** — `git add papergraph/prompts.py tests/test_rebuttal_prompts.py` · msg `feat(prompts): rebuttal classify and draft prompts`

---

### Task 7: Draft pipeline

**Files:** Create `papergraph/rebuttal/draft.py` · Test `tests/test_rebuttal_draft.py`

**Interfaces:** `draft_rebuttal(concerns, fulltext, llm, tone="balanced") -> RebuttalReport` (synchronous; the agent wraps it in to_thread). Per concern: classify via llm(classify prompt) → JSON kind (invalid JSON → RuntimeError with "rebuttal"); retrieve passages; draft via llm(draft prompt) → reply + planned_revision; `unverified = verify_reply_quotes(reply, fulltext)`; `verified = not unverified`; changelog = all non-empty planned_revisions (deduped, order-preserving); groups = `group_concerns(concerns)`. Reuses `extract._strip_code_fences` for JSON parsing.

- [ ] **Step 1: failing test**

```python
# tests/test_rebuttal_draft.py
"""Tests for the rebuttal drafting pipeline (LLM injected)."""
from __future__ import annotations

import json

import pytest

from papergraph.rebuttal.draft import draft_rebuttal
from papergraph.rebuttal.models import Concern

FULLTEXT = "Intro.\n\nIn Section 4.2 we compare against BaselineX on three datasets.\n"


def _llm(prompt: str) -> str:
    if '"kind"' in prompt:
        return json.dumps({"kind": "misunderstanding"})
    return json.dumps({
        "reply": 'We respectfully note "we compare against BaselineX on three datasets" in §4.2.',
        "planned_revision": "Make the baseline comparison more prominent.",
    })


def _bad_reply_llm(prompt: str) -> str:
    if '"kind"' in prompt:
        return json.dumps({"kind": "factual_error"})
    return json.dumps({"reply": 'The paper says "a totally fabricated sentence not in the paper".',
                       "planned_revision": ""})


def test_draft_grounds_verifies_and_builds_changelog():
    concerns = [Concern(concern_id="R1.1", reviewer="R1",
                        text="Missing baseline comparison against BaselineX")]
    report = draft_rebuttal(concerns, FULLTEXT, _llm)
    d = report.drafts[0]
    assert d.concern_id == "R1.1" and d.verified and d.unverified_spans == []
    assert d.cited_passages and d.cited_passages[0].location == "para 2"
    assert report.changelog == ["Make the baseline comparison more prominent."]
    assert report.groups == [["R1.1"]]
    assert concerns[0].kind == "misunderstanding"


def test_draft_flags_unverified_spans():
    concerns = [Concern(concern_id="R1.1", reviewer="R1", text="Some concern text here")]
    report = draft_rebuttal(concerns, FULLTEXT, _bad_reply_llm)
    d = report.drafts[0]
    assert not d.verified
    assert d.unverified_spans == ["a totally fabricated sentence not in the paper"]


def test_draft_bad_json_raises_runtimeerror():
    concerns = [Concern(concern_id="R1.1", reviewer="R1", text="Some concern text here")]
    with pytest.raises(RuntimeError, match="rebuttal"):
        draft_rebuttal(concerns, FULLTEXT, lambda p: "NOT JSON")
```

- [ ] **Step 2: run, watch fail** — `ModuleNotFoundError: papergraph.rebuttal.draft`
- [ ] **Step 3: implement**

```python
# papergraph/rebuttal/draft.py
"""Rebuttal drafting pipeline: classify -> retrieve -> draft -> verify -> assemble."""
from __future__ import annotations

import json
from collections.abc import Callable

from papergraph.rebuttal.dedup import group_concerns
from papergraph.rebuttal.models import Concern, RebuttalReport, ResponseDraft
from papergraph.rebuttal.retrieve import retrieve_passages
from papergraph.rebuttal.verify import verify_reply_quotes


def _parse(raw: str, what: str) -> dict:
    from papergraph.extract import _strip_code_fences

    try:
        return json.loads(_strip_code_fences(raw))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"rebuttal: LLM returned invalid JSON for {what}: {exc}") from exc


def draft_rebuttal(
    concerns: list[Concern],
    fulltext: str,
    llm: Callable[[str], str],
    tone: str = "balanced",
) -> RebuttalReport:
    from papergraph.prompts import format_classify_prompt, format_rebuttal_prompt

    drafts: list[ResponseDraft] = []
    changelog: list[str] = []
    for c in concerns:
        c.kind = _parse(llm(format_classify_prompt(c.text)), "classification").get(
            "kind", "clarification")
        passages = retrieve_passages(c.text, fulltext)
        passage_block = "\n".join(f"{p.location}: {p.text}" for p in passages) or "(none found)"
        out = _parse(llm(format_rebuttal_prompt(c.text, c.kind, passage_block, tone)), "draft")
        reply = out.get("reply", "")
        unverified = verify_reply_quotes(reply, fulltext)
        revision = out.get("planned_revision", "")
        if revision and revision not in changelog:
            changelog.append(revision)
        drafts.append(ResponseDraft(
            concern_id=c.concern_id, reply=reply, cited_passages=passages,
            verified=not unverified, unverified_spans=unverified,
            planned_revision=revision,
        ))
    return RebuttalReport(drafts=drafts, changelog=changelog, groups=group_concerns(concerns))
```

- [ ] **Step 4: run, watch pass** — `3 passed`
- [ ] **Step 5: full suite once, commit** — `git add papergraph/rebuttal/draft.py tests/test_rebuttal_draft.py` · msg `feat(rebuttal): drafting pipeline with grounding and verification`

---

### Task 8: RebuttalAgent + CLI + e2e

**Files:** Create `papergraph/agents/rebuttal.py` · Modify `papergraph/cli.py` (`_cmd_rebuttal` before `_build_parser`; subparser after `review` block) · Test `tests/test_cli_rebuttal.py`

**Interfaces:**
- `RebuttalAgent` — `name="rebuttal"`, `depends_on=("ingest",)`; consumes `ctx.data["_reviews_text"]` (raw reviews str) or `ctx.data["_concerns"]` (pre-segmented list[Concern], wins if present), `ctx.data["_llm"]`, `ctx.data.get("_tone", "balanced")`, fulltext via `store.load_text`; runs `await asyncio.to_thread(draft_rebuttal, ...)`; publishes `Finding(kind="rebuttal_draft")` per draft + `Finding(kind="rebuttal_report")`; result data = `RebuttalReport.to_dict()` + `{"concerns": [asdict(c)]}`.
- CLI: `papergraph rebuttal <paper_id> --reviews FILE [--emit-segments OUT] [--segments FILE] [--tone deferential|balanced|firm] [--json]`. `--emit-segments`: segment only, write `concerns_to_json`, print count, exit 0 (no LLM). `--segments`: load concerns from file instead of segmenting. Human output: per draft — concern id + kind, reply, `[OK all quotes verified]` or `[CHECK n unverified span(s)]`, planned revision; then `Planned revisions:` list. Exit 1 if paper/reviews missing or agent failed. Module-level `REBUTTAL_CONTEXT_OVERRIDES: dict = {}` test seam (same pattern as review).

- [ ] **Step 1: failing test**

```python
# tests/test_cli_rebuttal.py
"""End-to-end tests for `papergraph rebuttal` — LLM injected, no network."""
from __future__ import annotations

import json

import pytest

from papergraph import cli, store
from papergraph.prompts import extraction_prompt_sha256

REVIEWS = """Reviewer 1

1. Missing baseline comparison against BaselineX in the evaluation.
"""


def _seed():
    pid = "local:rebut0000001"
    store.PaperMetadata(paper_id=pid, title="P", authors=[]).save()
    store.save_extraction(pid, {"related_work": []}, prompt_sha=extraction_prompt_sha256())
    store.save_text(pid, "Intro.\n\nIn Section 4.2 we compare against BaselineX on three datasets.\n")
    return pid


def _llm(prompt):
    if '"kind"' in prompt:
        return json.dumps({"kind": "misunderstanding"})
    return json.dumps({"reply": 'See "we compare against BaselineX on three datasets".',
                       "planned_revision": "Highlight baseline comparison."})


def test_rebuttal_cli_end_to_end(monkeypatch: pytest.MonkeyPatch, tmp_path, capsys):
    pid = _seed()
    reviews = tmp_path / "reviews.txt"
    reviews.write_text(REVIEWS, encoding="utf-8")
    monkeypatch.setattr(cli, "REBUTTAL_CONTEXT_OVERRIDES", {"_llm": _llm})
    rc = cli.main(["rebuttal", pid, "--reviews", str(reviews)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "R1.1" in out and "misunderstanding" in out
    assert "verified" in out.lower()
    assert "Highlight baseline comparison." in out


def test_rebuttal_cli_emit_and_resume_segments(monkeypatch: pytest.MonkeyPatch, tmp_path, capsys):
    pid = _seed()
    reviews = tmp_path / "reviews.txt"
    reviews.write_text(REVIEWS, encoding="utf-8")
    seg = tmp_path / "segments.json"
    rc = cli.main(["rebuttal", pid, "--reviews", str(reviews), "--emit-segments", str(seg)])
    assert rc == 0 and seg.exists()
    assert json.loads(seg.read_text(encoding="utf-8"))[0]["concern_id"] == "R1.1"
    capsys.readouterr()
    monkeypatch.setattr(cli, "REBUTTAL_CONTEXT_OVERRIDES", {"_llm": _llm})
    rc2 = cli.main(["rebuttal", pid, "--segments", str(seg), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc2 == 0
    assert payload["drafts"][0]["concern_id"] == "R1.1"


def test_rebuttal_cli_missing_reviews_errors(capsys):
    pid = _seed()
    rc = cli.main(["rebuttal", pid])
    assert rc == 1
    assert "reviews" in capsys.readouterr().err.lower()
```

- [ ] **Step 2: run, watch fail** — argparse `invalid choice: 'rebuttal'` (SystemExit 2)
- [ ] **Step 3: implement**

`papergraph/agents/rebuttal.py`:

```python
# papergraph/agents/rebuttal.py
"""RebuttalAgent: grounded point-by-point replies to reviewer concerns."""
from __future__ import annotations

import asyncio
from dataclasses import asdict

from papergraph.agents import events
from papergraph.agents.base import Agent, AgentContext, AgentResult


class RebuttalAgent(Agent):
    name = "rebuttal"
    role = "Drafts evidence-grounded responses to every reviewer concern."
    depends_on = ("ingest",)

    async def run(self, ctx: AgentContext) -> AgentResult:
        from papergraph.agents.novelty import _default_llm
        from papergraph.rebuttal.draft import draft_rebuttal
        from papergraph.rebuttal.segment import segment_reviews
        from papergraph.store import load_text

        concerns = ctx.data.get("_concerns")
        if concerns is None:
            reviews_text = ctx.data.get("_reviews_text", "")
            if not reviews_text.strip():
                return AgentResult(agent=self.name, ok=False,
                                   error="no reviews provided (use --reviews or --segments)")
            concerns = segment_reviews(reviews_text)
        if not concerns:
            return AgentResult(agent=self.name, ok=False, error="no concerns found in reviews")

        llm = ctx.data.get("_llm") or _default_llm
        tone = ctx.data.get("_tone", "balanced")
        fulltext = load_text(ctx.paper_id) or ""

        report = await asyncio.to_thread(draft_rebuttal, concerns, fulltext, llm, tone)
        for d in report.drafts:
            await ctx.bus.publish(events.Finding(
                agent=self.name, kind="rebuttal_draft",
                summary=f"{d.concern_id}: {'verified' if d.verified else 'CHECK quotes'}",
                data={"concern_id": d.concern_id, "verified": d.verified},
            ))
        await ctx.bus.publish(events.Finding(
            agent=self.name, kind="rebuttal_report",
            summary=f"{len(report.drafts)} draft(s), {len(report.changelog)} planned revision(s)",
            data={"drafts": len(report.drafts)},
        ))
        data = report.to_dict()
        data["concerns"] = [asdict(c) for c in concerns]
        return AgentResult(agent=self.name, ok=True, data=data)
```

`papergraph/cli.py` — add before `_build_parser` (after `_cmd_review`):

```python
REBUTTAL_CONTEXT_OVERRIDES: dict = {}


def _cmd_rebuttal(args: argparse.Namespace) -> int:
    import asyncio

    from papergraph.agents.base import AgentContext
    from papergraph.agents.bus import Bus
    from papergraph.agents.ingest import IngestAgent
    from papergraph.agents.orchestrator import run_agents
    from papergraph.agents.rebuttal import RebuttalAgent
    from papergraph.rebuttal.models import concerns_from_json, concerns_to_json
    from papergraph.rebuttal.segment import segment_reviews

    if not args.reviews and not args.segments:
        print("papergraph: provide --reviews FILE or --segments FILE.", file=sys.stderr)
        return 1

    reviews_text = ""
    if args.reviews:
        rpath = Path(args.reviews)
        if not rpath.is_file():
            print(f"papergraph: reviews file not found: {rpath}", file=sys.stderr)
            return 1
        reviews_text = rpath.read_text(encoding="utf-8")

    if args.emit_segments:
        concerns = segment_reviews(reviews_text)
        Path(args.emit_segments).write_text(concerns_to_json(concerns), encoding="utf-8")
        print(f"papergraph: wrote {len(concerns)} segment(s) to {args.emit_segments}. "
              "Edit, then rerun with --segments.")
        return 0

    ctx_data = dict(REBUTTAL_CONTEXT_OVERRIDES)
    ctx_data["_reviews_text"] = reviews_text
    ctx_data["_tone"] = args.tone
    if args.segments:
        ctx_data["_concerns"] = concerns_from_json(
            Path(args.segments).read_text(encoding="utf-8"))

    ctx = AgentContext(paper_id=args.paper_id, bus=Bus(), data=ctx_data)
    results = asyncio.run(run_agents([IngestAgent(), RebuttalAgent()], ctx))
    reb = results["rebuttal"]
    if not reb.ok:
        print(f"papergraph: rebuttal failed: {reb.error}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(reb.data, indent=2, ensure_ascii=False))
        return 0

    kinds = {c["concern_id"]: c["kind"] for c in reb.data["concerns"]}
    for d in reb.data["drafts"]:
        status = ("[OK all quotes verified]" if d["verified"]
                  else f"[CHECK {len(d['unverified_spans'])} unverified span(s)]")
        print(f"\n{d['concern_id']} ({kinds.get(d['concern_id'], '?')})  {status}")
        print(f"  {d['reply']}")
        if d["planned_revision"]:
            print(f"  Revision: {d['planned_revision']}")
    if reb.data["changelog"]:
        print("\nPlanned revisions:")
        for item in reb.data["changelog"]:
            print(f"  - {item}")
    return 0
```

Subparser (after the `review` block, before `return p`):

```python
    prb = sub.add_parser("rebuttal", help="Draft grounded replies to reviewer comments")
    prb.add_argument("paper_id", help="ID of a paper already built")
    prb.add_argument("--reviews", help="Path to a text file with the reviewer comments")
    prb.add_argument("--emit-segments", help="Segment reviews, write JSON here, and stop")
    prb.add_argument("--segments", help="Resume from an edited segments JSON file")
    prb.add_argument("--tone", choices=["deferential", "balanced", "firm"], default="balanced")
    prb.add_argument("--json", action="store_true", help="JSON output")
    prb.set_defaults(func=_cmd_rebuttal)
```

- [ ] **Step 4: run, watch pass** — `python -m pytest tests/test_cli_rebuttal.py -q` → `3 passed`
- [ ] **Step 5: full suite + ruff on all plan-3 files (fix I001 only), commit** — `git add papergraph/agents/rebuttal.py papergraph/cli.py tests/test_cli_rebuttal.py` · msg `feat(cli): papergraph rebuttal - grounded reviewer responses end-to-end`

---

## Verification (whole plan)
1. `python -m pytest -q` — green (baseline + 24 new across 8 tasks).
2. Ruff clean on `papergraph/rebuttal papergraph/agents/rebuttal.py papergraph/cli.py papergraph/prompts.py tests/test_rebuttal_*.py tests/test_cli_rebuttal.py`.
3. Offline smoke: seed paper + reviews file, run `rebuttal` end-to-end with injected `_llm` (human + `--json` + emit/resume paths).

## What later plans consume
- Plan 4: `rebuttal_draft`/`rebuttal_report` Finding kinds; `RebuttalReport.to_dict()` shape for the report page.
- Plan 5 eval: `verify_reply_quotes` counts as a groundedness metric.
