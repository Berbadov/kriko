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
2. Click **Load unpacked** → select `~/kriko/extension/`
3. Visit any Sahibinden.com listing for a supported car (Renault Megane IV)
4. The Kriko panel appears automatically after ~1.5 seconds

After any code change to `extension/`:
```bash
# Chrome → chrome://extensions → click the reload (↺) button on Kriko
```

---

## 3. Install knowledge pipeline tools (one-time)

```bash
cd ~/kriko
pip install -r packs/cars/pipeline/requirements.txt
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
claims per variant at sync time. The per-market figures Wikipedia doesn't reliably
give (horsepower, exact trim years) are derived automatically or the row fails open
(no synced variant, no_match demand signal, coverage-report finding) — never
hand-filled by a human (automation principle).

### 4.0 The default path — hand a model to the research agent ($0)

Onboarding is one instruction to a subscription-billed agent. Start your harness
(§4e wires opencode, Claude Code, Codex and Cline) and tell the `kriko_research`
agent the make and model:

```
use the kriko_research agent to onboard renault megane_4
```

It calls `onboard_model` for the work list, researches the TR trim lineup and
submits it with `submit_trims` (which writes both variants and fitment YAML), then
researches each part into the ledger and runs one `run_pipeline_pass`. Cost: $0 —
every MCP write tool is deterministic or import-only. Then run Step 5 to sync.

**The server is the referee.** Every rule the agent prompt states is also
enforced in code at the write path, because a rule that lives only in a prompt
is a rule a cheap model can break and be told "OK" — that is exactly how a
trim-shaped VW Golf 8 lineup got written and reported as a success:

- **No guessed figures.** A trim whose power or displacement the agent could not
  source is written `draft: true`; the pack build skips it and the coverage
  report raises `draft_variant`. A visible gap, never a plausible invention.
- **No fabricated citations.** `add_evidence` rejects any quote that is not
  literally present in the document the agent submitted (whitespace- and
  case-insensitive). An agent cannot cite a source it did not read.
- **No trim-shaped lineups.** A row is a *powertrain*: two rows a listing could
  never tell apart are merged or refused, and an id must name the engine, not
  the showroom (`packs/cars/pipeline/catalog/identity.py`).
- **No description codes.** `transmission_code: "7-speed DSG"` is refused —
  "DSG" names three different gearboxes, so a claim attributed to it would
  contaminate its siblings. Find the unit code (`dq381`) or leave the row out.
- **No low-value rows.** Warning lights, ekspertiz-routine items (fluids, pads,
  compression) unless the title itself is config-specific or the text names an
  official recall, generic maintenance advice with no config anchor, and a
  title/rationale that is empty, too long, too short or ties to nothing
  specific are refused with the reason (`kriko/gates.py` + `structural_reasons`,
  reading the cars pack's own `packs/cars/vocabulary/gates.yaml` rows) — the
  CLAUDE.md product principle, enforced rather than requested.
- **Removed, not currently enforced.** The orphaned write-path gate this
  replaced also caught DTC-code litanies, rephrasings of a chronic already on
  file, a per-part research budget, and blocked forum/spec-farm sources —
  none of that is wired into the current agent path. Tracked as a backlog
  item rather than silently assumed; do not rely on the server to catch any
  of these until it is re-wired.

A rejection is an instruction: it names what would fix the row. The contract
tells the agent never to retry a rejection with a reworded version of the same
row — fix the substance or report the gap.

**Repairing what is already on disk** (the other half of the same rule):

```bash
python -m packs.cars.pipeline.catalog.doctor          # report identity damage, all cars
python -m packs.cars.pipeline.catalog.doctor --fix    # $0 deterministic repair
```

It canonicalizes codes, renames trim-shaped ids, merges duplicate powertrains,
prunes orphan fitment rows, and fails open (`draft: true`) on a code nobody
could resolve. Idempotent, and CI fails if anything fixable is left unfixed.

The CLI steps below remain the manual fallback and are what the agent path
ultimately drives.

### 4.1 Manual/CLI path

**Step 1 — Catalog discovery + variants scaffold** — what configs exist

```bash
python -m packs.cars.pipeline.catalog.discover --make renault --model megane_4 --write-variants
# → K9K (k9k, diesel), H5H (h5h, petrol), EDC (edc, transmission) …
```

This reads the Wikipedia article for the model, extracts engine/transmission codes
from the infobox, and writes a **draft** `packs/cars/data/variants/{make}_{model}.yaml`
(one row per engine × transmission combination, marked `draft: true`). Wikipedia
doesn't reliably give per-market power figures or exact trim years, so those fields
are left unset rather than guessed — they are derived automatically or the row fails
open (not synced; surfaced by the coverage report's `draft_variant` finding and the
demand miner's no_match rows). The pack builder refuses to include draft rows.
If `packs/cars/data/variants/{make}_{model}.yaml` already exists, this step is skipped
(never overwrites). Use `--dry-run` to preview without writing.

**Step 2 — (included above)** catalog discovery also prints the research targets
(part codes) needed for Step 4.

**Step 3 — Fitment YAML** — map variant_id → part codes

```bash
python -m packs.cars.pipeline.catalog.discover --make renault --model megane_4 --write-fitment
```

Matches the discovered engine/transmission specs to the variants YAML from Step 1 and
writes/updates `packs/cars/data/fitment/{make}_{model}.yaml` automatically
extra keys on existing rows are preserved. Use `--dry-run` to preview.

**Step 4 — Run the pipeline per part**

```bash
# Acquire: Exa/YouTube discovery → fetch → ingest to the ledger (no LLM)
python -m app.pipeline.ledger_run acquire --part k9k --part-type engine --fuel diesel
python -m app.pipeline.ledger_run acquire --part edc --part-type transmission

