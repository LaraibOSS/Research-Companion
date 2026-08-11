/**
 * briefHelpers.js — pure model + edit ops for the Brainstorm Brief panel.
 *
 * Escaping contract (like directionsHelpers.js): briefModel() returns
 * PRE-ESCAPED fields the caller interpolates directly. The edit ops operate on
 * the RAW brief object ({brief_id, topic, sections:[{title, bullets:[{text,
 * citations:[{paper_id,title,year}]}]}]}), return a NEW brief (never mutate),
 * and are total (out-of-range indices return the brief unchanged). Node-testable.
 */
import { escapeHtml } from './format.js';

function _clone(brief) {
  try { return JSON.parse(JSON.stringify(brief || {})); } catch { return {}; }
}
function _sections(brief) {
  return (brief && Array.isArray(brief.sections)) ? brief.sections : [];
}

/** Short, human citation label from a citation record: title (year). */
function _citationLabel(c) {
  const title = String((c && c.title) || '').trim() || (c && c.paper_id) || 'source';
  const short = title.length > 28 ? title.slice(0, 27) + '…' : title;
  const year = (c && c.year != null && c.year !== '') ? ` ${c.year}` : '';
  return `${short}${year}`;
}

/**
 * Build the pre-escaped display model for the brief panel.
 * @param {object} brief — raw brief
 * @returns {{briefId, topic, isEmpty, sectionCount, bulletCount,
 *   sections: Array}} — all string fields escaped. Never throws.
 */
export function briefModel(brief) {
  const secs = _sections(brief);
  let bulletCount = 0;
  const sections = secs.map((s, si) => {
    const bullets = (s && Array.isArray(s.bullets) ? s.bullets : []).map((b, bi) => {
      bulletCount += 1;
      const citations = (b && Array.isArray(b.citations) ? b.citations : []).map(c => ({
        label: escapeHtml(_citationLabel(c)),
        paperId: escapeHtml((c && c.paper_id) || ''),
      }));
      return {
        index: bi,
        text: escapeHtml(String((b && b.text) || '')),
        rawText: String((b && b.text) || ''),   // for seeding an inline editor
        citations,
        userAdded: citations.length === 0,       // your own point, not an AI-cited claim
      };
    });
    return { index: si, title: escapeHtml(String((s && s.title) || '')), bullets };
  });
  return {
    briefId: escapeHtml(String((brief && brief.brief_id) || '')),
    topic: escapeHtml(String((brief && brief.topic) || '')),
    isEmpty: sections.length === 0,
    sectionCount: sections.length,
    bulletCount,
    sections,
  };
}

// --- pure edit ops (return a new brief) -----------------------------------

export function setBulletText(brief, si, bi, text) {
  const next = _clone(brief);
  const secs = _sections(next);
  const b = secs[si] && Array.isArray(secs[si].bullets) ? secs[si].bullets[bi] : null;
  if (!b) return brief;
  b.text = String(text == null ? '' : text);
  return next;
}

export function deleteBullet(brief, si, bi) {
  const next = _clone(brief);
  const secs = _sections(next);
  if (!secs[si] || !Array.isArray(secs[si].bullets)) return brief;
  if (bi < 0 || bi >= secs[si].bullets.length) return brief;
  secs[si].bullets.splice(bi, 1);
  return next;
}

export function addBullet(brief, si, text = '') {
  const next = _clone(brief);
  const secs = _sections(next);
  if (!secs[si]) return brief;
  if (!Array.isArray(secs[si].bullets)) secs[si].bullets = [];
  secs[si].bullets.push({ text: String(text == null ? '' : text), citations: [] });
  return next;
}

export function deleteSection(brief, si) {
  const next = _clone(brief);
  const secs = _sections(next);
  if (si < 0 || si >= secs.length) return brief;
  secs.splice(si, 1);
  return next;
}

/** Move a bullet within its section by delta (-1 up / +1 down). */
export function moveBullet(brief, si, bi, delta) {
  const next = _clone(brief);
  const secs = _sections(next);
  const bullets = secs[si] && Array.isArray(secs[si].bullets) ? secs[si].bullets : null;
  if (!bullets) return brief;
  const j = bi + delta;
  if (bi < 0 || bi >= bullets.length || j < 0 || j >= bullets.length) return brief;
  const tmp = bullets[bi]; bullets[bi] = bullets[j]; bullets[j] = tmp;
  return next;
}
