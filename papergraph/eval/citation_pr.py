"""Citation precision/recall evaluation harness.

Builds a labeled benchmark from 40 synthetic ML-paper-style reference records,
applies seeded corruptions, runs the refcheck validator, and computes P/R/F1.

Run:
    python -m papergraph.eval.citation_pr
"""
from __future__ import annotations

import json
import random
from pathlib import Path

from papergraph.refcheck.matching import title_similarity
from papergraph.refcheck.validate import Reference, validate_bibliography

# ---------------------------------------------------------------------------
# GOLD: 40 deterministic reference records
# ---------------------------------------------------------------------------

GOLD: list[dict] = [
    {
        "title": "Attention Is All You Need",
        "authors": ["Ashish Vaswani", "Noam Shazeer", "Niki Parmar"],
        "year": 2017,
        "doi": "10.5555/3295222.3295349",
        "arxiv_id": "1706.03762",
    },
    {
        "title": "Deep Residual Learning for Image Recognition",
        "authors": ["Kaiming He", "Xiangyu Zhang", "Shaoqing Ren"],
        "year": 2016,
        "doi": "10.1109/cvpr.2016.90",
        "arxiv_id": "1512.03385",
    },
    {
        "title": "BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding",
        "authors": ["Jacob Devlin", "Ming-Wei Chang", "Kenton Lee"],
        "year": 2019,
        "doi": "10.18653/v1/n19-1423",
        "arxiv_id": "1810.04805",
    },
    {
        "title": "Generative Adversarial Nets",
        "authors": ["Ian Goodfellow", "Jean Pouget-Abadie", "Mehdi Mirza"],
        "year": 2014,
        "doi": "10.5555/2969033.2969125",
        "arxiv_id": "1406.2661",
    },
    {
        "title": "Dropout: A Simple Way to Prevent Neural Networks from Overfitting",
        "authors": ["Nitish Srivastava", "Geoffrey Hinton", "Alex Krizhevsky"],
        "year": 2014,
        "doi": "10.5555/2627435.2670313",
        "arxiv_id": None,
    },
    {
        "title": "Adam: A Method for Stochastic Optimization",
        "authors": ["Diederik P. Kingma", "Jimmy Ba"],
        "year": 2015,
        "doi": "10.48550/arXiv.1412.6980",
        "arxiv_id": "1412.6980",
    },
    {
        "title": "ImageNet Large Scale Visual Recognition Challenge",
        "authors": ["Olga Russakovsky", "Jia Deng", "Hao Su"],
        "year": 2015,
        "doi": "10.1007/s11263-015-0816-y",
        "arxiv_id": "1409.0575",
    },
    {
        "title": "Batch Normalization: Accelerating Deep Network Training by Reducing Internal Covariate Shift",
        "authors": ["Sergey Ioffe", "Christian Szegedy"],
        "year": 2015,
        "doi": "10.5555/3045118.3045167",
        "arxiv_id": "1502.03167",
    },
    {
        "title": "Long Short-Term Memory",
        "authors": ["Sepp Hochreiter", "Juergen Schmidhuber"],
        "year": 1997,
        "doi": "10.1162/neco.1997.9.8.1735",
        "arxiv_id": None,
    },
    {
        "title": "Sequence to Sequence Learning with Neural Networks",
        "authors": ["Ilya Sutskever", "Oriol Vinyals", "Quoc V. Le"],
        "year": 2014,
        "doi": "10.5555/2969033.2969173",
        "arxiv_id": "1409.3215",
    },
    {
        "title": "Playing Atari with Deep Reinforcement Learning",
        "authors": ["Volodymyr Mnih", "Koray Kavukcuoglu", "David Silver"],
        "year": 2013,
        "doi": "10.48550/arXiv.1312.5602",
        "arxiv_id": "1312.5602",
    },
    {
        "title": "Neural Machine Translation by Jointly Learning to Align and Translate",
        "authors": ["Dzmitry Bahdanau", "Kyunghyun Cho", "Yoshua Bengio"],
        "year": 2015,
        "doi": "10.48550/arXiv.1409.0473",
        "arxiv_id": "1409.0473",
    },
    {
        "title": "Very Deep Convolutional Networks for Large-Scale Image Recognition",
        "authors": ["Karen Simonyan", "Andrew Zisserman"],
        "year": 2015,
        "doi": "10.48550/arXiv.1409.1556",
        "arxiv_id": "1409.1556",
    },
    {
        "title": "Going Deeper with Convolutions",
        "authors": ["Christian Szegedy", "Wei Liu", "Yangqing Jia"],
        "year": 2015,
        "doi": "10.1109/cvpr.2015.7298594",
        "arxiv_id": "1409.4842",
    },
    {
        "title": "Mastering the Game of Go with Deep Neural Networks and Tree Search",
        "authors": ["David Silver", "Aja Huang", "Chris J. Maddison"],
        "year": 2016,
        "doi": "10.1038/nature16961",
        "arxiv_id": None,
    },
    {
        "title": "Fully Convolutional Networks for Semantic Segmentation",
        "authors": ["Jonathan Long", "Evan Shelhamer", "Trevor Darrell"],
        "year": 2015,
        "doi": "10.1109/cvpr.2015.7298965",
        "arxiv_id": "1411.4038",
    },
    {
        "title": "You Only Look Once: Unified, Real-Time Object Detection",
        "authors": ["Joseph Redmon", "Santosh Divvala", "Ross Girshick"],
        "year": 2016,
        "doi": "10.1109/cvpr.2016.91",
        "arxiv_id": "1506.02640",
    },
    {
        "title": "Faster R-CNN: Towards Real-Time Object Detection with Region Proposal Networks",
        "authors": ["Shaoqing Ren", "Kaiming He", "Ross Girshick"],
        "year": 2015,
        "doi": "10.1109/tpami.2016.2577031",
        "arxiv_id": "1506.01497",
    },
    {
        "title": "Variational Autoencoders for Disentangled Representation Learning",
        "authors": ["Irina Higgins", "Loic Matthey", "Arka Pal"],
        "year": 2017,
        "doi": "10.48550/arXiv.1606.05579",
        "arxiv_id": "1606.05579",
    },
    {
        "title": "Deep Learning on Graphs: A Survey",
        "authors": ["Ziwei Zhang", "Peng Cui", "Wenwu Zhu"],
        "year": 2020,
        "doi": "10.1109/tkde.2020.2981333",
        "arxiv_id": "1812.04202",
    },
    {
        "title": "Semi-Supervised Classification with Graph Convolutional Networks",
        "authors": ["Thomas N. Kipf", "Max Welling"],
        "year": 2017,
        "doi": "10.48550/arXiv.1609.02907",
        "arxiv_id": "1609.02907",
    },
    {
        "title": "Graph Attention Networks",
        "authors": ["Petar Velickovic", "Guillem Cucurull", "Arantxa Casanova"],
        "year": 2018,
        "doi": "10.48550/arXiv.1710.10903",
        "arxiv_id": "1710.10903",
    },
    {
        "title": "Convolutional Neural Networks on Graphs with Fast Localized Spectral Filtering",
        "authors": ["Michaël Defferrard", "Xavier Bresson", "Pierre Vandergheynst"],
        "year": 2016,
        "doi": "10.5555/3157382.3157527",
        "arxiv_id": "1606.09375",
    },
    {
        "title": "Deep Graph Infomax",
        "authors": ["Petar Velickovic", "William Fedus", "William L. Hamilton"],
        "year": 2019,
        "doi": "10.48550/arXiv.1809.10341",
        "arxiv_id": "1809.10341",
    },
    {
        "title": "Contrastive Multiview Coding",
        "authors": ["Yonglong Tian", "Dilip Krishnan", "Phillip Isola"],
        "year": 2020,
        "doi": "10.48550/arXiv.1906.05849",
        "arxiv_id": "1906.05849",
    },
    {
        "title": "A Simple Framework for Contrastive Learning of Visual Representations",
        "authors": ["Ting Chen", "Simon Kornblith", "Mohammad Norouzi"],
        "year": 2020,
        "doi": "10.48550/arXiv.2002.05709",
        "arxiv_id": "2002.05709",
    },
    {
        "title": "Momentum Contrast for Unsupervised Visual Representation Learning",
        "authors": ["Kaiming He", "Haoqi Fan", "Yuxin Wu"],
        "year": 2020,
        "doi": "10.48550/arXiv.1911.05722",
        "arxiv_id": "1911.05722",
    },
    {
        "title": "Bootstrap Your Own Latent: A New Approach to Self-Supervised Learning",
        "authors": ["Jean-Bastien Grill", "Florian Strub", "Florent Altche"],
        "year": 2020,
        "doi": "10.48550/arXiv.2006.07733",
        "arxiv_id": "2006.07733",
    },
    {
        "title": "Language Models are Few-Shot Learners",
        "authors": ["Tom B. Brown", "Benjamin Mann", "Nick Ryder"],
        "year": 2020,
        "doi": "10.48550/arXiv.2005.14165",
        "arxiv_id": "2005.14165",
    },
    {
        "title": "Exploring the Limits of Transfer Learning with a Unified Text-to-Text Transformer",
        "authors": ["Colin Raffel", "Noam Shazeer", "Adam Roberts"],
        "year": 2020,
        "doi": "10.5555/3455716.3455856",
        "arxiv_id": "1910.10683",
    },
    {
        "title": "Roberta: A Robustly Optimized BERT Pretraining Approach",
        "authors": ["Yinhan Liu", "Myle Ott", "Naman Goyal"],
        "year": 2019,
        "doi": "10.48550/arXiv.1907.11692",
        "arxiv_id": "1907.11692",
    },
    {
        "title": "XLNet: Generalized Autoregressive Pretraining for Language Understanding",
        "authors": ["Zhilin Yang", "Zihang Dai", "Yiming Yang"],
        "year": 2019,
        "doi": "10.48550/arXiv.1906.08237",
        "arxiv_id": "1906.08237",
    },
    {
        "title": "Transformer-XL: Attentive Language Models Beyond a Fixed-Length Context",
        "authors": ["Zihang Dai", "Zhilin Yang", "Yiming Yang"],
        "year": 2019,
        "doi": "10.48550/arXiv.1901.02860",
        "arxiv_id": "1901.02860",
    },
    {
        "title": "An Image is Worth 16x16 Words: Transformers for Image Recognition at Scale",
        "authors": ["Alexey Dosovitskiy", "Lucas Beyer", "Alexander Kolesnikov"],
        "year": 2021,
        "doi": "10.48550/arXiv.2010.11929",
        "arxiv_id": "2010.11929",
    },
    {
        "title": "Training Data-Efficient Image Transformers and Distillation Through Attention",
        "authors": ["Hugo Touvron", "Matthieu Cord", "Matthijs Douze"],
        "year": 2021,
        "doi": "10.48550/arXiv.2012.12877",
        "arxiv_id": "2012.12877",
    },
    {
        "title": "Denoising Diffusion Probabilistic Models",
        "authors": ["Jonathan Ho", "Ajay Jain", "Pieter Abbeel"],
        "year": 2020,
        "doi": "10.48550/arXiv.2006.11239",
        "arxiv_id": "2006.11239",
    },
    {
        "title": "Score-Based Generative Modeling Through Stochastic Differential Equations",
        "authors": ["Yang Song", "Jascha Sohl-Dickstein", "Diederik P. Kingma"],
        "year": 2021,
        "doi": "10.48550/arXiv.2011.13456",
        "arxiv_id": "2011.13456",
    },
    {
        "title": "Implicit Neural Representations with Periodic Activation Functions",
        "authors": ["Vincent Sitzmann", "Julien N. P. Martel", "Alexander W. Bergman"],
        "year": 2020,
        "doi": "10.48550/arXiv.2006.09661",
        "arxiv_id": "2006.09661",
    },
    {
        "title": "Neural Radiance Fields for View Synthesis",
        "authors": ["Ben Mildenhall", "Pratul P. Srinivasan", "Matthew Tancik"],
        "year": 2020,
        "doi": "10.48550/arXiv.2003.08934",
        "arxiv_id": "2003.08934",
    },
    {
        "title": "Zero-Shot Text-to-Image Generation",
        "authors": ["Aditya Ramesh", "Mikhail Pavlov", "Gabriel Goh"],
        "year": 2021,
        "doi": "10.48550/arXiv.2102.12092",
        "arxiv_id": "2102.12092",
    },
]

