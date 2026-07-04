# Research Companion: A Team of Verifiable Agents for Pre-Submission Paper Review

**Laraib Hasan** — Independent Researcher — Lxh417bham@gmail.com

Code: https://github.com/Laraib-Hasan/Research-Companion (MIT) · Demo video: [LINK] · Zero-key demo: `python examples/demo_offline.py`

## Abstract

Lack of novelty is the most common cause of desk rejection, and fabricated or incorrect citations are a growing failure mode of LLM-assisted writing — yet the tools researchers use before submission either check formatting without scientific judgment, or offer LLM critique without verifiable grounding. We present **Research Companion**, an open-source system in which a team of specialized agents analyzes a paper end-to-end and **every verdict carries checkable evidence**. A citation agent validates each reference against live CrossRef/OpenAlex lookups and flags fabricated entries; a novelty agent extracts the paper's claimed contributions, compares them against retrieved prior art, and verifies every supporting quote against the paper's own text; a rebuttal agent drafts point-by-point reviewer responses in which any span attributed to the paper is checked verbatim and unverifiable spans are flagged rather than shipped; a deterministic confidence agent scores each claim with an explicit uncertainty band. Agents run concurrently on an asyncio DAG with failure isolation, stream to a live browser dashboard, and write JSONL audit logs. On a controlled corruption benchmark, the citation validator attains 1.0 precision and 1.0 recall (fabricated-reference recall 1.0); we release the benchmark, a novelty-vs-OpenReview evaluation harness, and a 30-second offline demo requiring no API keys.

## 1 Introduction

Manuscripts fail before reviewers ever weigh in. Content analyses of desk rejections attribute 46–52% to lack of novelty or originality [Menon et al., 2022; Dantas-Torres, 2022], and large venues desk-reject 39–78% of submissions [Dantas-Torres, 2022; Bauchner et al., 2017]. Meanwhile, a new failure mode has emerged on the author side: LLM-assisted writing introduces plausible but nonexistent references, and surveys report that hallucinated citations are the top trust concern among students using AI tools [HEPI, 2025].

The tooling landscape is split into two camps that do not meet. Commercial pre-submission checkers (Paperpal, Penelope.ai) run dozens of deterministic compliance checks but state explicitly that they do not assess novelty or scientific merit. Research prototypes assess novelty with LLMs — OpenNovelty [Ref], GraphMind [da Silva et al., 2025] — or simulate peer review — AgentReview [Jin et al., 2024] — but are single-purpose, CS-centric, and not integrated with the deterministic checks authors also need. Worse, LLM reviewers are documented to be lenient and to accept author claims without verification [Ref], which makes *unverifiable* LLM critique actively dangerous in a pre-submission tool.

Research Companion's design premise is that a pre-submission assistant is only useful if its outputs can be **checked**. Concretely:

- **C1 — An agentic review runtime.** A small asyncio orchestrator runs specialized agents as a dependency DAG with per-lane failure isolation: a failing lane degrades the report, never the run. Every event (start, finding, error) is a typed object streamed to a live dashboard and appended to a JSONL audit log.
- **C2 — Verifiability by construction.** Citation verdicts come from live CrossRef/OpenAlex lookups (fabrication, wrong-DOI, author-mismatch detection); novelty verdicts attach evidence quotes that are verified against the paper's own fulltext; rebuttal drafts flag any quoted span that cannot be found verbatim in the paper; confidence scores are deterministic (no LLM) with explicit uncertainty bands.
- **C3 — An open, tested, reproducible system.** MIT-licensed; 213 tests with all network and LLM calls behind injectable seams; a zero-key offline demo; committed, seed-deterministic evaluation artifacts; and an evaluation harness for novelty-vs-human-reviewer agreement.

Target audience: researchers and students preparing submissions (catching fabricated references and anticipating novelty objections), and reviewers/educators demonstrating verification-first LLM system design.

## 2 System Overview

Research Companion builds on a local-first knowledge-graph substrate: papers ingested from arXiv/DOI/Semantic Scholar/PDF are LLM-extracted into concepts, methods, datasets, claims, results, and related work, merged into a cross-paper NetworkX graph (`GraphRAG` mentioned by five papers is one node with five `contains` edges).

**Runtime.** `research-companion review <paper>` instantiates an agent team over an in-process async bus. The orchestrator resolves the dependency DAG, runs all ready agents concurrently, and isolates failures: an exception becomes a failed lane; dependents are skipped with an explanatory error; independent lanes proceed. Typed events (`AgentStarted`, `Finding`, `AgentDone`, `AgentError`) stream over Server-Sent Events to a browser dashboard (`--serve`) and append to a per-run JSONL audit log.

