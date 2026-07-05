/**
 * graph/graphview.js — Live-growth graph engine for the Research Lab.
 *
 * PURE functions (node-testable, no vis/document at import time):
 *   seedPosition(newNode, edgesInDelta, getPositions, rng)
 *   makeFlasher(updateFn, schedule)
 *   makeFilterPredicate(sectionId, hiddenKinds, draftPaperId)
 *   dedup(newItems, existsSet)
 *   shouldReducePerf(nodeCount)
 *
 * Browser functions (require injected vis/container):
 *   initGraph(container, visLib)      — call once at boot from main.js
 *   loadSnapshot(graphJson)
 *   applyDelta(delta)
 *   setSectionFilter(sectionId)
 *   setKindFilter(hiddenKinds)
 *   setSearchFilter(query)
 *   onNodeClick(cb)
 *   onEdgeClick(cb)
 *   getNetwork()
 */

// ---------------------------------------------------------------------------
// Pure helpers — exported for node --test
// ---------------------------------------------------------------------------

/**
 * Seed a position for a new node by finding an anchored neighbor.
 *
 * @param {object} newNode              — the new node being added (has .id)
 * @param {Array}  edgesInDelta         — edges from the current delta [{source,target,...}]
 * @param {(id:string) => {x,y}|null} getPositions — lookup existing node positions
 * @param {() => number} [rng]          — injectable RNG, default Math.random
 * @returns {{x: number, y: number}|null}
 */
export function seedPosition(newNode, edgesInDelta, getPositions, rng = Math.random) {
  const nodeId = newNode.id;
  // Find any edge in this delta that involves the new node
  for (const edge of edgesInDelta) {
    const src = edge.source ?? edge.from;
    const tgt = edge.target ?? edge.to;
    const neighborId = src === nodeId ? tgt : (tgt === nodeId ? src : null);
    if (neighborId === null) continue;
    const pos = getPositions(neighborId);
    if (pos && typeof pos.x === 'number' && typeof pos.y === 'number') {
      return {
        x: pos.x + (rng() * 120 - 60),
        y: pos.y + (rng() * 120 - 60),
      };
    }
  }
  return null;
}

/**
 * Create a flasher that batches revert updates.
 * One setTimeout per flush, not per node.
 *
 * @param {(items: object[]) => void} updateFn  — DataSet.update
 * @param {(fn: Function, ms: number) => any} schedule — injectable setTimeout
 * @returns {{ flash: (items: object[], duration?: number) => void }}
 */
export function makeFlasher(updateFn, schedule = setTimeout) {
  return {
    flash(items, duration = 800) {
      if (!items || items.length === 0) return;
      const ids = items.map(n => n.id);
      schedule(() => {
        // Revert: remove flash styling for these nodes
        updateFn(ids.map(id => ({ id, borderWidth: 1, size: undefined, color: undefined })));
      }, duration);
    },
  };
}

/**
 * Compose a single DataView filter predicate from section + kind + draft-paper rules.
 *
 * @param {string|null}   sectionId    — null means "show all"
 * @param {Set<string>}   hiddenKinds  — set of kind strings to hide
 * @param {string|null}   draftPaperId — always visible when sectionId is active
 * @returns {(node: object) => boolean}
 */
export function makeFilterPredicate(sectionId, hiddenKinds, draftPaperId) {
  return function filterNode(node) {
    // Kind filter: always applied
    if (hiddenKinds && hiddenKinds.size > 0 && hiddenKinds.has(node.kind)) {
      return false;
    }
    // Section filter
    if (sectionId) {
      // Draft paper always visible in section mode
      if (draftPaperId && node.id === draftPaperId) return true;
      // Show node only if it belongs to the section
      const sections = node.sections;
      if (!Array.isArray(sections) || !sections.includes(sectionId)) {
        return false;
      }
    }
    return true;
  };
}

/**
 * Dedup: filter out items whose ids already exist in the existsSet.
 *
 * @param {object[]}   items      — array with .id
 * @param {Set<string>} existsSet  — set of already-known ids
 * @returns {object[]}
 */
export function dedup(items, existsSet) {
  return items.filter(item => !existsSet.has(item.id));
}

/**
 * Scale guard: decide whether to reduce performance options.
 *
 * @param {number} nodeCount
 * @returns {boolean}
 */
export function shouldReducePerf(nodeCount) {
  return nodeCount > 1200;
}

// ---------------------------------------------------------------------------
// Module state (browser-only, guarded by _network !== null check)
// ---------------------------------------------------------------------------

let _vis = null;          // the vis library (injected)
let _network = null;      // vis.Network instance
let _nodesDS = null;      // vis.DataSet — nodes
let _edgesDS = null;      // vis.DataSet — edges
let _nodesView = null;    // vis.DataView — filtered view
let _edgesView = null;    // vis.DataView — filtered view (may be null)
let _flasher = null;
let _flashDuration = 800;