assert len(GOLD) == 40, f"GOLD must have exactly 40 records, got {len(GOLD)}"

# Nonsense word bank for fabricated title generation (deterministic via rng)
_NONSENSE_WORDS = [
    "splork", "frimbulant", "zathoric", "quendex", "voplasmic",
    "trixelwave", "murnifold", "glaxxon", "sneldric", "pruvomatic",
    "crumblaxe", "stovenic", "brelwick", "flindrix", "quovantum",
    "zelphatic", "morbiflex", "trundaxic", "swiveloid", "glumdrop",
]


def _make_fabricated_title(rng: random.Random) -> str:
    """Generate a nonsense title that won't match any real record."""
    words = rng.sample(_NONSENSE_WORDS, k=rng.randint(4, 7))
    return " ".join(w.capitalize() for w in words)


def _shuffle_doi(doi: str, rng: random.Random) -> str:
    """Shuffle the digit characters in a DOI, keeping non-digits in place."""
    chars = list(doi)
    digit_indices = [i for i, c in enumerate(chars) if c.isdigit()]
    digits = [chars[i] for i in digit_indices]
    rng.shuffle(digits)
    for i, idx in enumerate(digit_indices):
        chars[idx] = digits[i]
    result = "".join(chars)
    # Ensure it actually changed (if all digits same, force a change)
    if result == doi and digit_indices:
        chars[digit_indices[0]] = str((int(chars[digit_indices[0]]) + 1) % 10)
        result = "".join(chars)
    return result


