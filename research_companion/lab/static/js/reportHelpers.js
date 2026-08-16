/**
 * reportHelpers.js — Pure, DOM-free display-model helpers for the
 * Deep-Research Report view (GET /api/report `sections[]` shape).
 * Mirrors the shape convention of gapHelpers.js/directionsHelpers.js.
 *
 * Testable with node --test (tests/js/reportHelpers.test.mjs).
 *
 * ESCAPING CONTRACT (identical to directionsHelpers.js): `question`,
 * `answer`, `errorMessage`, each unverified quote, each citation's
 * `label`, and (2e-2) each citation's `rcs.rationale` are returned
 * ALREADY HTML-escaped — interpolate them directly, do NOT re-escape.
 * Each citation's raw `paperId`/`sectionId` are NOT escaped — the caller
 * must escapeHtml them before writing into a DOM attribute. `rcs.stanceSlug`/
 * `rcs.stanceIcon` are fixed internal vocabulary (never derived from raw
 * server text) and are also safe to interpolate directly.
 */
import { escapeHtml, stanceIcon } from './format.js';

// RCS stance vocab (supports/contradicts/neutral, Report Evidence Scoring
// / RCS, 2e-2) -> the existing strengthens/challenges/alternative icon
// vocab (format.js's stanceIcon() -- the same one draft.js's alignment
// cards use for evidence stance).
const _RCS_STANCE_TO_RELATION = {
  supports: 'strengthens',
  contradicts: 'challenges',
  neutral: 'alternative',
};

/**
 * Map one citation's raw `rcs` field ({relevance, stance, rationale} |
 * undefined) to a badge display model, or null when there is nothing to
 * badge. RCS is an ADDITIVE, purely optional field -- absent/malformed
 * input means no badge, never a thrown error. Every value defaults
 * safely: an out-of-vocab stance normalizes to 'neutral', a non-numeric
 * relevance defaults to 0, relevance is clamped to [0,1] before the
 * percent conversion.
 */
function _rcsModel(raw) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;

  const stanceSlug = (raw.stance === 'supports' || raw.stance === 'contradicts' || raw.stance === 'neutral')
    ? raw.stance : 'neutral';
  const relation = _RCS_STANCE_TO_RELATION[stanceSlug];

  let relevance = (typeof raw.relevance === 'number' && Number.isFinite(raw.relevance)) ? raw.relevance : 0;
  relevance = Math.max(0, Math.min(1, relevance));

  const rationale = (typeof raw.rationale === 'string' && raw.rationale) ? raw.rationale : '';

  return {
    relevancePct: Math.round(relevance * 100),
    stanceSlug,
    stanceIcon: stanceIcon(relation),
    rationale: escapeHtml(rationale),
    tipRelevance: 'rcs_relevance',
    tipStance: 'rcs_stance',
  };
}

function _citationChipModel(raw) {
  const c = (raw && typeof raw === 'object') ? raw : {};
  const title = (typeof c.paper_title === 'string' && c.paper_title) ? c.paper_title : 'Untitled';
  return {
    label: escapeHtml(title),
    paperId: c.paper_id || '',
    sectionId: c.section_id || '',
    rcs: _rcsModel(c.rcs),
  };
}

/**
 * Map one raw GET /api/report `sections[]` item to a display model for the
 * Report view. Never throws; every field defaults safely for a partial or
 * malformed item.
 *
 * @param {object} rawSection — {question, answer, citations,
 *   unverified_quotes, error?}
 * @returns {{question:string, answer:string, hasError:boolean,
 *   errorMessage:(string|null), citations:Array<{label,paperId,sectionId}>,
 *   unverifiedQuotes:string[]}}
 */
/**
 * Map one section's raw `coverage` field ({pct, cited, relevant_available}
 * | undefined) -- or the report-level `coverage` field, same shape plus
 * `median_pct` -- to a numeric display model, or null when there is
 * nothing to show. Coverage / Saturation (2e-3) is an ADDITIVE, purely
 * optional, LLM-FREE field: absent or malformed input means no coverage
 * bar, never a thrown error. Every field is numeric (no HTML escaping
 * needed) and clamped defensively: pct to an integer in [0,100];
 * cited/relevantAvailable to non-negative integers (a negative or
 * non-numeric value degrades to 0, never a fabricated count).
 */
function _coverageModel(raw) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;

  const clampCount = (v) => (typeof v === 'number' && Number.isFinite(v) && v >= 0) ? Math.round(v) : 0;
  const pct = (typeof raw.pct === 'number' && Number.isFinite(raw.pct))
    ? Math.max(0, Math.min(100, Math.round(raw.pct))) : 0;

  return {
    pct,
    cited: clampCount(raw.cited),
    relevantAvailable: clampCount(raw.relevant_available),
    tip: 'coverage',
  };
}

export function reportSectionModel(rawSection) {
  const s = (rawSection && typeof rawSection === 'object' && !Array.isArray(rawSection)) ? rawSection : {};

  const question = (typeof s.question === 'string' && s.question) ? s.question : 'Untitled question';
  const answer = typeof s.answer === 'string' ? s.answer : '';
  const hasError = typeof s.error === 'string' && s.error.length > 0;
  const citations = Array.isArray(s.citations) ? s.citations.map(_citationChipModel) : [];
  const unverifiedQuotes = Array.isArray(s.unverified_quotes)
    ? s.unverified_quotes.filter(q => typeof q === 'string' && q).map(q => escapeHtml(q))
    : [];

  return {
    question: escapeHtml(question),
    answer: escapeHtml(answer),
    hasError,
    errorMessage: hasError ? escapeHtml(s.error) : null,
    citations,
    unverifiedQuotes,
    coverage: _coverageModel(s.coverage),
  };
}

