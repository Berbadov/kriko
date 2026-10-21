# Product search benchmark v2 — 2026-10-21

## Result

The fresh holdout contains 30 original, source-backed questions across shoes, computers, cars, phones and appliances. It balances easy lookups, multi-source jobs and missing-identity cases. Eleven model/search profiles ran each question twice: 660 research attempts, all fully graded by Mercury 3 and Mistral Large 4. A total of 180 attempts passed both judges' fact, citation and scope gates.

The rows below are point estimates, not a production winner. Acceptance intervals overlap broadly. Fact F1 is rubric-weighted answer coverage (credited required facts as true positives; missed facts and judge-confirmed false claims as false positives/negatives), not search-ranking F1. Costs and token counts marked `≥` are lower bounds where providers did not report usage. Costs include failed and rejected attempts.

| Profile | Accepted / 60 | Acceptance 95% CI | Fact F1 [95% CI] | Mean seconds | Known $ / attempt | Known tokens / attempt |
|---|---:|---:|---:|---:|---:|---:|
| Mercury 2.5 · Exa | 25 | 0.28–0.55 | 0.805 [0.71–0.89] | 33.48 | ≥ $0.00918 | ≥ 9,170 |
| Mercury 2.5 · federated | 23 | 0.25–0.52 | 0.826 [0.74–0.90] | 7.57 | ≥ $0.02529 | ≥ 12,613 |
| Mercury 2.5 → Mercury 3 · federated | 23 | 0.25–0.53 | 0.727 [0.62–0.83] | 12.21 | ≥ $0.03541 | ≥ 33,322 |
| Mistral Large 4 · DeepSeek | 20 | 0.20–0.47 | 0.793 [0.68–0.89] | 11.91 | ≥ $0.01656 | ≥ 22,477 |
| Mercury 2.5 · DeepSeek | 19 | 0.20–0.47 | **0.836 [0.76–0.90]** | 7.33 | ≥ $0.00212 | ≥ 11,697 |
| Mercury 2.5 → Mercury 3 · DeepSeek | 19 | 0.18–0.47 | 0.773 [0.68–0.86] | 12.62 | ≥ $0.00535 | ≥ 36,757 |
| Mercury 3 · DeepSeek | 12 | 0.10–0.30 | 0.807 [0.73–0.88] | **6.34** | ≥ $0.00325 | 15,280 |
| Mercury 2.5 · parallel | 11 | 0.08–0.30 | 0.825 [0.73–0.90] | 6.83 | ≥ $0.00210 | ≥ 11,752 |
| Ministral 14B · DeepSeek | 11 | 0.08–0.32 | 0.828 [0.74–0.90] | 8.85 | ≥ $0.00292 | ≥ 8,027 |
| Mercury 2.5 · Tavily | 10 | 0.05–0.30 | 0.392 [0.25–0.53] | 8.76 | ≥ $0.02208 | ≥ 9,742 |
| Ministral 8B · DeepSeek | 7 | 0.03–0.23 | 0.782 [0.69–0.86] | 9.87 | ≥ $0.00351 | ≥ 13,127 |

Mercury 2.5 with DeepSeek had the highest F1 point estimate and the lowest known cost per accepted answer (≥$0.00670), while Mercury 3 with DeepSeek had the lowest mean latency. Exa had the highest acceptance point estimate, but its mean was pulled up by a 1,609.6-second timeout; its accepted-answer median was 6.51 seconds. These differences need larger holdouts before they can guide a production choice.

## Search-only screen

The 360 retrieval trials used repeated identical queries; returned-source presence does not establish relevance or answer quality.

| Search | Median seconds | Known $ / request | Publisher evidence on identified easy/heavy trials |
|---|---:|---:|---:|
| Tavily ultra-fast | 0.15 | $0.00800 | 8/40 |
| Tavily fast | 0.15 | $0.00800 | 12/40 |
| Exa lite | 0.23 | $0.00400 | 40/40 |
| Exa auto | 0.23 | $0.00700 | 40/40 |
| DeepSeek content | 0.52 | $0.00075 | 22/40 |
| DeepSeek snippets | 0.51 | $0.00075 | 22/40 |

## Measurement and spend

- The 95% intervals use 2,000 bootstrap draws clustered by product prompt. Paired comparisons use Mercury 2.5 + DeepSeek as the baseline.
- Twelve controlled evaluator checks (six correct and six deliberately wrong answers, judged by both models) passed. This checks basic grader discrimination; it does not establish open-web research accuracy.
- The aggregate token ceiling was 100,000,000. The run used 19,950,226 (16,309,798 provider-reported; 3,640,428 conservative estimates), with no budget denials.
- Known research spend was $7.66606, search-screen spend $1.71000, and grading spend $2.59771. Known Mistral Large 4 spend across candidate and evaluator calls was $3.13; 72 calls had no provider-reported usage, so the account total may differ. No quota error was observed, so the Mercury 3 fallback was not triggered.
- Price assumptions are frozen to 2026-10-21 public rates. Tavily uses the declared $0.008/credit comparison rate; account-specific discounts and credits are excluded.

This is a small model-graded benchmark with two repetitions per question and six prompts per product category. No Google AI baseline was measured. The generated local static HTML report has low/high sort links, workload breakdowns and per-trial gold answers, citations and judge notes. The corpus contains criterion-to-primary-source mappings in `src/app/searchbench/products-v2.json`.

Design references: [BrowseComp](https://openai.com/index/browsecomp/), [SimpleQA](https://cdn.openai.com/papers/simpleqa.pdf) and [FRAMES](https://arxiv.org/abs/2409.12941). They informed evaluation design; benchmark questions were written for this corpus.
