"""Render the cross-paper graph as a self-contained interactive HTML page.

Uses vis-network (loaded from CDN) — battle-tested KG viz library, smaller bundle than
D3, supports clustering, search, drag, zoom out of the box. Single HTML file output:
no build step, no npm, no server. Open in a browser.

Color scheme:
    paper    — blue
    concept  — green
    method   — orange
    dataset  — purple
    claim    — gray
    result   — red
"""
from __future__ import annotations

import json
import webbrowser
from pathlib import Path

import networkx as nx

from research_companion.graph import graph_stats, load_graph
from research_companion.store import graph_html_path

# Desaturated jewel tones tuned for the dark canvas; papers are label cards,
# every entity kind is a dot (differentiated by color) — kept in sync with
# research_companion/lab/static/js/graph/mapping.js.
_KIND_COLORS = {
    "paper":   "#6c8cff",
    "concept": "#3fb6a8",
    "method":  "#d9a13d",
    "dataset": "#a78bfa",
    "claim":   "#7d8590",
    "result":  "#e5697f",
}
_KIND_SHAPES = {
    "paper":   "box",
    "concept": "dot",
    "method":  "dot",
    "dataset": "dot",
    "claim":   "dot",
    "result":  "dot",
}

# Citation-polarity edge colors for `cites` edges — kept in sync with the JS
# map in research_companion/lab/static/js/graph/mapping.js.
CITATION_POLARITY_COLORS = {
    "based_on": "#1f6feb",    # blue
    "support": "#3fb950",     # green
    "contrast": "#f85149",    # red
    "refutation": "#a40e26",  # dark red
    "mention": "#8b949e",     # gray
}


HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>research-companion — knowledge graph</title>
  <script src="https://unpkg.com/vis-network@9.1.9/standalone/umd/vis-network.min.js"></script>
  <style>
    html, body { margin: 0; padding: 0; height: 100%; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0e0f12; color: #e6e6e6; }
    #app { display: grid; grid-template-columns: 280px 1fr; height: 100vh; }
    #sidebar { background: #15171c; padding: 16px; border-right: 1px solid #2a2d34; overflow-y: auto; }
    #sidebar h1 { margin: 0 0 6px 0; font-size: 18px; }
    #sidebar p.tag { color: #9aa0a6; font-size: 12px; margin: 0 0 16px 0; }
    .stat { display: flex; justify-content: space-between; padding: 4px 0; border-bottom: 1px solid #1f2229; font-size: 13px; }
    .stat .v { color: #fff; font-variant-numeric: tabular-nums; }
    .legend { margin-top: 16px; }
    .legend .row { display: flex; align-items: center; gap: 8px; padding: 4px 0; font-size: 13px; }
    .legend .swatch { width: 12px; height: 12px; border-radius: 3px; }
    #search { width: 100%; padding: 6px 8px; background: #0e0f12; color: #e6e6e6; border: 1px solid #2a2d34; border-radius: 4px; font-size: 13px; margin: 12px 0; }
    #info { margin-top: 16px; padding: 10px; background: #0e0f12; border: 1px solid #2a2d34; border-radius: 4px; font-size: 13px; min-height: 40px; }
    #info h3 { margin: 0 0 6px 0; font-size: 14px; }
    #info .field { margin-top: 6px; font-size: 12px; }
    #info .field b { color: #9aa0a6; font-weight: 500; }
    #network { background: #0e0f12; }
    a { color: #6aa9ff; }
  </style>
</head>
<body>
  <div id="app">
    <aside id="sidebar">
      <h1>research-companion</h1>
      <p class="tag">{{ tagline }}</p>
      <input id="search" placeholder="Search nodes...">
      <div id="info">Click a node to inspect.</div>
      <h3 style="font-size:13px;margin:16px 0 4px 0;color:#9aa0a6;">Graph</h3>
      {% for label, value in stats %}
      <div class="stat"><span>{{ label }}</span><span class="v">{{ value }}</span></div>
      {% endfor %}
      <div class="legend">
        <h3 style="font-size:13px;margin:16px 0 4px 0;color:#9aa0a6;">Legend</h3>
        {% for kind, color in legend %}
        <div class="row"><span class="swatch" style="background:{{ color }}"></span>{{ kind }}</div>
        {% endfor %}
      </div>
    </aside>
    <div id="network"></div>
  </div>
  <script>
    const NODES = {{ nodes_json | safe }};
    const EDGES = {{ edges_json | safe }};
    const NODE_BY_ID = {};
    NODES.forEach(n => { NODE_BY_ID[n.id] = n; });

    const data = { nodes: new vis.DataSet(NODES), edges: new vis.DataSet(EDGES) };
    const opts = {
      nodes: { font: { color: '#e6e6e6', size: 12 }, borderWidth: 1 },
      edges: { color: { color: 'rgba(110,118,129,0.35)', highlight: 'rgba(139,148,158,0.8)' }, smooth: { type: 'continuous' }, arrows: { to: { enabled: true, scaleFactor: 0.5 } } },
      physics: { stabilization: { iterations: 200 }, barnesHut: { gravitationalConstant: -3000, springLength: 120 } },
      interaction: { hover: true, tooltipDelay: 150 },
    };
    const network = new vis.Network(document.getElementById('network'), data, opts);
    const info = document.getElementById('info');

    network.on('click', (params) => {
      if (!params.nodes.length) { info.innerHTML = 'Click a node to inspect.'; return; }
      const n = NODE_BY_ID[params.nodes[0]];
      if (!n) return;
      let html = `<h3>${escapeHtml(n.label)}</h3><div class="field"><b>kind:</b> ${n.kind}</div>`;
      ['definition', 'description', 'metric', 'value', 'dataset', 'authors', 'year', 'source_url', 'full_text'].forEach(k => {
        if (n[k]) {
          let val = Array.isArray(n[k]) ? n[k].join(', ') : n[k];
          if (k === 'source_url') val = `<a href="${val}" target="_blank" rel="noopener">${escapeHtml(val)}</a>`;
          else val = escapeHtml(val.toString());
          html += `<div class="field"><b>${k}:</b> ${val}</div>`;
        }
      });
      info.innerHTML = html;
    });

    document.getElementById('search').addEventListener('input', (e) => {
      const q = e.target.value.toLowerCase();
      if (!q) { data.nodes.update(NODES.map(n => ({ id: n.id, hidden: false }))); return; }
      data.nodes.update(NODES.map(n => ({ id: n.id, hidden: !n.label.toLowerCase().includes(q) })));
    });

    function escapeHtml(s) {
      const d = document.createElement('div'); d.textContent = s; return d.innerHTML;
    }
  </script>
</body>
</html>
"""


def _vis_nodes(G: nx.Graph) -> list[dict]:
    out: list[dict] = []
    for nid, data in G.nodes(data=True):
        kind = data.get("kind", "unknown")
        node = {
            "id": nid,
            "label": data.get("label", nid),
            "kind": kind,
            "color": _KIND_COLORS.get(kind, "#888"),
            "shape": _KIND_SHAPES.get(kind, "dot"),
        }
        # Carry the extras for the side panel.
        for key in ("definition", "description", "metric", "value", "dataset",
                    "authors", "year", "source_url", "full_text"):
            v = data.get(key)
            if v not in (None, "", []):
                node[key] = v
        out.append(node)
    return out


def _vis_edges(G: nx.Graph) -> list[dict]:
    out: list[dict] = []
    for u, v, data in G.edges(data=True):
        relation = data.get("relation", "")
        # No always-on text label (clutter); the relation stays on hover.
        edge = {
            "from": u,
            "to": v,
            "title": relation,
            "width": 1 + 0.3 * (data.get("weight", 1) - 1),
            "dashes": [4, 4] if relation == "co_mentioned" else False,
        }
        if relation == "cites" and data.get("polarity") in CITATION_POLARITY_COLORS:
            edge["color"] = CITATION_POLARITY_COLORS[data["polarity"]]
        out.append(edge)
    return out


def render(G: nx.Graph | None = None, *, output_path: Path | None = None) -> Path:
    """Render the graph to a self-contained HTML file. Returns the output path."""
    from jinja2 import Template

    G = G if G is not None else load_graph()
    out = output_path or graph_html_path()
    out.parent.mkdir(parents=True, exist_ok=True)

    stats = graph_stats(G)
    stats_view = [
        ("nodes", stats.get("nodes_total", 0)),
        ("edges", stats.get("edges_total", 0)),
        ("papers", stats.get("node_paper", 0)),
        ("concepts", stats.get("node_concept", 0)),
        ("methods", stats.get("node_method", 0)),
        ("datasets", stats.get("node_dataset", 0)),
        ("claims", stats.get("node_claim", 0)),
        ("results", stats.get("node_result", 0)),
    ]
    legend = [(k, c) for k, c in _KIND_COLORS.items()]

    html = Template(HTML_TEMPLATE).render(
        tagline=f"{stats.get('node_paper', 0)} papers, "
                f"{stats.get('nodes_total', 0)} nodes, "
                f"{stats.get('edges_total', 0)} edges",
        stats=stats_view,
        legend=legend,
        nodes_json=json.dumps(_vis_nodes(G)),
        edges_json=json.dumps(_vis_edges(G)),
    )
    out.write_text(html, encoding="utf-8")
    return out


def view(*, output_path: Path | None = None, open_browser: bool = True) -> Path:
    """Render and (optionally) open the graph HTML in the default browser."""
    p = render(output_path=output_path)
    if open_browser:
        webbrowser.open(p.resolve().as_uri())
    return p
