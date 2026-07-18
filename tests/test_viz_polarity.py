import networkx as nx

from research_companion import viz


def test_cites_edge_colored_by_polarity():
    G = nx.Graph()
    G.add_node("a", kind="paper")
    G.add_node("b", kind="paper")
    G.add_edge("a", "b", relation="cites", polarity="refutation")
    e = viz._vis_edges(G)[0]
    assert e["color"] == viz.CITATION_POLARITY_COLORS["refutation"]


def test_untyped_cites_has_no_polarity_color():
    G = nx.Graph()
    G.add_node("a", kind="paper")
    G.add_node("b", kind="paper")
    G.add_edge("a", "b", relation="cites")
    e = viz._vis_edges(G)[0]
    assert "color" not in e or e.get("color") is None
