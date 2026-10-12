# Kriko, internals

Data flow, file paths and the invariants the code relies on. Package layering
is in [ARCHITECTURE.md](ARCHITECTURE.md) and `CLAUDE.md`; this page is the
mechanism.

## The request path, serving plane

```mermaid
%%{init: {"theme":"base","themeVariables":{"fontFamily":"ui-monospace, SFMono-Regular, Consolas, monospace","primaryColor":"#090E1B","primaryTextColor":"#F2F5FF","primaryBorderColor":"#1F4FFF","lineColor":"#86A3FF","secondaryColor":"#1739C2","tertiaryColor":"#080B16","noteBkgColor":"#BFE4FF","noteTextColor":"#05070F","actorBkg":"#090E1B","actorTextColor":"#F2F5FF","actorBorder":"#1F4FFF","signalColor":"#86A3FF","signalTextColor":"#86A3FF"}}}%%
sequenceDiagram
    participant C as extension/content.js
    participant B as extension/background.js
    participant A as routers/analyze.py
    participant M as kriko/lookup/match.py
    participant L as kriko/lookup
    C->>B: buildScrape(knownLabels, panel)
    B->>A: POST /api/analyze
    A->>M: adapt the scrape to a Query, resolve subjects
    M->>L: lookup(query, conn)
    L-->>A: claims, verified and current only
    A-->>B: claims, packs and coverage, HTTP 200
    B-->>C: render cards
```

Serving never calls a model: `/api/analyze` reads the store.

| Step | File | Rule |
|---|---|---|
| Scrape | `extension/content.js` | Raw `label -> value`, uninterpreted. `knownLabels` (from `GET /api/adapters`) only says which labels are worth digging for; the adapter decides what a label means (`kriko/adapters.py`). |
| Panel rules | the adapter's `local_panel` block | Selectors, the site's own words and thresholds ride in the adapter, opaque to the engine, and are never compiled from pack patterns into a `RegExp`. `test_the_extension_speaks_no_sites_own_language` fails on a non-ASCII word in `extension/`. |
| Request | `extension/background.js` | Labels and panel travel per request, never cached. |
| Endpoint | `src/app/web/routers/analyze.py` | Answers 200 with `readable: true`, the matched `identity`, `claims`, `packs` and `coverage`. A page it cannot answer for is also 200, with `readable: false` and a `reason` (`no_adapter`, `unknown_product`, `page_not_read`). An unexpected error is a 500 from the handler in `src/app/web/app.py`. |
| Identity | `src/kriko/lookup/match.py` | Matches on attribute overlap, never on `subject_id` equality. Narrowing is soft: an unmatched hint flags a contradiction, it never produces `no_match`. The result is a `Resolution` (`lookup/query.py`): `subject_ids`, `method` (`exact`/`ambiguous`/`no_match`), `notes`, `flags`. |
| Claims | `src/kriko/lookup/__init__.py` | Reads the claims of the matched subjects, with their text in the reader's language, their conditions and their evidence. An unmet condition withdraws a claim; an unknown one lowers its weight. The store keeps no claim status, so none is a filter. |
| Ranking | `src/kriko/lookup/rank.py` (`relevance()`, `explain()`) | Severity, detection (lower for a component that has to be seen rather than measured), source trust, the pack's weight, the author's confidence and the conditions. Claims sort by that relevance, then severity and title. Near-duplicate titles in one domain merge into the best of them, keeping their sources, and the list stops at the query's `limit`. Each claim carries `why`, the reasons for its rank. |
| Render | `extension/hover_lite/hover_lite.js` | Risk cards plus local blocks. Alerts walk `listing.panel.alerts` in order, and `unless: [rule-id]` is an else-branch written as data. |

**Claim health** (`kriko/lookup/tree.py`) keeps four signals per claim, and
never combines them: contradiction (`stance='refutes'`), corroboration, best
trust tier, and staleness (`sources.retrieved_at`). Read them at
`GET /api/health/weakest` and `GET /api/health/subject/{subject_id}`, or
through the `subject_health` and `weakest_claims` MCP tools. `stance` is
written at acceptance (`app/findings.py`).

## The jobs plane