**Agents** (dependencies in parentheses):

| Agent | Function |
|---|---|
| ingest | loads the paper, builds/loads the knowledge graph |
| citation (ingest) | validates every reference via live CrossRef→OpenAlex lookups |
| priorart (ingest) | retrieves related work via Semantic Scholar |
| novelty (priorart) | extracts claimed contributions; compares each against prior art; verifies evidence quotes |
| confidence (citation, novelty) | deterministic per-claim score with uncertainty band |
| benchmark (ingest, priorart) | suggests evaluation benchmarks mined from the graph + related work |
| rebuttal (ingest) | grounded point-by-point reviewer responses (separate `rebuttal` command) |
| problem, tracker | library-level: problem-statement refinement against graph gaps; new-related-work sweep |
| report | post-run builder: self-contained HTML + JSON, rendered even when lanes fail |

`--fast` runs only the LLM-free lanes; `--report DIR` writes the report; all LLM/network calls sit behind injectable seams, so the full pipeline runs offline in tests and in the bundled demo.

## 3 Verifiability by Construction

**Citations: live lookups, not format checks.** Each bibliography entry is parsed (title/DOI/arXiv-id/year) and resolved against CrossRef, falling back to OpenAlex. Verdicts are `verified`, `suspect` (title match but <60% author overlap, or DOI/arXiv conflict), or `unverified` (no plausible record — the fabricated-citation case). This is the check compliance tools do not do: their citation checks validate formatting and internal consistency, not existence.

**Novelty: every verdict cites evidence that is then checked.** The novelty agent (i) prompts an LLM to extract 2–6 claimed contributions, each with a *verbatim* evidence quote; (ii) retrieves prior art and asks for a per-claim verdict (novel / incremental / overlaps / anticipated) grounded only in the retrieved works; (iii) independently verifies each evidence quote against the paper's fulltext (exact, then whitespace/case-normalized matching). A claim whose quote cannot be found is marked `evidence_verified: false` — surfacing prompt non-compliance instead of hiding it. LLM confidence values are clamped and non-finite values rejected, keeping all outputs JSON-safe.

**Rebuttal: no quote ships unchecked.** Reviews are segmented into concerns (deterministic heuristics; an emit-edit-resume flow lets authors correct segmentation), classified (factual error / misunderstanding / valid weakness / clarification), grounded in retrieved paper passages, and drafted with the instruction to quote the paper only from those passages. Every double-quoted span in the draft is then verified against the fulltext; drafts carry a tri-state `evidence_status` (verified / no_quotes / unverified) so a reply with zero checkable quotes is not presented as "verified". Cross-reviewer duplicate concerns are grouped, and planned revisions are aggregated into a changelog.

**Confidence: deterministic, banded, inspectable.** Each claim's score is a weighted mean of three signals — evidence verification (weight 1.0), novelty-comparison confidence (0.8), citation health (0.6) — with an uncertainty band of width 0.5/√n + 0.5·σ clamped to [0.05, 0.5]. No LLM is involved; the signals are shown on each card.

**Auditability.** Every run writes an append-only JSONL event log; the report and dashboard render from the same event stream, so what the user saw is what was logged.

## 4 Interface

The CLI covers the full lifecycle (add/build/chat/discover/refcheck/review/rebuttal). `review --serve` opens a live dashboard: one lane per agent with status and latest finding, plus a scrolling findings feed (XSS-escaped; paper content is untrusted input). The final report is a single self-contained HTML file — lane cards, non-verified references with reasons, a claims table with verdicts and evidence-verification flags, confidence cards with bands, benchmark suggestions — plus a machine-readable JSON twin. A bundled `examples/demo_offline.py` reproduces the entire pipeline in ~30 seconds with zero API keys and zero network, using the same injection seams as the test suite.

## 5 Evaluation

**Citation validator (controlled corruption benchmark).** From 40 gold reference records we generate labeled corruptions (seeded, deterministic; committed to the repo): fabricated titles, shuffled DOIs, swapped author lists. Against an oracle lookup over the gold records, the validator flags corrupted references with precision 1.0, recall 1.0, F1 1.0 (59 labeled pairs; per-type recall: fabricated 1.0, wrong-DOI 1.0, author-swap 1.0). We state the framing plainly: precision is 1.0 *by construction* under the oracle lookup (clean references self-match), so recall is the diagnostic number, and the benchmark is a regression floor rather than a field-realism claim. [IF LIVE EVAL RAN: **Novelty vs. human reviewers.** On N ICLR papers with public OpenReview reviews, per-paper novelty scores from the novelty agent achieve Spearman rank agreement ρ = X with mean reviewer novelty opinions. / ELSE: **Novelty-agreement harness.** We release a ready-to-run harness that scores papers via the novelty agent and computes rank agreement against OpenReview reviewer novelty opinions; running it requires LLM API access, and we document the protocol and case-assembly steps in the repository.]

