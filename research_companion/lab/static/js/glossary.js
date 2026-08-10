/**
 * js/glossary.js — Domain glossary for tooltip text.
 * Pure module: no DOM, no imports. Node-testable.
 *
 * tip(term) returns a ` data-tip="..."` HTML attribute string suitable for
 * insertion into a template literal.  Returns '' for unknown terms.
 * Attribute value is HTML-attribute-escaped (double-quotes -> &quot;).
 */

export const GLOSSARY = {
  verified:    'Claim directly quoted from an ingested paper section.',
  unverified:  'Claim not found verbatim in sources — treat as LLM inference.',
  band:        'Strength band grouping papers by evidence quality: strong / moderate / weak / failed.',
  strength:    'Evidence strength: how well a paper\'s claims are supported by verifiable quotes.',
  stance:      'How a paper relates to the draft — strengthens, challenges, or offers an alternative.',
  strengthens: 'Paper provides supporting evidence for the draft claim.',
  challenges:  'Paper contradicts or questions the draft claim.',
  alternative: 'Paper proposes a different approach without directly contradicting.',
  grounded:    'Answer backed by retrieved source sections — every sentence traces to a quote.',
  cited:       'Source retrieved AND the exact quote was verified in the original document.',
  gap:         'An open research question identified across the timeline that no paper has closed.',
  severity:    'Priority of an improvement suggestion: critical > high > medium > low.',
  hybrid:      'Search combining BM25 keyword matching with semantic (vector) similarity.',
  bm25:        'BM25: keyword-frequency ranking algorithm used in the hybrid retrieval stage.',
  rcs_relevance: 'How relevant this cited passage is to the question — an AI judgment, not independently verified.',
  rcs_stance:    'Whether this cited passage supports, contradicts, or is neutral toward the answer — an AI judgment, not independently verified.',
};

/**
 * Escape a string for safe use as an HTML attribute value.
 * Escapes ampersands and double-quotes (the attribute delimiter).
 * @param {string} s
 * @returns {string}
 */
function _attrEscape(s) {
  return s.replace(/&/g, '&amp;').replace(/"/g, '&quot;');
}

/**
 * Return a ` data-tip="..."` attribute string for the given term.
 * Returns '' if the term is not in the glossary.
 * @param {string} term
 * @returns {string}
 */
export function tip(term) {
  const text = GLOSSARY[term];
  if (!text) return '';
  return ` data-tip="${_attrEscape(text)}"`;
}