Long work is a row, not a request. How many run at once is the reader's
Settings choice (`run_concurrency`, 1 to 4, one by default); each job claims
the pack it writes (`claims()` in `src/app/web/jobs.py`), two overlapping claims never run
together, and a kind whose target cannot be named runs alone. Quick looks
keep their own lane.

```mermaid
%%{init: {"theme":"base","themeVariables":{"fontFamily":"ui-monospace, SFMono-Regular, Consolas, monospace","primaryColor":"#090E1B","primaryTextColor":"#F2F5FF","primaryBorderColor":"#1F4FFF","lineColor":"#86A3FF","secondaryColor":"#1739C2","tertiaryColor":"#080B16","noteBkgColor":"#BFE4FF","noteTextColor":"#05070F","actorBkg":"#090E1B","actorTextColor":"#F2F5FF","actorBorder":"#1F4FFF","signalColor":"#86A3FF","signalTextColor":"#86A3FF"}}}%%
flowchart LR
    P["POST /api/research<br/>POST /api/packs/update"]:::ice --> R["JobRunner<br/>N at once, one per pack, web/jobs.py"]:::brand
    R --> T["web/tasks.py<br/>settings, params, progress"]:::plain
    R <--> S[("app.sqlite jobs")]:::plain
    S --> V["GET /api/jobs/{job_id}<br/>polled by the client"]:::ice
    classDef brand  fill:#1F4FFF,stroke:#86A3FF,color:#F2F5FF
    classDef plain  fill:#090E1B,stroke:#3A4156,color:#C9D1EA
    classDef ice    fill:#BFE4FF,stroke:#1F4FFF,color:#05070F
```

```mermaid
%%{init: {"theme":"base","themeVariables":{"fontFamily":"ui-monospace, SFMono-Regular, Consolas, monospace","primaryColor":"#090E1B","primaryTextColor":"#F2F5FF","primaryBorderColor":"#1F4FFF","lineColor":"#86A3FF","secondaryColor":"#1739C2","tertiaryColor":"#080B16","noteBkgColor":"#BFE4FF","noteTextColor":"#05070F","actorBkg":"#090E1B","actorTextColor":"#F2F5FF","actorBorder":"#1F4FFF","signalColor":"#86A3FF","signalTextColor":"#86A3FF"}}}%%
stateDiagram-v2
    [*] --> queued
    queued --> running
    running --> succeeded
    running --> failed
    running --> cancelled: cooperative cancel
    running --> interrupted: recover() at startup
    succeeded --> [*]
    failed --> [*]
    cancelled --> [*]
    interrupted --> [*]
```

States are `queued`/`running`, then `succeeded`, `failed`, `cancelled` or
`interrupted`; `recover()` marks a dead process's rows `interrupted` at
startup. Cancel is cooperative (`Progress.check`) and kills the child process
tree. `POST /api/jobs/{job_id}/say` queues a message from the reader and the
handler reads it between steps, so a run can be answered while it runs.
`research` feeds `app/findings.py`, the same grounding path as the MCP
`submit_findings`; `pack_build` mirrors `kriko build`.

**A quick look needs no agent either.** With no coding agent, key or local
model, the extension's research door runs the quick look on the reader's own
chat (`app/providers/chat_bridge.py`, plane `chat`, cost basis `own_chat`).
The job puts its question in its partial result (`chat_prompt`); the panel
shows it with a Copy button and posts the pasted answer to
`POST /api/jobs/{id}/say`. Every page the answer cites is then fetched on this
machine and `quicklook.parse` keeps a risk only when its quote is in its page,
so an invented or misquoted line, or an unreadable source, is dropped. The
result is an ordinary quick look, filed into catalogs like any other.

**Filing quick looks needs no agent.** `pack_harvest` (`src/app/web/tasks.py`,
started by `POST /api/packs/harvest` and by **File quick looks** on Overview)
files every saved quick look not yet filed. `_file_quick_look` re-checks each
risk against its own page and attaches it to the catalog that already holds the
product, at no cost. A product no catalog holds is listed as `needs_agent`, and
nothing is sent to an agent for it. A catalog that gained claims is installed
once, at a raised version, and its `.kpack` is shared through
`GET /api/packs/drafts/{slug}/artifact`. A look filed once is never filed again.

## API surfaces

Each `app/web/routers/*.py` module is one surface. The engine's OpenAPI
schema (`/openapi.json`) is the authoritative list; this table is a map.

