/**
 * graph/mapping.js — kind→color/shape maps from viz.py; nodeToVis, edgeToVis.
 * DOM-free; used by F2 (graph view) and the Library legend.
 */

// Colors exactly as defined in research_companion/viz.py _KIND_COLORS
export const KIND_COLORS = {
  paper:   '#2b7cff',
  concept: '#3ec46d',
  method:  '#ff8a3d',
  dataset: '#9b59ff',
  claim:   '#9aa0a6',
  result:  '#e74c3c',
};

// Shapes exactly as defined in research_companion/viz.py _KIND_SHAPES
export const KIND_SHAPES = {
  paper:   'box',
  concept: 'dot',
  method:  'triangle',
  dataset: 'diamond',
  claim:   'ellipse',
  result:  'star',
};

const DEFAULT_COLOR = '#8b949e';
const DEFAULT_SHAPE = 'dot';

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

  const vis = {
    id: node.id,
    label: node.label || node.id,
    kind,
    color,
    shape,
    title: node.label || node.id,
  };

  // Carry extra attrs for the info panel
  if (node.attrs && typeof node.attrs === 'object') {
    Object.assign(vis, node.attrs);
  }

  return vis;
}

/**
 * Convert an API graph edge to a vis-network edge descriptor.
 *
 * @param {{ from: string, to: string, relation: string, weight?: number }} edge
 * @returns {object}  vis-network edge options
 */
export function edgeToVis(edge) {
  return {
    from: edge.from,
    to: edge.to,
    label: edge.relation || '',
    title: edge.relation || '',
    width: 1 + 0.3 * ((edge.weight || 1) - 1),
    arrows: 'to',
  };
}
