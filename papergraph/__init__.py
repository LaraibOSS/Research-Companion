"""papergraph: drop arXiv URLs or PDFs in, get an interactive knowledge graph
plus a chat interface that answers questions with paper citations.

Public API (programmatic use):
    from papergraph import add_paper, build_graph, chat, view

CLI:
    papergraph add <url-or-pdf>
    papergraph build
    papergraph view
    papergraph chat ["<question>"]
"""
from __future__ import annotations

__version__ = "0.1.0"


def __getattr__(name: str):
    # Lazy imports so `papergraph --help` doesn't pull every module.
    _map = {
        "add_paper": ("papergraph.fetch", "add_paper"),
        "build_graph": ("papergraph.graph", "build_graph"),
        "chat": ("papergraph.chat", "chat"),
        "view": ("papergraph.viz", "view"),
    }
    if name in _map:
        import importlib
        mod_name, attr = _map[name]
        return getattr(importlib.import_module(mod_name), attr)
    raise AttributeError(f"module 'papergraph' has no attribute {name!r}")