| Surface | Endpoints | Notes |
|---|---|---|
| analyze | `POST /api/analyze`, `GET /api/adapters`, `POST /api/diagnose/identity` | The check itself, the adapters a page may use, and the full identity weighing behind a "not recognised". |
| subjects | `GET /api/subjects`, `GET /api/subjects/{subject_id}`, `GET /api/subjects/filters`, `GET /api/search` | Pack knowledge, the filter vocabulary and the catalogue-wide search. The brief an agent works from is the MCP `research_brief` tool. |
| query | `POST /api/lookup`, `GET /api/identity-keys/{pack_id}` | A lookup, and the keys a pack declares. |
| history | `GET /api/history`, `GET /api/history/records`, `GET /api/lookup/{lookup_id}`, `GET\|POST /api/lookup/{lookup_id}/questions`, `DELETE /api/history/{lookup_id}`, `GET\|POST /api/settings` | Backed by `app.sqlite`. |
| live | `POST /api/lookup/{lookup_id}/refresh` | Re-read one past check. The knowledge clock it answers with rides on `GET /api/operations`. |
| marks | `GET\|POST /api/marks`, `DELETE /api/marks/{pack_id}/{claim_id}` | Author verdicts, pack-keyed. Counted by `GET /api/marks`; no route reads the verdicts back as a queue. |
| compare | `GET\|POST /api/compare-drafts`, `PUT\|DELETE /api/compare-drafts/{draft_id}`, `GET\|POST /api/compare-drafts/{draft_id}/questions`, `GET\|PUT /api/compare-drafts/{draft_id}/board` | Named comparisons of saved checks. App state, never knowledge. |
| queue | `GET\|POST /api/queue`, `PATCH\|DELETE /api/queue/{queue_id}` | The research queue: products queued from the extension's panel (Add to queue), researched in turn, then compared. One row per listing address; a second press answers `added: false`; PATCH sets `state` (waiting, researching, done) and the fresh `lookup_id` as the window researches them. App state, never knowledge. |
| jobs | `POST /api/research`, `POST /api/packs/update`, `POST /api/packs/harvest`, `GET /api/packs/updates`, `GET /api/jobs`, `GET /api/jobs/{job_id}`, `POST /api/jobs/{job_id}/cancel`, `POST /api/jobs/{job_id}/retry`, `POST /api/jobs/{job_id}/say` | A client follows a job by polling `GET /api/jobs/{job_id}`; there is no push stream. |
| agenda | `GET /api/agenda` | Computed on read from demand, gaps and thinness. |
| research | `GET /api/research-planes`, `GET /api/local-plane` | The planes read off the researcher classes, with a cost sentence and `ready` each; the local plane's own state. |
| prefs | `GET\|PUT /api/prefs`, `GET /api/costs` | Chosen providers, measured spend and next estimate. No credit balance, because no vendor exposes one. |
| factcheck | `GET\|POST /api/factcheck`, `GET /api/factcheck/grounding`, `GET /api/factcheck/document`, `POST /api/verify` | The quote comes from the store, never from the caller. Verdicts are `quoted`/`missing`/`unreadable`/`unreachable`, and `missing` means the page changed, not that the claim is false. |
| sites | `GET /api/sites`, `POST /api/sites/activation`, `POST /api/sites/seen`, `DELETE /api/sites/{host}`, `POST /api/sites/{host}/register` | A pack's adapter always beats a learned one (`app/sites.py`). |
| control | `GET /api/status` | The install's own status counts. |
| health | `GET /api/health`, `GET /api/health/weakest`, `GET /api/health/subject/{subject_id}` | The handshake every client polls (`docs/PROTOCOL.md`), and the thinnest claims in the store. |
| packs | `GET /api/packs`, `POST /api/packs/install`, `POST /api/packs/reset`, `POST /api/packs/{pack_id}/rollback`, `POST /api/packs/{pack_id}/enabled`, `GET /api/packs/{pack_id}/gaps`, `GET /api/packs/{pack_id}/vocabulary`, `GET /api/packs/drafts`, `GET /api/packs/drafts/{slug}`, `POST /api/packs/drafts/{slug}/build`, `POST /api/packs/drafts/{slug}/amend`, `POST /api/packs/drafts/{slug}/install`, `GET /api/packs/drafts/{slug}/artifact`, `DELETE /api/packs/drafts/{slug}` | Drafts live in `~/.kriko/drafts/<slug>/`. An adapter is `adapters/*.json`, not `.yaml`. A draft with no `principle` or no `lineup` is refused, and a subject named by neither the line-up nor `coverage.out_of_scope` is quarantined in `research/coverage.yaml`. The `artifact` link is the `.kpack` a harvest or author job hands the reader to share. `install` takes a `.kpack` file's bytes as the body (Overview's "Install from a file"), never a path; `kriko install` and the MCP `install_pack` tool do the same from a terminal or an agent. |
| keys | `GET\|PUT /api/keys`, `DELETE /api/keys/{provider_id}`, `POST /api/keys/test` | Stored in `~/.kriko/env`. No response ever carries a key: presence, source and the last four only. The test sends the provider one tiny request with the stored key (Settings, **Test**) and answers `ok`, latency, results or tokens, or why it failed. |
| agent | `GET /api/agent-targets`, `POST /api/agent-targets/{target_id}/connect`, `POST /api/agent-targets/{target_id}/skill`, `GET /api/agent-skill`, `POST /api/agent-verify` | `agent-verify` runs a real MCP `initialize` and `tools/list`. The skill an agent reads is `GET /api/agent-skill`. |
| operations | `GET /api/operations`, `GET /api/operations/stream` | The any-door live feed of agent work (`docs/AGENT_OPERATIONS.md`). |
| bench | `GET\|POST /api/bench`, `POST /api/bench/estimate` | The sweep runs on a throwaway copy of the store. `estimate` is a separate endpoint so that asking what a grid would cost can never start it. |
| machine | `GET /api/machine` | The GPU (name, VRAM total and used from `nvidia-smi`), system memory, the processor, and which local runtimes are installed with their path. A figure the machine does not report is `null`, never a guess. Cached for 60 seconds; `?fresh=true` skips the cache (`app/machine.py`). |
| app-update | `GET /api/app-update`, `POST /api/app-update/download` | The app's own clock, apart from the catalogs'. `GET` asks the releases API (`Settings.app_release_api_url`) for the latest release and compares versions as numbers; it fails quiet ("no published release found" on a private repository). `POST` downloads that release's MSI and keeps it only if it matches the release's `SHA256SUMS.txt`; the desktop shell runs it and reopens the app (`app/appupdate.py`). |
| agent install | `POST /api/agents/{agent_id}/install` | Starts an `agent_install` job: the agent's `install_command` (the vendor's own Windows instructions, run in PowerShell with the log streamed), then a look for the CLI on the login `PATH`. For `local` it downloads Ollama's own installer (signature checked, run silently), starts Ollama if stopped, reinstalls it if it answers but cannot run a model, and downloads the recommended model, `localplane.RECOMMENDED_MODEL` (`gemma4:e2b`), whatever the machine (`app/agentinstall.py`); the same constant is the default pick when the reader chose no model, and `/api/local-plane` reports it as `recommended_model` for the screens to mark. Rows in `/api/prefs` carry `can_install`. |
| local-models | `GET /api/local-models`, `POST /api/local-models/pull`, `POST /api/local-models/start` | `GET` is what Ollama holds, with the bytes, parameter count and quantisation it reports. `POST` starts a `model_pull` job: Ollama's own streamed `/api/pull`, progress as the share of bytes, cancel stops the stream, a failure carries Ollama's words. Ollama only; any other runtime is refused with where to get the model (`app/modelpull.py`). |
| extension | `GET /api/extension`, `POST /api/extension/stage`, `POST /api/extension/reveal`, `POST /api/extension/launch`, `GET\|POST /api/extension/research-plane`, `GET /api/extension/quick-looks`, `POST /api/extension/quick-looks/{job_id}/pack`, `GET /api/extension/quick-look/{job_id}/asks`, `POST /api/extension/quick-look/{job_id}/ask`, `POST /api/extension/firefox/stage` | The staged directory, the version verdict, opening a browser with it, and the door a check starts from. |
| terminal | `GET /api/terminal/state`, `POST /api/terminal/input`, `POST /api/terminal/resize`, `POST /api/terminal/close` | One PTY per session (`app/providers/termpty.py`), for a one-time sign-in. The client is `kriko tui`; scrollback is bounded and resumable with `?offset=`. The origin check excludes extension origins. |
| focus | `POST /api/focus` | "Open in Kriko": the extension posts a route, and the engine prints the line that makes the shell raise the window. Nothing reads the route back. |

