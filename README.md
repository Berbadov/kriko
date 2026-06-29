# Kriko

A Chrome extension + FastAPI backend that surfaces known reliability risks for specific used-car variants on Sahibinden.com — **before** the buyer books an expert inspection.

Kriko tells you what to worry about for *this exact engine and gearbox*, predictable from the listing data alone. It is not a generic checklist; it is part-revision-specific signal.

---

## What it shows

- **Maintenance intervals due from mileage** — timing belt at 90k km on K9K, EDC clutch fluid at 60k
- **Known-weak-point failures** — specific to this engine code and transmission hardware
- **"Unless the ad proves otherwise"** flags — if a belt replacement isn't mentioned, treat it as overdue

It does **not** show what a standard pre-purchase inspection already covers (fluid levels, brake wear, compression, warning lights). Those are noise for Kriko's audience.

---

## Live example — Megane 4 1.5 dCi 90hp, 95,000 km

```bash
curl -s http://localhost:8000/analyze -X POST \
  -H "Content-Type: application/json" \
  -d '{
    "ad_metadata": {
      "make": "renault", "model": "megane", "year": 2018,
      "fuel_type": "diesel", "engine_volume_cc": 1461,
      "power_hp": 90, "transmission": "manual", "mileage_km": 95000
    }
  }'
```

**Response summary:** `9 confirmed issues and 1 maintenance item due and 6 unverified reports for megane4_k9k_90`

Top confirmed risks returned:
| Title | Severity | Domain | Strength |
|-------|----------|--------|----------|
| DPF clogging and regeneration failure | high | emissions | confirmed |
| Timing belt and hydraulic lifter failure | high | engine | confirmed |
| Oil pump failure (90hp version) | high | engine | confirmed |
| Crankshaft seizure — longlife oil interval | high | engine | confirmed |
| Injector failure | medium | fuel system | confirmed |
| EGR valve clogging | medium | emissions | confirmed |
| K9K timing belt due at 90,000 km or 5 years | high | engine | **due** |

---

## Architecture

```
Chrome extension  →  POST /analyze
                         │
                    match_variant()       ← variants YAML
                    resolve_claims()      ← claims DB (assembled from parts × fitment)
                         │
                    JSON response (no LLM on request path)
```

### Knowledge plane — the "Lego" system

Research is done once per **part revision**, not per car model. A K9K claim in `backend/data/parts/engine/k9k_90.yaml` automatically applies to every variant that has `engine_family: k9k` in the fitment YAML — Megane 4, Clio 4, Duster, etc.

The pipeline discovers sources from the web and YouTube, runs LLM extraction and quality gates, then promotes claims into part YAMLs:

```
knowledge/catalog/discover.py  --make vw --model golf_7 --write-fitment
                                          # enumerates EA211/EA288/DQ200 from Wikipedia
knowledge/auto.py  --all-parts            # discover + extract + gate all parts at once
                   --part k9k …           # or target a single part
backend/sync.py                           # assemble parts × fitment → Postgres
```

**Part types covered per model:** engine families, gearbox revisions, cooling system, electrical systems.

### File layout

```
backend/
  data/
    variants/renault_megane_4.yaml        # trim configs: cc, hp, fuel, tx, years
    variants/volkswagen_golf_7.yaml
    fitment/renault_megane_4.yaml         # variant_id → engine_family + tx_code + ...
    fitment/volkswagen_golf_7.yaml
    parts/
      engine/k9k_90.yaml                  # K9K 90hp claims
      engine/ea211.yaml                   # VW EA211 TSI claims
      engine/ea288.yaml                   # VW EA288 TDI claims
      transmission/edc.yaml               # Renault EDC dual-clutch claims
      transmission/dq200.yaml             # VW DQ200 7-speed DSG claims
      transmission/dq250.yaml             # VW DQ250 6-speed DSG claims
      cooling/golf7_cool.yaml             # Golf 7 model-wide cooling system
      electrical/golf7_elec.yaml          # Golf 7 model-wide electrical systems
knowledge/
  catalog/discover.py                     # Wikipedia wikitext parser — catalog bootstrap
  auto.py                                 # orchestrator: all-parts mode + single-part
  parts/search_templates.py              # part-centric Exa + YouTube queries
  sources/curated/                        # discovered URLs per part
  cache/                                  # candidate JSON (--skip-extraction reuses this)
```

---

## Setup

### Requirements

- Docker Desktop with WSL2 integration
- Python 3.11+ in WSL
- `MISTRAL_API_KEY` (extraction + gates — `ministral-8b-latest`)
- `EXA_API_KEY` (web source discovery)
- `POSTGRES_PASSWORD` in `deploy/.env`

### Start the stack

```bash
cd ~/kriko
docker compose -f deploy/docker-compose.yml up -d
curl http://localhost:8000/health   # → {"status":"ok","db":"reachable"}
```

### Install offline tools

```bash
pip install -r knowledge/requirements.txt
pip install exa-py yt-dlp trafilatura mistralai
```

### Load the Chrome extension

Chrome → `chrome://extensions` → Developer mode → Load unpacked → select `extension_ui/`

---

## Growing the knowledge base

### Add a new model end-to-end

```bash
# 1. Bootstrap: discovers engine families from Wikipedia, creates variants + fitment YAMLs
python3 -m knowledge.catalog.discover --make volkswagen --model golf_7 --write-fitment

# 2. Run the pipeline for every part type (engine, transmission, cooling, electrical)
#    Auto-creates part stub YAMLs, discovers sources, extracts and gates claims.
python3 -m knowledge.auto --make volkswagen --model golf_7 --all-parts

# 3. Sync to DB
docker exec deploy-api-1 python -m backend.sync
```

### Re-run a single part (e.g. after tuning gates)

```bash
# Re-run gates only — zero token cost, uses cached candidates
python3 -m knowledge.process --part ea211 --part-type engine --skip-extraction

# Full re-run with fresh sources
python3 -m knowledge.auto --part dq200 --part-type transmission
```

### Promote a held claim to verified

Edit the part YAML — change `status: held` → `status: verified`, then re-sync.

### Check what's in the DB

```bash
docker exec deploy-db-1 psql -U postgres -d kriko \
  -c "SELECT claim_key, severity, status FROM claims WHERE status='verified' ORDER BY severity;"
```

---

## Supported cars

| Make | Model | Generation | Engines | Gearboxes |
|------|-------|------------|---------|-----------|
| Renault | Mégane | IV (2016–) | K9K 1.5 dCi · R9M 1.6 dCi · H5F 1.2 TCe · H5H 1.3 TCe | EDC dual-clutch |
| Volkswagen | Golf | VII (2013–2020) | EA211 1.0/1.4 TSI · EA288 1.6/2.0 TDI | DQ200 7-speed DSG · DQ250 6-speed DSG |

Adding a new model: run `knowledge.catalog.discover --write-fitment` to bootstrap, then `knowledge.auto --all-parts`. Part stubs are auto-generated — no hand-writing required.

---

## Docs

- `docs/USAGE.md` — full operational guide
- `docs/INTERNALS.md` — architecture and design decisions
- `docs/pipeline_postmortem.md` — what went wrong in early pipeline iterations and why
- `CLAUDE.md` — product principles and working notes (what Kriko surfaces and why)
