/**
 * reportHelpers.js — Pure, DOM-free display-model helpers for the
 * Deep-Research Report view (GET /api/report `sections[]` shape).
 * Mirrors the shape convention of gapHelpers.js/directionsHelpers.js.
 *
 * Testable with node --test (tests/js/reportHelpers.test.mjs).
 *
 * ESCAPING CONTRACT (identical to directionsHelpers.js): `question`,
 * `answer`, `errorMessage`, each unverified quote, and each citation's
 * `label` are returned ALREADY HTML-escaped — interpolate them directly,
 * do NOT re-escape. Each citation's raw `paperId`/`sectionId` are NOT
 * escaped — the caller must escapeHtml them before writing into a DOM
 * attribute.
 */
import { escapeHtml } from './format.js';

function _citationChipModel(raw) {
  const c = (raw && typeof raw === 'object') ? raw : {};
  const title = (typeof c.paper_title === 'string' && c.paper_title) ? c.paper_title : 'Untitled';
  return {
    label: escapeHtml(title),
    paperId: c.paper_id || '',
    sectionId: c.section_id || '',
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
