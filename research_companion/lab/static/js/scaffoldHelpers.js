/**
 * scaffoldHelpers.js — Pure, DOM-free helpers for the Brainstorm view's
 * per-direction "Draft this direction" action (POST /api/directions/draft).
 * Mirrors the shape convention of noveltyHelpers.js/directionsHelpers.js.
 *
 * Testable with node --test (tests/js/scaffoldHelpers.test.mjs).
 *
 * ESCAPING CONTRACT (identical to noveltyHelpers.js): `errorMessage` and
 * `successMessage` are returned ALREADY HTML-escaped — interpolate them
 * directly, do NOT re-escape. `openDraftRoute` is a fixed, non-user-derived
 * literal ('#/draft') returned raw — the view still escapes it when writing
 * it into an href attribute, per house style for every attribute value.
 */
import { escapeHtml } from './format.js';

const OPEN_DRAFT_ROUTE = '#/draft';

function _idleModel() {
  return {
    status: 'idle', errorMessage: null, sectionCount: null,
    replaced: false, openDraftRoute: OPEN_DRAFT_ROUTE, successMessage: null,
  };
}

/**
 * Map one per-card scaffold state (as tracked by views/brainstorm.js's
 * `_scaffoldByDirectionId` Map) to a display model for the "Draft this
 * direction" panel. Never throws; a missing/malformed state is the idle
 * button state.
 *
 * @param {{loading?:boolean, error?:(string|null),
 *   result?:({section_count?:number, replaced_draft?:boolean}|null)}} state
 * @returns {{status:('idle'|'loading'|'error'|'success'),
 *   errorMessage:(string|null), sectionCount:(number|null),
 *   replaced:boolean, openDraftRoute:string, successMessage:(string|null)}}
 */
export function scaffoldPanelModel(state) {
  const s = (state && typeof state === 'object' && !Array.isArray(state)) ? state : null;
  if (!s) return _idleModel();

  if (s.loading) {
    return { ..._idleModel(), status: 'loading' };
  }

  if (typeof s.error === 'string' && s.error) {
    return { ..._idleModel(), status: 'error', errorMessage: escapeHtml(s.error) };
  }

  const result = (s.result && typeof s.result === 'object') ? s.result : null;
  if (!result) return _idleModel();

  const sectionCount = typeof result.section_count === 'number' ? result.section_count : 0;
  const replaced = !!result.replaced_draft;
  const plural = sectionCount === 1 ? '' : 's';
  const successMessage = replaced
    ? `Replaced your previous draft — ${sectionCount} section${plural}.`
    : `Draft created with ${sectionCount} section${plural}.`;

  return {
    status: 'success',
    errorMessage: null,
    sectionCount,
    replaced,
    openDraftRoute: OPEN_DRAFT_ROUTE,
    successMessage: escapeHtml(successMessage),
  };
}
