/**
 * graph/draftLayout.js — Pure, DOM-free helpers for the draft-centric graph
 * mode (W4-F3): deterministic ego layout with the draft at the origin,
 * sections on an inner ring and papers on an outer ring split into fixed-order
 * relation sectors.
 *
 * Exports (all node-testable):
 *   buildDraftModel(alignmentResp, sections, papersArr)
 *   layoutDraftEgo(model, opts)
 *   makeDraftPredicate(visibleIds, expandedEntityIds)
 *   collectPaperEntities(edgesArr, paperId)
 */

import { dominantRelation } from '../libraryHelpers.js';

// Fixed sector order on the outer ring.
export const SECTOR_ORDER = ['strengthens', 'challenges', 'alternative', 'unaligned'];

// Strength band sort rank (strong first, unscored last).
const STRENGTH_RANK = { strong: 0, moderate: 1, weak: 2 };

function _papersToArray(papersMapOrArray) {
  if (papersMapOrArray instanceof Map) return [...papersMapOrArray.values()];
  if (Array.isArray(papersMapOrArray)) return papersMapOrArray;
  return [];
}

/**
 * Build the draft-mode model from the alignment response, the section list
 * and the store's papers.
 *
 * - relation = dominant stance across the paper's section alignments
 *   (dominantRelation from libraryHelpers — single source of truth).
 * - Papers with no alignments and status 'done' are included as 'unaligned';
 *   papers with no alignments and any other status are excluded.
 * - The draft itself is excluded from papers.
 *
 * @param {object|null} alignmentResp — GET /api/draft/alignment response:
 *   {draft_id, sections:[{section_id, title, alignments:[{paper_id, relation, relevance, ...}]}]}
 * @param {Array} sections — GET /api/sections response ([{section_id, title}])
 * @param {Map|Array} papersArr — papers from the store
 * @returns {{draftId: string|null,
 *            sections: Array<{id: string, title: string}>,
 *            papers: Array<{paperId, relation, relevance, strength,
 *                           edges: Array<{sectionId, relation, relevance}>}>}}
 */
export function buildDraftModel(alignmentResp, sections, papersArr) {
  const draftId = (alignmentResp && alignmentResp.draft_id) || null;
  const alignSections = (alignmentResp && alignmentResp.sections) || [];

  // Section list: prefer the /api/sections order, fall back to alignment sections.
  const srcSections = (sections && sections.length > 0) ? sections : alignSections;
  const secList = (srcSections || []).map(s => ({
    id: s.section_id,
    title: s.title || '',
  }));

  const papers = _papersToArray(papersArr);
  const paperById = new Map(papers.map(p => [p.paper_id, p]));

  // Collect alignment edges per paper (deterministic: alignment encounter order).
  const edgesByPaper = new Map(); // paperId -> [{sectionId, relation, relevance}]
  for (const sec of alignSections) {
    for (const al of (sec.alignments || [])) {
      if (!al || al.paper_id == null) continue;
      if (!edgesByPaper.has(al.paper_id)) edgesByPaper.set(al.paper_id, []);
      edgesByPaper.get(al.paper_id).push({
        sectionId: sec.section_id,
        relation: al.relation || null,
        relevance: typeof al.relevance === 'number' ? al.relevance : 0,
      });
    }
  }

  const modelPapers = [];
  const seen = new Set();

  const pushPaper = (paperId, edges) => {
    if (seen.has(paperId) || paperId === draftId) return;
    seen.add(paperId);

    const paper = paperById.get(paperId);
    const strength = paper && paper.strength ? (paper.strength.band || null) : null;

    let relation = 'unaligned';
    let relevance = 0;
    if (edges.length > 0) {
      const counts = { strengthens: 0, challenges: 0, alternative: 0 };
      for (const e of edges) {
        if (Object.prototype.hasOwnProperty.call(counts, e.relation)) counts[e.relation] += 1;
        if (e.relevance > relevance) relevance = e.relevance;
      }
      relation = dominantRelation(counts) || 'unaligned';
    }

    modelPapers.push({ paperId, relation, relevance, strength, edges });
  };

  // Aligned papers first (alignment encounter order)...
  for (const [paperId, edges] of edgesByPaper) pushPaper(paperId, edges);

  // ...then ingested papers with no alignments -> 'unaligned'.
  for (const p of papers) {
    if (p.paper_id == null || edgesByPaper.has(p.paper_id)) continue;
    if (p.status !== 'done') continue;
    pushPaper(p.paper_id, []);
  }

  return { draftId, sections: secList, papers: modelPapers };
}

/**
 * Deterministic total order within a sector:
 * relevance desc, then strength band (strong > moderate > weak > unscored),
 * then paperId asc.
 */
