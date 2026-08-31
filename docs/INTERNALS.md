# Kriko — How It Works

This document explains every mechanism in detail: data flow, key functions, file paths,
and the invariants the system relies on. Read this before touching the pipeline.

---

## Architecture: Four Packages

Dependencies form a fan. Interfaces and pipeline drivers sit above the generic
engine; each category pack provides its own data, vocabulary, and evidence
ledger/extraction machinery under `packs/<name>/pipeline/`.

```
app/             CLI, local web dashboard, MCP server
  └─ app/pipeline/  ledger and remediation drivers
                    └─ packs/     category data, builders, vocabulary, coverage
                                  └─ packs/cars/pipeline/  evidence ledger and
                                     grounded extraction for the cars pack
kriko/           generic pack store, lookup, ranking, and ledger primitives
extension/       Chrome client for the cars pack adapter
```

`kriko/` imports none of the other packages. `packs/` does not import `app/` or
`app/pipeline/`; only pipeline drivers coordinate the evidence pipeline and pack
data. The structural rules are enforced by
`src/app/pipeline/tests/test_repo_invariants.py`. The serving database is the local
SQLite pack store; the evidence ledger is a separate SQLite build database.

The cars source of truth is under `packs/cars/data/`. There is no `backend/`,
Postgres sync, or Docker-only serving layer in the current architecture.

The pack files are built into the serving SQLite store; the evidence ledger remains
separate from that read path. `app/pipeline/` is where operations that span packs
and their pipelines live; the generic ledger mechanics (chunking, ingest, cost
budgeting) live in `src/kriko/ledger/`, with each pack injecting its own policy.

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
**`src/app/web/app.py`** — `create_app()` and the `/api/analyze` route

Always returns HTTP 200. Exceptions are caught and wrapped as `coverage_state: unavailable`.

```python
meta   = payload.ad_metadata or {}
match  = match_variant(meta, db)       # → MatchResult
claims = resolve_claims(match, db)     # → list[Claim]
```

### 4. Variant matcher
**`src/kriko/lookup/match.py`** — generic identity and attribute matching

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
**`src/kriko/lookup/__init__.py`** — `lookup(query, conn)`

Queries `claim_variants` join table for all matched variant IDs, returns only
`status='verified'` and `is_current=True` claims.

Visual-detection suppression (payload v2): a claim whose registry component
(`claims.component_id`, filled by sync from `packs/cars/pipeline/catalog/components.yaml`)
has `detection: visual` gets `ClaimResult.detection_factor = 0.35` — but ONLY
when the claim has a component_id and a listing context exists. The claim is
never dropped (fail-open); the API layer multiplies the factor into
`relevance_score`.

### 5b. Ranking & payload v2
**`src/app/web/routers/analyze.py`** — the `/api/analyze` route

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

### Claim health — reading the evidence back out

`kriko/lookup/tree.py` answers the question the serving path cannot: *how well
supported is what we ship?* Four signals, never combined into a score —
contradiction (`evidence.stance = 'refutes'`), corroboration (distinct
independent supporting sources), the best source's trust tier, and staleness
(`sources.retrieved_at`).

Ordering is lexicographic and ascending on every element, exposed as
`ClaimHealth.concern`, so the order is inspectable rather than implied by a
weight nobody can justify. Two deliberate asymmetries:

- **A claim with no evidence is not weak, it is uncovered.** It is excluded
  from `weakest_claims()` and reported by the coverage report instead, matching
  `rank.py`'s treatment of source-free interval claims as trust-neutral.
- **An absent `retrieved_at` sorts LAST, not first.** No timestamp is not
  evidence of staleness. Before 2026-08-31 all three producers wrote `''`
  here; they now derive it (`documents.fetched_at` in the ledger, the
  submission time over MCP), and legacy rows stay honestly blank. One
  consequence follows from that choice: a claim with a known, fresh date
  ranks *worse* on this element than a claim with no date at all, because
  blank is deliberately treated as carrying no information rather than as
  maximally stale. Until B45–B47 land and the other three signals stop
  being near-universally inert, that makes the better-documented half of the
  catalog look worse than the undocumented half on this one column.
