# Kriko — How It Works

This document explains every mechanism in detail: data flow, key functions, file paths,
and the invariants the system relies on. Read this before touching the pipeline.

---

## Architecture: Two Planes

```
┌─────────────────────────────────────────────────────────────────┐
│  KNOWLEDGE PLANE  (offline, runs on your machine, uses LLM)     │
│                                                                  │
│  discover.py  →  curated YAML  →  process.py                    │
│                                      │                           │
│                   extract.py  ←──────┘                          │
│                   dedup.py                                       │
│                   judge.py  (LLM gates via Mistral)             │
│                   promote.py                                     │
│                       │                                          │
│                       ▼                                          │
│           backend/data/claims/*.yaml   (source of truth)        │
└──────────────────────────┬──────────────────────────────────────┘
                           │  sync.py (on container start)
┌──────────────────────────▼──────────────────────────────────────┐
│  SERVING PLANE  (Docker, no LLM, <10ms per request)             │
│                                                                  │
│  PostgreSQL ← sync.py                                           │
│       │                                                          │
│  FastAPI /analyze  →  matcher  →  resolver  →  JSON response    │
│       ▲                                                          │
│  Chrome extension (content.js → background.js → hover_lite.js)  │
└─────────────────────────────────────────────────────────────────┘
```

The two planes never communicate at runtime. YAML is the handoff point.

---

## Serving Plane: Request Path

### 1. Content script extracts listing data
**`extension_ui/content.js`** — `extractSahibindenMetadata()`

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
**`extension_ui/background.js`** — `requestAnalysis(adMetadata)`

Sends `POST http://127.0.0.1:8000/analyze` with the metadata as `ad_metadata`. Tries
two fallback URLs (`8000`, `8765`). Results are cached in `chrome.storage.session` for
6 hours by URL+metadata signature hash.

### 3. FastAPI /analyze endpoint
**`backend/api/main.py`** — `analyze(payload, db)`

Always returns HTTP 200. Exceptions are caught and wrapped as `coverage_state: unavailable`.

```python
meta   = payload.ad_metadata or {}
match  = match_variant(meta, db)       # → MatchResult
claims = resolve_claims(match, db)     # → list[Claim]
```

### 4. Variant matcher
**`backend/core/matcher.py`** — `match_variant(meta, db)`

Normalizes raw metadata → canonical values:
- `normalize_fuel("Benzinli")` → `"petrol"` (`backend/core/normalize.py:_FUEL_MAP`)
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
**`backend/core/resolver.py`** — `resolve_claims(match, db)`

Queries `claim_variants` join table for all matched variant IDs, returns only
`status='verified'` and `is_current=True` claims.

### 6. Response rendering
**`extension_ui/hover_lite/hover_lite.js`**

Reads `coverage_state`, `risks[]`, `summary`, `disclaimer` from the API response.
Renders the panel overlay with severity-colored risk cards.
Risk cards are in `hover_lite/risk_card.js`. Icons in `hover_lite/icons.js`.

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

`discover.py` writes `status: pending`. `process.py` updates to `status: processed`.
Duplicate guard: `discover.py` scans all curated YAMLs for existing `video_id` before
adding (`_load_known_ids()` in `knowledge/discover.py`).

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

Only writes `disposition == VERIFY` claims. Appends to
`backend/data/claims/{make}_{model}.yaml`. Checks `existing_keys` to avoid duplicates.

Claim ID format: `{make}_{model}_{domain}_{title_first_20}_v1`

### DB sync
**`backend/sync.py`** — `run()`

Upserts all YAML files in `backend/data/variants/` and `backend/data/claims/` into Postgres.
Runs automatically via Dockerfile CMD on container start. Re-trigger:
```bash
docker compose -f deploy/docker-compose.yml restart api
```

Tables: `variants`, `claims`, `claim_variants` (join), `claim_sources`, `analysis_log`.
ORM: `backend/db/models.py`. Session: `backend/db/session.py`.

---

## Data Formats

### Variants YAML (`backend/data/variants/{make}_{model}_{gen}.yaml`)
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

### Claims YAML (`backend/data/claims/{make}_{model}_{gen}.yaml`)
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

2. **YAML is the source of truth, not the DB.** The DB is rebuilt from YAML on every
   `sync.py` run. Never edit the DB directly; edit the YAML.

3. **`AnalysisLog.id` uses `UUID(as_uuid=False)`** (`backend/db/models.py:84`).
   The column is `UUID` in Postgres but stored as a plain string in Python.
   `as_uuid=False` tells psycopg to bind it as the proper Postgres UUID type.

4. **High-severity claims always require human review.** They can be served only
   after a human sets `status: verified` in the claims YAML and restarts the API.

5. **The serving plane never calls an LLM.** `/analyze` only reads the DB. All LLM
   work happens offline in the knowledge plane.

6. **`normalize_fuel()` maps Turkish adjective forms.** "Benzinli" → "petrol",
   not "Benzin". Both are in `_FUEL_MAP` (`backend/core/normalize.py`).

7. **WSL2 + Docker port conflict.** Never run `uvicorn` directly in WSL while Docker
   is up. Both listen on `0.0.0.0:8000` and WSL2 localhost forwarding means Windows
   Chrome will hit whichever bound the port first. The Docker stack is the only correct
   way to run the serving plane.