function _sectorSort(a, b) {
  if (b.relevance !== a.relevance) return b.relevance - a.relevance;
  const ra = STRENGTH_RANK[a.strength] !== undefined ? STRENGTH_RANK[a.strength] : 3;
  const rb = STRENGTH_RANK[b.strength] !== undefined ? STRENGTH_RANK[b.strength] : 3;
  if (ra !== rb) return ra - rb;
  return a.paperId < b.paperId ? -1 : (a.paperId > b.paperId ? 1 : 0);
}

/**
 * Deterministic ego layout: draft at (0,0), sections evenly spaced on the
 * inner ring, papers on the outer ring split into fixed-order relation
 * sectors with spans proportional to counts (empty sectors dropped, min span
 * enforced, gaps between sectors).
 *
 * @param {object} model — from buildDraftModel
 * @param {object} [opts]
 * @returns {{positions: Map<string, {x: number, y: number}>,
 *            sectorLabels: Array<{text, relation, x, y, midAngle, span}>}}
 */
export function layoutDraftEgo(model, opts = {}) {
  const {
    innerRadius = 180,
    outerRadius = 420,
    startAngle = -Math.PI / 2,
    minSectorRad = Math.PI / 6,
    sectorGapRad = 0.06,
  } = opts;

  const positions = new Map();
  const sectorLabels = [];

  // Draft at the origin.
  if (model && model.draftId) positions.set(model.draftId, { x: 0, y: 0 });

  // Sections evenly spaced on the inner ring, from startAngle, in given order.
  const secs = (model && model.sections) || [];
  const nSec = secs.length;
  secs.forEach((s, i) => {
    const a = startAngle + (nSec > 0 ? (2 * Math.PI * i) / nSec : 0);
    positions.set('sec:' + s.id, {
      x: innerRadius * Math.cos(a),
      y: innerRadius * Math.sin(a),
    });
  });

  // Group papers into fixed-order sectors.
  const groups = new Map(SECTOR_ORDER.map(rel => [rel, []]));
  for (const p of ((model && model.papers) || [])) {
    const rel = groups.has(p.relation) ? p.relation : 'unaligned';
    groups.get(rel).push(p);
  }

  const nonEmpty = SECTOR_ORDER.filter(rel => groups.get(rel).length > 0);
  const k = nonEmpty.length;
  if (k > 0) {
    // Full circle minus one gap per sector (the ring wraps around).
    const available = Math.max(0, 2 * Math.PI - k * sectorGapRad);
    const total = nonEmpty.reduce((s, rel) => s + groups.get(rel).length, 0);
    // Every sector gets the min span; the remainder is distributed
    // proportionally to counts (keeps proportionality AND the min guarantee).
    const extra = Math.max(0, available - k * minSectorRad);

    let angle = startAngle;
    for (const rel of nonEmpty) {
      const sorted = [...groups.get(rel)].sort(_sectorSort);
      const span = minSectorRad + extra * (sorted.length / total);
      const m = sorted.length;

      sorted.forEach((p, j) => {
        const a = angle + span * ((j + 0.5) / m);
        positions.set(p.paperId, {
          x: outerRadius * Math.cos(a),
          y: outerRadius * Math.sin(a),
        });
      });

      const midAngle = angle + span / 2;
      const labelR = outerRadius + 70;
      sectorLabels.push({
        text: rel.toUpperCase(),
        relation: rel,
        x: labelR * Math.cos(midAngle),
        y: labelR * Math.sin(midAngle),
        midAngle,
        span,
      });

      angle += span + sectorGapRad;
    }
  }

  return { positions, sectorLabels };
}

/**
 * Build the DataView override predicate for draft mode: only the draft,
 * papers and synthetic section nodes (visibleIds) are shown, plus any
 * per-paper expanded entity nodes.
 *
 * @param {Set<string>} visibleIds
 * @param {Set<string>} expandedEntityIds
 * @returns {(node: object) => boolean}
 */
export function makeDraftPredicate(visibleIds, expandedEntityIds) {
  const visible = visibleIds instanceof Set ? visibleIds : new Set(visibleIds || []);
  const expanded = expandedEntityIds instanceof Set ? expandedEntityIds : new Set(expandedEntityIds || []);
  return function draftPredicate(node) {
    return visible.has(node.id) || expanded.has(node.id);
  };
}

/**
 * Collect the entity node ids a paper "contains" (client-side entity
 * collection over the vis edges array).
 *
 * @param {Array} edgesArr — vis edges ({from, to, relation})
 * @param {string} paperId
 * @returns {string[]} entity node ids
 */
export function collectPaperEntities(edgesArr, paperId) {
  const out = [];
  for (const e of (edgesArr || [])) {
    if (!e || e.from !== paperId) continue;
    const rel = e.relation !== undefined ? e.relation : e.label;
    if (rel === 'contains') out.push(e.to);
  }
  return out;
}