# ---------------------------------------------------------------------------
# corrupt()
# ---------------------------------------------------------------------------

_CORRUPTION_TYPES = ["fabricated", "wrong_doi", "author_swap"]


def corrupt(
    records: list[dict], rng: random.Random
) -> list[tuple[Reference, str]]:
    """From GOLD, build a labeled set.

    For every record emit:
    - one clean Reference with label "clean"
    - with 50% probability (per-record coin flip), one corrupted variant with
      label from _CORRUPTION_TYPES (round-robin cycling).

    Returns a list of (Reference, label) tuples.
    """
    result: list[tuple[Reference, str]] = []
    corruption_cycle = 0

    for rec in records:
        # Clean copy
        clean_ref = Reference(
            title=rec["title"],
            authors=list(rec["authors"]),
            year=rec["year"],
            doi=rec.get("doi"),
            arxiv_id=rec.get("arxiv_id"),
        )
        result.append((clean_ref, "clean"))

        # 50% coin flip → add a corrupted variant
        if rng.random() < 0.5:
            ctype = _CORRUPTION_TYPES[corruption_cycle % len(_CORRUPTION_TYPES)]
            corruption_cycle += 1

            if ctype == "fabricated":
                corrupt_ref = Reference(
                    title=_make_fabricated_title(rng),
                    authors=list(rec["authors"]),
                    year=rec["year"],
                    doi=rec.get("doi"),
                    arxiv_id=rec.get("arxiv_id"),
                )

            elif ctype == "wrong_doi":
                # Keep title and authors intact; only corrupt the DOI
                original_doi = rec.get("doi") or "10.9999/000000"
                corrupt_ref = Reference(
                    title=rec["title"],
                    authors=list(rec["authors"]),
                    year=rec["year"],
                    doi=_shuffle_doi(original_doi, rng),
                    arxiv_id=rec.get("arxiv_id"),
                )

            else:  # author_swap
                # Replace authors with those from a different random record,
                # excluding donors that share any surname with the target.
                def _surnames(authors: list[str]) -> set[str]:
                    return {a.split()[-1].lower() for a in authors if a.split()}

                target_surnames = _surnames(rec["authors"])
                valid_donors = [
                    r for r in records
                    if r is not rec and not (_surnames(r["authors"]) & target_surnames)
                ]
                if not valid_donors:
                    # No valid surname-disjoint donor — fall back to fabricated title
                    corrupt_ref = Reference(
                        title=_make_fabricated_title(rng),
                        authors=list(rec["authors"]),
                        year=rec["year"],
                        doi=rec.get("doi"),
                        arxiv_id=rec.get("arxiv_id"),
                    )
                else:
                    other = rng.choice(valid_donors)
                    corrupt_ref = Reference(
                        title=rec["title"],
                        authors=list(other["authors"]),
                        year=rec["year"],
                        doi=rec.get("doi"),
                        arxiv_id=rec.get("arxiv_id"),
                    )

            result.append((corrupt_ref, ctype))

    return result


