# Evidence-Ledger Knowledge Pipeline — Design (Option B)

Date: 2026-07-07
Status: draft, pending review
Supersedes the write-time-gated pipeline described in `docs/INTERNALS.md` (knowledge
plane only — the serving plane is explicitly out of scope and unchanged).

---

## 1. Goal

Replace the destructive extract→gate→promote pipeline with an **append-only evidence
ledger** where claims are **deterministic, recomputable views** over stored evidence.

Three properties the current pipeline lacks, by construction:

1. **No fact is ever destroyed.** Fetched documents and extracted observations are
   stored permanently with provenance. Gating/purging become export-time filters,
   not deletions. Fixing a judge bug means re-running resolution over the ledger —
   zero re-fetching, zero re-extraction tokens.
2. **A claim's identity comes from its own text, not the search that found it.**
   Evidence is attributed to a component (engine/gearbox code) at a dedicated
   resolution stage using catalog-derived discriminative aliases — killing the
   DQ200-filed-as-DQ381 class of contamination (`docs/design_flaws.md` Flaw 1).
3. **Token spend is bounded and measured.** Every LLM call is cached by content
   hash, deterministic filters run before every LLM stage, the expensive model is
   called once per claim-cluster (not per gate per source), and every run prints a
   per-stage token/cost report with a `--max-usd` abort.

### Non-goals

- Serving plane changes. `sync.py`, matcher, resolver, `/analyze`, the extension,
  and the claims-YAML schema they consume are untouched. Export produces the same
  YAML shape as `promote.py` does today.
- Request-time LLM calls. The no-LLM-on-`/analyze` invariant stands.
- New UI. Review remains the existing `review_tool.py` flow (pointed at the ledger).

---

## 2. Architecture

```
ACQUISITION (append-only)
  structured feeds ──┐
  Exa/Tavily search ─┼─► documents ── chunk + keyword-gate ──► extraction (cheap LLM,
  yt-dlp transcripts ┘    (SQLite)                              cached by doc hash)
                                                                      │
                                                              evidence (SQLite)
RESOLUTION (recomputable, no fetching)                                │
  1. entity resolution: evidence → component id (deterministic, catalog aliases)
  2. clustering: evidence → claim-clusters (Jaccard + embedding, deterministic)
  3. verdict: ONE strong-model call per cluster (attribution + support +
     product-principle value), cached by cluster content hash
  4. aggregation: confidence from #independent sources × source class ×
     structured corroboration
                      │
EXPORT                ▼
  backend/data/claims/*.yaml   ← generated artifact (same schema as today)
  backend/data/parts/**/*.yaml ← generated artifact
```

### 2.1 Storage: single SQLite file `knowledge/ledger.db`

SQLite, stdlib `sqlite3`, no ORM. It is a build cache with provenance, not a serving
database. Gitignored; rebuildable from `documents` (raw text is stored). Tables:

```
documents      id, url_or_video_id, source_type, site_or_channel, lang,
               fetched_at, raw_text, text_hash, target_hint (the search context
               that found it — recorded as a HINT, never as attribution)

evidence       id, doc_id, span_start, span_end, quote, quote_grounded,
               title, domain, severity, rationale, inspection_advice,
               component_hint (extractor's own-text reading),
               mileage_km_hint, extractor_version, extracted_at

resolutions    evidence_id, component_id | 'unresolved' | 'foreign',
               method (alias-exact | verdict | manual), resolver_version

clusters       id, component_id, member evidence_ids, cluster_version

verdicts       cluster_id, input_hash, model, verdict_json
               (attribution, support, product_value, severity, rationale_tr/en),
               tokens_in, tokens_out, usd, created_at

runs           per-stage token/cost accounting rows
```

Key invariant: `documents` and `evidence` are **append-only** (rows may gain a
`superseded_by` when re-extracted with a newer extractor, never deleted).
`resolutions`, `clusters`, `verdicts` are derived and freely recomputable.

### 2.2 Acquisition

- **Web/YouTube**: keep Exa + yt-dlp + trafilatura from `auto.py`, but every fetch
  lands in `documents` first. **Remove the `doc.text[:6000]` cap.**
- **Forums re-admitted** (drop `FORUM_DOMAINS` from the exclude list): an anecdote
  is one evidence row; it only becomes a servable claim via aggregation (§2.5).
  The ledger's counting model is what makes forum data safe.
- **Structured feeds** (stage 2, near-zero tokens): EU Safety Gate/RAPEX, KBA and
  TR SGM recalls, UK DVSA MOT failure statistics + recalls, manufacturer
  maintenance schedules. Each ingester writes `documents` rows with
  `source_type: structured` and pre-structured evidence rows (no extraction LLM).
  Structured corroboration raises confidence of testimony-derived claims and seeds
  the "due unless the ad proves otherwise" maintenance-interval claim class.

### 2.3 Extraction (cheap model, chunked, keyword-gated, cached)

