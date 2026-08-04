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
claims per variant at sync time. Adding a new model is five steps — the pipeline
scaffolds Steps 1 and 3 for you; the per-market figures Wikipedia doesn't reliably
give (horsepower, exact trim years) are derived automatically or the row fails open
(no synced variant, no_match demand signal, coverage-report finding) — never
hand-filled by a human (automation principle).

**Step 1 — Catalog discovery + variants scaffold** — what configs exist

```bash
python -m knowledge.catalog.discover --make renault --model megane_4 --write-variants
# → K9K (k9k, diesel), H5H (h5h, petrol), EDC (edc, transmission) …
```

This reads the Wikipedia article for the model, extracts engine/transmission codes
from the infobox, and writes a **draft** `backend/data/variants/{make}_{model}.yaml`
(one row per engine × transmission combination, marked `draft: true`). Wikipedia
doesn't reliably give per-market power figures or exact trim years, so those fields
are left unset rather than guessed — they are derived automatically or the row fails
open (not synced; surfaced by the coverage report's `draft_variant` finding and the
demand miner's no_match rows). `backend/sync.py` refuses to sync draft rows.
If `backend/data/variants/{make}_{model}.yaml` already exists, this step is skipped
(never overwrites). Use `--dry-run` to preview without writing.

**Step 2 — (included above)** catalog discovery also prints the research targets
(part codes) needed for Step 4.

**Step 3 — Fitment YAML** — map variant_id → part codes

```bash
python -m knowledge.catalog.discover --make renault --model megane_4 --write-fitment
```

Matches the discovered engine/transmission specs to the variants YAML from Step 1 and
writes/updates `backend/data/fitment/{make}_{model}.yaml` automatically — hand-curated
extra keys on existing rows are preserved. Use `--dry-run` to preview.

**Step 4 — Run the pipeline per part**

```bash
# Full run: Exa/YouTube discovery → fetch → LLM extract → gate → promote → sync
python -m knowledge.auto --part k9k --part-type engine --fuel diesel
python -m knowledge.auto --part edc --part-type transmission

# Re-run gates/promotion only — zero fetches, zero extraction tokens
python -m knowledge.process --part k9k --part-type engine --skip-extraction
```

> **Retired 2026-08-03 (B16 swap):** the judge/promote gate stack no longer
> exists — `knowledge.process`'s promote steps raise with a pointer to the
> ledger path. Claims reach serving only through the ledger's deterministic
> verdict stage. For new-part research, use Step 4b instead.

**Step 4b — Auto-remediation loop (backlog B19) — no human research runs**

Per-part research no longer waits for a person. The coverage report is the
trigger; the ledger pipeline fills the gap unattended:

```bash
# What would the loop fix right now?
python -m knowledge.ledger.run remediate --dry-run

# One budget-capped, resumable pass: acquire → extract → resolve → cluster →
# verdict → export for every zero-claim/missing part the coverage report flags
python -m knowledge.ledger.run remediate --max-usd 2.0

# Any findings that aren't part-driven (e.g. diesel variants without an
# emissions value) are reported and logged, never silently fixed
tail -f logs/remediation.jsonl
```

Run it on a schedule (cron/systemd timer). Every pass appends one line to
`logs/remediation.jsonl` (findings seen, parts re-researched, rows gained,
spend) so the loop's behavior is observable without any human in the path.

**Step 4c — Pipeline + cost panel (student-budget discipline)**

One read-only screen answers "what is the pipeline doing" and "what would it
cost to finish it" — the dry-run estimates, live:

```bash
python -m knowledge.ledger.panel
```

Shows total spend by stage/model, pending extraction/verdict cost-to-finish
(the same numbers `--max-usd` caps enforce), catalog + coverage state, recent
runs, and the zero-cost command set. Check it before any paid run; a new
model should land under ~$0.10 with the source cap + budget cap discipline.

**Step 4d — kriko-hub: the clickable dashboard (desktop app)**

Same numbers, six clickable windows, live-updating every ~1s off the ledger
DB — watch the agent work in real time:

```bash
.venv/bin/python -m knowledge.hub.app
```

Overview (spend plot, cost-to-finish, log tails), Model & Make (part list →
claims/variants/findings), Sources (documents → raw text), Extraction
(run buttons: extract with a `--max-usd` cap, import verdicts, full $0 pass,
remediate, export — output streams into the log window), Ledger browser
(generic read-only SQLite explorer), Scaffold (coverage findings). Requires
a desktop session (dearpygui needs GLX/OpenGL); install with the rest of
`knowledge/requirements.txt`. On WSL (WSLg), install Mesa first or GLFW dies
with "GLX: Failed to load GLX": `sudo apt install -y libgl1-mesa-dri
libglx-mesa0 libgl1 mesa-utils` (verify with `glxinfo -B`; force software GL
with `LIBGL_ALWAYS_SOFTWARE=1`).

**Step 4e — LLM-driven control: the kriko MCP server + kriko_research agent**

The pipeline as tools for a subscription LLM — new-model research at $0 flat
rate instead of API tokens:

```bash
# opencode (already wired via opencode.json -> mcp.kriko)
opencode            # then: use the kriko_research agent (agent prompt
                    #       includes the full research loop)
# or Claude Code:
claude mcp add kriko -- python -m knowledge.mcp.server --project
```

The server registers 13 tools: read (`ledger_status`, `spend_summary`,
`pending_extract`, `pending_verdicts`, `list_parts`, `get_part`,
`list_documents`, `get_document`, `coverage_report`) and $0 write
(`add_document`, `add_evidence`, `run_pipeline_pass`,
`run_remediate_import_only`). Write tools are deterministic or import-only —
nothing in agent-land can spend API tokens; the pass is logged at
`model=agent, usd=0` so the panel stays honest. Agent evidence
(extractor_version=1) flows through the same deterministic verdict path as
imported legacy research (`⊆ {0,1}`), so onboarding a new part is ~$0.00.
The `kriko_research` agent (`.opencode/agents/kriko_research.md`) runs the
loop: coverage → next uncovered part → research with its own web tools →
`add_document`/`add_evidence` (max 5 sources/part, product-principle gated)
→ `run_pipeline_pass` → verify.

**Step 5 — Sync to DB**

```bash
docker exec deploy-api-1 python -m backend.sync
```

Part claims (from `backend/data/parts/`) are assembled into variant links using the
fitment YAML. The serving plane (`/analyze`) is unchanged.

**Step 6 — Catalog swap to the ledger export (backlog B16)**

The ledger export is the future serving catalog; swapping is mechanical and gated,
never a manual edit:

```bash
# What would change? (remap, superseded/retained files, fitment edits)
python -m knowledge.ledger.swap plan

# The automated acceptance gate — parity loss, serving monotonicity, coverage.
# Exits 1 while the export is thinner than the legacy catalog (the remediate
# loop is the fix); 0 = swap is safe to land.
python -m knowledge.ledger.swap check

# Land it (runs on a temp copy unless --in-place; revert: git checkout -- backend/data)
python -m knowledge.ledger.swap apply --in-place
```

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

### Promoting & rejecting claims — retired (automation principle, 2026-08-03)

Statuses are pipeline-owned: the evidence ledger's deterministic verdict stage
(`knowledge/ledger/verdict.py` + the product-value gate) decides them —
**hand-editing `status`/`promoted_by` in the claim YAMLs is a banned human step**
(no human verification anywhere in the data path; CLAUDE.md automation
principle). The status vocabulary above still describes what the pipeline
writes; the legacy judge/promote stack retires with the B16 catalog swap.

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