## Interface state, `app.sqlite`

Two SQLite files, on purpose. `~/.kriko/knowledge.sqlite` is the engine store;
`~/.kriko/app.sqlite` (`src/app/web/state.py`) is interface state.
Uninstalling a pack must not drop history, and history must not move a
`content_digest`. `/api/health` reports both paths.

```mermaid
%%{init: {"theme":"base","themeVariables":{"fontFamily":"ui-monospace, SFMono-Regular, Consolas, monospace","primaryColor":"#090E1B","primaryTextColor":"#F2F5FF","primaryBorderColor":"#1F4FFF","lineColor":"#86A3FF","secondaryColor":"#1739C2","tertiaryColor":"#080B16","noteBkgColor":"#BFE4FF","noteTextColor":"#05070F","actorBkg":"#090E1B","actorTextColor":"#F2F5FF","actorBorder":"#1F4FFF","signalColor":"#86A3FF","signalTextColor":"#86A3FF"}}}%%
flowchart LR
    ENGN["kriko/ engine"]:::brand --> K[("~/.kriko/knowledge.sqlite<br/>packs, claims, sources")]:::plain
    APP["app/ interfaces"]:::brand --> A[("~/.kriko/app.sqlite<br/>history, settings, jobs")]:::plain
    H["GET /api/health"]:::ice -.-> K
    H -.-> A
    classDef brand  fill:#1F4FFF,stroke:#86A3FF,color:#F2F5FF
    classDef plain  fill:#090E1B,stroke:#3A4156,color:#C9D1EA
    classDef ice    fill:#BFE4FF,stroke:#1F4FFF,color:#05070F
```

