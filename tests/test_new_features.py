"""Tests for batch-add, search, export, and discover features."""
from __future__ import annotations

import csv
import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import networkx as nx
import pytest
from networkx.readwrite import json_graph

from papergraph import cli
from papergraph.graph import build_graph
from papergraph.prompts import extraction_prompt_sha256
from papergraph.store import (
    PaperMetadata,
    graph_json_path,
    save_extraction,
    save_pdf,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _save_graph_compat(G: nx.Graph) -> None:
    """Save graph using the node-link format compatible with this networkx."""
    p = graph_json_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    data = json_graph.node_link_data(G)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _add_paper_with_extraction(
    fake_pdf_bytes: bytes,
    extraction: dict,
    *,
    paper_id: str = "arxiv:2410.05779",
    title: str = "GraphRAG paper",
    authors: list[str] | None = None,
    year: int = 2024,
) -> PaperMetadata:
    """Persist a paper + extraction to disk so build_graph() can pick it up."""
    meta = PaperMetadata(
        paper_id=paper_id,
        title=title,
        authors=authors or ["Alice", "Bob"],
        year=year,
        abstract="An abstract.",
        source_url=f"https://arxiv.org/abs/{paper_id.split(':')[-1]}",
        added_at="2024-01-01T00:00:00+0000",
    )
    meta.save()
    save_pdf(paper_id, fake_pdf_bytes)
    save_extraction(paper_id, extraction, prompt_sha=extraction_prompt_sha256())
    return meta


def _build_sample_graph(
    fake_pdf_bytes: bytes,
    sample_extraction: dict,
) -> None:
    """Add a paper, save its extraction, build and persist the graph."""
    meta = _add_paper_with_extraction(fake_pdf_bytes, sample_extraction)
    G = build_graph([meta])
    _save_graph_compat(G)


def _install_fake_fetch_module(monkeypatch, mock_add_paper):
    """Install a fake papergraph.fetch module so _cmd_add's lazy import works.

    The real papergraph.fetch requires feedparser/httpx at import time.
    We inject a minimal module with add_paper and FetchError into sys.modules.
    """
    fake_fetch = types.ModuleType("papergraph.fetch")
    fake_fetch.add_paper = mock_add_paper
    fake_fetch.FetchError = RuntimeError
    monkeypatch.setitem(sys.modules, "papergraph.fetch", fake_fetch)


# ---------------------------------------------------------------------------
# Batch-add tests
# ---------------------------------------------------------------------------


class TestBatchAdd:
    """Tests for `papergraph add` batch capabilities."""

    def test_add_from_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
    ):
        """--from-file reads URLs from a file and adds each one."""
        targets_file = tmp_path / "papers.txt"
        targets_file.write_text("2410.05779\n2301.00001\n", encoding="utf-8")

        fake_meta_1 = PaperMetadata(
            paper_id="arxiv:2410.05779", title="Paper One", authors=["A"],
            year=2024, added_at="2024-01-01T00:00:00+0000",
        )
        fake_meta_2 = PaperMetadata(
            paper_id="arxiv:2301.00001", title="Paper Two", authors=["B"],
            year=2023, added_at="2024-01-01T00:00:00+0000",
        )

        calls: list[str] = []

        def mock_add_paper(target, **kwargs):
            calls.append(target)
            if "2410.05779" in target:
                return fake_meta_1
            return fake_meta_2

        _install_fake_fetch_module(monkeypatch, mock_add_paper)
        rc = cli.main(["add", "--from-file", str(targets_file)])

        assert rc == 0
        assert len(calls) == 2
        out = capsys.readouterr().out
        assert "Paper One" in out
        assert "Paper Two" in out

    def test_add_from_file_with_comments(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
    ):
        """Lines starting with # and blank lines are skipped."""
        targets_file = tmp_path / "papers.txt"
        targets_file.write_text(
            "# This is a comment\n"
            "\n"
            "2410.05779   # inline comment\n"
            "  \n"
            "# Another comment\n",
            encoding="utf-8",
        )

        fake_meta = PaperMetadata(
            paper_id="arxiv:2410.05779", title="Only Paper", authors=["A"],
            year=2024, added_at="2024-01-01T00:00:00+0000",
        )

        calls: list[str] = []

        def mock_add_paper(target, **kwargs):
            calls.append(target)
            return fake_meta

        _install_fake_fetch_module(monkeypatch, mock_add_paper)
        rc = cli.main(["add", "--from-file", str(targets_file)])

        assert rc == 0
        assert len(calls) == 1
        out = capsys.readouterr().out
        assert "Only Paper" in out

    def test_add_multiple_positional(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture,
    ):
        """Multiple positional args each get added."""
        fake_meta_1 = PaperMetadata(
            paper_id="arxiv:2410.05779", title="Paper A", authors=["X"],
            year=2024, added_at="2024-01-01T00:00:00+0000",
        )
        fake_meta_2 = PaperMetadata(
            paper_id="arxiv:2301.00001", title="Paper B", authors=["Y"],
            year=2023, added_at="2024-01-01T00:00:00+0000",
        )

        calls: list[str] = []

        def mock_add_paper(target, **kwargs):
            calls.append(target)
            if "2410.05779" in target:
                return fake_meta_1
            return fake_meta_2

        _install_fake_fetch_module(monkeypatch, mock_add_paper)
        rc = cli.main(["add", "2410.05779", "2301.00001"])

        assert rc == 0
        assert len(calls) == 2
        out = capsys.readouterr().out
        assert "Paper A" in out
        assert "Paper B" in out

    def test_add_nothing_gives_error(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture,
    ):
        """Running `add` with no targets and no --from-file prints an error."""
        _install_fake_fetch_module(monkeypatch, MagicMock())
        rc = cli.main(["add"])
        assert rc == 1
        err = capsys.readouterr().err
        assert "nothing to add" in err.lower()


