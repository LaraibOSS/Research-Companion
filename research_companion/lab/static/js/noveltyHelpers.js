/**
 * noveltyHelpers.js — Pure, DOM-free helpers for the Brainstorm view's
 * per-direction "Check novelty" action (POST /api/novelty). Mirrors the
 * shape convention of directionsHelpers.js.
 *
 * Testable with node --test (tests/js/noveltyHelpers.test.mjs).
 *
 * ESCAPING CONTRACT (identical to directionsHelpers.js): `rationale`,
 * `verdictBadge.label`, every prior work's `label`, and `error` are returned
 * ALREADY HTML-escaped — interpolate them directly, do NOT re-escape (that
 * would double-escape). Each prior work's raw `url` is NOT escaped — the
 * caller must escapeHtml it before writing into a DOM attribute (e.g. href).
 */
import { escapeHtml } from './format.js';

const _VERDICT_BADGES = {
  novel: { slug: 'positive', label: 'Novel' },
  incremental: { slug: 'caution', label: 'Incremental' },
  overlaps: { slug: 'caution', label: 'Overlaps' },
  anticipated: { slug: 'negative', label: 'Anticipated' },
};

function _verdictBadge(verdict) {
  const entry = _VERDICT_BADGES[verdict];
  if (!entry) return { slug: 'none', label: escapeHtml('No verdict yet') };
  return { slug: entry.slug, label: escapeHtml(entry.label) };
}

function _clampConfidence(value) {
  const n = (typeof value === 'number' && Number.isFinite(value)) ? value : 0;
  return Math.max(0, Math.min(1, n));
}

/**
 * Map one raw POST /api/novelty `prior_works[]` item to a display model.
 * ESCAPING: `label` is pre-escaped. `url` is raw.
 */
function _priorWorkModel(raw) {
  const p = (raw && typeof raw === 'object') ? raw : {};
  const title = (typeof p.title === 'string' && p.title) ? p.title : 'Untitled';
  const year = typeof p.year === 'number' ? p.year : null;
  const label = year != null ? `${title} (${year})` : title;
  return {
    label: escapeHtml(label),
    url: typeof p.url === 'string' ? p.url : '',
    year,
  };
}

/**
 * Map one raw POST /api/novelty response to a display model for the
 * Brainstorm view's per-direction "Check novelty" panel. Never throws;
 * every field defaults safely for a partial, malformed, or missing input.
 *
 * @param {object} raw — {verdict, confidence, rationale, closest_prior,
 *   prior_works, query, error?}
 * @returns {{verdictBadge:{slug:string,label:string}, confidencePct:number,
 *   rationale:string, priorWorks:Array, error:(string|null), hasResult:boolean}}
 */
export function noveltyResultModel(raw) {
  const r = (raw && typeof raw === 'object') ? raw : null;
  if (!r) {
    return {
      verdictBadge: _verdictBadge(null),
      confidencePct: 0,
      rationale: '',
      priorWorks: [],
      error: null,
      hasResult: false,
    };
  }

  const rationale = typeof r.rationale === 'string' ? r.rationale : '';
  const priorWorks = Array.isArray(r.prior_works) ? r.prior_works.map(_priorWorkModel) : [];
  const error = (typeof r.error === 'string' && r.error) ? escapeHtml(r.error) : null;

  return {
    verdictBadge: _verdictBadge(r.verdict),
    confidencePct: Math.round(_clampConfidence(r.confidence) * 100),
    rationale: escapeHtml(rationale),
    priorWorks,
    error,
    hasResult: true,
  };
}
