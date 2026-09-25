> TL;DR (archived 2026-09-25): Design (2026-07-07, draft) replacing extract→gate→promote
with an append-only evidence ledger (SQLite `knowledge/ledger.db`): chunked keyword-gated
ministral-8b extraction, deterministic alias-tier resolution, Jaccard clustering, one
Haiku-batch verdict per cluster, deterministic aggregation/export. ~$0.20–0.40 per model,
re-runs free via content-hash caches, `--max-usd` enforced. Serving plane untouched.

# Evidence-Ledger Knowledge Pipeline — Design (Option B)

Date: 2026-07-07 · Status: draft, pending review · Supersedes write-time-gated pipeline in `docs/INTERNALS.md` (knowledge plane only; serving explicitly out of scope, unchanged).

## 1. Goal

Replace destructive extract→gate→promote with an **append-only evidence ledger**; claims become **deterministic, recomputable views** over stored evidence. Three missing properties:

1. **Nothing destroyed.** Documents + observations stored with provenance; gating/purge become export filters. Judge-bug fixes = re-run resolution, zero re-fetch/re-extract.
2. **Identity from own text, not the search.** Component attribution at a dedicated resolution stage via catalog-derived discriminative aliases (kills DQ200-as-DQ381 contamination, `design_flaws.md` Flaw 1).
3. **Bounded, measured tokens.** Content-hash caches, deterministic filters before every LLM stage, one strong-model call per cluster, per-stage cost reports + `--max-usd` abort.

### Non-goals

