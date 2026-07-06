"""Hugging Face Inference API embeddings with per-section vector cache.

Provides optional semantic embeddings WITHOUT local model downloads.  When no
HF token is available the public API of this module gracefully degrades:
``embed_paper_sections`` returns ``None`` and callers fall back to BM25.

Usage::

    from research_companion.embed import embed_paper_sections
    payload = embed_paper_sections("arxiv:2410.05779", token="hf-...")
    # payload is None when HF_TOKEN is absent; dict otherwise.
"""
from __future__ import annotations

import hashlib
import os
import time
from collections.abc import Callable
from typing import Any

DEFAULT_EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"  # 384-dim
HF_EMBED_URL = (
    "https://router.huggingface.co/hf-inference/models/{model}/pipeline/feature-extraction"
)

# Retry delays (seconds) for 429 / 503 responses.
_RETRY_DELAYS = [0.5, 1.0, 2.0, 4.0]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class EmbedError(RuntimeError):
    """Raised when the HF Inference API call fails or shape validation fails."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _mean_pool(matrix: list[list[float]]) -> list[float]:
    """Average a 2-D token matrix (rows=tokens, cols=dims) to a single vector."""
    if not matrix or not isinstance(matrix[0], list):
        raise EmbedError(f"_mean_pool: expected list-of-lists, got {type(matrix[0])!r}")
    n = len(matrix)
    dim = len(matrix[0])
    out = [0.0] * dim
    for row in matrix:
        for j, v in enumerate(row):
            out[j] += v
    return [v / n for v in out]


def _default_post(url: str, headers: dict, json_body: Any, timeout: float):
    """Default HTTP POST using httpx (synchronous). Returns (status, body)."""
    import httpx  # lazy import — not required for tests that inject post
    resp = httpx.post(url, headers=headers, json=json_body, timeout=timeout)
    try:
        body = resp.json()
    except Exception:
        body = resp.text
    return resp.status_code, body


def _normalize_response(raw_output: Any, n_inputs: int) -> list[list[float]]:
    """Turn the raw API output into exactly n_inputs flat float vectors.

    Handles two shapes returned by the HF feature-extraction pipeline:
    * Sentence-level: list of 1-D vectors  — [[f, …], [f, …], …]
    * Token-level:    list of 2-D matrices — [[[f,…],…], [[f,…],…], …]
    """
    if not isinstance(raw_output, list):
        raise EmbedError(f"Expected list from API, got {type(raw_output).__name__}")

    if len(raw_output) != n_inputs:
        raise EmbedError(
            f"API returned {len(raw_output)} vectors for {n_inputs} inputs"
        )

    out: list[list[float]] = []
    for i, item in enumerate(raw_output):
        if not isinstance(item, list):
            raise EmbedError(f"Item {i} from API is not a list: {type(item).__name__!r}")

        if len(item) == 0:
            raise EmbedError(f"Item {i} from API is empty")

        # Check if it's a 1-D vector (list of floats/ints)
        if isinstance(item[0], (int, float)):
            out.append([float(v) for v in item])
        # Check if it's a 2-D matrix (list of lists)
        elif isinstance(item[0], list):
            out.append(_mean_pool(item))
        else:
            raise EmbedError(
                f"Item {i}: first element is {type(item[0]).__name__!r}, "
                "expected float or list (token matrix)"
            )

    return out


# ---------------------------------------------------------------------------
# Core embedding function
# ---------------------------------------------------------------------------

def hf_embed(
    texts: list[str],
    *,
    model: str = DEFAULT_EMBED_MODEL,
    token: str | None = None,
    post: Callable | None = None,
    batch_size: int = 32,
    max_retries: int = 4,
    timeout: float = 30.0,
    sleep: Callable = time.sleep,
) -> list[list[float]]:
    """Embed *texts* using the HF Inference API.

    Parameters
    ----------
    texts:
        Input strings to embed.  Empty list returns ``[]`` without network.
    model:
        HF model ID.
    token:
        Bearer token.  Falls back to ``os.environ.get("HF_TOKEN")``.
        If still absent, raises ``EmbedError``.
    post:
        Injectable seam: ``post(url, headers, json_body, timeout) -> (status, body)``.
        Defaults to an httpx wrapper.
    batch_size:
        Number of texts per API call.
    max_retries:
        Maximum number of retries for 429 / 503 responses.
    timeout:
        Per-request timeout in seconds.
    sleep:
        Injectable sleep function (``time.sleep`` by default); called with the
        delay between retries.

    Returns
    -------
    list[list[float]]
        One vector per input text, in order.

    Raises
    ------
    EmbedError
        On auth failure, unrecoverable HTTP error, exhausted retries, or
        unexpected response shape.
    """
    if token is None:
        token = os.environ.get("HF_TOKEN")
    if not token:
        raise EmbedError("No HF token provided and HF_TOKEN environment variable is not set")

    if not texts:
        return []

    if post is None:
        post = _default_post

    url = HF_EMBED_URL.format(model=model)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    results: list[list[float]] = []

    for batch_start in range(0, len(texts), batch_size):
        batch = texts[batch_start : batch_start + batch_size]
        attempt = 0
        while True:
            status, body = post(url, headers, {"inputs": batch}, timeout)

            if status == 200:
                vectors = _normalize_response(body, len(batch))
                results.extend(vectors)
                break

            # Retryable statuses
            if status in (429, 503):
                if attempt >= max_retries:
                    raise EmbedError(
                        f"HF API returned {status} after {max_retries} retries"
                    )
                delay = _RETRY_DELAYS[attempt] if attempt < len(_RETRY_DELAYS) else _RETRY_DELAYS[-1]
                sleep(delay)
                attempt += 1
                continue

            # Non-retryable error
            body_str = str(body)[:200]
            raise EmbedError(
                f"HF API returned HTTP {status}: {body_str}"
            )

    return results


# ---------------------------------------------------------------------------
# embed_paper_sections
# ---------------------------------------------------------------------------

def embed_paper_sections(
    paper_id: str,
    *,
    model: str = DEFAULT_EMBED_MODEL,
    token: str | None = None,
    post: Callable | None = None,
) -> dict | None:
    """Embed all non-boilerplate sections of *paper_id* and cache results.

    Returns ``None`` (without error, without writing) when no HF token is
    available — callers should fall back to BM25.

    Returns the embeddings payload dict on success.
    """
    # Graceful degradation: no token -> None
    resolved_token = token if token is not None else os.environ.get("HF_TOKEN")
    if not resolved_token:
        return None

    from research_companion import qa  # lazy to avoid circular imports
    from research_companion.store import load_embeddings, save_embeddings

    # Build section units
    units = qa.build_section_index([paper_id])
    if not units:
        return None

    # Load cached embeddings for this model
    cached = load_embeddings(paper_id, embed_model=model)
    cached_vectors: dict = {}
    if cached is not None:
        cached_vectors = cached.get("vectors", {})

    # Determine which sections need (re-)embedding
    to_embed: list[tuple[str, str, str]] = []  # (section_id, text, sha256)
    for unit in units:
        section_id = unit["section_id"]
        text = unit.get("text", "")
        text_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()

        cached_entry = cached_vectors.get(section_id)
        if cached_entry and cached_entry.get("text_sha256") == text_sha:
            # Cache hit — reuse
            continue
        to_embed.append((section_id, text, text_sha))

    # Build merged vectors dict starting from cache
    merged: dict[str, dict] = dict(cached_vectors)

    if to_embed:
        texts_to_send = [t for _, t, _ in to_embed]
        vectors = hf_embed(
            texts_to_send,
            model=model,
            token=resolved_token,
            post=post,
        )
        for (section_id, _text, text_sha), vector in zip(to_embed, vectors, strict=True):
            merged[section_id] = {
                "text_sha256": text_sha,
                "vector": vector,
            }

    payload: dict = {
        "embed_model": model,
        "vectors": merged,
    }
    save_embeddings(paper_id, payload)
    return payload
