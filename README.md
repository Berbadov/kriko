# Kriko

A Chrome extension + FastAPI backend that surfaces known reliability risks for specific
used-car variants on Sahibinden.com — **before** the buyer books an expert inspection.

Kriko tells you what to worry about for *this exact engine and gearbox*, predictable from
the listing data alone. It is not a generic checklist; it is part-revision-specific signal.

---

## Design principles (read before contributing)

The two rules that shape every decision live in `CLAUDE.md`; the short version:

1. **Product principle — high-value claims only.** Surface config- and mileage-specific
   known risks a buyer can't cheaply get from the standard pre-purchase inspection.
   If the ekspertiz would catch it anyway (fluids, brake wear, warning lights), it's noise.
2. **Scalability principle — no hardcoded car data, no orphan patches.** Anything that
   grows with car coverage must be *derived from the catalog YAMLs*, never hand-enumerated
   in Python. And every per-model fix must ship with the mechanism (validation, coverage
   report, telemetry) that catches the same class of problem on every future car —
   patching car #3 by hand doesn't scale to car #400.

Task tracking: open work in [`backlog.md`](backlog.md) (goals + prioritized items),
finished work in [`done.md`](done.md).

---

## What it shows

- **Maintenance intervals due from mileage** — timing belt at 90k km on K9K, DSG service
  on high-mileage DQ250; flagged "due unless the ad proves otherwise"
- **Known-weak-point failures** — specific to this engine code and gearbox revision,
  gated by mileage/age/model-year windows where the evidence supports one
- **Two clearly-separated strengths** — corroborated claims show as *Confirmed*;
  single-source community reports show as *Reported*, never blurred together

It does **not** show what a standard pre-purchase inspection already covers, and a
per-listing cap keeps the panel readable instead of encyclopedic.

---

## Architecture

```
Chrome extension  →  POST /analyze
                         │
                    match_variant()       ← variants YAML (make/model/fuel/year/cc/hp/tx)
                    resolve_claims()      ← claims DB (assembled from parts × fitment)
                    context gates         ← mileage, age, model-year, equipment, ad-stated tx
                    rank + cap            ← consequence tier, max risks per listing
                         │
                    JSON response (no LLM on request path, <10ms)
```

Two planes, never talking at runtime — YAML is the handoff:

- **Knowledge plane** (offline, LLM-powered): discovers sources, extracts candidate
  claims, gates them, writes part YAMLs.
- **Serving plane** (FastAPI + Postgres/SQLite): assembles part claims per variant at
  sync time, answers `/analyze` with plain DB reads.

### The "Lego" system

Research is done once per **part revision**, not per car model. A claim in
`backend/data/parts/engine/ea211.yaml` automatically applies to every variant of every
model whose fitment row says `engine_family: ea211` — onboarding a new EA211-engined car
inherits the research for free.

### File layout

```
backend/
  core/                                   # matcher, resolver, normalize, gates
  api/main.py                             # /analyze endpoint, risk ranking + cap
  sync.py                                 # YAML → DB assembly (with grounding guards)
  data/
    variants/{make}_{model}.yaml          # trim configs: cc, hp, fuel, tx, years
    fitment/{make}_{model}.yaml           # variant_id → engine_family/tx_code/... (derived from variants)
    parts/
      engine/       ea211 ea288 ea888 k9k_* h5h_* h5f_* h5d_* h4d_* r9m_*
      transmission/ dq200 dq250 dq381 dc4 dw5 dw6
      electrical/   golf7_elec megane4_elec clio5_elec
      body/         golf7_body megane4_body clio5_body
knowledge/
  catalog/                                # Wikipedia bootstrap, variants/fitment writers
  auto.py                                 # orchestrator: discover → extract → gate → promote
  process.py                              # re-run gates on cached candidates (no token cost)
  ledger/                                 # evidence-ledger pipeline (Stage 1, on its own branch)
extension_ui/                             # Chrome extension (content.js scraper + panel)
logs/analyses.jsonl                       # every /analyze request+response (see backend.tools.analyses)
```

---

## Setup

### Requirements

- Python 3.11+ (WSL); Docker Desktop optional — see `scripts/run_local.sh` for a
  no-Docker SQLite mode
