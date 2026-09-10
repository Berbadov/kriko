# Kriko — Usage Guide

Kriko is a local-first knowledge engine for manufactured products. It ships as a
desktop app; the `cars` pack surfaces known reliability risks for used cars on
Sahibinden.com through a Chrome extension. This guide covers running it and
growing the knowledge base.

---

## Prerequisites

- **Nothing to install and nothing to run** if you use the desktop app: the
  installer carries its own Python. There is no Docker, no Postgres, no service
  to start — the store is a single SQLite file at `~/.kriko/knowledge.sqlite`
  and the interface's own history is beside it in `app.sqlite`.
- **Python 3.14+** only if you work from a checkout (the pipeline, the CLI, the
  tests).
- **MISTRAL_API_KEY** — LLM extraction + judge gates (`ministral-8b-latest`),
  for the pipeline only.
- **EXA_API_KEY** — web source discovery (Exa neural search), for the pipeline
  only.

---

## 1. Run it

**As a desktop app** — install `Kriko_<version>_amd64.deb`,
`Kriko_<version>_amd64.AppImage`, `Kriko_<version>_aarch64.dmg`, or
`Kriko_<version>_x64-setup.exe` from the `desktop` workflow's artifacts and
launch it. The window owns the engine: it starts a sidecar on an OS-chosen port,
waits for `/api/health`, and shuts the sidecar down when you close the window.
Nothing is left listening. See `tauri/README.md`.

**From a checkout**, for development:

```bash
cd ~/kriko
.venv/bin/python -m uvicorn app.web.app:create_app --factory --port 8000
```

Check it's healthy:
```bash
curl http://127.0.0.1:8000/api/health
# → {"ok":true,"store":"~/.kriko/knowledge.sqlite","app_state":"~/.kriko/app.sqlite", ...}
```

Stop it with Ctrl-C. There is nothing else running.

> **No Docker.** Kriko was a Postgres-and-compose deployment once; the pivot to
> a standalone app deleted `deploy/`, and
> `test_the_app_stays_standalone` in `src/app/pipeline/tests/test_repo_invariants.py`
> fails if a Dockerfile, a compose file, or a Postgres driver comes back. If you
> have containers left from that era, remove them — a restart-looping container
> with a bind mount into this repo will recreate directories inside your
> checkout.

---

## 2. Chrome Extension

**From the app — the path a reader takes.** Open **Check → Browser extension**.
Press *Add the extension* and it writes a loadable copy to `~/.kriko/extension/`,
then walks the three steps below with the folder path on screen and a button to
open it. Leave that page open while you load it: it turns green by itself the
first time the extension reaches the app, which is real evidence rather than a
setting — a browser stamps `Origin: chrome-extension://<id>` on every request its
extensions make, and nothing else on the machine can produce that header.

`~/.kriko/extension/` rather than the install directory because a browser
remembers an unpacked extension **by path**, and an install directory is replaced
wholesale by the next installer — staging there would uninstall the extension on
every app update.

**From a checkout**, `extension/` in the repo works just as well:

1. Open Chrome → `chrome://extensions` → enable **Developer mode**
2. Click **Load unpacked** → select `~/kriko/extension/`
3. Visit any Sahibinden.com listing for a supported car (Renault Megane IV)
4. The Kriko panel appears automatically after ~1.5 seconds

After an app update ships a newer extension, the page says so and *Add again*
plus the browser's own **Reload** is the whole repair.

The extension talks to `127.0.0.1:8787` and cannot be told a different port —
a page has no filesystem and no channel from the app. Both `python -m app.web`
and the **desktop app** serve that port (the desktop sidecar additionally takes
an OS-chosen one for its own window), so either will answer. If something else
already holds 8787, the desktop app logs a line on stderr, opens anyway, and the
extension will not find it — stop the other listener.

---

## 2b. Connect a coding agent to the installed app

*Coverage → Research* writes a **brief**: what to look for, and what counts as
evidence. It gathers nothing itself, because the free plane costs nothing
precisely by using a coding agent you already pay for.

