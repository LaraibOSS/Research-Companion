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

from research_companion import cli
from research_companion.graph import build_graph
from research_companion.prompts import extraction_prompt_sha256
from research_companion.store import (
    PaperMetadata,
    graph_json_path,
    save_extraction,
    save_pdf,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _save_graph_compat(G: nx.Graph) -> None:
    """Save via the shared writer so the on-disk key ("links") matches what
    load_graph and the CLI read — a bare node_link_data() writes "edges" on
    networkx >= 3.6 and broke CI while passing on older dev machines."""
    from research_companion.graph import save_graph
    save_graph(G, graph_json_path())


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
    """Install a fake research_companion.fetch module so _cmd_add's lazy import works.

    The real research_companion.fetch requires feedparser/httpx at import time.
    We inject a minimal module with add_paper and FetchError into sys.modules.
    """
    fake_fetch = types.ModuleType("research_companion.fetch")
    fake_fetch.add_paper = mock_add_paper
    fake_fetch.FetchError = RuntimeError
    monkeypatch.setitem(sys.modules, "research_companion.fetch", fake_fetch)


# ---------------------------------------------------------------------------
# Batch-add tests
# ---------------------------------------------------------------------------


class TestBatchAdd:
    """Tests for `research-companion add` batch capabilities."""

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
    """Tests for `research-companion search`."""

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
    """Tests for `research-companion export`."""

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

    def _add_two_colliding_papers(self, fake_pdf_bytes: bytes, sample_extraction: dict) -> None:
        """Two papers whose titles sanitize to the identical base filename
        ("Deep_Learning_A_Survey") — regression fixture for export collisions."""
        _add_paper_with_extraction(
            fake_pdf_bytes, sample_extraction,
            paper_id="arxiv:1111.11111", title="Deep Learning: A Survey!",
        )
        _add_paper_with_extraction(
            fake_pdf_bytes, sample_extraction,
            paper_id="arxiv:2222.22222", title="Deep Learning A Survey",
        )
        from research_companion.graph import build_graph, save_graph
        from research_companion.store import graph_json_path, list_papers
        G = build_graph(list_papers())
        save_graph(G, graph_json_path())

    def test_export_markdown_disambiguates_colliding_filenames(
        self, fake_pdf_bytes: bytes,
        sample_extraction: dict, tmp_path: Path, capsys: pytest.CaptureFixture,
    ):
        """Two papers whose titles sanitize to the same base filename must
        each get their own file — no silent overwrite (previously the second
        paper's .md clobbered the first's)."""
        self._add_two_colliding_papers(fake_pdf_bytes, sample_extraction)

        out_dir = tmp_path / "md-export-collide"
        rc = cli.main(["export", "--format", "markdown", "--output", str(out_dir)])
        assert rc == 0

        md_files = [f for f in out_dir.glob("*.md") if f.name != "_index.md"]
        assert len(md_files) == 2
        stems = {f.stem for f in md_files}
        assert "Deep_Learning_A_Survey" in stems
        assert any(s.startswith("Deep_Learning_A_Survey-") for s in stems)

        # Both titles are still findable in their respective files (nothing lost).
        all_content = "\n".join(f.read_text(encoding="utf-8") for f in md_files)
        assert "Deep Learning: A Survey!" in all_content
        assert "Deep Learning A Survey" in all_content

        # The index references two distinct filenames, matching what's on disk.
        index_text = (out_dir / "_index.md").read_text(encoding="utf-8")
        for f in md_files:
            assert f"({f.stem}.md)" in index_text

    def test_export_obsidian_disambiguates_and_backlinks_resolve(
        self, fake_pdf_bytes: bytes,
        sample_extraction: dict, tmp_path: Path, capsys: pytest.CaptureFixture,
    ):
        """Same collision, obsidian format: paper notes stay distinct AND
        entity notes' [[wikilinks]] back to papers resolve to real files
        (not a stale/re-sanitized name that no longer matches disk)."""
        self._add_two_colliding_papers(fake_pdf_bytes, sample_extraction)

        out_dir = tmp_path / "obsidian-export-collide"
        rc = cli.main(["export", "--format", "obsidian", "--output", str(out_dir)])
        assert rc == 0

        md_files = list(out_dir.glob("*.md"))
        stems = {f.stem for f in md_files}
        assert "Deep_Learning_A_Survey" in stems
        assert any(s.startswith("Deep_Learning_A_Survey-") for s in stems)

        # Shared concept "Knowledge graph" (from sample_extraction, used by both
        # papers) gets one entity note that backlinks to BOTH paper files.
        entity_file = out_dir / "Knowledge_graph.md"
        assert entity_file.exists()
        content = entity_file.read_text(encoding="utf-8")

        import re
        linked = re.findall(r"\[\[([^\]]+)\]\]", content)
        assert len(linked) == 2
        # Every backlink must resolve to an actual written file.
        for link in linked:
            assert (out_dir / f"{link}.md").exists(), f"[[{link}]] does not resolve to a file"

    def test_export_obsidian_paper_and_entity_name_collision(
        self, fake_pdf_bytes: bytes,
        sample_extraction: dict, tmp_path: Path, capsys: pytest.CaptureFixture,
    ):
        """A paper title and an entity name (concept/method/dataset) that
        sanitize to the SAME base filename must land in two distinct files
        (paper notes and entity notes previously deduped against separate
        used-name maps, so one silently overwrote the other), and the
        surviving entity->paper backlink must resolve to a real file."""
        # sample_extraction's methods include one named "GraphRAG" — give the
        # paper the identical title so both sanitize to "GraphRAG".
        _add_paper_with_extraction(
            fake_pdf_bytes, sample_extraction,
            paper_id="arxiv:3333.33333", title="GraphRAG",
        )
        from research_companion.graph import build_graph, save_graph
        from research_companion.store import graph_json_path, list_papers
        G = build_graph(list_papers())
        save_graph(G, graph_json_path())

        out_dir = tmp_path / "obsidian-export-name-collide"
        rc = cli.main(["export", "--format", "obsidian", "--output", str(out_dir)])
        assert rc == 0

        md_files = list(out_dir.glob("*.md"))
        stems = {f.stem for f in md_files}
        assert "GraphRAG" in stems
        assert any(s.startswith("GraphRAG-") for s in stems)

        contents = {f.stem: f.read_text(encoding="utf-8") for f in md_files}
        # The paper note has "**Authors:**"; the "GraphRAG" method note has
        # "**Type:** method" — distinguish which of the two "GraphRAG*" files
        # is which, and confirm neither clobbered the other.
        graphrag_stems = [s for s in stems if s == "GraphRAG" or s.startswith("GraphRAG-")]
        paper_stems = [s for s in graphrag_stems if "**Authors:**" in contents[s]]
        entity_stems = [s for s in graphrag_stems if "**Type:** method" in contents[s]]
        assert len(paper_stems) == 1, contents
        assert len(entity_stems) == 1, contents
        assert paper_stems[0] != entity_stems[0]

        # The entity note's "Mentioned in" backlink(s) to paper(s) must
        # resolve to actual written files.
        import re
        linked = re.findall(r"\[\[([^\]]+)\]\]", contents[entity_stems[0]])
        assert linked
        for link in linked:
            assert (out_dir / f"{link}.md").exists(), f"[[{link}]] does not resolve to a file"


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
    """Tests for `research-companion discover`."""

    def test_discover_topic_search(self, capsys: pytest.CaptureFixture):
        """Topic search returns discovered papers."""
        from research_companion import discover

        # Mock the httpx call inside search_topic.
        fake_resp = MagicMock()
        fake_resp.json.return_value = _fake_s2_search_response()
        fake_resp.raise_for_status = MagicMock()

        fake_client = MagicMock()
        fake_client.get.return_value = fake_resp
        fake_client.__enter__ = MagicMock(return_value=fake_client)
        fake_client.__exit__ = MagicMock(return_value=False)

        with patch("research_companion.discover.httpx.Client", return_value=fake_client):
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
        from research_companion import discover

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

        with patch("research_companion.discover.httpx.Client", return_value=fake_client):
            results = discover.search_topic("graph neural networks", limit=10)

        # The first result should be excluded because its arXiv ID matches.
        titles = [p.title for p in results]
        assert "Graph Neural Networks for NLP" not in titles

    def test_discover_expand(
        self, fake_pdf_bytes: bytes, sample_extraction: dict,
        capsys: pytest.CaptureFixture,
    ):
        """--expand follows citations/references of existing papers."""
        from research_companion import discover

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

        with patch("research_companion.discover.httpx.Client", return_value=fake_client):
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

    def test_discover_cli_add_all_fail_returns_nonzero(
        self, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch,
    ):
        """--add whose every attempted add fails must exit non-zero
        (previously always returned 0, hiding the failure from scripts)."""
        from research_companion.discover import DiscoveredPaper
        from research_companion.fetch import FetchError

        found = [DiscoveredPaper(title="Graph RAG Survey", authors=["A"], year=2024,
                                 citation_count=1, arxiv_id="2401.00001", doi=None,
                                 s2_id=None, url="")]
        monkeypatch.setattr("research_companion.discover.search_topic", lambda *a, **k: found)

        def _always_fails(target):
            raise FetchError("boom")

        monkeypatch.setattr("research_companion.fetch.add_paper", _always_fails)

        rc = cli.main(["discover", "graph RAG", "--add"])
        assert rc == 1

    def test_discover_cli_add_partial_success_returns_zero(
        self, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch,
    ):
        """When at least one add succeeds, exit code stays 0."""
        from research_companion.discover import DiscoveredPaper
        from research_companion.fetch import FetchError

        found = [
            DiscoveredPaper(title="Graph RAG Survey", authors=["A"], year=2024,
                            citation_count=1, arxiv_id="2401.00001", doi=None,
                            s2_id=None, url=""),
            DiscoveredPaper(title="Another Paper", authors=["B"], year=2023,
                            citation_count=2, arxiv_id="2301.00002", doi=None,
                            s2_id=None, url=""),
        ]
        monkeypatch.setattr("research_companion.discover.search_topic", lambda *a, **k: found)

        meta = types.SimpleNamespace(paper_id="arxiv:2401.00001", title="Graph RAG Survey")

        def _add(target):
            if target == "2401.00001":
                return meta
            raise FetchError("boom")

        monkeypatch.setattr("research_companion.fetch.add_paper", _add)

        rc = cli.main(["discover", "graph RAG", "--add"])
        assert rc == 0

    def test_discover_cli_json_output(self, capsys: pytest.CaptureFixture):
        """--json flag produces valid JSON output."""

        fake_resp = MagicMock()
        fake_resp.json.return_value = _fake_s2_search_response()
        fake_resp.raise_for_status = MagicMock()

        fake_client = MagicMock()
        fake_client.get.return_value = fake_resp
        fake_client.__enter__ = MagicMock(return_value=fake_client)
        fake_client.__exit__ = MagicMock(return_value=False)

        with patch("research_companion.discover.httpx.Client", return_value=fake_client):
            rc = cli.main(["discover", "graph RAG", "--json"])

        assert rc == 0
        out = capsys.readouterr().out
        data = json.loads(out)
        assert isinstance(data, list)
        assert len(data) >= 1
        assert "title" in data[0]
        assert "citation_count" in data[0]
        assert "add_cmd" in data[0]