/**
 * Map the top-level GET /api/report `coverage` field to the same numeric
 * display model _coverageModel produces for a section -- the report-level
 * saturation summary the view renders near the header -- plus `medianPct`
 * (the report-level roll-up's robust headline number; sections don't have
 * one). Null when the report has no `coverage` field (older client, or a
 * coverage computation that failed and was skipped -- see lab_api.py's
 * try/except around coverage.score_report).
 *
 * @param {object} rawReport -- the full GET /api/report payload
 */
export function reportCoverageModel(rawReport) {
  const r = (rawReport && typeof rawReport === 'object') ? rawReport : {};
  const base = _coverageModel(r.coverage);
  if (!base) return null;
  const raw = r.coverage;
  const medianPct = (raw && typeof raw.median_pct === 'number' && Number.isFinite(raw.median_pct))
    ? Math.max(0, Math.min(100, Math.round(raw.median_pct))) : base.pct;
  return { ...base, medianPct };
}


/**
 * Map the raw GET /api/report `plan` field ({topic, questions, status} |
 * null) to a safe display model for the Editable Research Plan (2e-4), or
 * null when there is no plan. Never throws. The returned `questions` are
 * ALREADY HTML-escaped (for read-only display, e.g. a "Plan: N questions"
 * summary line) -- the LIVE editable textarea state in views/report.js
 * uses the RAW `plan.questions` array directly (a textarea .value never
 * needs escaping), never this model's escaped copy.
 *
 * @param {object|null} rawPlan -- the report's raw `plan` field
 * @returns {{status:('draft'|'answered'), questions:string[]}|null}
 */
export function reportPlanModel(rawPlan) {
  if (!rawPlan || typeof rawPlan !== 'object' || Array.isArray(rawPlan)) return null;
  const status = (rawPlan.status === 'draft' || rawPlan.status === 'answered') ? rawPlan.status : null;
  if (!status) return null;
  const questions = Array.isArray(rawPlan.questions)
    ? rawPlan.questions.filter(q => typeof q === 'string' && q.trim().length > 0).map(q => escapeHtml(q))
    : [];
  return { status, questions };
}

// ---------------------------------------------------------------------------
// Page copy (empty state, cost expectation, plan status).
//
// These return PLAIN, UNESCAPED text — unlike the display models above, which
// pre-escape. Nothing here interpolates server text; the only variable parts
// are integers we format ourselves. The caller escapes at the interpolation
// site, so the two conventions never have to be told apart at a glance.
// ---------------------------------------------------------------------------

/** Below this, a report is technically fine but will read thin. */
export const REPORT_MIN_USEFUL_PAPERS = 10;

/**
 * What to say when there is no report yet. The distinction that matters is
 * "you have nothing to review" vs "you have little to review" — the first is a
 * missing prerequisite the user must act on, the second is a caveat about
 * quality. Conflating them sends people to a Generate button that cannot help.
 *
 * @param {{paperCount?: number}} opts
 * @returns {{headline: string, detail: string, tip: string, blocked: boolean}}
 *   `blocked` is true when generating cannot produce anything useful at all.
 */
export function reportEmptyState({ paperCount = 0 } = {}) {
  const n = Number.isFinite(paperCount) && paperCount > 0 ? Math.floor(paperCount) : 0;

  if (n === 0) {
    return {
      headline: 'Your library is empty, so there is nothing to review yet.',
      detail: 'A report is written from the papers you have added — never from the '
        + 'open web. Add a few papers first, then name a topic here.',
      tip: 'Use Discover to find papers on a topic, or Add paper if you already have one.',
      blocked: true,
    };
  }

  const thin = n < REPORT_MIN_USEFUL_PAPERS;
  return {
    headline: 'Name a topic and we will write a cited review of your library.',
    detail: thin
      ? `You have ${n} paper${n === 1 ? '' : 's'}. Reports work best with `
        + `${REPORT_MIN_USEFUL_PAPERS} or more on the topic — with fewer, expect thin `
        + 'coverage rather than a wrong answer.'
      : `You have ${n} papers. Only the ones relevant to your topic will be used.`,
    tip: 'Generate a plan first so you can edit the questions before the expensive '
      + 'answering pass runs.',
    blocked: false,
  };
}

/**
 * What a run will cost, in the only unit the user is billed in: model calls.
 *
 * Generating from scratch is ONE call to plan the questions plus one per
 * answer. With a plan already on screen the question count is known, so the
 * estimate becomes exact rather than a range.
 *
 * @param {{questionCount?: number|null}} opts
 * @returns {string} plain text; '' is never returned (there is always a cost).
 */
export function reportCostLine({ questionCount = null } = {}) {
  const n = Number.isFinite(questionCount) && questionCount > 0
    ? Math.floor(questionCount) : null;
  if (n === null) {
    return 'Generating uses one model call to plan the questions, then one per '
      + 'answer — usually 5 to 9 calls in total. Editing a plan is free.';
  }
  return `Answering this plan uses ${n} model call${n === 1 ? '' : 's'}, one per `
    + 'question. Editing the plan is free.';
}

/**
 * The plan's status, written so the free action and the costed one are
 * distinguishable. "draft" is not a quality judgement — it means not yet run.
 *
 * @param {{status: string, questions: string[]}|null} planModel
 * @returns {string} '' when there is no plan to describe.
 */
export function reportPlanStatus(planModel) {
  if (!planModel || !Array.isArray(planModel.questions)) return '';
  const n = planModel.questions.length;
  const q = `${n} question${n === 1 ? '' : 's'}`;
  if (planModel.status === 'answered') {
    return `Plan: ${q}, answered. Edit and re-run to change the report.`;
  }
  return `Plan: ${q}, not yet run. Edit them below, then run — changing the plan `
    + 'is free; answering is not.';
}