| Table | Holds |
|---|---|
| `settings` | The reader's preferences, as key and value. |
| `lookups` | Every check request and its response (History). |
| `claim_notes`, `claim_checks` | A reader's note and their tick-off, per check. |
| `claim_marks` | Author verdicts; they outlive the check that prompted them. |
| `jobs` | Job rows that outlive the request and the process. |
| `job_messages` | Reader-to-run messages. `taken_at` is set inside the read transaction, so a message is never delivered twice. |
| `pipeline_runs`, `pipeline_stages`, `pipeline_events` | What a run did, stage by stage, and what it printed. Written by the handlers; no route reads them back. |
| `submissions` | Agent-door input and the verdicts it drew. |
| `fact_checks` | The last "the page still says this" per (pack, claim). A dead link is a signal, not a retraction. |
| `extension_seen` | Extension origins, hit counts and versions. |
| `research_runs`, `research_run_claims` | Plane, model, budget against spend, outcome; per claim a `removed_at` for undo. Install-local. |
| `bench_runs` | Every benchmark row: plane, model, protocol, context size, cost, and the per-reason refusals. `rep` marks a repeat of the same case. `detail_json` keeps the versioned case, run settings, answer, evidence, runtime and diagnostics. |
| `operations` | The any-door work feed, bounded to 2000 rows. |
| `documents` | Quote-proving page text, one row per `source_id`, bounded. |
| `unmapped_labels` | Labels seen on pages that no adapter reads, written on each analysis. The analyze response carries the same list; nothing else reads the table back. |
| `local_adapters` | Site readers this installation taught itself. They never travel and never enter a digest. |
| `site_requests` | Unreadable sites the reader stood on, so "which site next" is answerable. |
| `site_activation` | The browser's per-site permission verdict. |
| `compare_drafts` | Named comparisons: which checks, in which order. |
| `queue_history` | Durable queue entries, including completed and removed products; active entries are reconciled from `research_queue`. |
| `research_queue` | Products queued from the extension, in research order, with the site each came from. |
| `compare_questions` | The reader's own questions about a comparison, and the answers their agent gave. |
| `compare_boards` | One comparison's pen marks and typed notes over the table, one JSON document per draft. Cleared when the draft is saved over, because a mark on a column that is gone is a mark about nothing. |