**System verification.** 213 tests (TDD throughout) with all LLM/network behind injectable seams; the full six-lane pipeline, dashboard endpoints, and both CLIs run in the suite with no network. The runtime survives adversarial conditions by design: bad LLM JSON fails one lane cleanly; a paper whose reference list contains HTML/JS is escaped in both report and dashboard.

**Case study.** Running `review` on a seeded paper whose bibliography contains one fabricated entry: the citation lane reports `1 verified / 1 unverified` and names the fabricated title with the reason "no matching record found in authoritative sources"; the novelty lane marks the paper's single claim `overlaps` with the retrieved prior work and `evidence_verified: true`; the confidence card shows 0.72 ± 0.15 with its three signals. Total wall time is dominated by the two LLM calls; the deterministic lanes complete in milliseconds.

## 6 Comparison With Existing Systems

| System | Live citation existence check | Novelty assessment | Evidence verified against paper | Rebuttal support | Multi-agent + dashboard | Open source |
|---|---|---|---|---|---|---|
| Paperpal | – (format/consistency) | – | – | – | – | – |
| Penelope.ai | – (format/consistency) | – | – | – | – | – |
| RefChecker | ✓ | – | – | – | – | ✓ |
| OpenNovelty | – | ✓ | ✓ (retrieved works) | – | – | ✓ |
| GraphMind | – | ✓ | partial | – | – | ✓ |
| AgentReview | – | (review sim) | – | – | multi-agent | ✓ |
| **Research Companion** | **✓** | **✓** | **✓ (own fulltext + prior art)** | **✓ (quote-checked)** | **✓ + live dashboard** | **✓ (MIT)** |

Compliance products state that they do not evaluate scientific merit; novelty prototypes do not validate references or draft rebuttals; to our knowledge no prior open system combines live reference validation, evidence-verified novelty assessment, and grounded rebuttal drafting behind one auditable runtime.

## 7 Conclusion

Research Companion demonstrates that an agentic pre-submission assistant can be useful *because* it is checkable: every verdict, quote, and score traces to evidence a human can inspect. The system is open, tested, and installable; the demo runs in 30 seconds without keys.

## Limitations

The novelty and rebuttal agents inherit LLM limitations; our mitigation is verification and flagging, not elimination. The citation benchmark is synthetic and oracle-based (ceiling scores expected); field precision against live CrossRef/OpenAlex is unmeasured. Reviewer-agreement evaluation [was run on a small N / requires API access and is shipped as a harness]. Retrieval relies on Semantic Scholar/CrossRef/OpenAlex coverage, which is weaker for non-English and non-indexed venues; the extraction prompts and evaluation are CS/ML-centric. The problem and tracker agents are library-level and not yet CLI-wired.

## Ethics Statement

The tool assists authors; it does not generate paper content, and its rebuttal drafts flag unverifiable claims rather than asserting them. Users must respect venue policies on AI assistance and disclose use where required. Reference validation queries public scholarly APIs with standard rate limits and a descriptive user agent. No personal data is collected; all state is local. The work aligns with the ACM Code of Ethics.

## Availability & License

MIT-licensed at https://github.com/Laraib-Hasan/Research-Companion. Install: `git clone … && pip install -e ".[demo]"`. Zero-key demo: `python examples/demo_offline.py`. Evaluation artifacts and reproduction commands: `eval/`.

## Appendix A: Audit-Log Excerpt

```json
{"event": "agent_started", "agent": "citation"}
{"event": "finding", "agent": "citation", "kind": "bad_reference",
 "summary": "[unverified] A Fabricated Paper Title",
 "data": {"status": "unverified", "reasons": ["No matching record found in authoritative sources"]}}
{"event": "finding", "agent": "novelty", "kind": "novelty_verdict",
 "summary": "[overlaps] We propose X.",
 "data": {"verdict": "overlaps", "confidence": 0.8, "evidence_verified": true}}
{"event": "agent_done", "agent": "confidence"}
```

## Appendix B: Reproduction

```bash
git clone https://github.com/Laraib-Hasan/Research-Companion && cd Research-Companion
pip install -e ".[demo]"
python -m pytest -q                      # 213 tests, no network
python examples/demo_offline.py         # full pipeline, zero keys
python -m research_companion.eval.citation_pr   # regenerates committed eval artifacts
```