- Split full document text into ~4,000-char chunks with 400-char overlap.
- **Deterministic chunk gate before any LLM call**: a chunk is extracted only if it
  contains at least one failure-lexicon token (arıza, sorun, kronik, failure,
  problem, fault, broken, replaced, recall, değişti, yaptırdım …) or a catalog
  component token. Transcripts are mostly filler; this typically drops 50–70% of
  chunks at zero cost.
- Extractor stays `langextract` + `ministral-8b-latest` (`langextract_client.py`),
  now invoked per surviving chunk; spans are stored relative to the full document.
- Cache key: `(text_hash, chunk_index, extractor_version)`. A document is never
  extracted twice for the same extractor version — re-runs are free.
- Migration seed: existing `knowledge/cache/*_candidates.json` files and existing
  claims YAMLs are backfilled into `documents`/`evidence` so day one starts with
  the current knowledge, not an empty ledger.

### 2.4 Resolution and judgment

**Entity resolution (deterministic first).** The catalog (`backend/data/**/*.yaml`)
yields a two-tier alias registry per the Flaw 3 fix — *discriminative* aliases
(`DQ200`, `0AM`, `K9K`) attribute; *search-only* aliases (`7-speed DSG`, `1.5 dCi`)
never do. Rules, in order:
1. Evidence own-text names exactly one discriminative alias → resolve to it
   (even when it differs from `target_hint` — this is the sibling reroute).
2. Names a foreign manufacturer's code → `foreign` (excluded from export, kept).
3. Names nothing discriminative → `unresolved`; attribution is decided by the
   cluster verdict call, with `target_hint` as context, not as truth.

**Clustering (deterministic).** Group same-component evidence by domain + Jaccard
title/rationale overlap (reuse `dedup.py`); embeddings only if Jaccard proves too
coarse (decide in eval, not up front). Independence check per today's rule.

**Verdict — one strong-model call per cluster.** Replaces `gate_support`,
`gate_variant`, `gate_generic`, `gate_inspection_value`, `gate_refute`, and the
code-token/model-mention bypasses and brand/sibling vetoes in `promote.py`.
Input: cluster's evidence quotes + rationales, component description, sibling-code
registry, the product principle from `CLAUDE.md`. Output (one JSON object):

```json
{
  "attribution": {"component_id": "...", "confidence": "...", "reason": "..."},
  "supported": true, "refuted_by": [],
  "product_value": "high | low | inspection_covered | generic",
  "severity": "high | medium | low",
  "title_en": "...", "title_tr": "...", "rationale_tr": "...",
  "inspection_advice_tr": "..."
}
```

Model: `claude-haiku-4-5` via the Batch API (50% discount; this is offline work —
latency is irrelevant). Existing deterministic pre-checks (`stoplists.py`
warning-light patterns, generic-maintenance terms, `has_specificity_signal`) run
*before* clustering and mark evidence `low_value` without an LLM call — per the
established rule that LLM gates need a deterministic pre-check. Verdicts are cached
by input hash; a re-run with unchanged evidence costs zero.

Folding translation into the verdict retires `translate_claims.py` and the
mixed-language served text ("Hidrolik tensioner failure") as a class.

### 2.5 Aggregation and export

Disposition (deterministic, over verdicts):
- `verified`: ≥2 independent sources with supporting verdict, or 1 testimony
  source + structured corroboration (recall / MOT-rate / service-schedule match).
- `review`: exactly 1 independent source, or `severity == high` (human sign-off
  stays mandatory for high severity — invariant preserved).
- Not exported (but retained): `foreign`, `low_value`, `refuted`, `unresolved`.

Export regenerates claims YAML wholesale per model/part with stable claim keys
(`{component}_{domain}_{slug}`), carrying source URLs + grounded quotes. The
`purge_*.py` scripts' invariants become assertions in the exporter (bad output
fails the build); the scripts themselves are retired.

### 2.6 Coverage-gap-driven acquisition (stage 3)

`/analyze` already logs analyses. A small offline job reads no-coverage/thin-
coverage variants from `analysis_log`, ranks by hit count, and runs acquisition for
the top gaps within a per-run budget. Demand decides what gets onboarded next.

---

## 3. Token-cost model (the design constraint)

### 3.1 Where money goes today (per onboarded model, ~67 sources)

| Stage | Calls | Notes |
|---|---|---|
| Extraction | ~67 × 1 | but capped at 6k chars — silently lossy |
| Gates | ~169 candidates × up to 5 gates × sources ≈ 500–800 | ministral-8b |
| Bug re-runs | ×3 historically | no persistence → full replay |

The dominant historical cost was **re-runs**, not unit price.

### 3.2 New pipeline, per onboarded model (assumptions stated, not promises)

Assume ~67 docs, avg 15k chars full text, 60% of chunks dropped by the keyword
gate, ~169 evidence rows → ~60 clusters after dedup.