- **The three producers agree on the column, not on the semantic.** The
  ledger exporter writes `MAX(d.fetched_at)` — "the last time we saw the
  page." `mcp_server.py` and `packs/cars/build.py` both write it with
  `INSERT OR IGNORE`, so a URL that is resubmitted, or shared by two claims,
  keeps whatever stamp it was *first* given. `EvidenceRow.retrieved_at`'s
  comment ("when WE last saw the page") is exactly true for the ledger path
  and only approximately true for the other two.

Served read-only via `GET /api/health/weakest` and `GET /api/health/subject/{id}`
(`src/app/web/routers/health.py`) and the `subject_health`/`weakest_claims` MCP
tools (`src/app/mcp_server.py`); the dashboard's Health tab
(`src/app/web/static/`) renders the same JSON.

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

The pipeline is a ledger, not a curated-YAML approval queue: `app.pipeline.ledger_run`
drives discovery through export with no human sign-off step (automation principle,
CLAUDE.md). Each stage splits into a generic half in `src/kriko/ledger/` (orchestration —
chunking loop, ingest, cost budgeting) and a cars-specific half in
`packs/cars/pipeline/` (policy — what counts as signal, which sources are
untrustworthy, which component an evidence chunk describes). A handful of legacy
per-make/model curated YAMLs remain under
`packs/cars/pipeline/sources/curated/part_{part_id}.yaml` (one file per *part*, not
per make+model) as a residual manual-add path; they are not required by the live flow.

### Acquisition
**`packs/cars/pipeline/ledger/acquire.py`** — discover → rank → fetch → ingest for a
part, no LLM involved. Results are ranked by part-code specificity before fetching
(backlog B8), rather than taking the first N results in discovery order.

### Chunking and extraction
**`src/kriko/ledger/chunking.py`** / **`src/kriko/ledger/extraction.py`** — generic chunk loop,
cache, and budget charge. **`packs/cars/pipeline/ledger/chunking.py`** supplies the cars
chunk gate (the failure lexicon plus catalog-derived engine/gearbox code tokens — a
chunk is worth extracting if it names a failure word or a code, so a new part is
covered the moment its stub exists). **`packs/cars/pipeline/ledger/extraction.py`**
supplies langextract as the extractor via **`packs/cars/pipeline/langextract_client.py`**
(grounded/few-shot extraction — each claim's quote is aligned to an exact character span
in the source rather than trusted as a self-reported string) plus the low-value rules
(`kriko.gates.gate_reason` over this pack's `vocabulary/gates.yaml`) that flag which
extracted claims are noise. `packs/cars/pipeline/extract.py` is a separate, offline-only
module (its own docstring: "never on the /analyze request path") — it is not part of
this ledger loop.

### Entity resolution
**`packs/cars/pipeline/ledger/resolve.py`** — decides which component a piece of
evidence describes, from the evidence's own text against catalog-derived codes, never
from the search query that found the document (design_flaws.md Flaw 1).

### Verdict
**`packs/cars/pipeline/ledger/verdict.py`** — one strong-model (`deepseek-v4-flash`)
verdict per claim-cluster. This replaced the old five-gate ministral stack
(`gate_generic`/`gate_variant`/`gate_support`/`gate_refute`) and the separate scored
promotion step (design_flaws.md Flaw 5): a single call sees the whole cluster, the
component, its sibling codes, and the product principle, and returns attribution +
support + value + severity + bilingual (EN/TR) copy in one JSON object. Verdicts are
cached by input hash. **`packs/cars/pipeline/ledger/eval_verdict.py`** runs the
acceptance eval against `packs/cars/pipeline/gold/gold.yaml` (11 hand-judged entries).

### Export
**`packs/cars/pipeline/ledger/export.py`** — claims as a deterministic view over
verdicts, written as the part-dict YAML schema under `packs/cars/data/parts/**`. Part
headers come from the served catalog itself, never hand-enumerated. The pack builder
validates references and avoids shipping rows that cannot be served.

### Regression check
**`packs/cars/pipeline/ledger/parity.py`** — diffs existing claim YAMLs against a fresh
ledger export; matching is by stable identity, not title text, because the verdict
stage rewrites titles (backlog B1 blocker 2).

### DB sync
**`src/kriko/pack/build.py`** — build the pack into SQLite

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

### Curated sources YAML (`packs/cars/pipeline/sources/curated/part_{part_id}.yaml`, legacy manual-add path)
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
