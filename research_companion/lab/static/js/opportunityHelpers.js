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
 *   noteRowModel(note) -> display fields for a saved note row (Notes view).
 *     Generalized (feat/notes-everywhere) beyond opportunity/alignment notes:
 *     carries `kind` and `sourceExcerpt` and tolerates a note with no
 *     paper/section/relation (e.g. an `ask` or freeform note).
 *   notesGroupModel(notes, groupBy) -> [{key, label, rows: [noteRowModel...]}]
 *     Groups saved notes for the Notes view: by paper title when
 *     groupBy === 'paper', else by section title. Ungrouped notes land in an
 *     'Unfiled' group, always sorted last.
 *
 * All three functions are total: malformed/empty/unexpected input never
 * throws, it degrades to an empty/neutral result instead.
 */

import { originLink } from './noteOriginHelpers.js';

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
 * Tolerant of notes that have no paper/section/relation at all (e.g. an
 * `ask` or freeform note captured outside the Draft opportunities flow):
 * those fields simply normalize to '' / null, same as any other missing
 * field, and the badge falls back to the muted/no-icon default.
 *
 * @param {object} note
 * @returns {{id: string, kind: string, sectionId: string, sectionTitle: string,
 *   paperId: string, paperTitle: string, relation: string,
 *   relevancePct: number, rationale: string, quote: string,
 *   quoteSectionId: string|null, sourceExcerpt: string, comment: string,
 *   status: string, createdAt: string, badgeColor: string, badgeIcon: string}}
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
      kind: safe.kind != null ? String(safe.kind) : '',
      sectionId: safe.draft_section_id != null ? String(safe.draft_section_id) : '',
      sectionTitle: safe.draft_section_title != null ? String(safe.draft_section_title) : '',
      paperId: safe.paper_id != null ? String(safe.paper_id) : '',
      paperTitle: safe.paper_title != null ? String(safe.paper_title) : '',
      relation,
      relevancePct: Math.round(relevance * 100),
      rationale: safe.rationale != null ? String(safe.rationale) : '',
      quote: safe.evidence_quote != null ? String(safe.evidence_quote) : '',
      quoteSectionId: safe.evidence_section_id != null ? String(safe.evidence_section_id) : null,
      sourceExcerpt: safe.source_excerpt != null ? String(safe.source_excerpt) : '',
      comment: safe.comment != null ? String(safe.comment) : '',
      status: safe.status != null ? String(safe.status) : 'open',
      createdAt: safe.created_at != null ? String(safe.created_at) : '',
      badgeColor: STANCE_COLORS[relation] || MUTED_COLOR,
      badgeIcon: STANCE_ICONS[relation] || '',
      origin: originLink({
        kind: safe.origin_kind, id: safe.origin_id, label: safe.origin_label,
      }),
    };
  } catch {
    return {
      id: '', kind: '', sectionId: '', sectionTitle: '', paperId: '', paperTitle: '',
      relation: '', relevancePct: 0, rationale: '', quote: '', quoteSectionId: null,
      sourceExcerpt: '', comment: '', status: 'open', createdAt: '',
      badgeColor: MUTED_COLOR, badgeIcon: '',
      origin: originLink(null),
    };
  }
}

// ---------------------------------------------------------------------------
// notesGroupModel
// ---------------------------------------------------------------------------

/**
 * Group saved notes (already-noteRowModel'd or raw records — noteRowModel is
 * applied internally) for the Notes view.
 *
 * groupBy === 'paper' groups by paperTitle (falling back to 'Unfiled' when
 * blank); any other value (including the default 'section') groups by
 * sectionTitle (same 'Unfiled' fallback). Group order otherwise follows
 * first-seen order among the input notes; the 'Unfiled' group, if present,
 * is always moved to the end regardless of when it was first seen.
 *
 * @param {Array} notes
 * @param {string} groupBy - 'paper' | 'section' (or anything else, treated as 'section')
 * @returns {Array<{key: string, label: string, rows: Array<ReturnType<typeof noteRowModel>>}>}
 */
export function notesGroupModel(notes, groupBy) {
  try {
    if (!Array.isArray(notes) || notes.length === 0) return [];

    const groups = new Map();
    for (const raw of notes) {
      const row = noteRowModel(raw);
      const key = groupBy === 'paper'
        ? (row.paperTitle || 'Unfiled')
        : (row.sectionTitle || 'Unfiled');
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(row);
    }

    const keys = [...groups.keys()];
    const unfiledIdx = keys.indexOf('Unfiled');
    if (unfiledIdx !== -1) {
      keys.splice(unfiledIdx, 1);
      keys.push('Unfiled');
    }

    return keys.map((key) => ({ key, label: key, rows: groups.get(key) }));
  } catch {
    return [];
  }
}
