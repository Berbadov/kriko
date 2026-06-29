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
                    match_variant()       ← variants YAML (7 Megane 4 configs)
                    resolve_claims()      ← claims DB (assembled from parts × fitment)
                         │
                    JSON response (no LLM on request path)
```

### Knowledge plane — the "Lego" system

Research is done once per **part revision**, not per car model. A K9K claim in `backend/data/parts/engine/k9k.yaml` automatically applies to every variant that has `engine_family: k9k` in the fitment YAML — Megane 4, Clio 4, Duster, etc.

```
knowledge/catalog/discover.py          # Step 1: given "megane_4", enumerate K9K/H5F/R9M/EDC
knowledge/auto.py  --part k9k …        # Step 2: discover web + YouTube sources for K9K
knowledge/process.py --part k9k …      # Step 3: extract → gate → score → write k9k.yaml
backend/sync.py                        # Step 4: assemble parts × fitment → DB
```

### File layout

```
backend/
  data/
    variants/renault_megane_4.yaml     # 7 engine/trim configs with cc/hp/year ranges
    fitment/renault_megane_4.yaml      # variant_id → engine_family + transmission_code
    parts/
      engine/k9k.yaml                  # K9K claims (9 verified, 7 review)
      engine/r9m.yaml                  # R9M 1.6 dCi claims
      engine/h5f.yaml                  # H5F 1.2 TCe claims
      engine/h5h.yaml                  # H5H 1.3 TCe claims
      transmission/edc.yaml            # EDC dual-clutch claims (10 verified)
    claims/renault_megane_4.yaml       # legacy flat claims (93 rejected/parked)
knowledge/
  catalog/discover.py                  # Wikipedia wikitext parser — catalog bootstrap
  parts/search_templates.py           # part-centric Exa + YouTube queries
  sources/curated/                    # discovered URLs per part, status=pending|processed
  cache/                              # candidate JSON cache (--skip-extraction)
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

### Discover a new model's parts

```bash
python -m knowledge.catalog.discover --make renault --model megane_4
# → H5Ft (h5f, petrol), K9K (k9k, diesel), R9M (r9m, diesel), EDC (transmission) …
```

### Run the pipeline for a part

```bash
# Full run: discover → fetch → extract → gate → promote → sync
python -m knowledge.auto --part k9k --part-type engine --fuel diesel

# Re-run gates only (zero token cost — uses cached candidates)
python -m knowledge.process --part k9k --part-type engine --skip-extraction
```

### Sync to DB after any YAML edit

```bash
docker exec deploy-api-1 python -m backend.sync
```

### Promote a held claim to verified

Edit `backend/data/parts/engine/k9k.yaml` — change `status: held` → `status: verified`, then re-sync.

### Check what's in the DB

```bash
docker exec deploy-db-1 psql -U postgres -d kriko \
  -c "SELECT claim_key, severity, status FROM claims WHERE status='verified' ORDER BY severity;"
```

---

## Supported cars

| Make | Model | Generation | Engines |
|------|-------|------------|---------|
| Renault | Mégane | IV (2016–) | K9K 1.5 dCi · R9M 1.6 dCi · H5F 1.2 TCe · H5H 1.3 TCe |

Adding a new model: create `backend/data/variants/{make}_{model}.yaml`, `backend/data/fitment/{make}_{model}.yaml`, run `knowledge.catalog.discover` to get part codes, run `knowledge.auto --part` for each part, then re-sync.

---

## Docs

- `docs/USAGE.md` — full operational guide
- `docs/INTERNALS.md` — architecture and design decisions
- `docs/pipeline_postmortem.md` — what went wrong in early pipeline iterations and why
- `CLAUDE.md` — product principles and working notes (what Kriko surfaces and why)
