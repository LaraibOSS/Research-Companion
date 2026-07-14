"""RIS export."""
from research_companion.interop.ris import papers_to_ris

REC = {
    "title": "GraphRAG",
    "authors": ["Ada Lovelace", "Alan Turing"],
    "year": 2024,
    "source_url": "https://example.org/graphrag",
    "doi": "10.1000/xyz",
}


def test_ris_entry_structure():
    out = papers_to_ris([REC])
    assert "TY  - JOUR" in out
    assert "TI  - GraphRAG" in out
    assert "AU  - Ada Lovelace" in out
    assert "AU  - Alan Turing" in out
    assert "PY  - 2024" in out
    assert "DO  - 10.1000/xyz" in out
    assert "UR  - https://example.org/graphrag" in out
    assert out.rstrip().endswith("ER  -")


def test_ris_multiple_and_empty():
    out = papers_to_ris([REC, {"title": "Second", "authors": [], "year": None}])
    assert out.count("TY  - JOUR") == 2
    assert out.count("ER  -") == 2
    assert papers_to_ris([]) == ""
