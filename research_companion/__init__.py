"""research-companion: drop arXiv URLs or PDFs in, get an interactive knowledge graph
plus a chat interface that answers questions with paper citations.

Public API (programmatic use):
    from research_companion import add_paper, build_graph, chat, view

CLI:
    research-companion add <url-or-pdf>
    research-companion build
    research-companion view
    research-companion chat ["<question>"]
"""
from __future__ import annotations

__version__ = "0.1.0"


def __getattr__(name: str):
    # Lazy imports so `research-companion --help` doesn't pull every module.
    _map = {
        "add_paper": ("research_companion.fetch", "add_paper"),
        "build_graph": ("research_companion.graph", "build_graph"),
        "chat": ("research_companion.chat", "chat"),
        "view": ("research_companion.viz", "view"),
    }
    if name in _map:
        import importlib
        mod_name, attr = _map[name]
        return getattr(importlib.import_module(mod_name), attr)
    raise AttributeError(f"module 'research-companion' has no attribute {name!r}")