# Then the ledger pipeline: extract → resolve → cluster → verdict → export
python -m app.pipeline.ledger_run all

# Re-run gates/promotion only — zero fetches, zero extraction tokens
python -m app.pipeline.process --part k9k --part-type engine --skip-extraction
```

> **Retired 2026-08-03 (B16 swap):** the judge/promote gate stack no longer
> exists — `app.pipeline.process`'s promote steps raise with a pointer to the
> ledger path. Claims reach serving only through the ledger's deterministic
> verdict stage. For new-part research, use Step 4b instead.

**Step 4b — Auto-remediation loop (backlog B19) — no human research runs**

Per-part research no longer waits for a person. The coverage report is the
trigger; the ledger pipeline fills the gap unattended:

```bash
# What would the loop fix right now?
python -m app.pipeline.ledger_run remediate --dry-run

# One budget-capped, resumable pass: acquire → extract → resolve → cluster →
# verdict → export for every zero-claim/missing part the coverage report flags
python -m app.pipeline.ledger_run remediate --max-usd 2.0

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
python -m app.pipeline.panel
```

Shows total spend by stage/model, pending extraction/verdict cost-to-finish
(the same numbers `--max-usd` caps enforce), catalog + coverage state, recent
runs, and the zero-cost command set. Check it before any paid run; a new
model should land under ~$0.10 with the source cap + budget cap discipline.

**Step 4d — kriko-hub: the clickable dashboard (web edition)**

Same numbers, six tab pages, rendered by your browser (hardware-accelerated,
native on the host — the DearPyGui desktop app is deprecated; GL rendering
on WSLg was slow and broken):

```bash
.venv/bin/python -m app.web          # then open http://127.0.0.1:8787
```

Tabs: **Models** (default — onboarding control room, below), **Claims** (the
claim inspector: every claim with the deterministic gate's verdict and its
reasons — agree/disagree records gate feedback in
`logs/claim_signals.jsonl` and never edits the catalog, because a
human decision inside the data path is what G5 forbids), Overview (ledger
counts, spend plot, cost-to-finish, recent runs),
Parts (part → claims/variants), Sources (documents → raw text, tiered), Run
(buttons: extract with a `--max-usd` cap, import verdicts, full $0 pass,
remediate, export, stop — output streams live), Ledger (generic read-only
SQLite browser), Coverage (the catalog doctor's identity findings with a $0
repair button, plus coverage findings). The browser polls state every second,
so agent-driven work appears live. The API is `127.0.0.1`-only, no auth.
Run `GET /api/state` for a JSON snapshot if you ever want the data without
the page.

**The Models tab — drive and watch the agent from the browser**

The onboarding control room — a top-down picker, no typing:

**1 · Make → 2 · Model → 3 · Generation → 4 · Run.** Each step reveals the next.

Makes and models are **not a maintained list** — they come from the installed
pack and its research workflow. The dashboard exposes the available subjects and
coverage state; onboarding is driven by pack data and recorded analysis activity.

Generation can't come from traffic (listings carry a year, not a generation
number), so it is **researched first**:

1. Pick make + model → the Generation step says *not researched yet*.
2. Hit **Find generations →**. The agent researches the lineup and calls
   `submit_generations`; every generation must cite a source or the lineup is
   rejected whole.
3. Generation buttons appear — `I (GA) 2016–2024`, `II 2024–`. Pick one.
4. **Onboard audi q2_1 →** runs the full onboarding loop against that key.

**Onboarding is armed only when the target is a real model key.** Until a
lineup is researched, the Onboard task is disabled and generation research is
selected for you; with a lineup but no generation picked, the Run button is
disabled and says which choice is missing. `POST /api/onboard` enforces the
same rule (400 with the reason), so no client can start the run either. The
case this prevents: the demand queue's display slug `vw_cc_1_4_tsi` onboarded
with no generation, producing the key `volkswagen_vw_cc_1_4_tsi` — not a car,
so the agent researches nothing and the run only *looks* like a broken hub.

That phase-1 step also **resolves scraped display names**. The demand queue
says `vw_cc_1_4_tsi` and `3 Series`, which are not model names; the agent
submits `canonical_model: passat_cc` and the queried name is kept as an alias,
so the picker's dirty slug still resolves afterwards. Guessing that mapping in
code would have been another hand-maintained car list.

Lineups are written to `packs/cars/pipeline/catalog/generations/{make}_{model}.yaml` —
machine-written from a validated payload, never hand-edited.

- **Catalog** lists every car with its rollup — `5 researched / 0 empty / 7
  missing` — plus a `draft` count for rows with unsourced figures. Click one to
  load its work list.
- **Live activity** is the real-time view of what the agent is doing. It reads
  the **ledger**, not the harness's stdout: every agent action goes through an
  MCP write tool, so this works identically whichever harness is driving, and
  each evidence row shows `✓ grounded` only when its quote was verified against
  the stored source.
- **Model detail** shows the part work list (researched/empty/missing with claim
  counts) and every draft row with the exact figures that are missing.

**Steps 4–5 pick the task, the harness, and the model**, and show the exact
command before you run it:

```
$ /home/beraat/.nvm/.../opencode run --agent kriko_research \
    -m opencode-go/kimi-k3 onboard audi q2_1
