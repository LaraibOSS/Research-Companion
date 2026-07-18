from research_companion import prompts


def test_format_includes_title_citations_and_enum():
    p = prompts.format_citation_polarity_prompt(
        "My Paper", "We build on Lewis et al. and unlike Smith we ...",
        ["Lewis et al. 2020", "Smith 2019"])
    assert "My Paper" in p
    assert "Lewis et al. 2020" in p and "Smith 2019" in p
    # the closed vocabulary must appear so the model is constrained
    for tag in ("based_on", "support", "contrast", "refutation", "mention"):
        assert tag in p


def test_sha_is_stable_and_hex():
    s = prompts.citation_polarity_prompt_sha256()
    assert isinstance(s, str) and len(s) == 64 and s == prompts.citation_polarity_prompt_sha256()
