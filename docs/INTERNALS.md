# Kriko — How It Works

This document explains every mechanism in detail: data flow, key functions, file paths,
and the invariants the system relies on. Read this before touching the pipeline.

---

## Architecture: Four Packages

Dependencies form a fan. Interfaces and pipeline drivers sit above the generic
engine; category packs provide data, while the knowledge package provides the
evidence/extraction machinery used to build packs.

```
app/             CLI, local web dashboard, MCP server
  └─ app/pipeline/  ledger and remediation drivers
                    ├─ packs/     category data, builders, vocabulary, coverage
                    └─ knowledge/ evidence ledger and grounded extraction
kriko/           generic pack store, lookup, ranking and research
extension/       Chrome client for the cars pack adapter
```

`kriko/` imports none of the other packages. `packs/` and `knowledge/` do not
import `app/` or `app/pipeline/`; only pipeline drivers coordinate the evidence
pipeline and pack data. The structural rules are enforced by
`app/pipeline/tests/test_repo_invariants.py`. The serving database is the local
SQLite pack store; the evidence ledger is a separate SQLite build database.

The cars source of truth is under `packs/cars/data/`. There is no `backend/`,
Postgres sync, or Docker-only serving layer in the current architecture.

The pack files are built into the serving SQLite store; the evidence ledger remains
separate from that read path. `app/pipeline/` is where operations that span packs and
knowledge live.

---

## Serving Plane: Request Path

### 1. Content script extracts listing data
**`extension/content.js`** — `extractSahibindenMetadata()`

Queries the DOM of a Sahibinden listing page and returns a structured object:
```js
{
  make, model, year, fuel_type,  // from classifiedInfoList <ul>
  transmission, engine_volume_cc, power_hp,  // from #technical-details table
  trim,          // Sahibinden "Model" field (e.g. "1.5 dCi Joy")
  damage_info,   // parsed body damage silhouette
  equipment,     // parsed Donanım checkboxes
  url, title, ...
}
```

Key mapping in `mapTurkishKeys()`: Sahibinden uses "Yakıt Tipi"/"Benzinli" etc. The map
converts Turkish field names → English keys. "Benzinli" → `fuel_type: "Benzinli"`.

### 2. Background script POSTs to /analyze
**`extension/background.js`** — `requestAnalysis(adMetadata)`

Sends `POST http://127.0.0.1:8000/analyze` with the metadata as `ad_metadata`. Tries
two fallback URLs (`8000`, `8765`). Results are cached in `chrome.storage.session` for
6 hours by URL+metadata signature hash.

### 3. FastAPI /analyze endpoint
**`app/web/app.py`** — `create_app()` and the `/api/analyze` route

Always returns HTTP 200. Exceptions are caught and wrapped as `coverage_state: unavailable`.

```python
meta   = payload.ad_metadata or {}
match  = match_variant(meta, db)       # → MatchResult
claims = resolve_claims(match, db)     # → list[Claim]
```

### 4. Variant matcher
**`kriko/lookup/match.py`** — generic identity and attribute matching

Normalizes raw metadata → canonical values:
- `normalize_fuel("Benzinli")` → "petrol" (pack-declared vocabulary and adapter normalization)
- `normalize_make("Renault")` → `"renault"`
- `normalize_model("Megane")` → `"megane"`
- `normalize_transmission("Otomatik")` → `"automatic"`

Hard filter: DB query on `(make, model, fuel, year_from ≤ year ≤ year_to)`.
Narrowing (never eliminates all): by cc tolerance ±100, hp ±10, transmission exact.

Returns `MatchResult(variant_ids, method, notes)` where method is:
- `"exact"` — single match
- `"ambiguous"` — multiple matches (all returned, all their claims served)
- `"no_match"` — missing required field or nothing found
- `"inconsistent_listing"` — cc/hp don't match any real variant

Missing required fields check (line 25):
```python
if not make or not model or not fuel or not year:
    missing = [k for k, v in [...] if not v]
    return MatchResult([], "no_match", f"Missing required fields: {missing}")
```

### 5. Claim resolver
**`kriko/lookup/__init__.py`** — `lookup(query, conn)`

Queries `claim_variants` join table for all matched variant IDs, returns only
`status='verified'` and `is_current=True` claims.