```

That preview comes from `POST /api/agent-preview`, which builds the argv with
the **same function the run endpoints call** — so it is literally the command
that executes, not a reconstruction that can drift.

Model lists are asked of the harness (`opencode models`), never shipped in this
repo. They are split by how they bill:

- **flat rate (subscription)** — 26 models on opencode's own plan. This is the
  $0 plane the agent path exists for.
- **⚠ pay-per-token** — ~380 more, unlocked by the `DEEPSEEK_API_KEY`,
  `MISTRAL_API_KEY` and `OPENROUTER_API_KEY` entries in `.env`, which the hub
  passes through to the harness. Picking one **spends API credits**. They are
  kept in a separate, labelled optgroup and the command preview warns, so it
  can't happen by an accidental dropdown pick. The split is derived from the
  `*_API_KEY` names in `.env` — a new key is classified the moment it appears.

Three safety notes on the run buttons, since this is the only place the hub
executes something other than `app.pipeline.ledger_run`: make/model must match
`[a-z0-9_]{1,40}` and the model id `[A-Za-z0-9_./:-]{1,80}` (argv only, never a
shell); the task selects a fixed prompt template and the harness a fixed argv
template, so neither the prompt nor the command comes from the request. The hub
still has one run slot, so starting an agent stops any active pipeline run.

> The opencode agent declares `mode: all` deliberately. With `mode: subagent`,
> `opencode run --agent kriko_research` silently falls back to the default
> `build` agent — which has bash and edit permissions the researcher is denied.
> `test_opencode_agent_is_launchable_as_primary` guards against that regression.

**Step 4e — LLM-driven control: the kriko MCP server + kriko_research agent**

The pipeline as tools for a subscription LLM — new-model research at $0 flat
rate instead of API tokens:

The server registers 19 tools: read (`ledger_status`, `spend_summary`,
`pending_extract`, `pending_verdicts`, `list_parts`, `get_part`,
`list_documents`, `get_document`, `coverage_report`, `onboard_model`,
`list_generations`, `research_brief`) and $0 write (`submit_trims`,
`submit_generations`, `add_document`, `add_evidence`, `run_pipeline_pass`,
`finish_model`, `run_remediate_import_only`).

Two of those shape the agent's *method* rather than its output:

- **`research_brief(part_id)`** — called before any web search. It returns what
  this subsystem can fail at (from `packs/cars/pipeline/catalog/components.yaml`), which
  chronics are already on file, how much of the 5-document budget is left, and
  which source tiers count (`packs/cars/pipeline/catalog/source_tiers.yaml`). "Do web
  research" left a cheap model to invent its own checklist per part, so
  coverage depended on what it happened to think of; the brief is derived from
  the catalog, so it is current without a prompt edit.
- **`finish_model(make, model, notes)`** — closes a pass: the $0 pipeline pass
  plus a recorded outcome in `logs/agent_runs.jsonl` (what closed, what is
  still zero-claim, which rows stayed draft and which figure each is missing).
  The result outlives the session; the hub's **Agent results** table reads it. Write tools are deterministic or import-only —
nothing in agent-land can spend API tokens; the pass is logged at
`model=agent, usd=0` so the panel stays honest. Agent evidence
(extractor_version=1) flows through the same deterministic verdict path as
imported legacy research (`⊆ {0,1}`), so onboarding a new part is ~$0.00.

The server is **harness-agnostic** — validation lives in the server, so any
client is interchangeable and none of them can bypass the gates. Wiring, by
harness:

```bash
# opencode — committed: opencode.json -> mcp.kriko
opencode            # then: use the kriko_research agent

