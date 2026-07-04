# Novelty vs. OpenReview - pilot results (live run, 2026-07-03)

- n = 10 ICLR 2025 papers (all agent runs succeeded)
- Spearman rank agreement: rho = 0.283
- Seeded permutation p-value (two-sided, 10k perms, seed 42): p = 0.416 - not significant

Diagnosis: system scores compress toward 'novel' (4.4-5.0) while human scores spread 2.3-5.0.
The agent matches humans at the top (both human-5.0 papers scored 5.0) but fails to penalize
low-novelty papers when prior-art retrieval misses their true competitors - consistent with the
documented optimism bias of LLM reviewers. Reported honestly as a pilot null; see paper Section 5.

| paper_id | system | human | ok |
|---|---|---|---|
| arxiv:2410.04209 | 5.00 | 3.667 | True |
| arxiv:2406.05946 | 5.00 | 5.0 | True |
| arxiv:2406.05565 | 4.45 | 4.333 | True |
| arxiv:2502.12456 | 5.00 | 5.0 | True |
| arxiv:2406.16232 | 5.00 | 2.333 | True |
| arxiv:2410.14581 | 4.73 | 3.667 | True |
| arxiv:2410.22069 | 4.44 | 2.333 | True |
| arxiv:2504.11457 | 4.73 | 3.667 | True |
| arxiv:2404.00578 | 4.44 | 3.667 | True |
| arxiv:2411.09361 | 5.00 | 3.667 | True |