Open **System → Connect an agent**. It lists the harnesses on this machine —
Claude Code, Claude Desktop, Cursor, VS Code — and says which state each is in:

| State | Means |
|-------|-------|
| Not connected | the harness has no `kriko` server |
| Connected | it has one, naming this window's store |
| Points elsewhere | it has one, naming a *different* `knowledge.sqlite` |
| Config unreadable | the file will not parse; nothing is written to it |

**Points elsewhere** is the state worth having a word for: the agent runs, it
answers, and its findings land in a store this window never reads. Nothing
errors.

*Connect* merges one key into that harness's config — re-serialised from what
was parsed, never a template over the top, so the reader's other servers and
settings survive. A config that will not parse is refused rather than replaced.
Restart the harness afterwards; none of them re-read their config while running.

*Verify* starts the advertised command and completes an MCP handshake with it.
A written config and a working one fail separately: a moved virtual environment
or a missing module surfaces here and, otherwise, only as an agent that quietly
returns nothing. It will only ever start the command the app itself
advertised — a local endpoint that runs a command the caller names would be an
RCE hole reachable by anything that can reach the port.

Any other harness still gets the paste-it-yourself block, generated per machine
so the command is right from a checkout or an installer alike.

### The research skill

Wiring MCP tells an agent which tools exist. It does not tell it *when* any of
this applies, or what this installation considers worth keeping. That is a
skill, written to `~/.claude/skills/kriko-research/SKILL.md` alongside the
config and **assembled from the installed packs** — each pack's own
`research/principle.md`, which the store already carries as a pack asset. So a
car and a power drill state two different bars without a line of `app/` knowing
either, and updating a pack updates the protocol without updating the binary.
Read it on the same screen, or at `GET /api/agent-skill`.

Only harnesses with a skill mechanism get one (today: Claude Code). The rest
still connect. A store with no enabled packs gets no skill at all — there is
nothing to research and nothing to say what would count.

The same binary serves both roles:

```bash
kriko-sidecar --mcp --store ~/.kriko/knowledge.sqlite   # installed
python -m app.sidecar --mcp                             # from a checkout
```

Findings arrive as drafts through `app/findings.py`, which refuses a quote it
cannot find in the document it cites — the acceptance path is the same one the
web UI and the CLI use.

After any code change to `extension/`:
```bash
# Chrome → chrome://extensions → click the reload (↺) button on Kriko
```

---

## 3. Install knowledge pipeline tools (one-time)