// Filter state
let _sectionId = null;
let _hiddenKinds = new Set();
let _draftPaperId = null;
let _searchQuery = '';

// Callbacks
let _onNodeClick = null;
let _onEdgeClick = null;

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

function _rebuildViews() {
  if (!_vis || !_nodesDS || !_edgesDS) return;

  const predicate = makeFilterPredicate(_sectionId, _hiddenKinds, _draftPaperId);

  // Build node filter that also considers search
  const filterFn = (node) => {
    if (!predicate(node)) return false;
    if (_searchQuery) {
      const label = (node.label || '').toLowerCase();
      return label.includes(_searchQuery.toLowerCase());
    }
    return true;
  };

  if (_nodesView) {
    _nodesView.setFilter(filterFn);
  } else {
    _nodesView = new _vis.DataView(_nodesDS, { filter: filterFn });
  }

  // Edges: vis-network DataView on nodes hides edges automatically when endpoints
  // are hidden, but we still set up a DataView on edges for safety
  if (!_edgesView) {
    _edgesView = new _vis.DataView(_edgesDS);
  }

  if (_network) {
    _network.setData({ nodes: _nodesView, edges: _edgesView });
  }
}

function _applyScaleGuard() {
  if (!_network || !_nodesDS) return;
  const count = _nodesDS.length;
  if (shouldReducePerf(count)) {
    _network.setOptions({ edges: { smooth: false } });
    _flashDuration = 200;
  } else {
    _flashDuration = 800;
  }
}

// ---------------------------------------------------------------------------
// Public browser API
// ---------------------------------------------------------------------------

/**
 * Initialize the vis.Network on the persistent #graph-canvas container.
 * Call ONCE at boot from main.js.
 *
 * @param {HTMLElement} container
 * @param {object} visLib  — the global `vis` object
 */
export function initGraph(container, visLib) {
  if (_network) return; // idempotent

  _vis = visLib;

  _nodesDS = new _vis.DataSet([]);
  _edgesDS = new _vis.DataSet([]);

  // Build initial DataViews
  _nodesView = new _vis.DataView(_nodesDS, { filter: () => true });
  _edgesView = new _vis.DataView(_edgesDS);

  const options = {
    physics: {
      stabilization: false,
      barnesHut: {
        gravitationalConstant: -3000,
        springLength: 120,
      },
    },
    interaction: {
      hover: true,
    },
  };

  _network = new _vis.Network(container, { nodes: _nodesView, edges: _edgesView }, options);

  // Flasher
  _flasher = makeFlasher(
    (items) => _nodesDS.update(items),
    setTimeout
  );

  // Node click
  _network.on('click', (params) => {
    if (params.nodes.length > 0) {
      const nodeId = params.nodes[0];
      const node = _nodesDS.get(nodeId);
      if (_onNodeClick) _onNodeClick(node);
    } else if (params.edges.length > 0) {
      const edgeId = params.edges[0];
      const edge = _edgesDS.get(edgeId);
      if (_onEdgeClick) _onEdgeClick(edge);
    }
  });
}

/**
 * Reset the graph from a full snapshot (GET /api/graph).
 *
 * @param {object} graphJson — {nodes, edges}
 * @param {string|null} [draftPaperId]
 */
export function loadSnapshot(graphJson, draftPaperId = null) {
  if (!_nodesDS || !_edgesDS) return;
  _draftPaperId = draftPaperId;

  const { nodeToVis, edgeToVis } = _getMapping();
  const nodes = (graphJson.nodes || []).map(n => {
    const v = nodeToVis(n);
    v.sections = n.sections || [];
    return v;
  });
  const edges = (graphJson.edges || []).map(e => edgeToVis(e));

  _nodesDS.clear();
  _edgesDS.clear();
  _nodesDS.add(nodes);
  _edgesDS.add(edges);

  _rebuildViews();
  _applyScaleGuard();
}

/**
 * Apply a graph_delta incrementally.
 *
 * @param {object} delta — {nodes_added, edges_added, paper_id, seq}
 * @param {string|null} [draftPaperId]
 */
