# Kriko — Build Specification (for Claude Code)

## Overview

**What Kriko is:** A browser extension that, on a Sahibinden car listing, shows the buyer the known reliability risks for that exact car variant — each with a severity, a plain-language rationale, inspection advice, and a real source they can click to verify. The product helps people not lose €10–20k on a bad used car.

- **UI:** Already built. Do not build or restyle UI. Your first task is to read the existing extension and make the backend match the response shape it already consumes.


** Everything shouldn't be complex, we need to avoid complexity **
---

## Table of Contents

1. [Prime Directive](#prime-directive)
2. [Build Rules](#build-rules)
3. [Architecture](#architecture)
4. [Stack](#stack)
5. [Repo Structure](#repo-structure)
6. [Serving Plane](#serving-plane)
7. [Database Schema](#database-schema)
8. [Knowledge Plane](#knowledge-plane)
9. [Data Sources](#data-sources)
10. [Deployment](#deployment)
11. [Build Order](#build-order)
12. [Invariants](#invariants)
13. [Human Decisions](#human-decisions)

---

## Prime Directive

**Read before writing any code.**

> Never show a buyer a claim that isn't (a) specific to their exact matched variant and (b) backed by a real, checkable source. The request path never generates text, never calls an LLM, and never searches the web. It is a plain database lookup.

**If you ever find yourself adding an LLM call, a vector search, or a web request to the `/analyze` path, stop — that is the bug this whole design exists to prevent.**

---

## Build Rules

Simple and accessible (hard constraints). These are not suggestions. An agent that "improves" by adding infrastructure has failed.

- **One repo. One backend service. One database (Postgres).** No microservices.
- **No Kafka, Redis, Celery, RabbitMQ, Kubernetes, vector DB, or message queue.** If you think you need one, you don't — write a function or a cron job.
- **The knowledge pipeline is plain Python scripts**, run by hand or by cron. Not a framework, not a DAG engine, not Airflow.
- **Files stay small and readable.** A file over ~200 lines is a smell. A function over ~40 lines is a smell. Prefer boring, obvious code over clever code.
- **Plain SQLAlchemy Core/ORM.** No repository patterns, no DDD layers, no dependency-injection frameworks. A junior dev should understand any file in 5 minutes.
- **Dependencies are minimal** (see §3). Adding a dependency requires a one-line justification in a comment.
- **The LLM is used ONLY in the offline knowledge pipeline**, never on the request path.
- **Every source is a small pluggable adapter** with the same interface, because sources die (assume any source can vanish; the system must shrug and keep serving from what's already verified).

---

## Architecture

### Two Planes

#### Knowledge Plane (offline)
- **Timeline:** Runs in minutes, not milliseconds
- **Allows:** LLM, scripts
- **Flow:** acquire (Tier A/B/C sources) → extract (LangChain) → verify (LLM-as-judge gate) → write VERIFIED, SOURCED, variant-tagged claims into Postgres

#### Serving Plane (online)
- **Timeline:** < 100 ms
- **Tech:** FastAPI
- **Restrictions:** NO LLM, NO web, fully reproducible
- **Flow:** POST /analyze: match listing → variant(s) → read claims → return

**The split is the point:** Completeness is won offline by adding messy sources; accuracy is enforced offline by the gate. The buyer only ever reads the survivors.

---

## Stack

- **Python 3.11+**
- **fastapi, uvicorn** — API
- **sqlalchemy, psycopg[binary]** — DB
- **pydantic v2** — schemas
- **pyyaml** — catalog + claims files
- **httpx, selectolax** — simple scraping in knowledge plane (selectolax = fast, tiny)
- **langchain, langchain-anthropic** — extraction + judge (KNOWLEDGE PLANE ONLY)
- **pytest** — tests
- **Deploy:** Docker + docker-compose + Caddy (automatic HTTPS for kriko.cc). Nothing else.

---

## Repo Structure

```
kriko/
├── extension/                          ← EXISTING UI. Read it; do not rebuild it.
│   └── ... (their files)               ← only change: API endpoint → https://api.kriko.cc/analyze
│
├── backend/
│   ├── api/
│   │   ├── main.py                    # FastAPI app: /analyze, /health, /admin/*
│   │   └── schemas.py                 # AnalyzeRequest / AnalyzeResponse (match the UI)
│   │
│   ├── core/
│   │   ├── matcher.py                 # listing metadata → candidate variant set (strict)
│   │   ├── resolver.py                # variant set → verified claims (intersection on ambiguity)
│   │   └── normalize.py               # Turkish→internal maps (fuel/transmission/make/model)
│   │
│   ├── db/
│   │   ├── models.py                  # SQLAlchemy models
│   │   ├── session.py                 # engine + get_db
│   │   └── schema.sql                 # plain SQL, run once at startup
│   │
│   ├── data/
│   │   ├── variants/                  # variant catalog (one file per model)
│   │   │   └── *.yaml
│   │   └── claims/                    # verified claims (one file per model) — SOURCE OF TRUTH
│   │       └── *.yaml
│   │
│   ├── sync.py                        # load YAML → DB (idempotent). YAML is authoritative.
│   ├── config.py
│   │
│   └── tests/
│       ├── test_matcher.py            # 20+ real Sahibinden listing shapes per model
│       └── test_resolver.py
│
├── knowledge/                          ← offline scripts. LLM lives here.
│   ├── sources/                       # one adapter per source, same interface
│   │   ├── base.py                    # Source protocol + Tier enum
│   │   ├── specialists.py             # Tier A (global repair blogs, parts shops)
│   │   ├── forums.py                  # Tier B (brand & engine specific forums)
│   │   ├── youtube.py                 # Tier C (transcripts) => more noise but abundant
│   │   └── recalls.py                 # Safety-critical only: airbags, brakes
│   │
│   ├── extract.py                     # LangChain: raw text → candidate claims
│   ├── judge.py                       # LLM-as-judge gates (grounding checks only)
│   ├── dedup.py                       # same-claim merge + source independence
│   ├── promote.py                     # weighted corroboration → write verified claims
│   │
│   ├── gold/                          # human-judged claims, for measuring the judge
│   │   └── gold.yaml
│   │
│   └── eval_judge.py                  # run judge vs gold, print accuracy + drift
│
├── deploy/
│   ├── docker-compose.yml
│   ├── Dockerfile
│   └── Caddyfile
│
└── README.md
```

---

## Serving Plane

### 5.1 Response Shape — Match the Existing UI First

**Step 1 of the whole project:** Open the extension files, find where it reads the analyze response, and write `AnalyzeResponse` to match exactly.

```python
# backend/api/schemas.py
from enum import Enum
from pydantic import BaseModel

class CoverageState(str, Enum):
    RISKS_FOUND     = "risks_found"      # matched + ≥1 verified claim
    MATCHED_NO_DATA = "matched_no_data"  # matched, but no verified claims yet
    NOT_MATCHED     = "not_matched"      # couldn't identify the variant
    UNAVAILABLE     = "unavailable"      # error/DB down — explicitly NOT "no problems"

class RiskItem(BaseModel):
    title: str
    severity: str                        # "high" | "medium" | "low"
    domain: str                          # "engine" | "transmission" | "electrical" | ...
    rationale: str
    inspection_advice: str
    sources: list[dict]                  # [{url, channel/site, quote, timestamp_s?}]
    source_count: int                    # how many independent sources back this

class AnalyzeRequest(BaseModel):
    listing_url: str | None = None
    ad_metadata: dict = {}

class AnalyzeResponse(BaseModel):
    coverage_state: CoverageState
    summary: str                         # NEVER asserts the car is reliable
    risks: list[RiskItem] = []
    disclaimer: str                      # always present
    matched_variant_ids: list[str] = []
```

### 5.2 /analyze Endpoint

```python
@app.post("/analyze", response_model=AnalyzeResponse)
def analyze(payload: AnalyzeRequest, db: Session = Depends(get_db)):
    meta = payload.ad_metadata or {}
    try:
        match = match_variant(meta, db)
        claims = resolve_claims(match, db)
    except Exception:
        log_safe(meta, "unavailable")
        return unavailable_response()      # "couldn't check this car" — never an empty clean list

    state = (CoverageState.RISKS_FOUND     if claims else
             CoverageState.MATCHED_NO_DATA if match.variant_ids else
             CoverageState.NOT_MATCHED)

    risks = [claim_to_risk(c) for c in claims]
    resp = AnalyzeResponse(
        coverage_state=state,
        summary=build_summary(state, match, risks),
        risks=risks,
        disclaimer=STANDARD_DISCLAIMER,
        matched_variant_ids=match.variant_ids,
    )
    log_analysis(db, meta, match, claims, resp)   # every call logged
    return resp
```

### 5.3 Matcher (core/matcher.py)

Strict. Never guesses a single winner out of an ambiguous set. Returns a set.

```python
@dataclass
class MatchResult:
    variant_ids: list[str]   # 0, 1, or N. N>1 = real ambiguity, handled by resolver.
    method: str              # "exact"|"ambiguous"|"no_match"|"inconsistent_listing"
    notes: str               # logged, human-readable

def match_variant(meta, db) -> MatchResult:
    make  = normalize_make(meta.get("make"))
    model = normalize_model(meta.get("model"))
    year  = meta.get("year")
    fuel  = normalize_fuel(meta.get("fuel_type"))   # benzin→petrol, lpg/dual→petrol, etc.
    cc    = meta.get("engine_volume_cc")
    hp    = meta.get("power_hp")
    tx    = normalize_transmission(meta.get("transmission"))

    candidates = hard_filter(db, make, model, fuel, year)   # make/model/fuel/year
    if not candidates:
        return MatchResult([], "no_match", f"No {make} {model} {fuel} for {year}.")

    # Seller data is often wrong. If the listing's own (cc,hp,fuel) match no real variant,
    # don't confidently pick the nearest — say so.
    if cc and not any_plausible_engine(candidates, cc, hp):
        return MatchResult([], "inconsistent_listing",
                           f"Listing values (cc={cc}, hp={hp}) match no real variant.")

    candidates = narrow_by_cc(candidates, cc, tol=100)       # each step only narrows
    candidates = narrow_by_power(candidates, hp, tol=10)
    candidates = narrow_by_transmission(candidates, tx)      # soft: skip if unknown

    if len(candidates) == 1:
        return MatchResult([candidates[0].id], "exact", f"Matched {candidates[0].id}")
    return MatchResult([c.id for c in candidates], "ambiguous",
                       f"Ambiguous among {[c.id for c in candidates]}.")
```

### 5.4 Resolver (core/resolver.py) — Intersection on Ambiguity

```python
def resolve_claims(match, db) -> list[Claim]:
    if not match.variant_ids:
        return []
    if len(match.variant_ids) == 1:
        return verified_claims_for(match.variant_ids[0], db)
    # Ambiguous → return only claims verified for EVERY surviving candidate.
    # Safe regardless of which variant it truly is. Unique-to-one claims are withheld.
    sets = [set(c.id for c in verified_claims_for(v, db)) for v in match.variant_ids]
    common = set.intersection(*sets)
    return [load_claim(cid, db) for cid in common]

def verified_claims_for(variant_id, db) -> list[Claim]:
    # Invariants re-checked at QUERY time: status='verified', is_current, ≥1 source, this variant.
    ...
```

### 5.5 Summary + Disclaimer Rules

- `build_summary` may say "X known issues for this variant" or "No known issues in our data for this variant."
- **It must never say or imply "this car is reliable / safe / a good buy."**
- `STANDARD_DISCLAIMER` is always present, e.g.: "Known risks from public sources for this specific variant. Absence of a listed issue does not mean the car is fault-free — always get an independent pre-purchase inspection."
- `MATCHED_NO_DATA` and `UNAVAILABLE` must render differently from `RISKS_FOUND`.
- **"No data" must never look like "clean."**

### 5.6 Observability

Every `/analyze` writes one row to `analysis_log` with:
- Listing fields
- Candidate set
- Matched set
- Coverage state
- Method
- The exact claim IDs returned
- Duration in milliseconds

This is how you answer "why did this risk show for this listing?" and "what did we tell this buyer on this date?"

---

## Database Schema

Plain SQL, applied once at startup. No migration framework until you actually need one.

```sql
CREATE TABLE variants (
  id TEXT PRIMARY KEY,                 -- "megane4_h5h_140"
  make TEXT NOT NULL, 
  model TEXT NOT NULL, 
  generation TEXT,
  engine_code TEXT, 
  fuel TEXT NOT NULL,
  displacement_cc INT, 
  power_min_hp INT, 
  power_max_hp INT, 
  transmission TEXT,
  year_from INT NOT NULL, 
  year_to INT,
  market TEXT DEFAULT 'TR', 
  notes TEXT
);
CREATE INDEX idx_variants_lookup ON variants(make, model, fuel);

CREATE TABLE claims (
  id TEXT PRIMARY KEY,                 -- per version
  claim_key TEXT NOT NULL,             -- stable across versions
  version INT NOT NULL DEFAULT 1, 
  is_current BOOLEAN NOT NULL DEFAULT true,
  title TEXT NOT NULL, 
  domain TEXT NOT NULL,
  severity TEXT NOT NULL,              -- high|medium|low
  confidence REAL NOT NULL,            -- DERIVED from tier+source_count
  rationale TEXT NOT NULL, 
  inspection_advice TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'draft', -- draft|verified|held|rejected
  promoted_by TEXT,                    -- 'auto' | reviewer name
  created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_claims_serve ON claims(is_current, status);

CREATE TABLE claim_variants (
  claim_id TEXT REFERENCES claims(id) ON DELETE CASCADE,
  variant_id TEXT REFERENCES variants(id) ON DELETE CASCADE,
  grounding_note TEXT,                 -- WHY this claim attaches to this variant
  PRIMARY KEY (claim_id, variant_id)
);
CREATE INDEX idx_cv_variant ON claim_variants(variant_id);

CREATE TABLE claim_sources (
  id SERIAL PRIMARY KEY,
  claim_id TEXT REFERENCES claims(id) ON DELETE CASCADE,
  tier TEXT NOT NULL,                  -- 'A'|'B'|'C'
  source_url TEXT NOT NULL, 
  source_domain TEXT, 
  site_or_channel TEXT,
  title TEXT, 
  timestamp_s INT,
  quote TEXT NOT NULL,                 -- verbatim, checked by judge
  independent BOOLEAN DEFAULT true
);

CREATE TABLE analysis_log (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(), 
  created_at TIMESTAMPTZ DEFAULT now(),
  listing_url TEXT, 
  make TEXT, 
  model TEXT, 
  year INT, 
  fuel_type TEXT,
  engine_cc INT, 
  power_hp INT, 
  transmission TEXT,
  candidate_variant_ids TEXT[], 
  matched_variant_ids TEXT[],
  coverage_state TEXT, 
  match_method TEXT, 
  match_notes TEXT,
  claim_ids_returned TEXT[], 
  claims_returned INT, 
  duration_ms INT
);
```

**Served claim invariant** (checked in resolver.py, not trusted from the DB):
- `status='verified'` AND `is_current` AND ≥1 `claim_sources` row AND a `claim_variants` row

---

## Knowledge Plane

### 7.1 Three Layers

1. **Acquire:** sources/*.py pull raw text for a (make, model) → returned as Document{text, url, tier, meta}
2. **Extract:** extract.py (LangChain) turns each Document into 0..N CandidateClaim (structured)
3. **Verify:** judge.py runs grounding gates; promote.py applies tier rules → verified claims

### 7.2 Source Adapter Interface (sources/base.py)

Every source is the same tiny shape. Sources die — when one throws, log and continue.

```python
from enum import Enum

class Tier(str, Enum):
    A = "A"
    B = "B"
    C = "C"

@dataclass
class Document:
    text: str
    url: str
    tier: Tier
    site_or_channel: str
    meta: dict          # e.g. {"model_hint": "...", "engine_hint": "K9K"}

class Source(Protocol):
    tier: Tier
    def fetch(self, make: str, model: str) -> list[Document]: ...
```

### 7.3 Extraction (extract.py)

Use LangChain structured output with a Pydantic schema. The model's job is only to turn messy text into a structured candidate + the verbatim quote it came from. Accuracy is the gate's job, not extraction's.

```python
class CandidateClaim(BaseModel):
    title: str
    domain: str
    severity: str                  # high|medium|low (provisional; reviewer/gate can adjust)
    rationale: str
    inspection_advice: str
    quote: str                     # VERBATIM span from the source text
    engine_or_variant_hint: str | None  # e.g. "1.3 TCe", "H5H", "K9K", or null
```

**System prompt:** Extract only concrete, checkable reliability issues; copy the supporting quote verbatim; if the text names an engine/variant, fill engine_or_variant_hint; do NOT invent.

### 7.4 The Gate (judge.py) — Grounding Checks Only

The judge only ever asks grounded questions (text vs text). It never judges truth-about-the-world. Each is a tiny, cheap LLM call returning a yes/no + reason.

| Gate Function | Question |
|---|---|
| `gate_support(claim, quote)` | Does this quote actually support this claim? |
| `gate_variant(claim, quote, candidate_variants)` | Which of these variants does the quote actually justify? |
| `gate_generic(claim)` | Is this just generic boilerplate true of all cars? |
| `gate_refute(claim, quote)` | Try to refute this claim from this quote. |

### 7.5 Promotion Rules (promote.py) — Weighted Corroboration

Tier and corroboration are two different things:
- **Tier** = source quality
- **Corroboration** = independence (how many unrelated sources vouch for the same claim)

Engines are global. We harvest global specialist sources and let them corroborate.

**Weights per independent source that passed `gate_support`:**

| Tier | Weight | Example |
|---|---|---|
| A | ~1.0 | Specialist repair sources, engine remanufacturers, parts shops |
| B | ~0.5 | Owner/engine forums, brand subreddits |
| C | ~0.34 | YouTube mechanic video transcripts, blog anecdotes |

**Scoring:**
- `score = sum(weight of each independent backing source)`
- `score ≥ 1.0` → **VERIFY (auto)**, confidence scaled from score (clamp ~0.6–0.9)
- `0.5 ≤ score < 1.0` → **HUMAN review**
- `score < 0.5` → **HELD** (never served) until more independent corroboration arrives

**Overrides (always win):**
- `severity == "high"` → HUMAN review regardless of score
- `gate_variant` returned `[]` → HELD (can't ground a variant)
- `gate_refute` disagreed → HUMAN review
- `gate_generic` flagged → REJECT

Auto-verified claims carry `promoted_by='auto'`; **20% are sampled into a review queue to measure the real error rate.**

### 7.5a Independence + Deduplication (dedup.py)

Weighting independent sources only works if you can (1) tell that two differently-worded candidates are the same claim and (2) tell that multiple items are just one viral claim reposted.

```python
def same_claim(a: CandidateClaim, b: CandidateClaim) -> bool:
    # "Do these describe the SAME underlying issue?" → merge into one claim, union their sources.
    # Start with: ask the LLM (volume is low, hundreds per model).
    # If that gets slow: embeddings + in-memory cosine (plain numpy, no DB).
    ...

def is_independent(a_source, b_source) -> bool:
    # Two sources are NOT independent if any of: same domain, same channel, same author,
    # or near-identical wording/specific details. Derivative repeats collapse to a SINGLE source.
    ...
```

**Counting order in promote.py:**
1. Merge same-claim candidates
2. Collapse non-independent sources
3. Sum weights

### 7.6 The Gold Set + Calibration Loop

`knowledge/gold/gold.yaml` holds 100–300 claims a human has personally judged correct/incorrect.

`eval_judge.py` runs the gates over the gold set and prints precision/recall + which gate failed.

We measure the judge and tune thresholds/prompts when it drifts.

---

## Data Sources

Facts aren't copyrightable ("the K9K has injector issues" is a fact), but scraping against a site's ToS is a separate contract issue. For forums/YouTube/blogs, store only the extracted claim + a short quote + the link, never whole pages. Treat every source as possibly-dead and build adapters that fail gracefully.

### Tier A — Specialist Repair & Technical Sources

Authoritative, variant-level domain expertise. Written by professionals who physically open and repair these engines global-wide. One good source can ground a claim if corroborated.

| Source Type | What it gives | Target Examples |
|---|---|---|
| Independent Garage & Mechanic Blogs | Direct failure breakdowns split by variant, engine code, and power output. | gaga.ba (Bosnian mechanic profiling variant differences), balancemotorworks.co.uk |
| Parts-Supplier Technical Blogs | Technical bulletins regarding known weak design components. | autoricambitritella.it (Italian parts-shop technical teardowns) |
| Engine Remanufacturers & Teardowns | Typical failure modes that require complete engine rebuilds. | enginefinders.co.uk (timing chain, EGR, turbo failures) |

### Tier B — Semi-Structured Owner & Engine Forums

Medium-noise, highly specific. Real diagnostic threads containing anecdotal data; requires ≥2 independent sources to clear thresholds.

| Source | Notes |
|---|---|
| Global Dedicated Forums | Often discuss problems directly by engine code. Examples: renaultforums.co.uk, daciaforum.co.uk, cliosport.net, forum-auto.caradisiac.com |
| Local Turkish Forums | Identifies local-market specific symptoms, fuel quality interactions. |
| Reddit | Community tracking via technical subreddits. Respect API/ToS constraints. Examples: reddit.com/r/MechanicAdvice/ |

### Tier C — High-Recall, High-Noise (Discovery Only)

**Never served uncorroborated.** Used to discover symptoms, which are held until Tier A or Tier B sources corroborate them.

| Source | Notes |
|---|---|
| YouTube Mechanic Transcripts | Abundant, local (Turkish mechanics), highly variant-specific. Mechanics routinely state precise engine codes. |
| Blog Reviews & Owner Anecdotes | General long-term ownership write-ups tracking minor electrical or trim defects. |

### Recalls — Narrow Safety Adapter

Demoted to a thin, automated script mapping strictly safety-critical manufacturer recalls (airbags, major braking failures). Completely blind to mechanical wear components like EGR, DPF, or injectors.

**Sources:** Manufacturer VIN lookup pages (Renault, Toyota, VW TR), EU recalls aggregator (car-recalls.eu), and GÜBİS (restricted to safety defects).

---

## Deployment

### Simple: Single Small VPS

Two containers (api + postgres) + Caddy for automatic HTTPS. Knowledge plane runs as manual/cron scripts on the same box, not as a service.

**Caddyfile:**
```caddyfile
api.kriko.cc {
    reverse_proxy api:8000
}

kriko.cc {
    respond "Kriko" 200
}
```

**docker-compose.yml:**
```yaml
services:
  db:
    image: postgres:16
    environment:
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - pgdata:/var/lib/postgresql/data

  api:
    build: .
    env_file: .env
    depends_on:
      - db
    command: uvicorn api.main:app --host 0.0.0.0 --port 8000

  caddy:
    image: caddy:2
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile
      - caddydata:/data

volumes:
  pgdata: {}
  caddydata: {}
```

### Wiring the Extension

- Point background.js fetch calls at `https://api.kriko.cc/analyze`
- Add `https://api.kriko.cc/*` to the extension manifest `host_permissions`
- Set CORS on the FastAPI app to allow the extension origin (`chrome-extension://<your-extension-id>`)
- `/health` returns `{ "status": "ok", "db": "reachable" }`

---

## Build Order

**Do it in this sequence.**

### Phase 1: UI + Schema
1. **Read the existing extension.** Pin down the exact response shape it consumes. Write `schemas.py` to match.

### Phase 2: Serving Plane Foundation
2. **Postgres + schema.sql + session.py + /health**

### Phase 3: Catalog & Matcher
3. **Catalog for ONE model** (Renault Megane 4) in `data/variants/`. Hand-write it from spec sheets.
4. **Add the catalog linter (CI):** within one (make, model, fuel, year), no two variants may overlap on both cc and power range — fail the build if they do.
5. **normalize.py + matcher.py + test_matcher.py** with 20+ real Sahibinden listing shapes.

### Phase 4: Claims & Resolver
6. **Seed ~5 claims by hand** in `data/claims/renault_megane_4.yaml`; `sync.py` loads YAML→DB.
7. **resolver.py (intersection) + /analyze end to end.** Smoke-test 5 real listings.

### Phase 5: Deploy & Validate
8. **Deploy to api.kriko.cc, wire the extension.** Done-1 = **10 consecutive real listings with zero confident wrong matches** (no-match/ambiguous is allowed; wrong match is not).

### Phase 6: Knowledge Plane
9. **Build the knowledge plane:** sources/base.py + youtube.py (Tier C) + specialists.py (Tier A) + recalls.py → extract.py → judge.py → promote.py. Build the gold set; run eval_judge.py.

### Phase 7: Grow & Repeat
10. **Grow Megane 4 to 20+ verified claims**, then repeat steps 3–9 per model (Clio 4 → RAV4 Hybrid → Golf 7 → 208/308). A model with no verified claims returns `MATCHED_NO_DATA`.

---

## Invariants

**Never break these.**

- **Request path:** no LLM, no web, no vector search. DB read only.
- **Matcher:** Never collapses an ambiguous set to a guessed single match. Resolver intersects.
- **Served claim:** Must be verified + is_current + ≥1 source + ≥1 variant (re-checked at query time)
- **UI language:** "No data" and "unavailable" never render as "no problems." Summary never asserts reliability.
- **DB failure:** → UNAVAILABLE, never an empty (apparently-clean) result.
- **Source of truth:** YAML in git is the source of truth; sync.py is one-way YAML→DB. Tooling edits YAML.
- **Variant IDs:** Stable forever. Add variants; never rename a live one.
- **CI gate:** Catalog linter is a hard CI gate.
- **Corroboration:** A claim is served only when its weighted corroboration score clears the threshold from independent sources; a single uncorroborated source (any tier) is never served.
- **Observability:** Every `/analyze` writes analysis_log with the exact claim IDs returned.

---

## Human Decisions

**The agent must not make these alone. Leave `# HUMAN DECISION` comments:**

1. Whether the existing UI renders all four `coverage_state` values; if not, flag it.
2. Auto-promote thresholds and the audit sample rate (§7.5) — risk appetite, not a code default.
3. Whether to show a confidence number to buyers at all, or just severity + "backed by N sources."
4. Final legal disclaimer wording.
5. Which exact forums/subreddits are in-scope per model (liveness + ToS) before their adapter ships.