# ---------------------------------------------------------------------------
# Search tests
# ---------------------------------------------------------------------------


class TestSearch:
    """Tests for `papergraph search`."""

    def test_search_finds_nodes(
        self, fake_pdf_bytes: bytes,
        sample_extraction: dict, capsys: pytest.CaptureFixture,
    ):
        """Searching for a known concept returns a match."""
        _build_sample_graph(fake_pdf_bytes, sample_extraction)

        rc = cli.main(["search", "Knowledge graph"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "Knowledge graph" in out

    def test_search_no_results(
        self, fake_pdf_bytes: bytes,
        sample_extraction: dict, capsys: pytest.CaptureFixture,
    ):
        """Searching for a nonsense term returns 0 matches."""
        _build_sample_graph(fake_pdf_bytes, sample_extraction)

        rc = cli.main(["search", "xyzzy_nonsense_42"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "no matches" in out.lower()

    def test_search_json_output(
        self, fake_pdf_bytes: bytes,
        sample_extraction: dict, capsys: pytest.CaptureFixture,
    ):
        """--json flag produces valid JSON output."""
        _build_sample_graph(fake_pdf_bytes, sample_extraction)

        rc = cli.main(["search", "RAG", "--json"])
        assert rc == 0
        out = capsys.readouterr().out
        data = json.loads(out)
        assert isinstance(data, list)
        assert len(data) > 0
        # Each entry has at least id, kind, label, score.
        for entry in data:
            assert "id" in entry
            assert "kind" in entry
            assert "label" in entry
            assert "score" in entry

    def test_search_kind_filter(
        self, fake_pdf_bytes: bytes,
        sample_extraction: dict, capsys: pytest.CaptureFixture,
    ):
        """--kind concept restricts results to concept nodes only."""
        _build_sample_graph(fake_pdf_bytes, sample_extraction)

        rc = cli.main(["search", "RAG", "--kind", "concept", "--json"])
        assert rc == 0
        out = capsys.readouterr().out
        data = json.loads(out)
        assert isinstance(data, list)
        for entry in data:
            assert entry["kind"] == "concept"


# ---------------------------------------------------------------------------
# Export tests
# ---------------------------------------------------------------------------


class TestExport:
    """Tests for `papergraph export`."""

    def test_export_markdown(
        self, fake_pdf_bytes: bytes,
        sample_extraction: dict, tmp_path: Path, capsys: pytest.CaptureFixture,
    ):
        """Markdown export creates _index.md and per-paper .md files."""
        _build_sample_graph(fake_pdf_bytes, sample_extraction)

        out_dir = tmp_path / "md-export"
        rc = cli.main(["export", "--format", "markdown", "--output", str(out_dir)])
        assert rc == 0
        assert (out_dir / "_index.md").exists()

        # At least one paper .md file besides _index.md.
        md_files = [f for f in out_dir.glob("*.md") if f.name != "_index.md"]
        assert len(md_files) >= 1

        # Paper file mentions the title.
        content = md_files[0].read_text(encoding="utf-8")
        assert "GraphRAG paper" in content

    def test_export_csv(
        self, fake_pdf_bytes: bytes,
        sample_extraction: dict, tmp_path: Path, capsys: pytest.CaptureFixture,
    ):
        """CSV export creates nodes.csv and edges.csv with correct headers."""
        _build_sample_graph(fake_pdf_bytes, sample_extraction)

        out_dir = tmp_path / "csv-export"
        rc = cli.main(["export", "--format", "csv", "--output", str(out_dir)])
        assert rc == 0
        assert (out_dir / "nodes.csv").exists()
        assert (out_dir / "edges.csv").exists()

        # Validate nodes.csv headers.
        with open(out_dir / "nodes.csv", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            header = next(reader)
        assert "id" in header
        assert "kind" in header
        assert "label" in header

        # Validate edges.csv headers.
        with open(out_dir / "edges.csv", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            header = next(reader)
        assert "source" in header
        assert "target" in header
        assert "relation" in header

    def test_export_json(
        self, fake_pdf_bytes: bytes,
        sample_extraction: dict, tmp_path: Path, capsys: pytest.CaptureFixture,
    ):
        """JSON export creates graph.json and papers.json."""
        _build_sample_graph(fake_pdf_bytes, sample_extraction)

        out_dir = tmp_path / "json-export"
        rc = cli.main(["export", "--format", "json", "--output", str(out_dir)])
        assert rc == 0
        assert (out_dir / "graph.json").exists()
        assert (out_dir / "papers.json").exists()

        # Both should be valid JSON.
        graph_data = json.loads((out_dir / "graph.json").read_text(encoding="utf-8"))
        assert isinstance(graph_data, dict)

        papers_data = json.loads((out_dir / "papers.json").read_text(encoding="utf-8"))
        assert isinstance(papers_data, list)
        assert len(papers_data) >= 1
        assert papers_data[0]["title"] == "GraphRAG paper"

    def test_export_obsidian(
        self, fake_pdf_bytes: bytes,
        sample_extraction: dict, tmp_path: Path, capsys: pytest.CaptureFixture,
    ):
        """Obsidian export produces paper files with [[wikilinks]]."""
        _build_sample_graph(fake_pdf_bytes, sample_extraction)

        out_dir = tmp_path / "obsidian-export"
        rc = cli.main(["export", "--format", "obsidian", "--output", str(out_dir)])
        assert rc == 0

        # At least one paper .md file.
        md_files = list(out_dir.glob("*.md"))
        assert len(md_files) >= 1

        # Find the paper file (starts with "# GraphRAG paper").
        paper_files = [
            f for f in md_files
            if f.read_text(encoding="utf-8").startswith("# GraphRAG paper")
        ]
        assert len(paper_files) >= 1

        content = paper_files[0].read_text(encoding="utf-8")
        # Obsidian format uses [[wikilinks]] for concepts/methods/datasets.
        assert "[[" in content
        assert "]]" in content
        # Check that a known concept has a wikilink.
        assert "[[Knowledge graph]]" in content


# ---------------------------------------------------------------------------
# Discover tests
# ---------------------------------------------------------------------------


def _fake_s2_search_response() -> dict:
    """Fake Semantic Scholar search API response."""
    return {
        "total": 2,
        "data": [
            {
                "paperId": "abc123",
                "title": "Graph Neural Networks for NLP",
                "authors": [{"name": "Alice Smith"}, {"name": "Bob Jones"}],
                "year": 2023,
                "citationCount": 150,
                "abstract": "We study GNN applications in NLP.",
                "externalIds": {"ArXiv": "2301.99999", "DOI": "10.1234/fake"},
                "url": "https://www.semanticscholar.org/paper/abc123",
            },
            {
                "paperId": "def456",
                "title": "Attention Mechanisms Survey",
                "authors": [{"name": "Carol Lee"}],
                "year": 2022,
                "citationCount": 80,
                "abstract": "A survey of attention mechanisms.",
                "externalIds": {"ArXiv": "2201.88888"},
                "url": "https://www.semanticscholar.org/paper/def456",
            },
        ],
    }


def _fake_s2_references_response() -> dict:
    """Fake Semantic Scholar references API response."""
    return {
        "data": [
            {
                "citedPaper": {
                    "paperId": "ref001",
                    "title": "Original Transformer Paper",
                    "authors": [{"name": "Vaswani"}, {"name": "Shazeer"}],
                    "year": 2017,
                    "citationCount": 90000,
                    "externalIds": {"ArXiv": "1706.03762"},
                    "url": "https://www.semanticscholar.org/paper/ref001",
                },
            },
        ],
    }


def _fake_s2_citations_response() -> dict:
    """Fake Semantic Scholar citations API response."""
    return {
        "data": [
            {
                "citingPaper": {
                    "paperId": "cite001",
                    "title": "Improved Graph RAG Techniques",
                    "authors": [{"name": "Dave Wilson"}],
                    "year": 2025,
                    "citationCount": 12,
                    "externalIds": {"ArXiv": "2501.11111"},
                    "url": "https://www.semanticscholar.org/paper/cite001",
                },
            },
        ],
    }


class TestDiscover:
    """Tests for `papergraph discover`."""

    def test_discover_topic_search(self, capsys: pytest.CaptureFixture):
        """Topic search returns discovered papers."""
        from papergraph import discover

        # Mock the httpx call inside search_topic.
        fake_resp = MagicMock()
        fake_resp.json.return_value = _fake_s2_search_response()
        fake_resp.raise_for_status = MagicMock()

        fake_client = MagicMock()
        fake_client.get.return_value = fake_resp
        fake_client.__enter__ = MagicMock(return_value=fake_client)
        fake_client.__exit__ = MagicMock(return_value=False)

        with patch("papergraph.discover.httpx.Client", return_value=fake_client):
            results = discover.search_topic("graph neural networks", limit=10)

        assert len(results) >= 1
        assert results[0].title == "Graph Neural Networks for NLP"
        assert results[0].citation_count == 150
        assert results[0].arxiv_id == "2301.99999"

    def test_discover_topic_excludes_existing(
        self, fake_pdf_bytes: bytes, sample_extraction: dict,
        capsys: pytest.CaptureFixture,
    ):
        """Papers already in the store are excluded from discover results."""
        from papergraph import discover

        # Add a paper with a matching title to the store.
        _add_paper_with_extraction(
            fake_pdf_bytes, sample_extraction,
            paper_id="arxiv:2301.99999",
            title="Graph Neural Networks for NLP",
        )

        fake_resp = MagicMock()
        fake_resp.json.return_value = _fake_s2_search_response()
        fake_resp.raise_for_status = MagicMock()

        fake_client = MagicMock()
        fake_client.get.return_value = fake_resp
        fake_client.__enter__ = MagicMock(return_value=fake_client)
        fake_client.__exit__ = MagicMock(return_value=False)

        with patch("papergraph.discover.httpx.Client", return_value=fake_client):
            results = discover.search_topic("graph neural networks", limit=10)

        # The first result should be excluded because its arXiv ID matches.
        titles = [p.title for p in results]
        assert "Graph Neural Networks for NLP" not in titles

    def test_discover_expand(
        self, fake_pdf_bytes: bytes, sample_extraction: dict,
        capsys: pytest.CaptureFixture,
    ):
        """--expand follows citations/references of existing papers."""
        from papergraph import discover

        # Add an arXiv paper to the store.
        _add_paper_with_extraction(fake_pdf_bytes, sample_extraction)

        # Mock: references returns Transformer, citations returns Improved Graph RAG.
        def mock_get(url, **kwargs):
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            if "/references" in url:
                resp.json.return_value = _fake_s2_references_response()
            elif "/citations" in url:
                resp.json.return_value = _fake_s2_citations_response()
            else:
                resp.json.return_value = {"data": []}
            return resp

        fake_client = MagicMock()
        fake_client.get = mock_get
        fake_client.__enter__ = MagicMock(return_value=fake_client)
        fake_client.__exit__ = MagicMock(return_value=False)

        with patch("papergraph.discover.httpx.Client", return_value=fake_client):
            results = discover.expand_from_existing(limit=10, min_citations=5)

        titles = [p.title for p in results]
        assert "Original Transformer Paper" in titles
        assert "Improved Graph RAG Techniques" in titles
        # Transformer should rank first (90k citations > 12).
        assert results[0].title == "Original Transformer Paper"

    def test_discover_cli_no_args_errors(self, capsys: pytest.CaptureFixture):
        """Running `discover` with no topic and no --expand gives an error."""
        rc = cli.main(["discover"])
        assert rc == 1
        err = capsys.readouterr().err
        assert "provide a topic" in err.lower()

    def test_discover_cli_json_output(self, capsys: pytest.CaptureFixture):
        """--json flag produces valid JSON output."""

        fake_resp = MagicMock()
        fake_resp.json.return_value = _fake_s2_search_response()
        fake_resp.raise_for_status = MagicMock()

        fake_client = MagicMock()
        fake_client.get.return_value = fake_resp
        fake_client.__enter__ = MagicMock(return_value=fake_client)
        fake_client.__exit__ = MagicMock(return_value=False)

        with patch("papergraph.discover.httpx.Client", return_value=fake_client):
            rc = cli.main(["discover", "graph RAG", "--json"])

        assert rc == 0
        out = capsys.readouterr().out
        data = json.loads(out)
        assert isinstance(data, list)
        assert len(data) >= 1
        assert "title" in data[0]
        assert "citation_count" in data[0]
        assert "add_cmd" in data[0]