Serving changes (`sync.py`, matcher, resolver, `/analyze`, extension, YAML schema untouched — export matches `promote.py`'s shape); request-time LLM (no-LLM-on-`/analyze` stands); new UI (`review_tool.py` pointed at the ledger).

## 2. Architecture

```
ACQUISITION (append-only): feeds + Exa/Tavily + yt-dlp → documents (SQLite)
  → chunk + keyword-gate → extraction (cheap LLM, doc-hash cached) → evidence
RESOLUTION (recomputable): entity resolution (catalog aliases) → clustering
  (Jaccard + embedding) → ONE verdict per cluster → aggregation
EXPORT: backend/data/claims/*.yaml + backend/data/parts/**/*.yaml (same schema)
```

### 2.1 Storage: single SQLite file `knowledge/ledger.db`

`knowledge/ledger.db` (stdlib `sqlite3`, no ORM; gitignored build cache): `documents` (url, type, channel, lang, fetched_at, raw_text, text_hash, target_hint as HINT never attribution); `evidence` (doc span, quote, title/domain/severity/rationale/advice, component_hint, mileage hint, extractor version); `resolutions` (component_id | unresolved | foreign, method, version); `clusters`; `verdicts` (input_hash, model, attribution/support/product_value/severity/tr rationales, tokens, usd); `runs` (per-stage accounting). `documents`/`evidence` append-only (`superseded_by`, never delete); rest recomputable.

### 2.2 Acquisition

Keep Exa + yt-dlp + trafilatura into `documents`; **drop the `doc.text[:6000]` cap**; re-admit forums (drop `FORUM_DOMAINS` — anecdote = one row, servable only via aggregation). Stage-2 structured feeds (EU Safety Gate/RAPEX, KBA, TR SGM, DVSA MOT stats/recalls, maintenance schedules) write `source_type: structured` rows with no extraction LLM; structured corroboration seeds confidence + the "due unless proved otherwise" maintenance class.

### 2.3 Extraction (cheap model, chunked, keyword-gated, cached)

~4,000-char chunks / 400 overlap; deterministic keyword gate first (failure-lexicon or catalog-component token — drops 50–70% of transcript filler free); `langextract` + `ministral-8b-latest` per surviving chunk, full-document-relative spans; cache `(text_hash, chunk_index, extractor_version)`; backfill existing `cache/*_candidates.json` + claims YAMLs on day one.

### 2.4 Resolution and judgment

Alias tiers from catalog — *discriminative* (`DQ200`, `0AM`, `K9K`) attribute, *search-only* (`7-speed DSG`, `1.5 dCi`) never. Rules: exact discriminative mention ⇒ resolve (even vs `target_hint` — the sibling reroute); foreign code ⇒ `foreign` (kept, unexported); nothing ⇒ `unresolved` (verdict decides, hint as context). Clustering: same-component, domain + Jaccard (reuse `dedup.py`); embeddings only if eval proves Jaccard too coarse. **Verdict: one strong-model call per cluster**, replacing `gate_support/variant/generic/inspection_value/refute` + `promote.py` bypasses/vetoes. Input: quotes + rationales, component description, sibling registry, `CLAUDE.md` principle. Output JSON: attribution{component, confidence, reason}, supported, refuted_by, product_value, severity, title_en/tr, rationale_tr, advice_tr. Model `claude-haiku-4-5` Batch API (50% off; offline). Deterministic pre-checks (warning-light patterns, generic terms, `has_specificity_signal`) mark `low_value` pre-clustering — LLM gates keep their deterministic pre-check rule. Verdicts cached by input hash. Translation folds in ⇒ `translate_claims.py` retired (ends mixed-language served text).

### 2.5 Aggregation and export

`verified` = ≥2 independent supporting sources, or 1 testimony + structured corroboration; `review` = exactly 1 source, or severity high (mandatory human sign-off preserved); retained-unexported: foreign/low_value/refuted/unresolved. Wholesale YAML regen per model/part, stable keys (`{component}_{domain}_{slug}`), URLs + grounded quotes. `purge_*.py` invariants become exporter assertions (fail the build); scripts retired.

### 2.6 Coverage-gap-driven acquisition (stage 3)

Offline job reads thin/no-coverage variants from `analysis_log`, ranks by hits, acquires top gaps within budget — demand decides onboarding.

## 3. Token-cost model (the design constraint)

### 3.1 Where money goes today (per onboarded model, ~67 sources)

Extraction ~67×1 (lossy 6k cap); gates ~169 candidates × ≤5 × sources ≈ 500–800 ministral calls; bug re-runs ×3 (no persistence) — **re-runs dominated, not unit price**.

### 3.2 New pipeline, per onboarded model (assumptions stated, not promises)

~67 docs @15k chars, 60% chunks gated, ~169 evidence → ~60 clusters: extraction ~0.45M in/0.05M out ministral (~$0.10/MTok) ≈ **$0.05**; 60 batch verdicts ~0.20M in/0.02M out haiku-batch ($0.50/$2.50) ≈ **$0.15**; feeds $0; re-runs $0 (cache). ≈ **$0.20–0.40/model** (~$200–400 per 1,000 models; at scale Exa/Tavily fees bind, not tokens).

### 3.3 Enforcement (not just estimation)

`runs` table (tokens + USD/stage/run); `--max-usd` aborts cleanly (ledger intact, resumable); printed cost report + `--dry-run` plan estimate; caches make iteration ~free.

## 4. Code impact

**New** (`knowledge/ledger/`): `db, ingest, chunking, resolve, cluster, verdict, export, costs`, `feeds/{dvsa,safety_gate,recalls_tr}.py` (stage 2). **Modified:** `auto/process` (ledger stages; drop forum exclusion), `extract` (per-chunk, uncapped), `langextract_client` (chunk-relative spans), `review_tool` (ledger dispositions), `stoplists` (catalog-derived alias tiers). **Retired at parity:** `judge.py` gates, `promote.py` bypass/veto stack, `translate_claims, dedup` (absorbed), `purge_forums/german/invalid_severity/offtopic_contamination`, `downgrade_unsourced_claims`, `normalize_domains` (→ export assertions), `find_cross_file_duplicates`, `fix_sibling_contamination`. New subsystem smaller than deleted code.

## 5. Testing and acceptance

Unit (chunk gate TR+EN, alias tiers, resolution rules, dispositions, cost accounting); ledger invariants (append-only; derived stages byte-identical + token-free on re-run); golden export regression (backfill → export → diff; every delta an explainable improvement, e.g. DQ200 claims leaving `dq381.yaml`; hand-reviewed once, then frozen); judge eval (`gold/` + cluster-verdict set with sibling-contamination canaries — Haiku must beat the gate stack before gates die); serving e2e (`sync.py` + backend tests unchanged; `replay.py` diffs served output before/after).

## 6. Rollout stages

1. **Ledger core** (schema, backfill, gated extraction, resolution/clustering, batch verdicts, export + parity, costs; gates/purges retire only after golden + eval acceptance). 2. **Structured feeds** + corroboration + forum re-admission (needs aggregation live). 3. **Coverage-gap queue** (budgeted). Each lands independently; serving sees only better YAML.

## 7. Open questions

Exa vs Tavily (stage-1 experiment; search fees dominate); embedding clustering only on measured Jaccard under-merge; DVSA bulk-vs-API after an ingestion spike.
