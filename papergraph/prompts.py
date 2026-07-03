"""Centralized LLM prompts.

All prompts in one auditable file. Prompt SHA256 is recorded in extraction cache
so changes to the prompt automatically invalidate previously-cached extractions.
"""
from __future__ import annotations

import hashlib


# ---------------------------------------------------------------------------
# Paper extraction prompt
# ---------------------------------------------------------------------------
# Extracts structured entities from a single paper. Schema is intentionally narrow:
#   concepts  — abstract ideas the paper introduces or builds on
#   methods   — concrete techniques / algorithms / architectures the paper uses or proposes
#   datasets  — named datasets used or introduced
#   claims    — main empirical or theoretical claims (1-sentence each)
#   results   — quantitative results (metric, value, dataset)
#   related_work — referenced prior work (informal title strings; we don't try to resolve to IDs in v0.1)

EXTRACTION_PROMPT = """You are extracting a structured knowledge graph from a research paper.

Return JSON ONLY (no prose, no markdown fences) matching this schema exactly:

{
  "concepts": [
    {"name": "string (concise, lowercase phrase)", "definition": "one sentence"}
  ],
  "methods": [
    {"name": "string (canonical name, e.g. 'GraphRAG', 'BM25')", "description": "one sentence"}
  ],
  "datasets": [
    {"name": "string (canonical name, e.g. 'HotpotQA')", "description": "one sentence on what it is"}
  ],
  "claims": [
    {"text": "one-sentence claim made by the paper, in the paper's voice"}
  ],
  "results": [
    {"metric": "string (e.g. 'F1', 'pass@1')", "value": "string (e.g. '78.9')", "dataset": "string (must match a dataset name above, or be a string)"}
  ],
  "related_work": [
    "string (a referenced paper title or first-author + year, e.g. 'Lewis et al. 2020')"
  ]
}

Rules:
- Be precise and selective. Quality over quantity. Prefer 5 important concepts over 20 weak ones.
- Concept/method/dataset names must be canonical. "Graph RAG", "graphrag", and "GraphRAG" should all be "GraphRAG".
- Claims are the paper's own assertions, not your evaluation of them.
- Results: only include numeric results explicitly stated in the paper.
- related_work: just the names/titles as they appear in the paper. Do NOT fabricate IDs or URLs.
- If a section is absent, return an empty list for it.
- DO NOT wrap the JSON in code fences or add commentary. Output starts with `{` and ends with `}`.

Paper title: <<TITLE>>
Paper authors: <<AUTHORS>>

Paper text follows. Extract from this text only:
---
<<PAPER_TEXT>>
---

JSON output:"""


def render_extraction_prompt(*, title: str, authors: str, paper_text: str) -> str:
    """Substitute placeholders in EXTRACTION_PROMPT.

    Uses .replace() rather than .format() because the prompt contains literal
    JSON-schema braces that would confuse str.format.
    """
    return (
        EXTRACTION_PROMPT
        .replace("<<TITLE>>", title)
        .replace("<<AUTHORS>>", authors)
        .replace("<<PAPER_TEXT>>", paper_text)
    )


# ---------------------------------------------------------------------------
# Chat answer-generation prompt
# ---------------------------------------------------------------------------
# Used by chat.py. Receives a question + a graph subgraph rendered as text + a
# list of papers contributing to that subgraph. Must cite sources.

CHAT_SYSTEM_PROMPT = """You answer questions about a corpus of research papers using ONLY the knowledge-graph context provided. You are precise, terse, and always cite sources.

Rules:
1. Use ONLY the context provided. Do NOT use prior knowledge about papers, authors, or methods.
2. If the context is insufficient, say "The knowledge graph does not contain enough information to answer this." Do not speculate.
3. Cite every factual claim with the paper title in square brackets, e.g. "GraphRAG uses community summaries [Edge et al., 2024]". Multiple papers: "[A et al., 2023; B et al., 2024]".
4. Keep answers under 150 words unless the user asks for detail.
5. When listing methods or approaches, prefer a numbered list with one citation per item.
6. Do NOT invent paper titles or author names not present in the context.
"""


CHAT_USER_PROMPT = """Knowledge graph context:
---
<<CONTEXT>>
---

Papers in this context:
<<PAPER_LIST>>

Question: <<QUESTION>>

Answer (cite sources):"""


def render_chat_user_prompt(*, context: str, paper_list: str, question: str) -> str:
    """Substitute placeholders in CHAT_USER_PROMPT."""
    return (
        CHAT_USER_PROMPT
        .replace("<<CONTEXT>>", context)
        .replace("<<PAPER_LIST>>", paper_list)
        .replace("<<QUESTION>>", question)
    )


# ---------------------------------------------------------------------------
# Hashes — recorded in extraction cache + chat telemetry
# ---------------------------------------------------------------------------

def extraction_prompt_sha256() -> str:
    return hashlib.sha256(EXTRACTION_PROMPT.encode("utf-8")).hexdigest()


def chat_prompt_sha256() -> str:
    combined = (CHAT_SYSTEM_PROMPT + "\n---\n" + CHAT_USER_PROMPT).encode("utf-8")
    return hashlib.sha256(combined).hexdigest()


# ---------------------------------------------------------------------------
# Novelty assessment prompts (agents/novelty.py). SHA-cached like extraction.
# ---------------------------------------------------------------------------

CONTRIBUTION_PROMPT = """You are extracting the claimed contributions of a research paper.

Paper title: {title}

Paper text:
{paper_text}

Return ONLY valid JSON, no markdown fences, matching exactly:
{{
  "claims": [
    {{
      "text": "one-sentence statement of the claimed contribution",
      "kind": "method|dataset|finding|theory|application|resource",
      "evidence_quote": "short verbatim span from the paper supporting this claim"
    }}
  ]
}}

Rules:
- 2 to 6 claims. Only contributions the AUTHORS claim as new.
- evidence_quote must be copied verbatim from the paper text above.
"""


COMPARISON_PROMPT = """You are assessing the novelty of one claimed contribution against prior work.

Claimed contribution:
{claim}

Prior work (title, year - abstract):
{prior_art}

Return ONLY valid JSON, no markdown fences, matching exactly:
{{
  "verdict": "novel|incremental|overlaps|anticipated",
  "confidence": 0.0,
  "closest_prior": ["title of the most similar prior work, if any"],
  "rationale": "one or two sentences grounded in the prior work above"
}}

Rules:
- Base the verdict ONLY on the prior work listed above. If none is similar, verdict is "novel".
- confidence is your certainty in the verdict, 0.0-1.0.
"""


def format_contribution_prompt(title: str, paper_text: str) -> str:
    return CONTRIBUTION_PROMPT.format(title=title, paper_text=paper_text)


def format_comparison_prompt(claim: str, prior_art: str) -> str:
    return COMPARISON_PROMPT.format(claim=claim, prior_art=prior_art)


def novelty_prompt_sha256() -> str:
    both = CONTRIBUTION_PROMPT + COMPARISON_PROMPT
    return hashlib.sha256(both.encode("utf-8")).hexdigest()
