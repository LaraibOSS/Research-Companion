/**
 * noteRecord.js — Pure, DOM-free helper that maps a capture surface's local
 * fields (Draft opportunities, Alignment, Reader, Paper card, Ask, or a
 * freeform note) into the POST /api/notes record shape.
 *
 * Consumed by the UI tasks (Draft/Alignment/Reader/Paper/Ask "Save note"
 * affordances); the record it returns is passed straight to api.saveNote().
 *
 * Total: never throws. An unrecognized kind degrades to "freeform" and any
 * field missing from `data` becomes "" (relevance becomes "" too, not 0/NaN,
 * so an omitted relevance is distinguishable from an explicit 0).
 */

const KINDS = ['opportunity', 'alignment', 'reader', 'paper', 'ask', 'freeform'];

/**
 * @param {string} kind - one of KINDS; anything else normalizes to 'freeform'.
 * @param {object} [data] - surface-local fields (paperId, paperTitle,
 *   sectionId, sectionTitle, relation, relevance, rationale, quote,
 *   quoteSectionId, sourceExcerpt, comment). Only the fields relevant to the
 *   calling surface need to be present; everything else defaults to "".
 * @returns {{kind: string, paper_id: string, paper_title: string,
 *   draft_section_id: string, draft_section_title: string, relation: string,
 *   relevance: number|string, rationale: string, evidence_quote: string,
 *   evidence_section_id: string, source_excerpt: string, comment: string}}
 */
export function buildNoteRecord(kind, data) {
  const k = KINDS.includes(kind) ? kind : 'freeform';
  const d = (data && typeof data === 'object') ? data : {};
  const s = (v) => (typeof v === 'string' ? v : (v == null ? '' : String(v)));

  return {
    kind: k,
    paper_id: s(d.paperId),
    paper_title: s(d.paperTitle),
    draft_section_id: s(d.sectionId),
    draft_section_title: s(d.sectionTitle),
    relation: s(d.relation),
    relevance: d.relevance == null ? '' : d.relevance,
    rationale: s(d.rationale),
    evidence_quote: s(d.quote),
    evidence_section_id: s(d.quoteSectionId),
    source_excerpt: s(d.sourceExcerpt),
    comment: s(d.comment),
  };
}