**Migration.** `connect()` stamps `PRAGMA user_version` with
`schema_stamp(SCHEMA)`, and `add_missing_columns()` reconciles
`declared_columns()` against `PRAGMA table_info`, additions only. History is
never dropped.

**Version handshake**, no polling. Requests carry `x-kriko-extension`
(`extension.VERSION_HEADER`) and responses `x-kriko-minimum-extension`
(`extension.MINIMUM_HEADER`); the floor is `extension.MINIMUM_VERSION`.

## The interfaces beside the web app

```mermaid
%%{init: {"theme":"base","themeVariables":{"fontFamily":"ui-monospace, SFMono-Regular, Consolas, monospace","primaryColor":"#090E1B","primaryTextColor":"#F2F5FF","primaryBorderColor":"#1F4FFF","lineColor":"#86A3FF","secondaryColor":"#1739C2","tertiaryColor":"#080B16","noteBkgColor":"#BFE4FF","noteTextColor":"#05070F","actorBkg":"#090E1B","actorTextColor":"#F2F5FF","actorBorder":"#1F4FFF","signalColor":"#86A3FF","signalTextColor":"#86A3FF"}}}%%
flowchart LR
    CLI["kriko (app/cli.py)"]:::ice -->|"packs, install, uninstall,<br/>enable, build, lookup"| ST[("knowledge.sqlite")]:::plain
    CLI -->|"prefs, costs, sites, verify,<br/>drafts, operations, bench, tui"| ENG["Engine client<br/>app/tui/client.py"]:::brand
    TUI["kriko tui"]:::ice --> ENG
    ENG -->|HTTP| WEB["a running app,<br/>or an in-process engine"]:::plain
    classDef brand  fill:#1F4FFF,stroke:#86A3FF,color:#F2F5FF
    classDef plain  fill:#090E1B,stroke:#3A4156,color:#C9D1EA
    classDef ice    fill:#BFE4FF,stroke:#1F4FFF,color:#05070F
```

Only the store commands open the database directly; everything else goes over
HTTP, because a second direct open is a second writer. Discovery order is
`--url`, `KRIKO_URL`, `EXTENSION_PORT` (8787), then an in-process engine
(`--no-start` fails instead of starting one).

**The operator console** (`src/app/tui/`) speaks the same HTTP API as the
desktop app and browser extension: `client.py` holds discovery and calls, `term.py` raw mode and the
frame differ, `screen.py` is a pure function of state, `app.py` is the loop.
Its tabs are Planes, Agenda, Jobs and Ops, and `s` hands the terminal to the
PTY until Ctrl-]. It is reachable as `kriko tui` or `kriko-sidecar --tui`, and
the Windows installer adds a Start-menu shortcut for it.

## The desktop shell

```mermaid
%%{init: {"theme":"base","themeVariables":{"fontFamily":"ui-monospace, SFMono-Regular, Consolas, monospace","primaryColor":"#090E1B","primaryTextColor":"#F2F5FF","primaryBorderColor":"#1F4FFF","lineColor":"#86A3FF","secondaryColor":"#1739C2","tertiaryColor":"#080B16","noteBkgColor":"#BFE4FF","noteTextColor":"#05070F","actorBkg":"#090E1B","actorTextColor":"#F2F5FF","actorBorder":"#1F4FFF","signalColor":"#86A3FF","signalTextColor":"#86A3FF"}}}%%
sequenceDiagram
    participant G as kriko-gpui/src/engine.rs
    participant S as src/app/sidecar.py
    G->>S: spawn
    S-->>G: KRIKO_PORT n (first line)
    loop while the window says it is starting
        G->>S: GET /api/health
    end
    Note over G,S: on failure the window renders stderr
```

`src/app/sidecar.py` binds port 0, prints `KRIKO_PORT <n>` first and hands the
bound socket to uvicorn. `kriko-gpui/src/engine.rs` spawns it, polls
`/api/health` while the window says it is starting; a failure renders stderr. `--mcp` runs
the MCP stdio server from the same binary and `--exit-with-parent` is the crash
belt. `packaging/kriko-sidecar.spec` freezes it,
`packaging/smoke_sidecar.py` gates the handshake, health and extension, and
`.github/workflows/desktop.yml` is the hand-run installer recipe. The
supervisor rules are in `CLAUDE.md` and `kriko-gpui/README.md`.

