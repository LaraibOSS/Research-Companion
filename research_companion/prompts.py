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
  ],
  "paper_meta": {
    "title": "string — this paper's real title as printed on the first page (NOT a filename)",
    "authors": ["string — author names as printed, first author first"],
    "year": "integer — publication year, or null if not determinable"
  }
}

Rules:
- Be precise and selective. Quality over quantity. Prefer 5 important concepts over 20 weak ones.
- Concept/method/dataset names must be canonical. "Graph RAG", "graphrag", and "GraphRAG" should all be "GraphRAG".
- Claims are the paper's own assertions, not your evaluation of them.
- Results: only include numeric results explicitly stated in the paper.
- related_work: just the names/titles as they appear in the paper. Do NOT fabricate IDs or URLs.
- paper_meta describes THIS paper's own bibliography (its title/authors/year), distinct from related_work which lists cited prior work. Read it from the first page; use null for year if not determinable.
- If a section is absent, return an empty list for it.
- DO NOT wrap the JSON in code fences or add commentary. Output starts with `{` and ends with `}`.
<<SECTION_OUTLINE_BLOCK>>
Paper title: <<TITLE>>
Paper authors: <<AUTHORS>>

Paper text follows. Extract from this text only:
---
<<PAPER_TEXT>>
---

JSON output:"""

_SECTION_OUTLINE_INSTRUCTION = """\

Section outline (the paper is divided into these sections, in order):
<<SECTION_OUTLINE>>

Additional rules when section outline is provided:
- Every object in concepts, methods, datasets, claims, and results must include a "section" field.
- Set "section" to the id of the section it primarily comes from (one of the listed ids above),
  or null when the entity spans multiple sections or the section is unclear.
- related_work entries do NOT need a "section" field.

"""


def render_extraction_prompt(
    *,
    title: str,
    authors: str,
    paper_text: str,
    section_outline: str = "",
) -> str:
    """Substitute placeholders in EXTRACTION_PROMPT.

    Uses .replace() rather than .format() because the prompt contains literal
    JSON-schema braces that would confuse str.format.

    section_outline: one line per section in the form ``id title``, e.g.::

        s1 Introduction
        s2 Methods
        s2.1 Datasets

    When empty (default) the rendered prompt contains no mention of sections
    and degrades to exactly the original behavior.
    """
    if section_outline:
        outline_block = _SECTION_OUTLINE_INSTRUCTION.replace(
            "<<SECTION_OUTLINE>>", section_outline
        )
    else:
        outline_block = ""

    return (
        EXTRACTION_PROMPT
        .replace("<<SECTION_OUTLINE_BLOCK>>", outline_block)
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


# ---------------------------------------------------------------------------
# Citation polarity prompts (graph-enrichment). SHA-cached.
# ---------------------------------------------------------------------------

CITATION_POLARITY_PROMPT = """You are labeling how a paper relates to each work it cites.

Paper title: {title}

Paper text:
{paper_text}

Cited works (one per line):
{citations}

For EACH cited work, decide the paper's stance toward it and copy a short
verbatim quote from the paper text above that shows the stance.

Return ONLY valid JSON, no markdown fences, matching exactly:
{{
  "citations": [
    {{
      "cite": "the cited work string, exactly as given above",
      "polarity": "based_on|support|contrast|refutation|mention",
      "evidence_quote": "short verbatim span from the paper text (may be empty if none)",
      "rationale": "one short clause"
    }}
  ]
}}

Polarity meanings:
- based_on: the paper builds on / extends / uses this work.
- support: the paper agrees with or is corroborated by this work.
- contrast: the paper differs from or compares against this work.
- refutation: the paper disputes, challenges, or refutes this work.
- mention: a passing reference with no clear stance.

Rules:
- Include every cited work exactly once, using the string as given.
- evidence_quote MUST be copied verbatim from the paper text, or be "".
- When unsure, use "mention".
"""


def format_citation_polarity_prompt(title: str, paper_text: str, citations: list[str]) -> str:
    joined = "\n".join(str(c) for c in citations)
    return CITATION_POLARITY_PROMPT.format(title=title, paper_text=paper_text, citations=joined)


def citation_polarity_prompt_sha256() -> str:
    return hashlib.sha256(CITATION_POLARITY_PROMPT.encode("utf-8")).hexdigest()


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


# ---------------------------------------------------------------------------
# Problem-statement refinement prompt (agents/problem.py). SHA-cached.
# ---------------------------------------------------------------------------

PROBLEM_PROMPT = """You are a research advisor helping refine a researcher's problem statement
against a knowledge graph and prior-art context.