| Stage | Model | Est. tokens | Est. cost |
|---|---|---|---|
| Extraction (chunked, gated) | ministral-8b (~$0.10/MTok) | ~0.45M in / 0.05M out | **~$0.05** |
| Verdicts (60 clusters, batch) | claude-haiku-4-5 batch (~$0.50/$2.50 per MTok) | ~0.20M in / 0.02M out | **~$0.15** |
| Structured feeds | none | ~0 | ~$0 |
| Re-runs after any bug fix | cache hits | 0 | **$0** |

≈ **$0.20–0.40 per model onboarding**, i.e. roughly $200–400 for a 1,000-model
catalog — at that scale the binding cost is Exa/Tavily search API fees, not tokens.
Reading *full* documents costs ~3× today's extraction tokens but at the cheap
model's price; the strong model sees only clustered claim text, never raw pages.

### 3.3 Enforcement (not just estimation)

- `runs` table records tokens_in/out and USD per stage per run.
- Every pipeline entry point takes `--max-usd`; the run aborts cleanly (ledger
  intact, resumable) when the cap is hit.
- Every run ends with a printed cost report; `--dry-run` prints the *planned* call
  count and cost estimate before spending anything.
- Caches (extraction by doc hash, verdicts by cluster hash) make the marginal cost
  of iteration ~zero — the property whose absence caused the historical 3× burns.

---

## 4. Code impact

**New** (`knowledge/ledger/`): `db.py` (schema + migrations), `ingest.py`
(documents from fetchers + backfill), `chunking.py` (chunker + keyword gate),
`resolve.py` (aliases + entity resolution), `cluster.py`, `verdict.py` (batch
client + cache), `export.py`, `costs.py`, structured-feed ingesters
(`feeds/dvsa.py`, `feeds/safety_gate.py`, `feeds/recalls_tr.py` — stage 2).

**Modified**: `auto.py` / `process.py` (orchestrate ledger stages; drop
`FORUM_DOMAINS` exclusion), `extract.py` (per-chunk, uncapped),
`langextract_client.py` (chunk-relative spans), `review_tool.py` (read/write
ledger dispositions), `stoplists.py` (alias tiers derived from catalog).

**Retired once export parity is proven**: the five gates in `judge.py`, the
bypass/veto stack in `promote.py`, `translate_claims.py`, `dedup.py` (absorbed),
`purge_forums.py`, `purge_german.py`, `purge_invalid_severity.py`,
`purge_offtopic_contamination.py`, `downgrade_unsourced_claims.py`,
`normalize_domains.py` (absorbed into export assertions),
`find_cross_file_duplicates.py`, `fix_sibling_contamination.py`.

Net: the new subsystem is smaller than the code it deletes.

---

## 5. Testing and acceptance

- **Unit**: chunk gate (drops filler, keeps failure text, TR + EN), alias-tier
  derivation from catalog fixtures, entity-resolution rules (sibling reroute,
  foreign veto), aggregation dispositions, cost accounting.
- **Ledger invariants**: append-only enforcement; re-running any derived stage
  twice is byte-identical (determinism) and token-free (cache hit).
- **Golden export regression**: backfill current YAMLs → export → diff. Every
  difference must be an explainable improvement (e.g. DQ200 claims leaving
  `dq381.yaml`) — reviewed by hand once, then frozen as the new golden set.
- **Judge eval**: extend `knowledge/gold/` + `eval_judge.py` with a labelled
  cluster-verdict set, including the known sibling-contamination cases as
  must-catch canaries. The Haiku verdict must beat the current gate stack on it
  before the gates are deleted.
- **End-to-end serving check**: `sync.py` + existing backend tests pass against
  exported YAML unchanged; `backend/tools/replay.py` diffs served output on
  logged analyses before/after.

---

## 6. Rollout stages

1. **Ledger core**: schema, backfill (cache JSONs + claims YAMLs), chunked gated
   extraction, deterministic resolution/clustering, Haiku batch verdicts, export
   with parity check, cost accounting. Gates/purges retired at the end of this
   stage only after the golden-export and judge-eval acceptance above.
2. **Structured feeds**: TR SGM + EU Safety Gate recalls, DVSA MOT statistics,
   maintenance-interval ingestion; corroboration wiring into aggregation;
   forum re-admission (needs the aggregation model live first).
3. **Coverage-gap acquisition**: `analysis_log`-driven onboarding queue with
   per-run budget.

Each stage lands independently; the serving plane never notices anything but
better YAML.

---

## 7. Open questions

1. **Exa vs Tavily vs both** for discovery — cost/recall comparison deferred to a
   small stage-1 experiment (search API fees, not tokens, dominate at scale).
2. **Embedding-assisted clustering** — only if Jaccard clustering measurably
   under-merges on the eval set; not built speculatively.
3. **DVSA data volume** — the anonymised MOT results dataset is large (GBs);
   stage 2 will decide between the bulk dataset and the per-vehicle API based on
   an ingestion spike.
