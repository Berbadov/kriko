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

Two guarantees make this safe to run unattended:

- **No guessed figures.** A trim whose power or displacement the agent could not
  source is written `draft: true`; `backend/sync.py` skips it and the coverage
  report raises `draft_variant`. A visible gap, never a plausible invention.
- **No fabricated citations.** `add_evidence` rejects any quote that is not
  literally present in the document the agent submitted (whitespace- and
  case-insensitive). An agent cannot cite a source it did not read.

The CLI steps below remain the manual fallback and are what the agent path
ultimately drives.

### 4.1 Manual/CLI path

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

**Step 4d — kriko-hub: the clickable dashboard (web edition)**

Same numbers, six tab pages, rendered by your browser (hardware-accelerated,
native on the host — the DearPyGui desktop app is deprecated; GL rendering
on WSLg was slow and broken):

```bash
.venv/bin/python -m knowledge.hub.web     # then open http://127.0.0.1:8787
```

Tabs: **Models** (default — onboarding control room, below), Overview (ledger
counts, spend plot, cost-to-finish, recent runs),
Parts (part → claims/variants), Sources (documents → raw text), Run
(buttons: extract with a `--max-usd` cap, import verdicts, full $0 pass,
remediate, export, stop — output streams live), Ledger (generic read-only
SQLite browser), Coverage (findings). The browser polls state every second,
so agent-driven work appears live. The API is `127.0.0.1`-only, no auth.
Run `GET /api/state` for a JSON snapshot if you ever want the data without
the page.

**The Models tab — drive and watch the agent from the browser**

The onboarding control room. Type a make and model, pick a harness, hit
**Onboard →**: the hub spawns the research agent and streams its output into
the page. You never leave the browser.

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

Two safety notes on the Onboard button, since it is the only place the hub runs
something other than `knowledge.ledger.run`: make/model must match
`[a-z0-9_]{1,40}` (argv only, never a shell), and the harness selects a fixed
argv template rather than supplying a command. The hub still has one run slot,
so starting an onboarding stops any active pipeline run.

> The opencode agent declares `mode: all` deliberately. With `mode: subagent`,
> `opencode run --agent kriko_research` silently falls back to the default
> `build` agent — which has bash and edit permissions the researcher is denied.
> `test_opencode_agent_is_launchable_as_primary` guards against that regression.

**Step 4e — LLM-driven control: the kriko MCP server + kriko_research agent**

The pipeline as tools for a subscription LLM — new-model research at $0 flat
rate instead of API tokens:

The server registers 15 tools: read (`ledger_status`, `spend_summary`,
`pending_extract`, `pending_verdicts`, `list_parts`, `get_part`,
`list_documents`, `get_document`, `coverage_report`, `onboard_model`) and $0
write (`submit_trims`, `add_document`, `add_evidence`, `run_pipeline_pass`,
`run_remediate_import_only`). Write tools are deterministic or import-only —
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
args = ["-m", "knowledge.mcp.server"]
env = { PYTHONPATH = "/home/beraat/kriko" }
```

Cline — add to `cline_mcp_settings.json` (VS Code → Cline → MCP Servers →
Configure):

```json
{
  "mcpServers": {
    "kriko": {
      "command": "/home/beraat/kriko/.venv/bin/python",
      "args": ["-m", "knowledge.mcp.server"],
      "env": { "PYTHONPATH": "/home/beraat/kriko" }
    }
  }
}
```

The agent prompt is one canonical file, `.opencode/agents/kriko_research.md`;
`.claude/agents/kriko_research.md` is the same body with Claude Code
frontmatter. For Codex/Cline, paste that file's body as the system prompt.
Tool names are prefixed per host (`kriko_onboard_model` in opencode,
`mcp__kriko__onboard_model` in Claude Code) — the prompt says so.

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