- `MISTRAL_API_KEY` (extraction + judge gates — `ministral-8b-latest`)
- `EXA_API_KEY` (web source discovery)
- Keys live in the repo-root `.env` (pipeline) and `deploy/.env` (Docker stack)

### Start the API

```bash
# With Docker (Postgres):
docker compose -f deploy/docker-compose.yml up -d
curl http://localhost:8000/health

# Without Docker (SQLite, port 8077):
./scripts/run_local.sh
```

### Connect with DBeaver (Postgres)

The Kriko Postgres is exposed on host port **5433** (not 5432 — another project on this
machine owns 5432). Create a new PostgreSQL connection in DBeaver with:

| Setting | Value |
|---------|-------|
| Host | `localhost` (or `127.0.0.1`) |
| Port | `5433` |
| Database | `kriko` |
| Username | `postgres` |
| Password | `kriko_dev` |
| JDBC URL | `jdbc:postgresql://localhost:5433/kriko` |

Tables: `variants`, `claims`, `claim_sources`, `claim_variants`, `analysis_log`.

The password comes from `POSTGRES_PASSWORD` in `deploy/.env`; the port mapping lives in
`deploy/docker-compose.yml` (`db` service → `5433:5432`). If you change either, update
this table too.

### Load the Chrome extension

Chrome → `chrome://extensions` → Developer mode → Load unpacked → select `extension_ui/`

### Tests

```bash
python -m pytest backend knowledge     # Python (serving + pipeline)
npm test                               # extension scraper (jsdom fixtures)
```

---

## Growing the knowledge base

```bash
# 1. Bootstrap a new model: variants scaffold + fitment derived from it
python3 -m knowledge.catalog.discover --make volkswagen --model golf_7 --write-variants
#    → human fills in per-market hp/years, removes `draft: true` (sync refuses drafts)
python3 -m knowledge.catalog.discover --make volkswagen --model golf_7 --write-fitment

# 2. Run the pipeline per part (or --all-parts)
python3 -m knowledge.auto --part dq200 --part-type transmission

# 3. Re-run gates only — zero token cost, uses cached candidates
python3 -m knowledge.process --part dq200 --part-type transmission --skip-extraction

# 4. Sync to DB
python3 -m backend.sync          # (inside the api container when using Docker)
```

Full operational detail — including promoting/tombstoning claims, replaying logged
requests, and the debug endpoints — is in `docs/USAGE.md`.

---

## Supported cars (TR market)

| Make | Model | Generation | Engines | Gearboxes |
|------|-------|------------|---------|-----------|
| Renault | Mégane | IV (2016–2023) | K9K 1.5 dCi · R9M 1.6 dCi · H5F 1.2 TCe · H5H 1.3 TCe | manual · DC4 EDC · DW5/DW6 EDC* |
| Renault | Clio | V (2019–) | H4D 1.0 SCe · H5D 1.0 TCe · H5H 1.3 TCe · K9K 1.5 dCi | manual · DC4 EDC |
| Volkswagen | Golf | VII (2013–2020) | EA211 1.0/1.2/1.4 TSI · EA288 1.6/2.0 TDI · EA888 2.0 TSI (GTI/R) | manual · DQ200 · DQ250 · DQ381 DSG |

\* DW5/DW6 (7/6-speed wet EDC) part files exist but are **unresearched stubs** — automatic
1.3 TCe / 1.6 dCi Méganes currently get no gearbox claims. Tracked as backlog B2/B3.

---

## Docs

| Doc | Contents |
|-----|----------|
| `backlog.md` / `done.md` | Task tracking — goals, open items, finished work |
| `CLAUDE.md` | Product + scalability principles, doc map, working rules |
| `docs/USAGE.md` | Full operational guide (stack, pipeline, claim lifecycle) |
| `docs/INTERNALS.md` | Mechanism-level architecture reference |
| `docs/design_flaws.md` | The 2026-07-04 audit — root causes behind claim mismatches |
| `docs/overhaul_plan.md` / `docs/claim_relevance_plan.md` | Claim-quality roadmap |
| `docs/pipeline_postmortem.md` | Early pipeline history (what failed and why) |

`docs/handover.md`, `docs/SCAFFOLD.md`, and `kriko_build_plan.md` predate the
part-centric system — historical context only, don't follow their instructions.
