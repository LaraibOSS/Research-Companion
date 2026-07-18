import networkx as nx

from research_companion import graph as graphmod
from research_companion import report as reportmod


def test_serialize_and_stats_unchanged_without_polarity():
    G = nx.Graph()
    G.add_node("a", kind="paper")
    G.add_node("b", kind="paper")
    G.add_edge("a", "b", relation="cites")  # no polarity
    edge = [e for e in graphmod.serialize_graph(G)["edges"] if e.get("relation") == "cites"][0]
    assert "polarity" not in edge
    stats = graphmod.graph_stats(G)
    assert not any(k.startswith("edge_cites_") for k in stats)  # no polarity sub-counts

def test_report_has_no_polarity_or_taxonomy_when_lanes_absent():
    report = {"paper_id": "p", "title": "T", "lanes": {
        "citation": {"ok": True, "data": {"counts": {"verified": 1}, "references": []}}}}
    html = reportmod.render_report_html(report)
    assert "Citation Stance" not in html and "Prior-art taxonomy" not in html