Problem statement:
{statement}

Knowledge-graph context (top concepts by centrality + relevant prior-art titles):
{graph_context}

Return ONLY valid JSON, no markdown fences, matching exactly:
{{
  "refined_statement": "one precise sentence capturing the sharpened research question",
  "gaps": [
    "gap 1 grounded in the graph context above",
    "gap 2 grounded in the graph context above"
  ],
  "next_steps": [
    "concrete next step 1",
    "concrete next step 2"
  ]
}}

Rules:
- refined_statement must sharpen the original statement — do not copy it verbatim.
- gaps must be grounded ONLY in the provided graph context; do not invent prior work.
- next_steps are concrete, actionable research tasks.
- Return ONLY valid JSON. Output starts with {{ and ends with }}.
"""


def format_problem_prompt(statement: str, graph_context: str) -> str:
    return PROBLEM_PROMPT.format(statement=statement, graph_context=graph_context)


def problem_prompt_sha256() -> str:
    return hashlib.sha256(PROBLEM_PROMPT.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Alignment prompt (agents/align.py). SHA-cached.
# Assesses how a candidate paper relates to sections of a draft paper.
# ---------------------------------------------------------------------------

ALIGNMENT_PROMPT = """You are assessing how a candidate paper relates to the sections of a draft paper.

Draft paper sections (id, title, first ~400 chars each):
<<DRAFT_SECTIONS_BLOCK>>

Candidate paper (title, abstract/first chunk, claims):
<<CANDIDATE_BLOCK>>

For each draft section, determine the relation of the candidate paper to that section.

Return ONLY valid JSON, no markdown fences, matching exactly:
{
  "sections": [
    {
      "section_id": "string (one of the section ids listed above)",
      "relation": "strengthens|challenges|different_perspective|irrelevant",
      "relevance": 0.0,
      "rationale": "one or two sentences grounded in the blocks above",
      "evidence": [
        {"quote": "verbatim quote from the candidate paper text"}
      ]
    }
  ]
}

Rules:
- Relation must be exactly one of: strengthens, challenges, different_perspective, irrelevant.
- relevance is a float between 0.0 and 1.0 (0 = completely irrelevant, 1 = highly relevant).
- rationale must be grounded ONLY in the provided draft sections and candidate blocks.
- evidence quotes MUST be verbatim from the candidate paper text provided above. Do not paraphrase.
  If no direct quote supports the relation, use an empty list for evidence.
- Return one entry per draft section.
- Return ONLY valid JSON. Output starts with { and ends with }.
"""


def format_alignment_prompt(*, draft_sections_block: str, candidate_block: str) -> str:
    """Substitute placeholders in ALIGNMENT_PROMPT."""
    return (
        ALIGNMENT_PROMPT
        .replace("<<DRAFT_SECTIONS_BLOCK>>", draft_sections_block)
        .replace("<<CANDIDATE_BLOCK>>", candidate_block)
    )


def alignment_prompt_sha256() -> str:
    return hashlib.sha256(ALIGNMENT_PROMPT.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# QA prompt (agents/qa.py). SHA-cached.
# Answers a question using only numbered sources, citing [S#] inline.
# ---------------------------------------------------------------------------

QA_PROMPT = """You answer a research question using ONLY the numbered sources provided.

Question: <<QUESTION>>

Sources:
<<SOURCES_BLOCK>>