## The knowledge plane, the ledger

No human sign-off anywhere (`CLAUDE.md`, automation). The generic machinery is
in `src/kriko/ledger/`; the policy is the pack's own, in
`packs/<name>/pipeline/`.

```mermaid
%%{init: {"theme":"base","themeVariables":{"fontFamily":"ui-monospace, SFMono-Regular, Consolas, monospace","primaryColor":"#090E1B","primaryTextColor":"#F2F5FF","primaryBorderColor":"#1F4FFF","lineColor":"#86A3FF","secondaryColor":"#1739C2","tertiaryColor":"#080B16","noteBkgColor":"#BFE4FF","noteTextColor":"#05070F","actorBkg":"#090E1B","actorTextColor":"#F2F5FF","actorBorder":"#1F4FFF","signalColor":"#86A3FF","signalTextColor":"#86A3FF"}}}%%
flowchart LR
    A["acquire<br/>discover, rank, fetch, ingest"]:::plain --> X["extract<br/>grounded quotes"]:::plain
    X --> R["resolve<br/>component from evidence"]:::plain
    R --> V["cluster + verdict<br/>one call per cluster"]:::brand
    V --> E["export<br/>the pack's own YAML"]:::plain
    E --> B["build<br/>YAML to the store"]:::ice
    classDef brand  fill:#1F4FFF,stroke:#86A3FF,color:#F2F5FF
    classDef plain  fill:#090E1B,stroke:#3A4156,color:#C9D1EA
    classDef ice    fill:#BFE4FF,stroke:#1F4FFF,color:#05070F
```

| Stage | Where |
|---|---|
| acquire | the pack's own `pipeline/ledger/acquire.py`, with no model involved |
| chunk, extract | `src/kriko/ledger/chunking.py` and `extraction.py`; the noise gates run `kriko.gates` over the pack's own vocabulary file |
| resolve | the pack's `pipeline/ledger/resolve.py`, from the evidence text against the catalog's own codes, never from the query |
| verdict | the pack's `pipeline/ledger/verdict.py`, with `eval_verdict.py` checking it against that pack's gold set |
| export, parity | `packs/<name>/pipeline/ledger/export.py` writes the pack's own data files; `packs/<name>/pipeline/ledger/parity.py` diffs those files against the export by a stable identity |
| build | `src/kriko/pack/build.py` (`kriko build packs/<name>`). The ledger's database is never on the request path |

## Data formats

A **subject** is whatever the pack declares it to be. A mature pack's shape
happens to carry a variant record and a claim record; neither name is required
and neither is understood by the engine.

A claim, as a pack writes it in `packs/<name>/data/claims.yaml` (the `drill`
pack is the minimum, and `packs/drill/data/claims.yaml` is the full example):

```yaml
- subject: {kind: battery_platform, identity: {brand: makita, platform: LXT}}
  kind: known_issue              # the pack's own kinds
  domain: battery                # the pack's own area vocabulary
  severity: high                 # the pack's own scale
  detection: diagnostic          # visual | test_drive | diagnostic | history_check
  confidence: 0.7
  text:
    en:
      title: "<the claim, in the pack's own words>"
      body: "<what goes wrong, and when>"
      advice: "<what to check>"
  evidence:
    - url: "https://..."
      quote: "verbatim quote..."
      stance: supports           # supports | refutes | qualifies
```

`src/kriko/pack/build.py` stores that record as written: the subject, the
claim's kind, domain, severity and detection, its text per language, its
conditions and its evidence rows. It does not refuse a claim without evidence,
and it does not check a quote against its page. Quotes are checked where they
are kept: agent findings in `src/app/findings.py`, ledger output in the pack's
own `pipeline/`.

## Invariants

1. A subject's identity is permanent. A rename silently breaks every claim that
   referenced it.
2. Pack data is the source of truth. Rebuild; never edit the store.
3. Serving never calls a model or the ledger.
4. Verdicts are pipeline-owned.
5. Vocabulary is pack-owned. `kriko/` holds no category constant.
6. Nothing is deployed: one process, two SQLite files, no container and no
   database server (`test_the_app_stays_standalone`).
