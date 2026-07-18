/**
 * graph/mapping.js — kind→color/shape/size maps; nodeToVis, edgeToVis.
 * DOM-free; used by F2 (graph view) and the Library legend.
 *
 * Styling philosophy (v0.2.1 "premium" pass): papers are rounded label cards;
 * every entity kind is a uniform dot differentiated by a desaturated jewel-tone
 * palette and size. Edges carry no always-on text labels (relation lives in the
 * hover title and the edge-click detail panel) so dense graphs stay readable.
 */

// Desaturated jewel tones tuned for the #0d1117 canvas.
export const KIND_COLORS = {
  paper:   '#6c8cff',
  concept: '#3fb6a8',
  method:  '#d9a13d',
  dataset: '#a78bfa',
  claim:   '#7d8590',
  result:  '#e5697f',
};

// Papers are cards; all entities are dots (differentiated by color + size).
export const KIND_SHAPES = {
  paper:   'box',
  concept: 'dot',
  method:  'dot',
  dataset: 'dot',
  claim:   'dot',
  result:  'dot',
};

// Dot radius per kind (papers size via their label box).
export const KIND_SIZES = {
  concept: 14,
  method:  13,
  dataset: 13,
  claim:   9,
  result:  10,
};

const DEFAULT_COLOR = '#7d8590';
const DEFAULT_SHAPE = 'dot';
const DEFAULT_SIZE = 11;
const ENTITY_LABEL_MAX = 42;
const ENTITY_FONT = { color: '#9aa4b2', size: 10.5 };
const PAPER_FONT = { color: '#e6edf3', size: 12, face: 'arial', bold: { color: '#e6edf3' } };

function truncateLabel(s, max = ENTITY_LABEL_MAX) {
  if (!s || s.length <= max) return s;
  return s.slice(0, max - 1).trimEnd() + '…';
}

/**
 * Convert an API graph node to a vis-network node descriptor.
 *
 * @param {{ id: string, kind: string, label: string, attrs: object, strength?: object }} node
 * @returns {object}  vis-network node options
 */
export function nodeToVis(node) {
  const kind = node.kind || 'unknown';
  const color = KIND_COLORS[kind] || DEFAULT_COLOR;
  const shape = KIND_SHAPES[kind] || DEFAULT_SHAPE;
  const fullLabel = node.label || node.id;

  const vis = {
    id: node.id,
    kind,
    shape,
    title: fullLabel,
  };

  if (kind === 'paper') {
    vis.label = truncateLabel(fullLabel, 60);
    vis.font = PAPER_FONT;
    vis.margin = 8;
    // Strength band as the card border when known (string color otherwise —
    // vis derives a matching border automatically).
    const strengthColor = node.strength && node.strength.color;
    if (strengthColor) {
      vis.color = {
        background: color,
        border: strengthColor,
        highlight: { background: color, border: strengthColor },
        hover: { background: color, border: strengthColor },
      };
      vis.borderWidth = 2;
    } else {
      vis.color = color;
    }
  } else {
    vis.label = truncateLabel(fullLabel);
    vis.color = color;
    vis.size = KIND_SIZES[kind] || DEFAULT_SIZE;
    vis.font = ENTITY_FONT;
  }

  // Carry extra attrs for the info panel
  if (node.attrs && typeof node.attrs === 'object') {
    Object.assign(vis, node.attrs);
  }

  return vis;
}

/**
 * Provenance summary for a non-paper entity node: which papers it appears in.
 * Pure/DOM-free — the caller escapes `label` and each `items` string.
 *
 * @param {{ kind?: string, paper_count?: number, papers?: string[] }} node
 * @param {Map<string, { title?: string }>} [papersMap]  store.papers (id -> paper)
 * @returns {{ count: number, label: string, items: string[] }|null}
 *          null for paper/synthetic nodes or nodes lacking provenance.
 */
export function entityProvenanceLabel(node, papersMap) {
  if (!node || node.kind === 'paper') return null;
  const count = node.paper_count;
  if (typeof count !== 'number' || count < 1) return null;
  const label = `Appears in ${count} paper${count === 1 ? '' : 's'}`;
  const ids = Array.isArray(node.papers) ? node.papers : [];
  const items = ids.map((id) => {
    const p = papersMap && typeof papersMap.get === 'function' ? papersMap.get(id) : null;
    return (p && p.title) ? p.title : id;
  });
  return { count, label, items };
}

// Citation-stance colors for 'cites' edges. Values MUST match
// research_companion/viz.py's CITATION_POLARITY_COLORS exactly, so the lab
// view and the static HTML export agree on edge coloring.
export const CITATION_POLARITY_COLORS = {
  based_on: '#1f6feb',
  support: '#3fb950',
  contrast: '#f85149',
  refutation: '#a40e26',
  mention: '#8b949e',
};

/**
 * Convert an API graph edge to a vis-network edge descriptor.
 * No always-on text label; the relation stays available on hover (`title`)
 * and in the edge-click detail panel. 'cites' edges are colored by
 * `edge.polarity` (citation stance) when present; all other edges (and
 * untyped 'cites' edges) keep the neutral default color.
 *
 * @param {{ from: string, to: string, relation: string, weight?: number, polarity?: string }} edge
 * @returns {object}  vis-network edge options
 */
export function edgeToVis(edge) {
  const relation = edge.relation || '';
  const polarity = edge.polarity || '';
  const polColor = relation === 'cites' && polarity ? CITATION_POLARITY_COLORS[polarity] : null;
  return {
    from: edge.from,
    to: edge.to,
    relation,
    polarity,
    title: polarity ? `${relation}: ${polarity}` : relation,
    width: 1 + 0.3 * ((edge.weight || 1) - 1),
    color: polColor
      ? { color: polColor, highlight: polColor }
      : { color: 'rgba(110,118,129,0.35)', highlight: 'rgba(139,148,158,0.8)' },
    arrows: { to: { enabled: true, scaleFactor: 0.5 } },
    dashes: relation === 'co_mentioned' ? [4, 4] : false,
  };
}
