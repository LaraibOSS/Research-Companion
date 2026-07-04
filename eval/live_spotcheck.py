"""Live-API citation spot check: real references vs. real CrossRef/OpenAlex.

Every input reference below is a real, published, widely-cited paper, cited the
way our parser emits references (title, optionally a correct arXiv id). Because
all inputs are genuine, any `suspect` or `unverified` verdict from the live
pipeline is a measured FIELD FALSE POSITIVE. This complements the offline
corruption benchmark (eval/results/citation_pr.*), whose precision is at
ceiling by construction: here nothing is an oracle, everything is live.

Run (network required, no LLM):  python eval/live_spotcheck.py [out_dir]
Writes: <out_dir>/live_spotcheck.json + .md   (default: eval/results)

Note: results depend on live API state and network; this is a field
measurement, not a seeded benchmark.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from research_companion.refcheck.retrieval import default_lookup
from research_companion.refcheck.validate import Reference, validate_bibliography

# (title, arxiv_id or None) — all real.
REAL_REFERENCES: list[tuple[str, str | None]] = [
    ("Attention Is All You Need", "1706.03762"),
    ("BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding", "1810.04805"),
    ("Language Models are Few-Shot Learners", "2005.14165"),
    ("RoBERTa: A Robustly Optimized BERT Pretraining Approach", "1907.11692"),
    ("Exploring the Limits of Transfer Learning with a Unified Text-to-Text Transformer", "1910.10683"),
    ("ELECTRA: Pre-training Text Encoders as Discriminators Rather Than Generators", "2003.10555"),
    ("XLNet: Generalized Autoregressive Pretraining for Language Understanding", "1906.08237"),
    ("ALBERT: A Lite BERT for Self-supervised Learning of Language Representations", "1909.11942"),
    ("DistilBERT, a distilled version of BERT: smaller, faster, cheaper and lighter", "1910.01108"),
    ("BART: Denoising Sequence-to-Sequence Pre-training for Natural Language Generation, Translation, and Comprehension", "1910.13461"),
    ("Transformer-XL: Attentive Language Models Beyond a Fixed-Length Context", "1901.02860"),
    ("Longformer: The Long-Document Transformer", "2004.05150"),
    ("Big Bird: Transformers for Longer Sequences", "2007.14062"),
    ("Reformer: The Efficient Transformer", "2001.04451"),
    ("Sentence-BERT: Sentence Embeddings using Siamese BERT-Networks", "1908.10084"),
    ("SimCSE: Simple Contrastive Learning of Sentence Embeddings", "2104.08821"),
    ("Dense Passage Retrieval for Open-Domain Question Answering", "2004.04906"),
    ("REALM: Retrieval-Augmented Language Model Pre-Training", "2002.08909"),
    ("Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks", "2005.11401"),
    ("Leveraging Passage Retrieval with Generative Models for Open Domain Question Answering", "2007.01282"),
    ("ColBERT: Efficient and Effective Passage Search via Contextualized Late Interaction over BERT", "2004.12832"),
    ("Chain-of-Thought Prompting Elicits Reasoning in Large Language Models", "2201.11903"),
    ("Self-Consistency Improves Chain of Thought Reasoning in Language Models", "2203.11171"),
    ("Training language models to follow instructions with human feedback", "2203.02155"),
    ("LLaMA: Open and Efficient Foundation Language Models", "2302.13971"),
    ("Llama 2: Open Foundation and Fine-Tuned Chat Models", "2307.09288"),
    ("Training Compute-Optimal Large Language Models", "2203.15556"),
    ("PaLM: Scaling Language Modeling with Pathways", "2204.02311"),
    ("Scaling Instruction-Finetuned Language Models", "2210.11416"),
    ("LoRA: Low-Rank Adaptation of Large Language Models", "2106.09685"),
    ("QLoRA: Efficient Finetuning of Quantized LLMs", "2305.14314"),
    ("Adam: A Method for Stochastic Optimization", "1412.6980"),
    ("Deep Residual Learning for Image Recognition", "1512.03385"),
    ("Very Deep Convolutional Networks for Large-Scale Image Recognition", "1409.1556"),
    ("Generative Adversarial Nets", None),
    ("Auto-Encoding Variational Bayes", "1312.6114"),
    ("Efficient Estimation of Word Representations in Vector Space", "1301.3781"),
    ("GloVe: Global Vectors for Word Representation", None),
    ("Deep contextualized word representations", "1802.05365"),
    ("Sequence to Sequence Learning with Neural Networks", "1409.3215"),
    ("Neural Machine Translation by Jointly Learning to Align and Translate", "1409.0473"),
    ("BLEU: a Method for Automatic Evaluation of Machine Translation", None),
    ("Learning Transferable Visual Models From Natural Language Supervision", "2103.00020"),
    ("An Image is Worth 16x16 Words: Transformers for Image Recognition at Scale", "2010.11929"),
    ("Denoising Diffusion Probabilistic Models", "2006.11239"),
    ("HotpotQA: A Dataset for Diverse, Explainable Multi-hop Question Answering", "1809.09600"),
    ("SQuAD: 100,000+ Questions for Machine Comprehension of Text", "1606.05250"),
    ("GLUE: A Multi-Task Benchmark and Analysis Platform for Natural Language Understanding", "1804.07461"),
    ("SuperGLUE: A Stickier Benchmark for General-Purpose Language Understanding Systems", "1905.00537"),
    ("Batch Normalization: Accelerating Deep Network Training by Reducing Internal Covariate Shift", "1502.03167"),
    ("Layer Normalization", "1607.06450"),
    ("Dropout: A Simple Way to Prevent Neural Networks from Overfitting", None),
    ("From Local to Global: A Graph RAG Approach to Query-Focused Summarization", "2404.16130"),
    ("Emergent Abilities of Large Language Models", "2206.07682"),
    ("Holistic Evaluation of Language Models", "2211.09110"),
]


def run(out_dir: str = "eval/results") -> dict:
    refs = [Reference(title=t, arxiv_id=a) for t, a in REAL_REFERENCES]
    lookup = default_lookup()
    t0 = time.perf_counter()
    report = validate_bibliography(refs, lookup)
    elapsed = time.perf_counter() - t0

    counts = report.counts()
    n = len(report.entries)
    false_positives = [
        {"title": ref.title, "status": v.status, "reasons": v.reasons}
        for ref, v in report.entries if v.status != "verified"
    ]
    result = {
        "n_references": n,
        "counts": counts,
        "field_false_positive_rate": round(len(false_positives) / n, 4),
        "elapsed_seconds": round(elapsed, 1),
        "false_positives": false_positives,
        "note": "All inputs are real published papers; any non-verified verdict is a field false positive. Live CrossRef->OpenAlex; results depend on API state at run time.",
    }

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "live_spotcheck.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    md = ["# Live-API citation spot check", "",
          f"- References (all real): {n}",
          f"- Verified: {counts['verified']}  |  Suspect: {counts['suspect']}  |  Unverified: {counts['unverified']}",
          f"- Field false-positive rate: {result['field_false_positive_rate']:.2%}",
          f"- Wall time: {elapsed:.1f}s (live CrossRef->OpenAlex)", ""]
    if false_positives:
        md.append("## False positives")
        for fp in false_positives:
            md.append(f"- [{fp['status']}] {fp['title']} - {'; '.join(fp['reasons'])}")
    (out / "live_spotcheck.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    res = run(sys.argv[1] if len(sys.argv) > 1 else "eval/results")
    print(json.dumps({k: v for k, v in res.items() if k != "false_positives"}, indent=2))
    for fp in res["false_positives"]:
        print(f"  FP [{fp['status']}] {fp['title'][:70]} :: {'; '.join(fp['reasons'])[:80]}")