export function applyDelta(delta, draftPaperId = null) {
  if (!_nodesDS || !_edgesDS) return;
  if (draftPaperId !== null) _draftPaperId = draftPaperId;

  const { nodeToVis, edgeToVis } = _getMapping();

  const rawNodes = delta.nodes_added || [];
  const rawEdges = delta.edges_added || [];

  // Get current positions from network
  const getPositions = (id) => {
    if (!_network) return null;
    const positions = _network.getPositions([id]);
    return positions[id] || null;
  };

  // Dedup
  const existingNodeIds = new Set(_nodesDS.getIds());
  const existingEdgeIds = new Set(_edgesDS.getIds());

  const newNodes = dedup(rawNodes, existingNodeIds);
  // Edges use "from|to" as logical dedup key but vis uses generated id — check label+from+to
  const existingEdgeKeys = new Set(
    _edgesDS.get().map(e => `${e.from}|${e.to}|${e.label || ''}`)
  );
  const newEdges = rawEdges.filter(e => {
    const src = e.source ?? e.from;
    const tgt = e.target ?? e.to;
    return !existingEdgeKeys.has(`${src}|${tgt}|${e.relation || ''}`);
  });

  if (newNodes.length === 0 && newEdges.length === 0) return;

  // Seed positions and build vis nodes with flash styling
  const visNodes = newNodes.map(n => {
    const v = nodeToVis(n);
    v.sections = n.sections || [];
    // Flash styling
    v.borderWidth = 3;
    v.color = {
      border: '#58a6ff',
      background: v.color,
      highlight: { border: '#58a6ff', background: v.color },
      hover: { border: '#58a6ff', background: v.color },
    };
    v.size = (v.size || 15) * 1.4;

    // Seed position
    const pos = seedPosition(n, rawEdges, getPositions);
    if (pos) {
      v.x = pos.x;
      v.y = pos.y;
      v.physics = true; // allow physics to continue from seeded position
    }

    return v;
  });

  const visEdges = newEdges.map(e => {
    const edge = {
      from: e.source ?? e.from,
      to: e.target ?? e.to,
      label: e.relation || '',
      title: e.relation || '',
      width: 1,
      arrows: 'to',
    };
    return edge;
  });

  // Add to DataSets
  if (visNodes.length) _nodesDS.add(visNodes);
  if (visEdges.length) _edgesDS.add(visEdges);

  // Schedule a SINGLE batched revert per flush
  if (visNodes.length && _flasher) {
    _flasher.flash(visNodes, _flashDuration);
  }

  _applyScaleGuard();
}

/**
 * Set (or clear) the section filter.
 * @param {string|null} sectionId
 */
export function setSectionFilter(sectionId) {
  _sectionId = sectionId || null;
  _rebuildViews();
}

/**
 * Update the set of hidden kinds and rebuild the filter.
 * @param {Set<string>} hiddenKinds
 */
export function setKindFilter(hiddenKinds) {
  _hiddenKinds = hiddenKinds instanceof Set ? hiddenKinds : new Set(hiddenKinds);
  _rebuildViews();
}

/**
 * Set search query for node label dimming.
 * Matching nodes are shown at full opacity; others are hidden in the DataView.
 * @param {string} query
 */
export function setSearchFilter(query) {
  _searchQuery = (query || '').trim();
  _rebuildViews();
}

/**
 * Register a node click callback.
 * @param {(node: object) => void} cb
 */
export function onNodeClick(cb) {
  _onNodeClick = cb;
}

/**
 * Register an edge click callback.
 * @param {(edge: object) => void} cb
 */
export function onEdgeClick(cb) {
  _onEdgeClick = cb;
}

/**
 * Get the underlying vis.Network instance (for advanced ops).
 * @returns {object|null}
 */
export function getNetwork() {
  return _network;
}

/**
 * Get the nodes DataSet.
 * @returns {object|null}
 */
export function getNodesDataSet() {
  return _nodesDS;
}

/**
 * Get the edges DataSet.
 * @returns {object|null}
 */
export function getEdgesDataSet() {
  return _edgesDS;
}

/**
 * Set the draft paper id (used by section filter to always show it).
 * @param {string|null} id
 */
export function setDraftPaperId(id) {
  _draftPaperId = id;
  _rebuildViews();
}

// ---------------------------------------------------------------------------
// Private: lazy import of mapping (avoids circular-dep issues in tests)
// ---------------------------------------------------------------------------

let _mappingCache = null;

function _getMapping() {
  if (_mappingCache) return _mappingCache;
  // Dynamic import would be async; for the browser build we access via the
  // module namespace. mapping.js has no side-effects so we can import synchronously
  // from a sibling path. Since this code only runs in the browser, we reference
  // the module that was already imported by graph.js (the view) which re-exports
  // these. We store them via setMapping().
  throw new Error('graphview: mapping not injected — call setMapping() first');
}

/**
 * Inject mapping functions (nodeToVis, edgeToVis) to break circular deps.
 * Called from views/graph.js before any graph operation.
 *
 * @param {{ nodeToVis: Function, edgeToVis: Function }} mapping
 */
export function setMapping(mapping) {
  _mappingCache = mapping;
}
