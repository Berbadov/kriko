# Kriko — Usage Guide

Kriko is a Chrome extension that surfaces known reliability risks for used cars on Sahibinden.com.
This guide covers everything from starting the stack to growing the knowledge base.

---

## Prerequisites

- **Docker Desktop** running (with WSL2 integration enabled)
- **Python 3.11+** in WSL (for the offline knowledge tools)
- **uv** recommended: `pip install uv` — fast package manager
- **MISTRAL_API_KEY** — LLM extraction + judge gates (`ministral-8b-latest`)
- **EXA_API_KEY** — web source discovery (Exa neural search)

---

## 1. Start the API + Database

```bash
cd ~/kriko
docker compose -f deploy/docker-compose.yml up -d
```

Check it's healthy:
```bash
curl http://127.0.0.1:8000/health
# → {"status":"ok","db":"ok"}
```

Stop everything:
```bash
docker compose -f deploy/docker-compose.yml down
```

> The API restarts automatically on Docker Desktop launch (`restart: unless-stopped`).
> Don't run `uvicorn` directly in WSL — it will conflict with the Docker port binding.

---

## 2. Chrome Extension

1. Open Chrome → `chrome://extensions` → enable **Developer mode**
2. Click **Load unpacked** → select `~/kriko/extension_ui/`
3. Visit any Sahibinden.com listing for a supported car (Renault Megane IV)
4. The Kriko panel appears automatically after ~1.5 seconds

After any code change to `extension_ui/`:
```bash
# Chrome → chrome://extensions → click the reload (↺) button on Kriko
```

---

## 3. Install knowledge pipeline tools (one-time)

```bash
cd ~/kriko
pip install -r knowledge/requirements.txt
pip install exa-py yt-dlp trafilatura mistralai
```

Set keys in `deploy/.env` and export locally:
```bash
export MISTRAL_API_KEY=...
export EXA_API_KEY=...
```

---

## 4. Add a new car model (part-centric "Lego" pipeline)

Kriko researches each **part revision** once (K9K engine, EDC gearbox) and assembles
claims per variant at sync time. Adding a new model is four steps:

**Step 1 — Variants YAML** — what configs exist

Create `backend/data/variants/{make}_{model}.yaml`. Copy from `renault_megane_4.yaml`.
Each row is one engine/trim combination with cc, hp, year range, fuel, transmission.

**Step 2 — Catalog discovery** — enumerate the part codes

```bash
python -m knowledge.catalog.discover --make renault --model megane_4
# → K9K (k9k, diesel), H5H (h5h, petrol), EDC (edc, transmission) …
```

This reads the Wikipedia article for the model and extracts engine codes from the infobox.
Use `--write-fitment --dry-run` to preview the fitment YAML it would generate.

**Step 3 — Fitment YAML** — map variant_id → part codes

Create `backend/data/fitment/{make}_{model}.yaml`:
```yaml
- variant_id: megane4_k9k_90
  engine_family: k9k
  transmission_code: manual

- variant_id: megane4_h5h_140
  engine_family: h5h
  transmission_code: edc
```

**Step 4 — Run the pipeline per part**

```bash
# Full run: Exa/YouTube discovery → fetch → LLM extract → gate → promote → sync
python -m knowledge.auto --part k9k --part-type engine --fuel diesel
python -m knowledge.auto --part edc --part-type transmission

# Re-run gates/promotion only — zero fetches, zero extraction tokens
python -m knowledge.process --part k9k --part-type engine --skip-extraction
```

**Step 5 — Sync to DB**

```bash
docker exec deploy-api-1 python -m backend.sync
```

Part claims (from `backend/data/parts/`) are assembled into variant links using the
fitment YAML. The serving plane (`/analyze`) is unchanged.

---

## 5. Discover YouTube sources (model-centric legacy mode)

```bash
python -m knowledge.discover "megane 4 1.5 dCi arıza" --make renault --model megane --gen 4
```

| Key | Action |
|-----|--------|
| `↑↓` | Navigate results |
| `Enter` | Fetch transcript for selected video |
| `A` | Approve — adds to curated YAML as `status: pending` |
| `S` | Skip — marks in session only, no file write |
| `T` | View full transcript in scrollable overlay |
| `F5` | New search (focuses query input) |
| `Q` | Quit |

Status column: `·` not reviewed · `✓` approved · `—` skipped · `✗` already in YAML

After the session, approved videos sit in `knowledge/sources/curated/{make}_{model}_{gen}.yaml`
with `status: pending`.

---

## 6. Add page sources manually

Edit `knowledge/sources/curated/{make}_{model}_{gen}.yaml` directly and append:

```yaml
- type: page
  url: "https://www.enginefinders.co.uk/renault-1-5-dci-k9k-engine-problems"
  site_or_channel: "enginefinders.co.uk"
  notes: "K9K injector fouling — specialist remanufacturer"
  status: pending
  added_at: "2026-06-26"
  processed_at: null
```

All sources carry equal weight — the LLM gates (gate_support, gate_refute, gate_variant) are the sole quality filter.

A claim needs **≥ 2 independent sources** that pass all gates to auto-verify. A single source lands in `review` (human must confirm).

---

## 7. Process pending sources

