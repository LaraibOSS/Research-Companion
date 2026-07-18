"""Backend resolver + embed_sections_with core (all offline; fake embedders)."""
import research_companion.embed as embed_mod
from research_companion.embed import embed_sections_with, resolve_embedder


def _fake_embed(texts):
    # deterministic 4-dim vector derived from text length
    return [[float(len(t)), 1.0, 0.0, 0.0] for t in texts]


class _FakeST:
    """Stands in for a loaded SentenceTransformer model."""
    def encode(self, texts):
        return [[1.0, 2.0, 3.0] for _ in texts]


def test_resolve_embedder_prefers_local(monkeypatch):
    monkeypatch.setattr(embed_mod, "_load_local_model", lambda model: _FakeST())
    resolved = resolve_embedder(model="m", allow_remote=False)
    assert resolved is not None
    embed_fn, label = resolved
    assert label == "local"
    assert embed_fn(["a", "b"]) == [[1.0, 2.0, 3.0], [1.0, 2.0, 3.0]]


def test_resolve_embedder_none_without_local_or_consent(monkeypatch):
    monkeypatch.setattr(embed_mod, "_load_local_model", lambda model: None)
    monkeypatch.setenv("HF_TOKEN", "tok")
    assert resolve_embedder(model="m", allow_remote=False) is None


def test_resolve_embedder_remote_needs_consent_and_token(monkeypatch):
    monkeypatch.setattr(embed_mod, "_load_local_model", lambda model: None)
    monkeypatch.delenv("HF_TOKEN", raising=False)
    assert resolve_embedder(model="m", allow_remote=True) is None  # no token
    resolved = resolve_embedder(model="m", allow_remote=True, token="tok")
    assert resolved is not None and resolved[1] == "remote"


def test_local_model_load_failure_is_none(monkeypatch):
    def _boom(model):
        raise RuntimeError("corrupt weights")
    monkeypatch.setattr(embed_mod, "_load_local_model", _boom)
    monkeypatch.delenv("HF_TOKEN", raising=False)
    assert resolve_embedder(model="m", allow_remote=False) is None


def test_embed_sections_with_caches_and_returns_payload(tmp_path, monkeypatch):
    calls = []

    def _counting_embed(texts):
        calls.append(list(texts))
        return _fake_embed(texts)

    units = [{"section_id": "s1", "chunk_index": 0, "text": "hello world"},
             {"section_id": "s1", "chunk_index": 1, "text": "second chunk"}]
    monkeypatch.setattr("research_companion.qa.build_section_index",
                        lambda pids: list(units))

    saved = {}
    monkeypatch.setattr("research_companion.store.save_embeddings",
                        lambda pid, payload: saved.update({pid: payload}) or tmp_path)
    monkeypatch.setattr("research_companion.store.load_embeddings",
                        lambda pid, embed_model=None: saved.get(pid))

    payload = embed_sections_with("p1", embed_fn=_counting_embed, embed_model="m")
    assert payload["embed_model"] == "m"
    assert set(payload["vectors"]) == {"s1#0", "s1#1"}
    assert len(calls) == 1  # one batched call

    # second run: everything cached -> embed_fn not called again
    payload2 = embed_sections_with("p1", embed_fn=_counting_embed, embed_model="m")
    assert len(calls) == 1
    assert payload2["vectors"] == payload["vectors"]


def test_embed_paper_sections_still_none_without_token(monkeypatch):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    from research_companion.embed import embed_paper_sections
    assert embed_paper_sections("p-any") is None
