"""Deterministic near-duplicate detection + the consent-gated external seam."""
from research_companion import overlap

# --- shingling / metrics ---------------------------------------------------

def test_shingles_windows_and_short_text():
    sh = overlap.shingles("the quick brown fox jumps over lazy dog", k=3)
    # tokenizer drops words <3 chars ("the") — order-preserving trigrams remain.
    assert "quick brown fox" in sh
    assert overlap.shingles("", k=3) == set()
    # fewer than k tokens -> a single shingle of what's there
    assert overlap.shingles("alpha beta", k=5) == {"alpha beta"}


def test_containment_and_jaccard():
    a, b = {"x y z"}, {"x y z", "p q r"}
    assert overlap.containment(a, b) == 1.0        # a fully inside b
    assert overlap.containment(b, a) == 0.5
    assert overlap.jaccard(a, b) == 0.5
    assert overlap.containment(set(), b) == 0.0


# --- near_duplicate_passages ----------------------------------------------

_SHARED = ("Contrastive learning maximizes agreement between differently augmented "
           "views of the same data example via a contrastive loss in the latent "
           "space, and it substantially improves representation quality across a "
           "wide range of downstream visual recognition benchmarks and datasets. ")


def test_flags_shared_passage_with_provenance():
    target = "Our intro. " + _SHARED + "We then propose a new sampling method entirely."
    corpus = [("arxiv:other", "Prior work. " + _SHARED + "Different conclusion here.")]
    res = overlap.near_duplicate_passages(target, corpus, min_shingles=5)
    assert res["findings"]
    f = res["findings"][0]
    assert f["matched_paper_id"] == "arxiv:other"
    assert f["score"] >= 0.6
    # target-side offsets slice back into the target text
    assert target[f["char_start"]:f["char_end"]]
    assert "near-duplicate" in res["summary"]["text"]


def test_no_findings_for_unrelated_papers():
    target = "This paper studies galaxy formation and dark matter halos in cosmology."
    corpus = [("arxiv:x", "A study of protein folding kinetics in molecular biology.")]
    res = overlap.near_duplicate_passages(target, corpus, min_shingles=3)
    assert res["findings"] == []
    assert res["summary"]["text"] == "no near-duplicate passages found"


def test_empty_corpus_is_non_alarming():
    res = overlap.near_duplicate_passages("Some text here about anything at all.", [])
    assert res["findings"] == []
    assert "no other library papers" in res["summary"]["text"]


def test_threshold_gates_findings():
    target = "Our intro. " + _SHARED
    corpus = [("arxiv:other", "Prior. " + _SHARED)]
    hi = overlap.near_duplicate_passages(target, corpus, threshold=0.99, min_shingles=5)
    lo = overlap.near_duplicate_passages(target, corpus, threshold=0.3, min_shingles=5)
    assert len(lo["findings"]) >= len(hi["findings"])


# --- external seam: consent + provider gates -------------------------------

class _FakeProvider:
    name = "fake"

    def __init__(self):
        self.calls = 0

    def check(self, text):
        self.calls += 1
        return [{"source": "example.com/x", "score": 0.9}]


def test_external_disabled_without_provider():
    res = overlap.check_external("some text", provider=None, consent=True)
    assert res["enabled"] is False
    assert "no external" in res["reason"]


def test_external_never_calls_provider_without_consent():
    prov = _FakeProvider()
    res = overlap.check_external("some text", provider=prov, consent=False)
    assert res["enabled"] is False
    assert prov.calls == 0  # privacy: nothing sent


def test_external_runs_only_with_provider_and_consent():
    prov = _FakeProvider()
    res = overlap.check_external("some text", provider=prov, consent=True)
    assert res["enabled"] is True
    assert res["provider"] == "fake"
    assert res["matches"] and prov.calls == 1


def test_register_and_clear_global_provider():
    prov = _FakeProvider()
    overlap.register_external_provider(prov)
    try:
        assert overlap.get_external_provider() is prov
        assert overlap.check_external("t", consent=True)["enabled"] is True
    finally:
        overlap.register_external_provider(None)
    assert overlap.get_external_provider() is None