Visual-detection suppression (payload v2): a claim whose registry component
(`claims.component_id`, filled by sync from `knowledge/catalog/components.yaml`)
has `detection: visual` gets `ClaimResult.detection_factor = 0.35` — but ONLY
when the claim has a component_id and a listing context exists. The claim is
never dropped (fail-open); the API layer multiplies the factor into
`relevance_score`.

### 5b. Ranking & payload v2
**`app/web/routers/analyze.py`** — the `/api/analyze` route

`relevance_score = severity weight (low 0.3 / medium 0.6 / high 1.0)
× mileage-gate match (satisfied 1.0 / unknown 0.7, fail-open)
× detection factor (visual 0.35 / else 1.0)
× source-trust weight (best tier across sources, NULL = neutral)`

Risks sort by `-relevance_score` (strength → consequence → severity as
tiebreak), then are capped to `MAX_RISKS_PER_LISTING`. Each risk carries
`why_shown`: human-readable reasons the card is shown — config match (variant
label), mileage gate ("187.000 km > 120.000 km threshold" or "mileage unknown
— shown by default"), visual-detection suppression, source trust. The
response also carries `subsystems: [{name, display_tr, risks}]` — the same
risks grouped by registry subsystem (`claims.subsystem`) for the v2 UI; the
flat `risks` array stays for the current extension.

### 6. Response rendering
**`extension/hover_lite/hover_lite.js`**

Reads `coverage_state`, `risks[]`, `summary`, `disclaimer` from the API response.
Renders the panel overlay with severity-colored risk cards.
Risk cards are in `hover_lite/risk_card.js`. Icons in `hover_lite/icons.js`.
When the response carries `subsystems[]`, groups render per subsystem with the
Turkish label (`display_tr`) instead of per domain; `why_shown` renders as
small muted chips under each card title.

---

## Knowledge Plane: Pipeline

### Source curation
**`knowledge/sources/curated/{make}_{model}.yaml`**

One file per make+model. Each entry has `type: youtube|page`, identifiers,
and lifecycle fields:
```yaml
status: pending | processed | skipped
added_at: "YYYY-MM-DD"
processed_at: "YYYY-MM-DD" | null
```

Curated YAMLs are a legacy hand-authored path. The live flow is
`app.pipeline.ledger_run acquire`, which discovers, fetches and ingests straight to the
ledger with no curated-YAML step and no human approval (see the automation
principle in CLAUDE.md). `process.py` still updates `status: processed` for the
entries that remain.

### Document fetching
**`knowledge/sources/curated.py`** — `CuratedSource.fetch(make, model, pending_only=False)`

- YouTube entries → `knowledge/sources/youtube.py:get_transcript(video_id)` via yt-dlp
- Page entries → `trafilatura.fetch_url(url)` + `trafilatura.extract()` (universal article extractor)

VTT normalization in `youtube.py:_normalize_vtt()` strips timestamp lines and collapses
duplicate cues from YouTube's rolling-window auto-captions.

### Claim extraction
**`knowledge/extract.py`** — `extract_claims(doc) → list[CandidateClaim]`

Sends `doc.text[:6000]` to `ministral-8b-latest` via `knowledge/langextract_client.py`
(langextract, grounded/few-shot extraction — see that module's docstring for why: each
claim's quote is aligned to an exact character span in the source rather than trusted as
a self-reported string). Returns typed `CandidateClaim` objects: title, domain, severity,
rationale, inspection_advice, verbatim quote, optional engine_or_variant_hint, and
`quote_grounded` (whether the quote's span aligned exactly).

### Deduplication
**`knowledge/dedup.py`** — `merge_candidates(candidates)`

Called internally by `promote()`. Groups same-claim candidates from different sources:
- Fast path: different `domain` → definitely different claim
- Same-claim check: `same_claim(a, b)` — deterministic title-token Jaccard ≥ 0.4, no LLM
- Independence check: Jaccard word overlap >85% → non-independent (repost)

### LLM Gates
**`knowledge/judge.py`** — gate functions, all using `ministral-8b-latest` (Mistral API),
with deterministic pre-checks ahead of each LLM call (see `knowledge/stoplists.py`)

| Gate | Question | Passes if |
|------|----------|-----------|
| `gate_generic` | Is this claim true of all cars? | Claim is model-specific |
| `gate_variant` | Does the quote mention this variant? | At least one variant confirmed |
| `gate_support` | Does the quote actually support the claim? | Evidence is concrete |
| `gate_refute` | Does the quote contradict the claim? | No contradiction found |

### Promotion scoring
**`knowledge/promote.py`** — `promote(candidates, variant_descriptors)`

Each source that passes gate_support + gate_refute contributes 1 point. Domain trust is
not used — the LLM gates are the sole quality filter.

Disposition rules:
- `score ≥ 2` → `VERIFY` (auto-promote), 20% sampled for audit → `REVIEW`
- `score ≥ 1` → `REVIEW` (single source — human must confirm with a second)
- `score = 0` → `HELD`
- `severity == "high"` → always `REVIEW` regardless of score
- `gate_generic` failed → `REJECT`
- `gate_variant` failed → `HELD`

### Writing claims
**`knowledge/promote.py`** — `write_promoted_claims(results, make, model, claims_dir)`

The ledger export writes claims into the cars pack under
`packs/cars/data/parts/`. The pack builder validates references and avoids
shipping rows that cannot be served.

Claim ID format: `{make}_{model}_{domain}_{title_first_20}_v1`

### DB sync
**`kriko/pack/build.py`** — build the pack into SQLite

Builds the pack YAML into the local SQLite serving store. Rebuild explicitly with
`python -m app.cli build packs/cars`.

The serving store contains generic subjects, attributes, claims, evidence and
relations. The evidence ledger uses its own SQLite database and is never read by
the request path.

---

## Data Formats

### Variants YAML (`packs/cars/data/variants/{make}_{model}_{gen}.yaml`)
```yaml
- id: megane4_h5h_140          # stable forever, never rename
  make: renault                 # lowercase canonical
  model: megane                 # lowercase canonical
  generation: "IV"
  engine_code: H5H
  fuel: petrol                  # petrol | diesel | hybrid | electric | lpg
  displacement_cc: 1332
  power_min_hp: 115
  power_max_hp: 140
  transmission: automatic       # manual | automatic
  year_from: 2018
  year_to: null                 # null = still in production
  market: TR
```

### Claims YAML (`packs/cars/data/parts/{part_type}/{part_id}.yaml`)
```yaml
- id: megane4_h5h_timingchain_v1      # {claim_key}_v{version}
  claim_key: megane4_h5h_timingchain  # stable across versions
  version: 1
  is_current: true
  title: "1.3 TCe (H5H) timing chain stretch and tensioner wear"
  domain: engine                      # engine|transmission|electrical|emissions|fuel system|brakes|suspension|general
  severity: high                      # high|medium|low
  confidence: 0.72                    # 0.0–1.0
  rationale: "..."
  inspection_advice: "..."
  status: verified                    # verified|draft|held|review|rejected
  promoted_by: human                  # human|auto|auto_audit
  variants:
    - variant_id: megane4_h5h_140
      grounding_note: "..."
  sources:
    - source_url: "https://..."
      site_or_channel: "Reddit r/Renault"
      quote: "verbatim quote..."
      independent: true
```

### Curated sources YAML (`knowledge/sources/curated/{make}_{model}.yaml`)
```yaml
- type: youtube                   # youtube | page
  video_id: "abc123xyz"           # for youtube
  # url: "https://..."            # for page
  site_or_channel: "Auto Tanı TR"
  notes: "human note"
  status: pending                 # pending | processed | skipped
  added_at: "2026-06-26"
  processed_at: null
```

---

## Key Invariants

1. **Variant IDs are permanent.** Once a variant is in the DB, its ID never changes.
   Claims reference variant IDs — renaming breaks the link silently.

2. **Pack YAML is the source of truth, not the serving DB.** Rebuild the local
   SQLite pack from YAML with `python -m app.cli build packs/cars`; never edit the
   generated store directly.

3. **The serving store is generic and local.** Pack data is compiled into SQLite;
   the request path does not call the evidence ledger or an LLM.

4. **Verdicts are pipeline-owned.** Deterministic gates and verdict stages decide
   what can be exported; no human sign-off is part of the data path.

5. **The serving plane never calls an LLM.** `/analyze` only reads the DB. All LLM
   work happens offline in the knowledge plane.

6. **Category vocabulary is pack-owned.** Cars-specific labels and aliases live
   under `packs/cars/`; the generic engine does not contain car constants.

7. **WSL2 + Docker port conflict.** Never run `uvicorn` directly in WSL while Docker
   is up. Both listen on `0.0.0.0:8000` and WSL2 localhost forwarding means Windows
   Chrome will hit whichever bound the port first. The Docker stack is the only correct
   way to run the serving plane.
