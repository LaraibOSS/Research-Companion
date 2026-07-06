/**
 * draftLayout.test.mjs — Tests for W4-F3 pure draft-mode layout helpers:
 *   buildDraftModel, layoutDraftEgo, makeDraftPredicate, collectPaperEntities
 *   (js/graph/draftLayout.js)
 *
 * Run from repo root:
 *   node --test tests/js/draftLayout.test.mjs
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot  = path.resolve(__dirname, '..', '..');

const { buildDraftModel, layoutDraftEgo, makeDraftPredicate, collectPaperEntities } = await import(
  pathToFileURL(path.join(
    repoRoot, 'research_companion', 'lab', 'static', 'js', 'graph', 'draftLayout.js',
  )).href
);

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const ALIGNMENT = {
  draft_id: 'draft1',
  sections: [
    {
      section_id: 'sA',
      title: 'Intro',
      alignments: [
        { paper_id: 'p1', relation: 'strengthens', relevance: 0.9, score: 0.9, verdict: 'ok' },
        { paper_id: 'p2', relation: 'challenges',  relevance: 0.7, score: 0.7, verdict: 'ok' },
      ],
    },
    {
      section_id: 'sB',
      title: 'Methods',
      alignments: [
        { paper_id: 'p1', relation: 'strengthens', relevance: 0.5, score: 0.5, verdict: 'ok' },
        { paper_id: 'p1', relation: 'challenges',  relevance: 0.4, score: 0.4, verdict: 'ok' },
      ],
    },
  ],
};

const SECTIONS = [
  { section_id: 'sA', title: 'Intro' },
  { section_id: 'sB', title: 'Methods' },
];

const PAPERS = [
  { paper_id: 'draft1', title: 'My Draft',  status: 'done',       strength: null },
  { paper_id: 'p1',     title: 'Alpha',     status: 'done',       strength: { band: 'strong', score: 0.9 } },
  { paper_id: 'p2',     title: 'Beta',      status: 'done',       strength: { band: 'weak', score: 0.2 } },
  { paper_id: 'p3',     title: 'Gamma',     status: 'done',       strength: null },   // no alignments -> unaligned
  { paper_id: 'p4',     title: 'Delta',     status: 'processing', strength: null },   // not done, no alignments -> excluded
];

function makeModel() {
  return buildDraftModel(ALIGNMENT, SECTIONS, PAPERS);
}

// ---------------------------------------------------------------------------
// buildDraftModel
// ---------------------------------------------------------------------------

test('buildDraftModel: carries draftId and sections in given order', () => {
  const m = makeModel();
  assert.equal(m.draftId, 'draft1');
  assert.deepEqual(m.sections, [{ id: 'sA', title: 'Intro' }, { id: 'sB', title: 'Methods' }]);
});

test('buildDraftModel: dominant relation across section alignments', () => {
  const m = makeModel();
  const p1 = m.papers.find(p => p.paperId === 'p1');
  // p1: strengthens x2, challenges x1 -> strengthens
  assert.equal(p1.relation, 'strengthens');
});

test('buildDraftModel: collects one edge per alignment with relation + relevance', () => {
  const m = makeModel();
  const p1 = m.papers.find(p => p.paperId === 'p1');
  assert.equal(p1.edges.length, 3);
  assert.deepEqual(p1.edges[0], { sectionId: 'sA', relation: 'strengthens', relevance: 0.9 });
});

test('buildDraftModel: paper relevance is max across its alignments', () => {
  const m = makeModel();
  const p1 = m.papers.find(p => p.paperId === 'p1');
  assert.equal(p1.relevance, 0.9);
});

test('buildDraftModel: strength band taken from papers array', () => {
  const m = makeModel();
  assert.equal(m.papers.find(p => p.paperId === 'p1').strength, 'strong');
  assert.equal(m.papers.find(p => p.paperId === 'p3').strength, null);
});

test('buildDraftModel: done paper with no alignments is classified unaligned', () => {
  const m = makeModel();
  const p3 = m.papers.find(p => p.paperId === 'p3');
  assert.ok(p3, 'p3 must be included');
  assert.equal(p3.relation, 'unaligned');
  assert.deepEqual(p3.edges, []);
});

test('buildDraftModel: non-done paper with no alignments is excluded', () => {
  const m = makeModel();
  assert.equal(m.papers.find(p => p.paperId === 'p4'), undefined);
});

test('buildDraftModel: the draft itself is excluded from papers', () => {
  const m = makeModel();
  assert.equal(m.papers.find(p => p.paperId === 'draft1'), undefined);
});

test('buildDraftModel: accepts papers as a Map too', () => {
  const map = new Map(PAPERS.map(p => [p.paper_id, p]));
  const m = buildDraftModel(ALIGNMENT, SECTIONS, map);
  assert.ok(m.papers.find(p => p.paperId === 'p1'));
});

test('buildDraftModel: empty/missing inputs produce an empty model', () => {
  const m = buildDraftModel(null, [], []);
  assert.equal(m.draftId, null);
  assert.deepEqual(m.sections, []);
  assert.deepEqual(m.papers, []);
});

// ---------------------------------------------------------------------------
// layoutDraftEgo — determinism + geometry
// ---------------------------------------------------------------------------

test('layoutDraftEgo: two calls on the same model are identical', () => {
  const m = makeModel();
  const a = layoutDraftEgo(m);
  const b = layoutDraftEgo(m);
  assert.deepEqual([...a.positions.entries()], [...b.positions.entries()]);
  assert.deepEqual(a.sectorLabels, b.sectorLabels);
});

test('layoutDraftEgo: draft node sits at the origin', () => {
  const { positions } = layoutDraftEgo(makeModel());
  assert.deepEqual(positions.get('draft1'), { x: 0, y: 0 });
});

test('layoutDraftEgo: every section gets a sec:-namespaced node on the inner ring', () => {
  const { positions } = layoutDraftEgo(makeModel(), { innerRadius: 100 });
  const secIds = ['sec:sA', 'sec:sB'];
  for (const id of secIds) {
    const pos = positions.get(id);
    assert.ok(pos, `${id} must have a position`);
    const r = Math.hypot(pos.x, pos.y);
    assert.ok(Math.abs(r - 100) < 1e-6, `${id} must sit on innerRadius (got ${r})`);
  }
});

test('layoutDraftEgo: sections are evenly spaced from startAngle', () => {
  const model = {
    draftId: 'd', papers: [],
    sections: [{ id: 's1', title: '' }, { id: 's2', title: '' }, { id: 's3', title: '' }, { id: 's4', title: '' }],
  };
  const { positions } = layoutDraftEgo(model, { innerRadius: 100, startAngle: -Math.PI / 2 });
  const angles = ['s1', 's2', 's3', 's4'].map(id => {
    const p = positions.get('sec:' + id);
    return Math.atan2(p.y, p.x);
  });
  // First section at startAngle
  assert.ok(Math.abs(angles[0] - (-Math.PI / 2)) < 1e-6);
  // Consecutive angular gaps all equal 2π/4 (mod 2π)
  for (let i = 1; i < 4; i++) {
    let gap = angles[i] - angles[i - 1];
    while (gap < 0) gap += 2 * Math.PI;
    assert.ok(Math.abs(gap - Math.PI / 2) < 1e-6, `gap ${i} must be π/2 (got ${gap})`);
  }
});

test('layoutDraftEgo: sector labels appear in the fixed relation order, empty sectors dropped', () => {
  // Papers: challenges + unaligned only — strengthens/alternative sectors must be absent.
  const model = {
    draftId: 'd',
    sections: [{ id: 's1', title: '' }],
    papers: [
      { paperId: 'c1', relation: 'challenges', relevance: 0.5, strength: null, edges: [] },
      { paperId: 'u1', relation: 'unaligned',  relevance: 0,   strength: null, edges: [] },
    ],
  };
  const { sectorLabels } = layoutDraftEgo(model);
  assert.deepEqual(sectorLabels.map(l => l.relation), ['challenges', 'unaligned']);
});

test('layoutDraftEgo: sector spans are proportional to paper counts', () => {
  const model = {
    draftId: 'd',
    sections: [],
    papers: [
      { paperId: 's1', relation: 'strengthens', relevance: 0.9, strength: null, edges: [] },
      { paperId: 's2', relation: 'strengthens', relevance: 0.8, strength: null, edges: [] },
      { paperId: 's3', relation: 'strengthens', relevance: 0.7, strength: null, edges: [] },
      { paperId: 'c1', relation: 'challenges',  relevance: 0.5, strength: null, edges: [] },
    ],
  };
  const { sectorLabels } = layoutDraftEgo(model);
  const strengthens = sectorLabels.find(l => l.relation === 'strengthens');
  const challenges  = sectorLabels.find(l => l.relation === 'challenges');
  assert.ok(strengthens.span > challenges.span,
    'sector with more papers must span a larger angle');
});

test('layoutDraftEgo: min sector span is enforced', () => {
  // 19 strengthens vs 1 challenges — challenges would get < min proportionally.
  const papers = [];
  for (let i = 0; i < 19; i++) {
    papers.push({ paperId: `s${String(i).padStart(2, '0')}`, relation: 'strengthens', relevance: 0.5, strength: null, edges: [] });
  }
  papers.push({ paperId: 'c1', relation: 'challenges', relevance: 0.5, strength: null, edges: [] });
  const minSectorRad = Math.PI / 6;
  const { sectorLabels } = layoutDraftEgo({ draftId: 'd', sections: [], papers }, { minSectorRad });
  for (const lbl of sectorLabels) {
    assert.ok(lbl.span >= minSectorRad - 1e-9, `${lbl.relation} span must be >= min`);
  }
});

test('layoutDraftEgo: gaps between sectors — spans + gaps fill the full circle', () => {
  const model = {
    draftId: 'd', sections: [],
    papers: [
      { paperId: 'a', relation: 'strengthens', relevance: 0.5, strength: null, edges: [] },
      { paperId: 'b', relation: 'challenges',  relevance: 0.5, strength: null, edges: [] },
      { paperId: 'c', relation: 'unaligned',   relevance: 0,   strength: null, edges: [] },
    ],
  };
  const sectorGapRad = 0.06;
  const { sectorLabels } = layoutDraftEgo(model, { sectorGapRad });
  const total = sectorLabels.reduce((s, l) => s + l.span, 0) + sectorLabels.length * sectorGapRad;
  assert.ok(Math.abs(total - 2 * Math.PI) < 1e-6, `spans + gaps must equal 2π (got ${total})`);
});

test('layoutDraftEgo: papers on the outer ring at outerRadius', () => {
  const { positions } = layoutDraftEgo(makeModel(), { outerRadius: 300 });
  for (const pid of ['p1', 'p2', 'p3']) {
    const p = positions.get(pid);
    assert.ok(p, `${pid} must be positioned`);
    assert.ok(Math.abs(Math.hypot(p.x, p.y) - 300) < 1e-6, `${pid} must sit at outerRadius`);
  }
});

test('layoutDraftEgo: sector label sits at mid-angle on outerRadius + 70', () => {
  const model = {
    draftId: 'd', sections: [],
    papers: [{ paperId: 'a', relation: 'strengthens', relevance: 0.5, strength: null, edges: [] }],
  };
  const { sectorLabels } = layoutDraftEgo(model, { outerRadius: 400 });
  const lbl = sectorLabels[0];
  const r = Math.hypot(lbl.x, lbl.y);
  assert.ok(Math.abs(r - 470) < 1e-6, `label radius must be outerRadius+70 (got ${r})`);
  assert.equal(typeof lbl.text, 'string');
});

test('layoutDraftEgo: in-sector ordering is relevance desc, tie by paperId', () => {
  const model = {
    draftId: 'd', sections: [],
    papers: [
      { paperId: 'pB', relation: 'strengthens', relevance: 0.5, strength: null, edges: [] },
      { paperId: 'pA', relation: 'strengthens', relevance: 0.5, strength: null, edges: [] },
      { paperId: 'pC', relation: 'strengthens', relevance: 0.9, strength: null, edges: [] },
    ],
  };
  const outerRadius = 400;
  const { positions, sectorLabels } = layoutDraftEgo(model, { outerRadius });
  const lbl = sectorLabels[0];
  const sectorStart = lbl.midAngle - lbl.span / 2;
  // Expected order: pC (0.9), then pA before pB (tie on 0.5 -> id asc)
  const expectedOrder = ['pC', 'pA', 'pB'];
  expectedOrder.forEach((pid, j) => {
    const a = sectorStart + lbl.span * ((j + 0.5) / 3);
    const expected = { x: outerRadius * Math.cos(a), y: outerRadius * Math.sin(a) };
    const got = positions.get(pid);
    assert.ok(Math.abs(got.x - expected.x) < 1e-6 && Math.abs(got.y - expected.y) < 1e-6,
      `${pid} must be at slot ${j}`);
  });
});

test('layoutDraftEgo: strength band breaks relevance ties before paperId', () => {
  const model = {
    draftId: 'd', sections: [],
    papers: [
      { paperId: 'pA', relation: 'strengthens', relevance: 0.5, strength: 'weak',   edges: [] },
      { paperId: 'pB', relation: 'strengthens', relevance: 0.5, strength: 'strong', edges: [] },
    ],
  };
  const outerRadius = 400;
  const { positions, sectorLabels } = layoutDraftEgo(model, { outerRadius });
  const lbl = sectorLabels[0];
  const sectorStart = lbl.midAngle - lbl.span / 2;
  // pB (strong) must occupy slot 0 despite larger paperId
  const a0 = sectorStart + lbl.span * (0.5 / 2);
  const expected = { x: outerRadius * Math.cos(a0), y: outerRadius * Math.sin(a0) };
  const got = positions.get('pB');
  assert.ok(Math.abs(got.x - expected.x) < 1e-6 && Math.abs(got.y - expected.y) < 1e-6,
    'strong-band paper must come first on a relevance tie');
});

// ---------------------------------------------------------------------------
// makeDraftPredicate
// ---------------------------------------------------------------------------

test('makeDraftPredicate: shows visible ids, hides everything else', () => {
  const pred = makeDraftPredicate(new Set(['draft1', 'p1', 'sec:sA']), new Set());
  assert.equal(pred({ id: 'draft1' }), true);
  assert.equal(pred({ id: 'p1' }), true);
  assert.equal(pred({ id: 'sec:sA' }), true);
  assert.equal(pred({ id: 'entity-x' }), false);
});

test('makeDraftPredicate: expanded entity ids become visible', () => {
  const pred = makeDraftPredicate(new Set(['p1']), new Set(['entity-x']));
  assert.equal(pred({ id: 'entity-x' }), true);
  assert.equal(pred({ id: 'entity-y' }), false);
});

test('makeDraftPredicate: tolerates missing sets', () => {
  const pred = makeDraftPredicate(undefined, undefined);
  assert.equal(pred({ id: 'anything' }), false);
});

// ---------------------------------------------------------------------------
// collectPaperEntities
// ---------------------------------------------------------------------------

test('collectPaperEntities: returns entity targets of contains edges from the paper', () => {
  const edges = [
    { from: 'p1', to: 'e1', relation: 'contains' },
    { from: 'p1', to: 'e2', relation: 'contains' },
    { from: 'p1', to: 'p2', relation: 'cites' },
    { from: 'p2', to: 'e3', relation: 'contains' },
  ];
  assert.deepEqual(collectPaperEntities(edges, 'p1'), ['e1', 'e2']);
});

test('collectPaperEntities: empty edge list or no matches -> empty array', () => {
  assert.deepEqual(collectPaperEntities([], 'p1'), []);
  assert.deepEqual(collectPaperEntities([{ from: 'x', to: 'y', relation: 'contains' }], 'p1'), []);
});
