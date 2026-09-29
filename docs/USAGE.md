# Kriko — usage

Run it, load the extension, connect an agent, grow the knowledge. Mechanism is
in [INTERNALS.md](INTERNALS.md).

```mermaid
flowchart LR
    R["Research<br/>agent + ledger"] --> B["Build<br/>pack to .kpack"]
    B --> I["Install<br/>~/.kriko/knowledge.sqlite"]
    I --> L["Lookup<br/>extension, POST /api/analyze"]
```

## Prerequisites

- **Desktop app:** nothing. It carries its own Python; no Docker, no Postgres.
  Store `~/.kriko/knowledge.sqlite`, history `~/.kriko/app.sqlite`.
- **Checkout work** (pipeline, CLI, tests): Python 3.14+.
- **Pipeline keys:** `MISTRAL_API_KEY`, `EXA_API_KEY` (extraction, discovery);
  `DEEPSEEK_API_KEY` for the verdict stage. Set them in the environment or in
  the app's key screen (stored in `~/.kriko/env`).

## 1. Run it

Install the `desktop` workflow's installer (`Kriko_<version>_x64-setup.exe`,
`.deb`, `.AppImage`, `.dmg`) and launch it; see `tauri/README.md`. From a
checkout:

```bash
.venv/bin/python -m app.web            # http://127.0.0.1:8787
curl http://127.0.0.1:8787/api/health  # {"ok":true,"store":...,"app_state":...}
```

> Port 8787 taken? The extension only talks to 8787. The desktop app opens
> anyway and logs to stderr; stop the other listener.

## 2. Chrome extension

**From the app:** Check, then Browser extension, then *Add the extension*. It is
staged under `~/.kriko/extension/`; the page turns green when the extension
first reaches the app.

**From a checkout:** `chrome://extensions`, Developer mode, *Load unpacked*,
select `extension/`. Open a supported listing; the panel appears after about
1.5 seconds.

> After an app update or any `extension/` change: *Add again*, then the
> browser's Reload (the circular arrow on Kriko at `chrome://extensions`).

## 3. Connect a coding agent

Coverage, then Research writes a **brief** and gathers nothing; the research
runs on an agent you already pay for. Open System, then Connect an agent, and
press *Connect* per harness (Claude Code, Claude Desktop, Cursor, VS Code).

| State | Meaning |
|---|---|
| Not connected | No `kriko` server in the harness config. |
| Connected | Names this window's store. |
| Points elsewhere | Names a different `knowledge.sqlite`; findings land where this window never reads. |
| Config unreadable | Will not parse; nothing written. |

*Verify* runs a real MCP handshake and tool listing. Restart the harness
afterwards. The research skill (`~/.claude/skills/kriko-research/SKILL.md`) is
assembled from installed packs (`GET /api/agent-skill`). One binary serves both
roles:

```bash
kriko-sidecar --mcp --store ~/.kriko/knowledge.sqlite   # installed
python -m app.sidecar --mcp                             # checkout
```

The tool list lives in `src/app/mcp_server.py`; findings enter as drafts through
`app/findings.py`, which refuses quotes not found in the cited document.

## 4. Terminal

Store-only commands need no server; the rest attach to a running app or start an
engine for one command (`--no-start` fails instead; `--url` or `KRIKO_URL`
picks an engine).

| Command | Does |
|---|---|
| `kriko packs`, `install`, `uninstall`, `enable` | Manage installed packs |
| `kriko build packs/cars` | Build a pack directory into a `.kpack` |
| `kriko lookup` | Ask installed packs about a product |
| `kriko agenda`, `brief`, `submit` | What to research next, one subject's brief, file findings |
| `kriko prefs`, `costs` | Chosen providers (`--model NAME`), spend and next estimate |
| `kriko sites [register HOST\|forget HOST]` | Site readability; teach a site (starts a job) |
| `kriko verify [--list] [--pack ID] [--subject ID]` | Re-read claims' sources |
| `kriko drafts [show\|amend\|build\|install\|discard SLUG]` | Agent-written pack drafts |
| `kriko operations`, `bench --cases 5` | Live agent-work feed; measure the research planes |
| `kriko tui` | Operator console |

## 5. Add a car model

The default path costs $0: hand the make and model to the research agent.

```
use the kriko_research agent to onboard renault megane_4
```

The agent researches the trim lineup, then each part, then runs one pass. The
server refuses what a prompt could only ask for: unsourced power or
displacement (row becomes `draft: true`, skipped by build), quotes absent from
the submitted `document_text`, trim-shaped lineups, description codes such as
"7-speed DSG", and low-value rows (warning lights, routine inspection items,
unanchored generic advice; `src/kriko/gates.py`,
`packs/cars/vocabulary/gates.yaml`). A refusal names the fix; do not retry it
reworded.

**Manual fallback** (what the agent drives):

```bash
# 1. Catalog: writes draft variants and fitment YAML, prints the part codes
python -m packs.cars.pipeline.catalog.discover --make renault --model megane_4 --write-variants
python -m packs.cars.pipeline.catalog.discover --make renault --model megane_4 --write-fitment
# 2. Evidence per part, then the ledger stages
python -m app.pipeline.ledger_run acquire --part k9k --part-type engine --fuel diesel
python -m app.pipeline.ledger_run all
# 3. Build and install
python -m app.cli build packs/cars
python -m app.cli packs
```

| Command | Use |
|---|---|
| `ledger_run` subcommands | `acquire backfill extract resolve cluster verdict export report remediate all` |
| `python -m app.pipeline.ledger_run remediate --dry-run` | Unattended gap-filling from the coverage report; `--max-usd` caps spend; one line per pass in `logs/remediation.jsonl` |
| `python -m app.pipeline.panel` | Spend, cost-to-finish, coverage, recent runs; check before paid runs |
| `python -m app.pipeline.process renault megane 4 [--dry-run\|--skip-extraction]` | End-to-end driver; `--skip-extraction` replays cached candidates for free |
| `python -m packs.cars.pipeline.catalog.doctor [--fix]` | Report or repair catalog identity damage |
| `python -m packs.cars.pipeline.agent.render [--check]` | Regenerate the harness agent files from `packs/cars/pipeline/agent/kriko_research.md` |
| `python -m packs.cars.pipeline.ledger.eval_verdict` | Verdict quality against `packs/cars/pipeline/gold/gold.yaml` |

Processing writes YAML; nothing serves until the pack is rebuilt and installed.
Statuses are pipeline-owned, so never hand-edit `status`.

## What a buyer sees

| Status | Shown as | Meaning |
|---|---|---|
| `verified` | Confirmed | Two or more independent sources |
| `review`, `held` | Reported, N sources | Thin, or high severity |
| `rejected`, `draft` | not served | Junk, or not pipeline output |

Only claims with at least one grounded source are served, and single-source
reports are always labelled as reports.

## Check the store

```bash
sqlite3 ~/.kriko/knowledge.sqlite "SELECT pack_id, version, built_at FROM packs;"
sqlite3 ~/.kriko/knowledge.sqlite "SELECT subject_id, kind FROM subjects LIMIT 20;"
```

`/api/health` reports both file paths. Full payloads of past analyses are in
`logs/analyses.jsonl`.