# ---------------------------------------------------------------------------
# Lookup: in-memory best-title-match over GOLD (mirrors _db_lookup in tests)
# ---------------------------------------------------------------------------

def _gold_lookup(ref: Reference) -> dict | None:
    """Resolve a Reference to the best title-matching GOLD record (floor 0.7)."""
    best: dict | None = None
    best_score = -1.0
    for record in GOLD:
        score = title_similarity(ref.title, record["title"])
        if score > best_score:
            best, best_score = record, score
    return best if best_score >= 0.7 else None


# ---------------------------------------------------------------------------
# Metrics helpers
# ---------------------------------------------------------------------------

def _f1(precision: float, recall: float) -> float:
    if precision + recall == 0.0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def _compute_metrics(
    pairs: list[tuple[Reference, str]]
) -> dict:
    """Compute P/R/F1 overall and per corruption type.

    Positive class = "corrupted" (label != 'clean').
    Prediction = "flagged" when refcheck status != 'verified'.
    """
    report = validate_bibliography(
        [ref for ref, _ in pairs], _gold_lookup
    )

    # Build (label, predicted_corrupted) pairs
    labeled_predictions: list[tuple[str, bool]] = []
    for (_ref, label), (_, verdict) in zip(pairs, report.entries, strict=True):
        predicted_corrupted = verdict.status != "verified"
        labeled_predictions.append((label, predicted_corrupted))

    # Overall metrics
    tp = sum(1 for lbl, pred in labeled_predictions if lbl != "clean" and pred)
    fp = sum(1 for lbl, pred in labeled_predictions if lbl == "clean" and pred)
    fn = sum(1 for lbl, pred in labeled_predictions if lbl != "clean" and not pred)

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0

    overall = {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(_f1(precision, recall), 4),
        "tp": tp,
        "fp": fp,
        "fn": fn,
    }

    # Per corruption type
    per_type: dict[str, dict] = {}
    for ctype in _CORRUPTION_TYPES:
        type_tp = sum(
            1 for lbl, pred in labeled_predictions if lbl == ctype and pred
        )
        type_fn = sum(
            1 for lbl, pred in labeled_predictions if lbl == ctype and not pred
        )
        # FP is shared across all corruptions (from clean examples) — report per-type recall only
        type_recall = type_tp / (type_tp + type_fn) if (type_tp + type_fn) > 0 else 0.0
        per_type[ctype] = {
            "recall": round(type_recall, 4),
            "tp": type_tp,
            "fn": type_fn,
            "total": type_tp + type_fn,
        }

    return {"overall": overall, "per_type": per_type}


