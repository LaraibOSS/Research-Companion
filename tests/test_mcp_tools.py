"""Unit tests for the deterministic MCP tool logic (no SDK, no network)."""
from research_companion import mcp_tools, store

# --- verify_citation (offline via injected lookup) -------------------------

def test_verify_citation_unverified_when_no_record():
    res = mcp_tools.verify_citation(title="A Totally Made Up Paper",
                                    lookup=lambda ref: None)
    assert res["status"] == "unverified"
    assert res["reference"]["title"] == "A Totally Made Up Paper"


def test_verify_citation_verified_on_match():
    record = {"title": "Attention Is All You Need",
              "authors": ["Ashish Vaswani", "Noam Shazeer"], "year": 2017}
    res = mcp_tools.verify_citation(
        title="Attention Is All You Need",
        authors=["Vaswani", "Shazeer"],
        lookup=lambda ref: record,
    )
    assert res["status"] == "verified"
    assert res["matched"] == record


def test_verify_citation_suspect_on_title_mismatch():
    res = mcp_tools.verify_citation(
        title="Attention Is All You Need",
        lookup=lambda ref: {"title": "A Completely Different Title", "authors": []},
    )
    assert res["status"] == "suspect"
    assert res["reasons"]


# --- ground_claim ----------------------------------------------------------

def test_ground_claim_grounded_with_offsets():
    pid = "local:g1"
    store.PaperMetadata(paper_id=pid, title="T", authors=[]).save()
    store.save_text(pid, "Intro. The transformer relies entirely on self-attention. End.")

    res = mcp_tools.ground_claim(quote="relies entirely on self-attention", paper_id=pid)
    assert res["grounded"] is True
    assert res["char_start"] is not None and res["char_end"] > res["char_start"]


def test_ground_claim_not_grounded_for_absent_quote():
    pid = "local:g2"
    store.PaperMetadata(paper_id=pid, title="T", authors=[]).save()
    store.save_text(pid, "This paper is about graph neural networks.")

    res = mcp_tools.ground_claim(quote="a quote that does not appear here at all",
                                 paper_id=pid)
    assert res["grounded"] is False


def test_ground_claim_missing_paper():
    res = mcp_tools.ground_claim(quote="anything long enough", paper_id="local:nope")
    assert res["grounded"] is False
    assert "error" in res


# --- citation_coverage -----------------------------------------------------

def test_citation_coverage_returns_counts_dict():
    pid = "local:draft1"
    store.PaperMetadata(paper_id=pid, title="Draft", authors=[]).save()
    store.save_text(pid, "A short draft with no bibliography section.")

    res = mcp_tools.citation_coverage(paper_id=pid)
    assert res["paper_id"] == pid
    assert "total" in res["counts"]


# --- search_library --------------------------------------------------------

def test_search_library_finds_relevant_paper():
    store.PaperMetadata(paper_id="local:s1", title="Transformers", authors=[]).save()
    store.save_text("local:s1", "The transformer architecture uses multi-head attention.")
    store.PaperMetadata(paper_id="local:s2", title="Diffusion", authors=[]).save()
    store.save_text("local:s2", "Diffusion models generate images by denoising.")

    res = mcp_tools.search_library(query="attention transformer", k=5)
    assert res["query"] == "attention transformer"
    assert res["results"]
    top = res["results"][0]
    assert top["paper_id"] == "local:s1"
    assert top["mode"] == "bm25"
    assert top["char_start"] is not None


def test_search_library_empty_on_no_match():
    store.PaperMetadata(paper_id="local:s3", title="X", authors=[]).save()
    store.save_text("local:s3", "Completely unrelated content about botany.")
    res = mcp_tools.search_library(query="quantum chromodynamics lattice", k=5)
    assert res["results"] == []