Rules:
- Use ONLY the numbered sources above ([S1], [S2], ...). Do NOT use prior knowledge.
- Cite [S#] inline after every factual claim (e.g. "GraphRAG uses community summaries [S1]").
- When quoting, quote exactly and verbatim from the source text. Wrap quotes in double quotes.
- If the sources are insufficient to answer the question, say so explicitly:
  "The provided sources do not contain enough information to answer this question."
- Keep the answer focused and under 200 words unless detail is explicitly requested.
- Do NOT invent facts, paper titles, author names, or results not present in the sources.

Answer (cite [S#] after every claim):"""


def format_qa_prompt(*, question: str, sources_block: str) -> str:
    """Substitute placeholders in QA_PROMPT."""
    return (
        QA_PROMPT
        .replace("<<QUESTION>>", question)
        .replace("<<SOURCES_BLOCK>>", sources_block)
    )


def qa_prompt_sha256() -> str:
    return hashlib.sha256(QA_PROMPT.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Compare prompt (agents/compare.py). SHA-cached.
# Produces a short narrative comparison of two papers grounded in provided blocks.
# ---------------------------------------------------------------------------

COMPARE_PROMPT = """You are writing a short narrative comparison of two research papers.

Paper A:
<<PAPER_A_BLOCK>>

Paper B:
<<PAPER_B_BLOCK>>

Shared context (datasets, methods, or topics both papers address):
<<SHARED_BLOCK>>

Write a concise comparison of 3-6 sentences. Cite paper titles in [brackets] whenever you refer
to a specific paper (e.g. [Paper Title A]). Your comparison must be grounded only in the provided
blocks above — do NOT introduce facts, claims, or results not present in the blocks.

Comparison:"""


def format_compare_prompt(
    *, paper_a_block: str, paper_b_block: str, shared_block: str
) -> str:
    """Substitute placeholders in COMPARE_PROMPT."""
    return (
        COMPARE_PROMPT
        .replace("<<PAPER_A_BLOCK>>", paper_a_block)
        .replace("<<PAPER_B_BLOCK>>", paper_b_block)
        .replace("<<SHARED_BLOCK>>", shared_block)
    )


def compare_prompt_sha256() -> str:
    return hashlib.sha256(COMPARE_PROMPT.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Suggest-structure prompt (suggestions.py). SHA-cached.
# Proposes structure improvements given a section outline + open deterministic
# suggestions. Strict JSON output — bad JSON is silently skipped by caller.
# ---------------------------------------------------------------------------

SUGGEST_STRUCTURE_PROMPT = """You are a research writing advisor reviewing a paper draft.

Section outline (id title, one per line):
<<SECTION_OUTLINE>>

Open deterministic suggestions already identified (one per line):
<<OPEN_SUGGESTIONS>>

Propose up to 3 structural improvements NOT already covered by the open suggestions above.
Focus on: missing sections, section ordering, depth imbalance, clarity of transitions.

Return ONLY valid JSON, no markdown fences, matching exactly:
{
  "suggestions": [
    {
      "title": "one short imperative sentence",
      "detail": "one to two sentences explaining what to fix and why",
      "section_id": "the id of the most relevant section, or null",
      "severity": "high|medium|low"
    }
  ]
}

Rules:
- Return at most 3 suggestions. If nothing meaningful, return {"suggestions": []}.
- section_id must be one of the ids in the outline above, or null.
- severity must be exactly high, medium, or low.
- Return ONLY valid JSON. Output starts with { and ends with }.
"""


def format_suggest_structure_prompt(*, section_outline: str, open_suggestions: str) -> str:
    """Substitute placeholders in SUGGEST_STRUCTURE_PROMPT."""
    return (
        SUGGEST_STRUCTURE_PROMPT
        .replace("<<SECTION_OUTLINE>>", section_outline)
        .replace("<<OPEN_SUGGESTIONS>>", open_suggestions)
    )


def suggest_structure_prompt_sha256() -> str:
    return hashlib.sha256(SUGGEST_STRUCTURE_PROMPT.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Addressed-check prompt (journey.py). SHA-cached.
# Used to confirm whether a draft revision has addressed a suggestion.
# STRICT: only mark addressed when evidence quote verifies verbatim.
# ---------------------------------------------------------------------------

ADDRESSED_CHECK_PROMPT = """You are a research writing auditor. Determine whether a specific
suggestion has been addressed in the new draft excerpt below.

Suggestion:
<<SUGGESTION_BLOCK>>

New draft excerpt (top-3 most relevant sections):
<<DRAFT_EXCERPT>>

Rules:
- Only mark addressed=true if there is CLEAR, SPECIFIC evidence in the excerpt.
- The evidence field MUST be a verbatim quote copied exactly from the excerpt above.
- If you are uncertain, err on the side of addressed=false.
- Do NOT paraphrase or invent evidence. If no direct quote supports addressing, use addressed=false.

Return ONLY valid JSON, no markdown fences, matching exactly:
{"addressed": false, "evidence": "verbatim quote from the excerpt, or empty string if not addressed"}

JSON output:"""


def format_addressed_check_prompt(suggestion_block: str, draft_excerpt: str) -> str:
    """Substitute placeholders in ADDRESSED_CHECK_PROMPT."""
    return (
        ADDRESSED_CHECK_PROMPT
        .replace("<<SUGGESTION_BLOCK>>", suggestion_block)
        .replace("<<DRAFT_EXCERPT>>", draft_excerpt)
    )


def addressed_check_prompt_sha256() -> str:
    return hashlib.sha256(ADDRESSED_CHECK_PROMPT.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Converse prompt (converse.py). SHA-cached.
# Companion voice: candid senior research colleague answering about an artifact.
# ---------------------------------------------------------------------------

CONVERSE_PROMPT = """You are a candid senior research colleague helping the researcher understand \
their analysis artifacts. You are direct, warm, and give zero flattery. You say plainly when the \
material doesn't answer the question.

CONTEXT (the analysis artifact):
<<CONTEXT_BLOCK>>

SOURCES (retrieved paper sections numbered [S1]..[Sk]):
<<SOURCES_BLOCK>>

CONVERSATION HISTORY:
<<HISTORY_BLOCK>>

User: <<MESSAGE>>

Rules:
- Ground your response ONLY in CONTEXT, SOURCES, and HISTORY. Do NOT use outside knowledge.
- Cite [S#] inline after every claim drawn from a paper section (e.g. "This method is BM25-based [S1]").
- When quoting verbatim from a source, wrap the quote in double quotes and copy it exactly.
- If the material does not answer the question, say so plainly: \
"The provided context and sources do not contain enough information to answer this."
- When asked how to fix or improve something, respond with NUMBERED edit suggestions that \
reference specific draft section ids where applicable.
- Use prose, not JSON. Keep the response focused and concrete.

Companion:"""


def format_converse_prompt(
    *,
    context_block: str,
    sources_block: str,
    history_block: str,
    message: str,
) -> str:
    """Substitute placeholders in CONVERSE_PROMPT."""
    return (
        CONVERSE_PROMPT
        .replace("<<CONTEXT_BLOCK>>", context_block)
        .replace("<<SOURCES_BLOCK>>", sources_block)
        .replace("<<HISTORY_BLOCK>>", history_block)
        .replace("<<MESSAGE>>", message)
    )


def converse_prompt_sha256() -> str:
    return hashlib.sha256(CONVERSE_PROMPT.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Gap extraction prompt (gaps.py). SHA-cached.
# Extracts self-declared limitations/future work gaps from paper sections.
# Returns STRICT JSON {"gaps": [...]} — max 5 gaps per paper.
# ---------------------------------------------------------------------------

GAP_PROMPT = """You are extracting research gaps declared by the authors of a paper.

The text below contains the paper's Limitations, Future Work, Discussion, or Conclusion sections.

Return ONLY valid JSON, no markdown fences, matching exactly:
{
  "gaps": [
    {
      "statement": "<=1 sentence, the authors' own words distilled",
      "kind": "limitation|future_work",
      "evidence_quote": "verbatim span from the text"
    }
  ]
}

Rules:
- Up to 5 gaps total. Only gaps the AUTHORS themselves declare.
- statement is at most 1 sentence, capturing the essence in the authors' own words.
- kind is "limitation" for things the paper cannot do, "future_work" for what should be done next.
- evidence_quote MUST be copied verbatim from the text below.
- Return ONLY valid JSON. Output starts with { and ends with }.

Paper title: <<TITLE>>

Gap sections text:
<<GAP_SECTIONS_TEXT>>

JSON output:"""


def format_gap_prompt(*, title: str, gap_sections_text: str) -> str:
    """Substitute placeholders in GAP_PROMPT."""
    return (
        GAP_PROMPT
        .replace("<<TITLE>>", title)
        .replace("<<GAP_SECTIONS_TEXT>>", gap_sections_text)
    )


def gap_prompt_sha256() -> str:
    return hashlib.sha256(GAP_PROMPT.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Gap resolution prompt (gaps.py). SHA-cached.
# Assesses whether a gap is addressed by later papers or the draft.
# ---------------------------------------------------------------------------

GAP_RESOLUTION_PROMPT = """You are determining whether a research gap has been addressed by later work.

Research gap:
<<GAP_STATEMENT>>

Candidate excerpts from later papers (each tagged [paper_id]):
<<CANDIDATE_EXCERPTS>>

Return ONLY valid JSON, no markdown fences, matching exactly:
{
  "status": "addressed|partially|open",
  "resolved_by": "<paper_id or null>",
  "rationale": "1-2 sentences",
  "evidence_quote": "verbatim from the excerpts"
}

Rules:
- status "addressed" only if the gap is clearly and directly resolved.
- status "partially" if there is relevant progress but the gap is not fully resolved.
- status "open" if none of the excerpts address the gap.
- resolved_by is the paper_id of the most relevant resolving paper, or null.
- evidence_quote MUST be copied verbatim from the excerpts above. If no direct quote, use "".
- Return ONLY valid JSON. Output starts with { and ends with }.

JSON output:"""


def format_gap_resolution_prompt(*, gap_statement: str, candidate_excerpts: str) -> str:
    """Substitute placeholders in GAP_RESOLUTION_PROMPT."""
    return (
        GAP_RESOLUTION_PROMPT
        .replace("<<GAP_STATEMENT>>", gap_statement)
        .replace("<<CANDIDATE_EXCERPTS>>", candidate_excerpts)
    )


def gap_resolution_prompt_sha256() -> str:
    return hashlib.sha256(GAP_RESOLUTION_PROMPT.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Gap synthesis prompt (gaps.py). SHA-cached.
# Groups near-duplicate VERIFIED gaps into cross-corpus themes for the
# dedicated Gaps section. Honest: only groups the given gaps, never invents.
# ---------------------------------------------------------------------------

GAP_SYNTHESIS_PROMPT = """You are grouping research gaps into themes for a researcher scanning what is missing across a corpus.

Below are VERIFIED research gaps (self-declared by paper authors), one per line, tagged [gap_id] (kind, year, status): statement.

<<GAPS_BLOCK>>

Group NEAR-DUPLICATE or closely related gaps into themes. Every gap_id you use MUST be copied EXACTLY from the list above — do NOT invent gap_ids, statements, or gaps not listed.

Return ONLY valid JSON, no markdown fences, matching exactly:
{
  "themes": [
    {
      "title": "short theme name (a few words)",
      "bullet": "one-line, actionable synthesis of what is missing across the grouped gaps",
      "fws_type": "method|resources|evaluation|application|problem|other",
      "gap_ids": ["gap_id copied exactly from the list above", "..."]
    }
  ]
}

Rules:
- Group gaps that describe the SAME underlying missing piece of work, even if worded differently across papers.
- A theme needs at least 1 gap_id; do not create a theme with no members.
- fws_type is the Future-Work-Sentence taxonomy: method (a technique/algorithm is missing), resources (data/tools/benchmarks are missing), evaluation (missing evaluation/analysis), application (missing application/deployment), problem (an unsolved problem is named), other (anything else).
- bullet is one sentence, actionable, grounded ONLY in the grouped gaps' statements — do not add facts not present in them.
- Do NOT invent gaps, statements, or gap_ids. Only group what is given.
- Return ONLY valid JSON. Output starts with { and ends with }.

JSON output:"""


def format_gap_synthesis_prompt(*, gaps_block: str) -> str:
    """Substitute placeholders in GAP_SYNTHESIS_PROMPT."""
    return GAP_SYNTHESIS_PROMPT.replace("<<GAPS_BLOCK>>", gaps_block)


def gap_synthesis_prompt_sha256() -> str:
    return hashlib.sha256(GAP_SYNTHESIS_PROMPT.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Venue-fit prompt (agents/venuefit.py). SHA-cached.
# Judges whether a paper matches a target venue's scope.
# ---------------------------------------------------------------------------

VENUE_FIT_PROMPT = """You are assessing whether a paper is a good fit for a target publication venue.

Target venue: <<VENUE_NAME>>
Venue scope:
<<VENUE_SCOPE>>

Venue requirements (reporting checklists and common desk-reject triggers):
<<REQUIREMENTS_BLOCK>>

Paper abstract:
<<ABSTRACT>>

Paper contributions:
<<CONTRIBUTIONS_BLOCK>>

Return ONLY valid JSON, no markdown fences, matching exactly:
{
  "fit": "strong|moderate|weak|out_of_scope",
  "confidence": 0.0,
  "rationale": "one or two sentences grounded ONLY in the venue scope and paper above",
  "reasons": ["short bullet grounded in the scope/paper"],
  "suggested_alternatives": ["venue name, only if fit is weak or out_of_scope"]
}

Rules:
- fit must be exactly one of: strong, moderate, weak, out_of_scope.
- Base the judgement ONLY on the venue scope, requirements, and paper text above.
- Weigh the desk-reject triggers: a paper that plainly violates one is at best a weak fit.
- confidence is your certainty in the fit, 0.0-1.0.
- suggested_alternatives is [] unless fit is weak or out_of_scope.
- Return ONLY valid JSON. Output starts with { and ends with }."""


def format_venuefit_prompt(
    *, venue_name: str, venue_scope: str, requirements_block: str,
    abstract: str, contributions_block: str,
) -> str:
    """Substitute placeholders in VENUE_FIT_PROMPT."""
    return (
        VENUE_FIT_PROMPT
        .replace("<<VENUE_NAME>>", venue_name)
        .replace("<<VENUE_SCOPE>>", venue_scope)
        .replace("<<REQUIREMENTS_BLOCK>>", requirements_block)
        .replace("<<ABSTRACT>>", abstract)
        .replace("<<CONTRIBUTIONS_BLOCK>>", contributions_block)
    )


def venuefit_prompt_sha256() -> str:
    return hashlib.sha256(VENUE_FIT_PROMPT.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Readiness narrative prompt (readiness_narrative.py). SHA-cached.
# Turns the deterministic submission-readiness verdict into a reviewer's take
# and a prioritized fix plan, grounded ONLY in the blockers/warnings provided.
# ---------------------------------------------------------------------------

READINESS_NARRATIVE_PROMPT = """You are a senior meta-reviewer. Below is the deterministic
submission-readiness assessment of a paper: the verdict, the desk-reject blockers, and the
warnings, each with a recommended action.

Write for the AUTHOR:
1. "take": a 2-4 sentence reviewer's take consistent with the verdict — what this adds up to.
2. "plan": an ordered list of the fixes, most urgent first (blockers before warnings). Use only
   the items listed below. Do not invent findings, checks, or advice about anything not listed.

Assessment:
- Verdict: <<VERDICT>>
- Summary: <<SUMMARY>>
<<ITEMS_BLOCK>>

Return ONLY valid JSON, no markdown fences, matching exactly:
{
  "take": "...",
  "plan": ["...", "..."]
}

JSON output:"""


def format_readiness_narrative_prompt(readiness: dict) -> str:
    """Substitute placeholders in READINESS_NARRATIVE_PROMPT."""
    lines = []
    for kind, key in (("BLOCKER", "blockers"), ("warning", "warnings")):
        for item in readiness.get(key) or []:
            lines.append(
                f"- [{kind}][{item.get('lane', '')}] {item.get('title', '')}"
                f" -> {item.get('action', '')}"
            )
    return (
        READINESS_NARRATIVE_PROMPT
        .replace("<<VERDICT>>", str(readiness.get("verdict", "")))
        .replace("<<SUMMARY>>", str(readiness.get("summary", "")))
        .replace("<<ITEMS_BLOCK>>", "\n".join(lines))
    )


def readiness_narrative_prompt_sha256() -> str:
    return hashlib.sha256(READINESS_NARRATIVE_PROMPT.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Discover query-expansion prompt (discover.py expand_query). SHA-cached.
# Turns a rough title/topic into a small set of literature-search queries.
# ---------------------------------------------------------------------------

DISCOVER_EXPAND_PROMPT = """You are helping a researcher turn a rough topic or working title into a
small set of well-formed literature-search queries.

Rough topic/title: <<TITLE>>

Return ONLY valid JSON, no markdown fences, matching exactly:
{
  "queries": ["string", "string", "..."]
}

Rules:
- Produce at most 4 ADDITIONAL queries beyond the original title.
- Each query is a short search phrase (a keyphrase, a synonym, or an adjacent subfield) suitable
  for a literature-search API — not a full sentence, not a question.
- Do NOT repeat the original title verbatim as one of your queries.
- Do NOT invent unrelated topics; stay grounded in the rough topic/title above.
- Return ONLY valid JSON. Output starts with { and ends with }.

JSON output:"""


def format_discover_expand_prompt(title: str) -> str:
    """Substitute placeholders in DISCOVER_EXPAND_PROMPT."""
    return DISCOVER_EXPAND_PROMPT.replace("<<TITLE>>", title)


def discover_expand_prompt_sha256() -> str:
    return hashlib.sha256(DISCOVER_EXPAND_PROMPT.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Research Directions prompt (directions.py synthesize_directions). SHA-cached.
# Turns a topic + a grounding block of real papers/underexplored concepts/
# open gaps into over-generated, citation-backed candidate directions.
# Honest: every suggestion must cite a key copied EXACTLY from the block;
# inventing a key is forbidden (assembly drops any key not in the index).
# ---------------------------------------------------------------------------

DIRECTIONS_PROMPT = """You are a research ideation assistant helping a researcher find their next research direction.

Topic: <<TOPIC>>

Below is a list of items you may ground suggestions in: real papers from the researcher's library and topic search, underexplored concepts from their knowledge graph, and open research gaps. Each item is tagged with a stable key in brackets ([p:...] for a paper, [c:...] for a concept, [g:...] for a gap).

<<GROUNDING_BLOCK>>

Suggest 8 to 12 candidate research directions. Every direction MUST be grounded ONLY in the items listed above — cite them by copying their keys EXACTLY. Do NOT invent a key, a paper, a concept, or a gap not listed above.

Return ONLY valid JSON, no markdown fences, matching exactly:
{
  "directions": [
    {
      "title": "short, actionable direction title",
      "rationale": "one-line, actionable rationale grounded ONLY in the cited items",
      "direction_type": "extend_method|new_application|underexplored_concept|open_gap|cross_pollination|other",
      "grounded_in": ["key copied exactly from the list above", "..."]
    }
  ]
}

Rules:
- Over-generate: aim for 8-12 directions, more than a researcher would act on, so ranking can surface the best.
- Every grounded_in key MUST be copied EXACTLY from the list above (a [p:...]/[c:...]/[g:...] key). Inventing a key is forbidden.
- rationale is exactly one sentence, actionable, and grounded ONLY in the cited items' content — do not add facts not present in them.
- direction_type must be exactly one of: extend_method, new_application, underexplored_concept, open_gap, cross_pollination, other.
- Do NOT invent papers, concepts, gaps, or keys not given above.
- Return ONLY valid JSON. Output starts with { and ends with }.

JSON output:"""


def format_directions_prompt(*, topic: str, grounding_block: str) -> str:
    """Substitute placeholders in DIRECTIONS_PROMPT."""
    return (
        DIRECTIONS_PROMPT
        .replace("<<TOPIC>>", topic)
        .replace("<<GROUNDING_BLOCK>>", grounding_block)
    )


def directions_prompt_sha256() -> str:
    return hashlib.sha256(DIRECTIONS_PROMPT.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Draft-scaffold outline prompt (scaffold.py generate_outline). SHA-cached.
# Turns one chosen Research Direction (2b) into a research-paper section
# outline tailored to it. Honest: grounded ONLY in the direction's own
# rationale + its real grounding papers; must NOT invent papers/citations.
# ---------------------------------------------------------------------------

SCAFFOLD_OUTLINE_PROMPT = """You are a research writing advisor helping a researcher turn one chosen research direction into the start of a paper.

Direction title: <<TITLE>>
Direction type: <<DIRECTION_TYPE>>
Rationale: <<RATIONALE>>

Below are the real papers this direction is grounded in (title, year), if any:
<<GROUNDING_BLOCK>>

Produce a research-paper section outline tailored to this specific direction -- NOT a generic template. Aim for 6 to 10 top-level (level 1) sections in a sensible paper order (e.g. Introduction, Related Work, Method, Experiments/Evaluation, Discussion, Conclusion, adapted to what this direction actually needs), with optional level-2 subsections under a level-1 section where it helps (e.g. a Method section split into two sub-approaches). Every section gets a one-to-two-sentence description of what should go there, grounded in the rationale and the grounding papers above -- you may reference a grounding paper by its title, but you must NOT invent papers, citations, or results not given above.

Return ONLY valid JSON, no markdown fences, matching exactly:
{
  "sections": [
    {
      "title": "short section title",
      "level": 1,
      "description": "one or two sentences, grounded ONLY in the rationale and grounding papers above"
    }
  ]
}

Rules:
- 6 to 10 top-level (level 1) sections; a level-2 section must immediately follow the level-1 section it belongs under.
- level is exactly 1 or 2.
- description is one or two sentences and must not introduce a paper, citation, dataset, or result not given above.
- Do NOT invent papers or citations not supplied in the grounding papers above.
- Return ONLY valid JSON. Output starts with { and ends with }.

JSON output:"""


def format_scaffold_outline_prompt(
    *, title: str, rationale: str, direction_type: str, grounding_block: str
) -> str:
    """Substitute placeholders in SCAFFOLD_OUTLINE_PROMPT."""
    return (
        SCAFFOLD_OUTLINE_PROMPT
        .replace("<<TITLE>>", title)
        .replace("<<RATIONALE>>", rationale)
        .replace("<<DIRECTION_TYPE>>", direction_type)
        .replace("<<GROUNDING_BLOCK>>", grounding_block)
    )


def scaffold_outline_prompt_sha256() -> str:
    return hashlib.sha256(SCAFFOLD_OUTLINE_PROMPT.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Deep-Research Report questions prompt (deep_research.py
# generate_questions). SHA-cached. Turns a topic + a grounding block of
# real library papers/underexplored concepts into 4-max_questions distinct
# investigation sub-questions (STORM-style perspectives). Honest: grounded
# ONLY in the listed library items; must NOT invent papers or concepts.
# ---------------------------------------------------------------------------

REPORT_QUESTIONS_PROMPT = """You are a research assistant helping a researcher produce a structured literature-review report over their own paper library.

Topic: <<TOPIC>>

Below is a grounding block of real papers already in the researcher's library and underexplored concepts from their knowledge graph, if any:
<<GROUNDING_BLOCK>>

Break the topic down into 4 to <<MAX_QUESTIONS>> distinct investigation sub-questions -- different perspectives/angles on the topic (for example: definitions, methods, evidence, limitations, comparisons, applications -- adapted to what this topic actually needs), grounded in the library items listed above where relevant. Each question must be a standalone question a researcher could answer just by reading their own library -- do not reference "the papers above" or "this list" inside the question text itself.

Return ONLY valid JSON, no markdown fences, matching exactly:
{
  "questions": [
    "standalone investigation question"
  ]
}

Rules:
- 4 to <<MAX_QUESTIONS>> questions, each a distinct perspective on the topic.
- Every question must be answerable on its own, without seeing this prompt or the grounding block.
- Do NOT invent papers, concepts, or facts not given above -- ground the ANGLE of each question in the listed items, but the question itself must not assert anything as already true.
- Return ONLY valid JSON. Output starts with { and ends with }.

JSON output:"""


def format_report_questions_prompt(*, topic: str, grounding_block: str, max_questions: int) -> str:
    """Substitute placeholders in REPORT_QUESTIONS_PROMPT."""
    return (
        REPORT_QUESTIONS_PROMPT
        .replace("<<TOPIC>>", topic)
        .replace("<<GROUNDING_BLOCK>>", grounding_block)
        .replace("<<MAX_QUESTIONS>>", str(max_questions))
    )


def report_questions_prompt_sha256() -> str:
    return hashlib.sha256(REPORT_QUESTIONS_PROMPT.encode("utf-8")).hexdigest()
