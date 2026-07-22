/**
 * opportunityHelpers.js — Pure, DOM-free helpers for the Draft view's
 * "uncited papers that could help here" block and the Notes view row model.
 *
 * Consumes GET /api/draft/opportunities' shape:
 *   { draft_id, sections: [{ section_id, section_title,
 *       suggestions: [{ paper_id, title, relation, relevance, rationale,
 *                        evidence: [{ quote, section_id }], strength_band }] }] }
 *
 * Exports:
 *   opportunityModel(sections) -> [{sectionId, sectionTitle, count,
 *     suggestions: [{paperId, title, relation, relevance, rationale,
 *                    quote, quoteSectionId, strengthBand}]}]
 *   noteRowModel(note) -> display fields for a saved note row (Notes view, Task 4)
 *
 * Both functions are total: malformed/empty/unexpected input never throws,
 * it degrades to an empty/neutral result instead.
 */

// Stance palette — mirrors views/draft.js's local STANCE_COLORS/STANCE_ICONS
// (format.js has no STANCE_COLORS export; this is the canonical relation->color
// mapping shared by the Draft opportunities block and the Notes row model).
const STANCE_ICONS = {
  strengthens: '▲', // ▲
  challenges:  '⚡', // ⚡
  alternative: '◆', // ◆
};

const STANCE_COLORS = {
  strengthens: '#3fb950',
  challenges:  '#f85149',
  alternative: '#58a6ff',
};

const MUTED_COLOR = '#8b949e';

// ---------------------------------------------------------------------------
// opportunityModel
// ---------------------------------------------------------------------------

/**
 * Normalize GET /api/draft/opportunities' `sections` array into a flat
 * display model for the Draft view's per-section opportunities block.
 *
 * @param {Array} sections
 * @returns {Array<{sectionId: string, sectionTitle: string, count: number,
 *   suggestions: Array<{paperId: string, title: string, relation: string,
 *     relevance: number, rationale: string, quote: string,
 *     quoteSectionId: string|null, strengthBand: string|null}>}>}
 */
export function opportunityModel(sections) {
  try {
    if (!Array.isArray(sections)) return [];

    const out = [];
    for (const sec of sections) {
      if (!sec || typeof sec !== 'object') continue;

      const rawSuggestions = Array.isArray(sec.suggestions) ? sec.suggestions : [];
      const suggestions = rawSuggestions.map(_normalizeSuggestion);

      out.push({
        sectionId: sec.section_id != null ? String(sec.section_id) : '',
        sectionTitle: sec.section_title != null
          ? String(sec.section_title)
          : (sec.section_id != null ? String(sec.section_id) : ''),
        count: suggestions.length,
        suggestions,
      });
    }
    return out;
  } catch {
    return [];
  }
}

function _normalizeSuggestion(s) {
  const safe = (s && typeof s === 'object') ? s : {};
  const evidence = Array.isArray(safe.evidence) ? safe.evidence : [];
  const first = (evidence.length > 0 && evidence[0] && typeof evidence[0] === 'object')
    ? evidence[0]
    : null;

  return {
    paperId: safe.paper_id != null ? String(safe.paper_id) : '',
    title: safe.title != null ? String(safe.title) : '',
    relation: safe.relation != null ? String(safe.relation) : '',
    relevance: typeof safe.relevance === 'number' && !Number.isNaN(safe.relevance)
      ? safe.relevance
      : 0,
    rationale: safe.rationale != null ? String(safe.rationale) : '',
    quote: (first && first.quote != null) ? String(first.quote) : '',
    quoteSectionId: (first && first.section_id != null) ? String(first.section_id) : null,
    strengthBand: safe.strength_band != null ? String(safe.strength_band) : null,
  };
}

// ---------------------------------------------------------------------------
// noteRowModel
// ---------------------------------------------------------------------------

/**
 * Map a saved note record (research_companion.notes_store shape) to display
 * fields for a Notes view row: relation -> badge color/icon, relevance -> a
 * rounded percent, plus comment/status passed through unchanged.
 *
 * @param {object} note
 * @returns {{id: string, sectionId: string, sectionTitle: string,
 *   paperId: string, paperTitle: string, relation: string,
 *   relevancePct: number, rationale: string, quote: string,
 *   quoteSectionId: string|null, comment: string, status: string,
 *   createdAt: string, badgeColor: string, badgeIcon: string}}
 */
export function noteRowModel(note) {
  try {
    const safe = (note && typeof note === 'object') ? note : {};
    const relation = safe.relation != null ? String(safe.relation) : '';
    const relevance = typeof safe.relevance === 'number' && !Number.isNaN(safe.relevance)
      ? safe.relevance
      : 0;

    return {
      id: safe.id != null ? String(safe.id) : '',
      sectionId: safe.draft_section_id != null ? String(safe.draft_section_id) : '',
      sectionTitle: safe.draft_section_title != null ? String(safe.draft_section_title) : '',
      paperId: safe.paper_id != null ? String(safe.paper_id) : '',
      paperTitle: safe.paper_title != null ? String(safe.paper_title) : '',
      relation,
      relevancePct: Math.round(relevance * 100),
      rationale: safe.rationale != null ? String(safe.rationale) : '',
      quote: safe.evidence_quote != null ? String(safe.evidence_quote) : '',
      quoteSectionId: safe.evidence_section_id != null ? String(safe.evidence_section_id) : null,
      comment: safe.comment != null ? String(safe.comment) : '',
      status: safe.status != null ? String(safe.status) : 'open',
      createdAt: safe.created_at != null ? String(safe.created_at) : '',
      badgeColor: STANCE_COLORS[relation] || MUTED_COLOR,
      badgeIcon: STANCE_ICONS[relation] || '',
    };
  } catch {
    return {
      id: '', sectionId: '', sectionTitle: '', paperId: '', paperTitle: '',
      relation: '', relevancePct: 0, rationale: '', quote: '', quoteSectionId: null,
      comment: '', status: 'open', createdAt: '', badgeColor: MUTED_COLOR, badgeIcon: '',
    };
  }
}