# Claude Code — committed: .mcp.json (approve it on first run)
claude              # then: use the kriko_research agent
```

Codex and Cline configs live outside the repo. Codex — add to `~/.codex/config.toml`:

```toml
[mcp_servers.kriko]
command = "/home/beraat/kriko/.venv/bin/python"
args = ["-m", "app.mcp_server"]
env = { PYTHONPATH = "/home/beraat/kriko" }
```

Cline — add to `cline_mcp_settings.json` (VS Code → Cline → MCP Servers →
Configure):

```json
{
  "mcpServers": {
    "kriko": {
      "command": "/home/beraat/kriko/.venv/bin/python",
      "args": ["-m", "app.mcp_server"],
      "env": { "PYTHONPATH": "/home/beraat/kriko" }
    }
  }
}
```

The agent prompt has exactly one source: `packs/cars/pipeline/agent/kriko_research.md`.
The harness files (`.opencode/agents/`, `.claude/agents/`) are **generated**:

```bash
python -m packs.cars.pipeline.agent.render          # rewrite the harness files
python -m packs.cars.pipeline.agent.render --check  # CI: are they current?
```

Two hand-maintained copies meant the harness a run happened to use decided
which rules the agent had been told about; `test_agent_contract.py` now fails
if a checked-in file is stale, or if the contract grants a tool the server does
not expose. For Codex/Cline, paste the canonical file's body as the system
prompt.
Tool names are prefixed per host (`kriko_onboard_model` in opencode,
`mcp__kriko__onboard_model` in Claude Code) — the prompt says so.

**Step 5 — Build and install the pack**

The cars pack is the source of truth. Build it into the local SQLite store, then
use the web app or CLI to inspect the result:

```bash
python -m app.cli build packs/cars
python -m app.cli packs
```

Part claims from `packs/cars/data/parts/` are assembled through the pack builder.
There is no separate Postgres sync or catalog-swap step.

---

## 5. Add page sources manually

Edit `packs/cars/pipeline/sources/curated/{make}_{model}_{gen}.yaml` directly and append:

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

## 6. Process pending sources

```bash
# Preview (no writes)
python -m app.pipeline.process renault megane 4 --dry-run

# Full run
python -m app.pipeline.process renault megane 4

# Re-run gates/promotion on cached candidates — zero fetches, zero extraction LLM calls
python -m app.pipeline.process renault megane 4 --skip-extraction
```

This runs: fetch → LLM extract → dedup → gate → score → write claims YAML → sync DB.
Extracted candidates are cached to `packs/cars/pipeline/cache/{make}_{model}_{gen}_candidates.json`;
`--skip-extraction` replays the cache, so tuning gates/thresholds costs no tokens.
High-severity claims always go to manual review regardless of score.

After processing, the API container auto-reloads via the Docker `restart` policy. If it
doesn't pick up new claims immediately:
```bash
docker compose -f deploy/docker-compose.yml restart api
```

### What buyers see (serving model)

The pipeline writes claims to the YAML with a `status` field. The extension shows **two
strengths**, never blurring them (`kriko/lookup`, `lookup`):

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
(`packs/cars/pipeline/ledger/verdict.py` + the product-value gate) decides them —
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

## 7. Check the database

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
# Pipeline state, spend, and recent activity
python -m app.pipeline.panel
```

`GET /debug/analyses?limit=20&model=golf` exposes the same JSONL over HTTP, but is
**off (404) by default** — it dumps full request/response history, so only set
`ENABLE_DEBUG_ENDPOINT=true` in `deploy/.env` temporarily if you don't have shell
access to the deploy host.

---

## 8. Eval the LLM gates (optional)

```bash
DEEPSEEK_API_KEY=... python -m packs.cars.pipeline.ledger.eval_verdict
```

Runs the verdict-quality check over `packs/cars/pipeline/gold/gold.yaml` and prints
per-entry outcomes. Add more gold entries to `gold.yaml` as you run the pipeline.