# ---------------------------------------------------------------------------
# run_eval()
# ---------------------------------------------------------------------------

def run_eval(seed: int = 42) -> dict:
    """Run the full citation P/R evaluation with a fixed seed.

    Returns a dict with overall metrics and per-corruption-type breakdown.
    """
    rng = random.Random(seed)
    pairs = corrupt(GOLD, rng)
    metrics = _compute_metrics(pairs)

    # Counts summary
    labels = [lbl for _, lbl in pairs]
    metrics["counts"] = {
        "total": len(pairs),
        "clean": labels.count("clean"),
        "corrupted": sum(1 for lbl in labels if lbl != "clean"),
    }
    for ctype in _CORRUPTION_TYPES:
        metrics["counts"][ctype] = labels.count(ctype)

    metrics["seed"] = seed
    return metrics


# ---------------------------------------------------------------------------
# Artifact writer + main()
# ---------------------------------------------------------------------------

def _write_artifacts(result: dict, out_dir: str) -> None:
    """Write citation_pr.json and citation_pr.md to out_dir."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    # JSON
    (out / "citation_pr.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )

    # Markdown table
    ov = result["overall"]
    pt = result["per_type"]
    lines = [
        "# Citation P/R Benchmark Results",
        "",
        f"Seed: {result.get('seed', 42)} | "
        f"Total: {result['counts']['total']} | "
        f"Clean: {result['counts']['clean']} | "
        f"Corrupted: {result['counts']['corrupted']}",
        "",
        "## Overall Metrics",
        "",
        "| Metric | Value |",
        "| ------ | ----- |",
        f"| Precision | {ov['precision']:.4f} |",
        f"| Recall    | {ov['recall']:.4f} |",
        f"| F1        | {ov['f1']:.4f} |",
        f"| TP / FP / FN | {ov['tp']} / {ov['fp']} / {ov['fn']} |",
        "",
        "## Per Corruption Type",
        "",
        "| Type | Recall | TP | FN | Total |",
        "| ---- | ------ | -- | -- | ----- |",
    ]
    for ctype in _CORRUPTION_TYPES:
        row = pt.get(ctype, {})
        lines.append(
            f"| {ctype} | {row.get('recall', 0.0):.4f} | "
            f"{row.get('tp', 0)} | {row.get('fn', 0)} | {row.get('total', 0)} |"
        )
    lines.append("")

    (out / "citation_pr.md").write_text("\n".join(lines), encoding="utf-8")


def _print_table(result: dict) -> None:
    """Print the results table to stdout."""
    ov = result["overall"]
    pt = result["per_type"]
    print("\nCitation P/R Benchmark")
    print("=" * 50)
    print(f"  Precision : {ov['precision']:.4f}")
    print(f"  Recall    : {ov['recall']:.4f}")
    print(f"  F1        : {ov['f1']:.4f}")
    print(f"  TP/FP/FN  : {ov['tp']}/{ov['fp']}/{ov['fn']}")
    print()
    print(f"  {'Type':<14} {'Recall':>8}  {'TP':>4}  {'FN':>4}  {'Total':>5}")
    print("  " + "-" * 42)
    for ctype in _CORRUPTION_TYPES:
        row = pt.get(ctype, {})
        print(
            f"  {ctype:<14} {row.get('recall', 0.0):>8.4f}  "
            f"{row.get('tp', 0):>4}  {row.get('fn', 0):>4}  {row.get('total', 0):>5}"
        )
    print()


def main(out_dir: str = "eval/results") -> None:
    """Run the evaluation, write artifacts, and print the table."""
    result = run_eval(seed=42)
    _write_artifacts(result, out_dir)
    _print_table(result)


if __name__ == "__main__":
    main()
