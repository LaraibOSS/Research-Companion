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
  };
}