```bash
# Preview (no writes)
python -m knowledge.process renault megane 4 --dry-run

# Full run
python -m knowledge.process renault megane 4

# Re-run gates/promotion on cached candidates — zero fetches, zero extraction LLM calls
python -m knowledge.process renault megane 4 --skip-extraction
```

This runs: fetch → LLM extract → dedup → gate → score → write claims YAML → sync DB.
Extracted candidates are cached to `knowledge/cache/{make}_{model}_{gen}_candidates.json`;
`--skip-extraction` replays the cache, so tuning gates/thresholds costs no tokens.
High-severity claims always go to manual review regardless of score.

After processing, the API container auto-reloads via the Docker `restart` policy. If it
doesn't pick up new claims immediately:
```bash
docker compose -f deploy/docker-compose.yml restart api
```

### What buyers see (serving model)

The pipeline writes claims to the YAML with a `status` field. The extension shows **two
strengths**, never blurring them (`backend/core/resolver.py`, `_servable_claims_for`):

| Status | Shown as | Meaning |
|--------|----------|---------|
| `verified` | **Confirmed** (green badge) | corroborated — ≥2 independent sources, or a hand-vetted seed claim |
| `review`   | **Reported · N source(s)** (amber) | cleared the gates but thin/high-severity — shown for awareness, not asserted |
| `held`     | **Reported · N source(s)** (amber) | genuine but thinly corroborated (zero sources passed gates) |
| `rejected` | not served | tombstoned junk |
| `draft`    | not served | not pipeline output |

Only claims with **≥1 grounded source** are served, so ungrounded score-0 noise (e.g. generic
OBD-code dumps) never reaches a buyer. The `/analyze` summary counts "confirmed issues" and
"unverified reports" separately and never calls a single-source report a known issue.

> **Why we serve unverified reports:** corroboration (≥2 sources) is scarce for niche reliability
> topics. Rather than show an empty panel, we surface single-source reports *clearly labelled* so
> the cards signal the general picture, while the `Confirmed` badge stays trustworthy.
> Verification still needs ≥2 independent sources — we do **not** lower that bar.

### Promoting & rejecting claims (human step)

Edit `backend/data/claims/{make}_{model}.yaml` by hand — it's a **one-line change** per claim:

- **Promote:** set `status: review` (or `held`) → `status: verified`, and optionally
  `promoted_by: human`. It then shows as **Confirmed**.
- **Reject junk:** set `status: rejected`. This **tombstones** it — a later pipeline re-run
  will *not* re-add the claim. Prefer this over deleting the lines.
- **Delete:** removing a claim from the YAML now also removes it from the DB on next sync
  (`sync.py` prunes rows no longer present), so a mis-grounded claim stops serving. Tombstoning
  is still safer than deleting if you want the junk to stay suppressed across re-extraction.

Re-running the pipeline never overwrites an existing claim_key, so your edits are safe.
Re-sync after editing: `python -m knowledge.process … --skip-extraction` (or restart the api
container) to push the new statuses into the DB.

> Fuel grounding: a fuel-specific claim (K9K/dCi → diesel, TCe/H5x → petrol, AdBlue → diesel)
> is grounded only to same-fuel variants, so a diesel issue never shows on a petrol listing.
> Fuel-agnostic claims (A/C, electrical) stay grounded across all variants.

> Note: a `held` claim does not automatically upgrade when a new source corroborates it in a
> later run — cross-run score accumulation is out of scope. Promote held claims manually.

---

## 8. Check the database

```bash
# All claims in DB
docker exec deploy-db-1 psql -U postgres -d kriko \
  -c "SELECT id, title, severity FROM claims WHERE status='verified';"

# Recent analysis log (what the extension queried)
docker exec deploy-db-1 psql -U postgres -d kriko \
  -c "SELECT make, model, coverage_state, claims_returned, created_at FROM analysis_log ORDER BY created_at DESC LIMIT 10;"

# Variants
docker exec deploy-db-1 psql -U postgres -d kriko \
  -c "SELECT id, fuel, displacement_cc, power_min_hp FROM variants;"
```

`analysis_log` above only has IDs and counts. For the full request/response payload
(what a specific buyer actually saw, and why — mileage/equipment/description that drove
gating), read `logs/analyses.jsonl` instead — no `docker exec`/psql needed:

```bash
# Last 20 analyses, one-line summaries
python -m backend.tools.analyses --last 20

# Filter by model, full JSON per record
python -m backend.tools.analyses --last 20 --model golf --json

# Re-run a logged request through the CURRENT pipeline and diff the result —
# use this to confirm a promote.py/gate/fitment fix actually changed the served
# claims for a request that was previously wrong.
python -m backend.tools.replay <analysis-id>
python -m backend.tools.replay --last 5
```

`GET /debug/analyses?limit=20&model=golf` exposes the same JSONL over HTTP, but is
**off (404) by default** — it dumps full request/response history, so only set
`ENABLE_DEBUG_ENDPOINT=true` in `deploy/.env` temporarily if you don't have shell
access to the deploy host.

---

## 9. Eval the LLM gates (optional)

```bash
OPENROUTER_API_KEY=... python -m knowledge.eval_judge
```

Runs the 2-gate check (generic + support) over `knowledge/gold/gold.yaml` and prints
precision/recall. Add more gold entries to `gold.yaml` as you run the pipeline.
