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
 * Convert an API graph edge to a vis-network edge descriptor.
 * No always-on text label; the relation stays available on hover (`title`)
 * and in the edge-click detail panel.
 *
 * @param {{ from: string, to: string, relation: string, weight?: number }} edge
 * @returns {object}  vis-network edge options
 */
export function edgeToVis(edge) {
  const relation = edge.relation || '';
  return {
    from: edge.from,
    to: edge.to,
    relation,
    title: relation,
    width: 1 + 0.3 * ((edge.weight || 1) - 1),
    color: { color: 'rgba(110,118,129,0.35)', highlight: 'rgba(139,148,158,0.8)' },
    arrows: { to: { enabled: true, scaleFactor: 0.5 } },
    dashes: relation === 'co_mentioned' ? [4, 4] : false,
  };
}