```bash
cd ~/kriko
pip install -e ".[pipeline]"
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
- **No fabricated citations.** `submit_findings` rejects any quote that is not
  literally present in the `document_text` the agent submitted (whitespace- and
  case-insensitive). An agent cannot cite a source it did not read.
- **No trim-shaped lineups.** A row is a *powertrain*: two rows a listing could
  never tell apart are merged or refused, and an id must name the engine, not
  the showroom (`packs/cars/pipeline/catalog/identity.py`).
- **No description codes.** `transmission_code: "7-speed DSG"` is refused —
  "DSG" names three different gearboxes, so a claim attributed to it would
  contaminate its siblings. Find the unit code (`dq381`) or leave the row out.
- **No low-value rows.** Warning-light claims are always refused. Ekspertiz-routine
  items (fluids, pads, compression) are refused unless the title itself is
  config-specific or the text names an official recall — that recall exemption
  waives only the ekspertiz-routine check, not warning lights. Generic
  maintenance advice with no config anchor, and a title/rationale that is
  empty, too long, too short, or ties to nothing specific, are also refused
  with the reason (`src/kriko/gates.py` + `structural_reasons`, reading the cars
  pack's own `packs/cars/vocabulary/gates.yaml` rows) — the CLAUDE.md product
  principle, enforced rather than requested.
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

The engine as tools for a subscription LLM — research at $0 flat rate instead
of API tokens. The wiring, the states a harness can be in, and the generated
skill are §2b; this step is the pipeline-side view of the same server.

> **What used to be here was pre-pivot and is gone.** It described a
> pipeline-specific MCP server under `packs/cars/` with nineteen tools —
> `ledger_status`, `submit_trims`, `add_document`, `add_evidence`,
> `run_pipeline_pass` and the rest. Not one of them is defined anywhere in the
> tree. The cost was not the stale paragraph: `AgentResearcher.brief` had been
> written against the same list, so every research brief the app produced until
> 2026-09-10 told agents to call two tools that did not exist, and a reader saw
> a Research button whose output nothing could act on (B90). A second written
> copy of a tool list is the thing that goes stale. This step now names the
> single source for each thing it describes instead of restating it.

The tools an agent is granted are one tuple, `render.MCP_TOOLS` in
`packs/cars/pipeline/agent/render.py`, and
`test_every_tool_the_contract_grants_exists_on_the_server` fails the suite if
any of them is not callable on `app/mcp_server.py`. Two of them shape the
agent's *method* rather than its output:

- **`research_brief(subject_id, pack_id)`** — called before any web search. It
  returns the pack's own value principle and its rendered query templates
  (`packs/<pack>/research/principle.md` and `research/templates.yaml`), so the
  same agent researching a car and a power drill is told two different things
  about what is worth keeping, without a line of `app/` knowing either. "Do web
  research" left a cheap model to invent its own checklist per subject, so
  coverage depended on what it happened to think of; the brief comes off pack
  data, so it is current without a prompt edit. A pack shipping no
  `templates.yaml` renders zero queries and the brief says so — see
  `docs/PACK_CONTRACT.md`.
- **`submit_findings(subject_id, pack_id, findings)`** — the whole write
  surface, and the only one. It answers with a verdict per finding, so an agent
  learns in the same call which of its work did not survive. Findings arrive as
  drafts through `app/findings.py`, which refuses a quote it cannot find in the
  document it cites; the web UI and the CLI enter through that same function, so
  a claim's provenance does not depend on which door it came in. Nothing in
  agent-land can spend API tokens.

The server is **harness-agnostic** — validation lives in the server, so any
client is interchangeable and none of them can bypass the gates. Wiring, by
harness:

```bash
# opencode — committed: opencode.json -> mcp.kriko
opencode            # then: use the kriko_research agent

# Claude Code — committed: .mcp.json (approve it on first run)
claude              # then: use the kriko_research agent
```

For an *installed* app rather than a checkout, use **System → Connect an
agent** (§2b) — it writes the same key, naming that window's store, and
*Verify* completes a real handshake with what it wrote.

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

Tool names are prefixed per host — `kriko_submit_findings` in opencode,
`mcp__kriko__submit_findings` in Claude Code — and the prompt says so.

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

Processing writes YAML under `packs/cars/data/`. Nothing is serving it until the
pack is rebuilt and installed — `python -m app.cli build packs/cars`, or the
**Jobs** screen's build form, which does the same thing through the same
acceptance path.

### What buyers see (serving model)

The pipeline writes claims to the YAML with a `status` field. The extension shows **two
strengths**, never blurring them (`src/kriko/lookup`, `lookup`):

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

## 7. Check the store

The store is one SQLite file. No server, no container, no credentials:

```bash
# All claims currently served
sqlite3 ~/.kriko/knowledge.sqlite \
  "SELECT c.claim_id, t.title, c.severity
     FROM claims c JOIN claim_text t USING (claim_id, pack_id)
    WHERE t.lang = 'en' LIMIT 20;"

# What is installed, and how big
sqlite3 ~/.kriko/knowledge.sqlite \
  "SELECT pack_id, version, built_at FROM packs;"

# Subjects a pack knows about
sqlite3 ~/.kriko/knowledge.sqlite \
  "SELECT subject_id, kind FROM subjects LIMIT 20;"
```

`/api/health` reports both file paths, and the **Store** screen shows the same
counts without a shell. Interface history (what you looked up, and when) is a
*separate* file — `~/.kriko/app.sqlite` — so uninstalling a pack cannot drop it.

`analysis_log` above only has IDs and counts. For the full request/response payload
(what a specific buyer actually saw, and why — mileage/equipment/description that drove
gating), read `logs/analyses.jsonl`:

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
