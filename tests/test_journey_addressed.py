"""The paid "was this suggestion addressed" check must be able to say yes."""
from __future__ import annotations

import json


def test_addressed_check_reads_section_text_from_offsets(isolated_papergraph_dir):
    """sections.json stores offsets, not text. Reading a missing "text" key
    made every unit empty, so the model was asked about nothing and the
    evidence quote could never verify."""
    from research_companion.journey import _llm_check_addressed

    intro = "Introduction. We study caching for language model inference. "
    related = ("Related work. Prior systems compress the key value cache with "
               "quantization and report a twofold memory reduction. ")
    draft = intro + related
    sections = {"sections": [
        {"section_id": "s1", "title": "Introduction", "char_start": 0, "char_end": len(intro)},
        {"section_id": "s2", "title": "Related work", "char_start": len(intro),
         "char_end": len(draft)},
    ]}
    seen = {}

    def llm(prompt: str) -> str:
        seen["prompt"] = prompt
        return json.dumps({"addressed": True,
                           "evidence": "compress the key value cache with quantization"})

    sug = {"kind": "related_work", "title": "Discuss key value cache quantization",
           "detail": "Cite prior work on cache compression"}
    assert _llm_check_addressed(sug, "local:draft", draft, sections, llm) is True
    assert "key value cache" in seen["prompt"]
