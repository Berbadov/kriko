# Kriko — How It Works

Data flow, key functions, file paths, and relied-on invariants. Read before
touching the pipeline.

---

## Architecture: Four Packages, a Frontend, and a Shell

Interfaces and pipeline drivers sit above the generic engine; each pack ships
its own data, vocabulary, and evidence machinery under `packs/<name>/pipeline/`.

```
tauri/           desktop shell (Rust) — owns the sidecar's lifetime, nothing else
ui/              Svelte + Vite frontend, built into src/app/web/static/
app/             CLI, web dashboard, MCP server, job runner, sidecar
  └─ app/pipeline/  ledger and remediation drivers
                    └─ packs/     category data, builders, vocabulary, coverage
kriko/           generic pack store, lookup, ranking, ledger primitives
extension/       Chrome client for pack adapters (cars pack adapter ships first)
```

`kriko/` imports no other package; `packs/` doesn't import `app/`. Enforced
by `src/app/pipeline/tests/test_repo_invariants.py`. Serving DB: local SQLite
pack store; evidence ledger: separate SQLite build DB. Cars source of truth:
`packs/cars/data/`. No `backend/`, Postgres, or Docker layer. Generic ledger
mechanics (chunking, ingest, budgeting) in `src/kriko/ledger/`; packs inject
policy.

---

## Serving Plane: Request Path

### 1. Content script reads the page with the pack's own rules
**`extension/content.js`** — `buildScrape(knownLabels, panel)`

**Fields**: raw `label -> value` as printed, uninterpreted (which label means
`fuel` is the adapter's job in `kriko/adapters.py`; `knownLabels` from
`GET /api/adapters` only says which labels are worth digging for).
**Listing**: never on the wire — the panel draws it from the cached entry
(`damage_info`, `equipment`, `panel`; presentation rules ride in
`listing.panel` to reach the renderer without reaching the engine).

**`local_panel`**: selectors, the site's damage-state words, English
titles/hints, equipment categories, alert thresholds — adapter-declared,
returned opaque by `kriko.adapters.local_panel()`, carried on
`GET /api/adapters` (`{}` when none). Never a `RegExp` from pack patterns
(escaped *terms* only): shippable JS/regex would mean code execution on every
page the extension sees. `test_the_extension_speaks_no_sites_own_language`
fails non-ASCII *words* in `extension/` (lone chars are legitimate folds).
Array order is precedence (`"lokal boyalı"` before `"boyalı"`); **`unless:
[<rule-id>]`** is an else-branch as data (broad rule quiet when the narrower
fired).

### 2. Background script POSTs to /api/analyze
**`extension/background.js`** — labels/panel travel per request (never cached;
last week's rules would be invisible). `listing` stays out (engine must gain
no damage-silhouette schema). Results cached in `chrome.storage.session` by URL.

### 3. FastAPI /analyze endpoint
**`src/app/web/app.py`** — always HTTP 200; exceptions wrap as
`coverage_state: unavailable`. Variant matching, then claim resolution
(see `src/kriko/lookup/match.py`).

### 4. Identity resolver
**`src/kriko/lookup/match.py`** — category behaviour as `terms.match_json`
pack rows: `load_terms` (rules), per-pack unmerged `alias_map` /
`value_alias_map` (cars `brand`→`make`, drill the reverse — merging breaks
one), `normalize_identity` (caller keys/values onto pack vocabulary),
`resolve` (per-pack resolution, engine unions — two confident packs isn't
ambiguity), `expand` (related subjects, `max_hops=2`). Rules: **match on
attribute overlap, never `subject_id` equality** (disagreeing identity keys
hash one product apart — id-keying silently unmerges); **narrowing is soft**
(unmatched hints never yield `no_match` — keep subject, flag contradiction).
`Resolution` (`src/kriko/lookup/query.py`): `subject_ids`, `method`
(`exact`/`ambiguous`/`no_match`), `notes`, `flags` (unappliable narrowings —
coverage signal, never dropped).

### 5. Claim resolver
**`src/kriko/lookup/__init__.py`** — `lookup(query, conn)` over
`claim_variants`, only `verified` + `is_current`. Visual suppression (payload
v2): registry component (`claims.component_id` ←
`packs/cars/pipeline/catalog/components.yaml`) with `detection: visual` gets
`detection_factor = 0.35` (only with component_id + listing context; never
dropped — fail-open, multiplied into `relevance_score`).

### 5b. Ranking & payload v2
**`src/app/web/routers/analyze.py`**: severity (0.3/0.6/1.0) × mileage gate
(1.0/0.7 unknown, fail-open) × detection (0.35 visual / 1.0) × best-tier
source trust (NULL neutral). Sort `-relevance_score` (strength → consequence
→ severity), cap `MAX_RISKS_PER_LISTING`. Each risk carries `why_shown`;
response adds `subsystems: [{name, display_tr, risks}]` (by
`claims.subsystem`); flat `risks` stays for the current extension.

### Claim health — reading the evidence back out

`kriko/lookup/tree.py`: four uncombined signals — contradiction
(`stance='refutes'`), corroboration (distinct independent supporters), best
trust tier, staleness (`sources.retrieved_at`) — lexicographic ascending as
`ClaimHealth.concern`. No evidence = uncovered (excluded from
`weakest_claims()`, covered by the coverage report). Absent `retrieved_at`
sorts LAST (no timestamp ≠ stale; fresh-dated rows rank worse on this element
until B45–B47 activate the rest). Same column, three semantics: ledger writes
`MAX(d.fetched_at)` (last seen); `mcp_server.py` + `packs/cars/build.py` use
`INSERT OR IGNORE` (first-seen kept). `stance` is written at acceptance
(`app/findings.py::accept_findings`, default `supports`); `lang` threads
through `subject_tree()`/`weakest_claims()`/`Query.lang`/`/api/query`
(default `"en"`, never hardcoded in `kriko/`). Served via
`GET /api/health/weakest`, `GET /api/health/subject/{id}`
(`routers/health.py`), `subject_health`/`weakest_claims` MCP tools
(`src/app/mcp_server.py`); dashboard Health tab renders the same JSON.

### 6. Response rendering
**`extension/hover_lite/hover_lite.js`** — risk cards (`risk_card.js`,
`icons.js`) + step-1 local blocks. `buildCriticalAlerts` walks
`listing.panel.alerts` in order (fired-ids for `unless`; per-rule `say`
templates; names/tones/hints from `panel.states`/`panel.measures`; title-less
*original* state counted, never shown). `local_panel.test.js` reads e.g. the
shipped `packs/cars/adapters/sahibinden.json` (example adapter — Sahibinden ships first, any site can get one) — copies can't go stale
unnoticed.

---

## Jobs Plane: long work with a state a browser can see

Subject research and pack builds were terminal-only (vs G6 delivery).

**`src/app/web/state.py`** — `jobs` in `~/.kriko/app.sqlite` (never the
engine store): `state`, `progress`, `message`, `log`, `result_json`,
`cancel_requested`, three timestamps; `queued`/`running` → `succeeded |
failed | cancelled | interrupted`.

**`src/app/web/jobs.py`** — `JobRunner`, `ThreadPoolExecutor(max_workers=1)`:
row-write every transition; `recover()` at lifespan turns dead-process rows
`interrupted`; one worker (no concurrent same-dir builds); cooperative cancel
(`Progress.check()` → `Cancelled` between steps); one connection per job.

**`src/app/web/tasks.py`** — `(settings, params, progress) -> dict`.
`research` drives `kriko.research`'s `Researcher` (`plan_task` → `brief` →
`gather` → `extract`) into `app/findings.py::accept_findings` — the same
grounding/gate path as MCP `submit_findings` (door-independent provenance).
Default `agent` plane: `gather()` returns nothing; the brief is the $0
output. `pack_build` mirrors `kriko pack build` (pack `build.py` wins;
subject-less/claim-less artifacts refused).

**`src/app/web/routers/jobs.py`** — `POST /api/research`,
`POST /api/packs/build`, `GET /api/jobs[/{id}]`,
`POST /api/jobs/{id}/cancel`, `GET /api/jobs/{id}/stream` (SSE polls the row —
reconnect-safe; `ui/src/lib/jobs.ts` falls back to polling).

---

## The other API surfaces

Unlisted surfaces get treated as private — `test_docs_match_the_code.py`
fails until each names an endpoint.

**History** (`routers/history.py`): `GET /api/history`, `GET /api/lookup/{id}`
(`app.sqlite` `lookups`); per-lookup `POST /api/lookups/{id}/notes`,
`GET|POST /api/lookups/{id}/checked`, `GET /api/lookups/{id}/triage`;
`GET|POST /api/settings` (mode/theme).
**Marks** (`routers/marks.py`): `GET|POST /api/marks`,
`DELETE /api/marks/{pack_id}/{claim_id}` (withdrawal = never made),
`GET /api/marks/signals` — pack-keyed author verdicts (`wrong`, …).
**Subjects** (`routers/subjects.py`): `GET /api/subjects[/{id}[/brief]]` —
pack knowledge + the $0-path brief.
**Pipeline** (`routers/pipeline.py`): `GET /api/pipeline/runs[/{id}]`,
`/stream` — "what came of it" (sources, kept findings, refusals with reason)
vs the job log's "work happened". SSE polls rows.
**Agenda** (`routers/agenda.py`): `GET /api/agenda`, computed on read from
demand (analyses JSONL — survives history clears), gaps, thinness,
`fact_checks=missing`. No table/clock. `unknown_subject` rows (no
`subject_id`, unfileable) = catalog-coverage demand. Same computation as
`research_agenda` MCP tool; skill embeds top five, tool authoritative.
**Factcheck** (`routers/factcheck.py`): `GET|POST /api/factcheck` (only
`(pack_id, claim_id)` — quote from store, never caller: extension-reachable,
so no "URL contains string" oracle), verdicts
`quoted/missing/unreadable/unreachable` (`missing` = page changed, never
"claim false"; in `fact_checks`, no digest move; `GET` batches the screen);
`GET /api/factcheck/grounding` (B120/B128: offline
`grounded/ungrounded/not_kept` vs acceptance-kept text — only verdict able to
say "never kept"); `GET /api/factcheck/document` (kept text per `source_id`,
404 = `not_kept`); `POST /api/verify` (at `/api`: whole-screen operation;
`verify` job over `(pack_id, subject_id, limit)`, substring test, no model).
**Sites** (`routers/sites.py`): `GET /api/sites`, `POST /api/sites/seen`
(extension's unreadable-page report under `activeTab`), `POST
/api/sites/{host}/register` (agent job, checked adapter — `site` becomes a
host permission), `DELETE /api/sites/{host}`. Pack adapters always beat
learned ones (`app/sites.py`).
**Prefs/costs** (`routers/prefs.py`): `GET|PUT /api/prefs`, `GET /api/costs` —
agent/model/search + measured spend as one decision; unset = prior behaviour;
**no credit balance** (no vendor API exposes one).
**Operations** (`routers/operations.py`): `GET /api/operations[/stream]` —
any-door live agent-work feed (`docs/AGENT_OPERATIONS.md`); `app/operations.py`
wraps every MCP tool, job start, `/api/analyze` (MCP work visible *in flight*,
previously only post-hoc `submissions`). Open-before/close-after rows
(`running`; dead processes `interrupted`); payloads summarised (page text
elided — it has a table); stream polls (MCP server is a separate process).
**Pack drafts** (`routers/packs.py` ← `app/packauthor.py`, `app/packdraft.py`):
`POST /api/packs/scaffold` (contract-passing skeleton, installs nothing),
`GET /api/packs/drafts[/{slug}]`,
`POST /api/packs/drafts/{slug}/{build,amend,install}`,
`DELETE /api/packs/drafts/{slug}`. Drafts in `~/.kriko/drafts/<slug>/`;
**adapter is `adapters/*.json`, not `.yaml`** (the suffix `kriko.pack.build`
reads — a `.yaml` adapter once installed silently unreachable). Refused
without `principle` or **`lineup`** (no line-up ≈ named-everything: gap reads
zero). Subjects checked vs line-up (fuzzy) + `coverage.out_of_scope`;
named-by-neither **quarantined** with reason in `research/coverage.yaml`
(refusing wastes the rest; shipping miscategorises). `amend` (B127) fills gaps
only; `install` builds-if-needed, marks installed (re-amendable).
**Submissions** (`routers/submissions.py`): `GET /api/submissions` — only
legible refusals (`app/findings.py` grounding rejects).
**Keys** (`routers/keys.py`): `GET|PUT /api/keys`,
`DELETE /api/keys/{provider}` — `~/.kriko/env` (`app/sidecar.py` loads first).
Two providers only (generic writer = localhost `PATH`-setter). **No body
carries a key** (presence, source — environment beats file — last-four only;
`test_api_keys.py` covers error paths).
**Agent wiring** (`routers/agent.py` ← `app/agentconfig.py`):
`GET /api/agent-config` (exact `.mcp.json` `command`/`args`/`env`, never the
venv interpreter), `GET /api/agent-targets`, `POST
/api/agent-targets/{id}/{skill,connect}`, `GET /api/agent-skill`,
`POST /api/agent-verify` (real MCP `initialize` + `tools/list` over the exact
command, stderr reported — "written" ≠ "talking"). `env` non-empty **on
Windows only** (spawned Python without `SYSTEMROOT` can't resolve DNS).
**Research planes** (`routers/research.py`): `GET /api/research-planes` read
off `AgentResearcher`/`ApiResearcher` (no second vocabulary copy) + reader
cost sentence + `ready` (paid key check; agent readiness is
`/api/agent-targets`' question). No key material. **Harness cancel kills the
tree** (`check_cancelled` → `Progress.check`, 3 sites; propagates to
`_kill_tree(proc)` — cancel reads `cancelled`, no orphans).
**Agenda runs**: `POST /api/agenda/run` (inline per-row `_research` stages —
single worker can't submit-then-wait; `unknown_subject` skipped+counted, B82;
shared ceiling), `GET|DELETE /api/research-runs[/{id}]` (`DELETE` =
`research_undo` via `retract_claim`, tolerating absent — undo before the loop
needing it).
**Bench** (`routers/bench.py` ← `app/bench.py`, `app/protocols.py`):
`GET|POST /api/bench` (B111/B126). Store-derived cases (never enumerated);
`POST` job sweeps planes × protocols × provider × reps vs a throwaway store
copy (never grows the measured pack). Kinds: `specific` / `bulk` /
`validation` (re-fetch vs known answer, no model). `GET`: runs,
`bench.verdict()` (failure *how*, e.g. "4/5 harness, all `auth`"),
`bench.scored()` (recall/precision/hallucination + Wilson),
`protocols.choose()`, **readout** (per-model batch/context/preamble/provider,
cost/claim, hallucination + interval; <2 runs → default + `note`). `kriko
bench` = same sweep in-terminal.
**Extension** (`routers/extension.py`): `GET /api/extension`, `POST
/api/extension/stage`, `POST /api/extension/reveal` — staged dir for Chrome + version verdict;
`reveal` opens the folder, path fallback.
**Terminal** (`routers/terminal.py`): `GET /api/terminal/state`, `GET
/api/terminal/stream`, `POST /api/terminal/input`, `POST /api/terminal/resize`,
`POST /api/terminal/close` — real shell for harness one-time
`login`s; one PTY per session (`app/providers/termpty.py::SESSION`).
**Client is `kriko tui`, not the app** (§2.9): dashboard panel removed (335 KB
xterm + 440 KB budget for a detour); endpoints stay for Ctrl-] pass-through.
HTTP since 0.7.12: six B107/B109 releases fixed socket-handler paths while
0.7.10 showed close **1006** vs hand-made `Upgrade` → `101` + PTY bytes —
refused above the app, unfixable inside. `TermSession` drains to 256 KB
`SCROLLBACK`; consumers ask *after byte N?* (`/stream` resumable SSE
`?offset=`; `/state` one-shot + bug-report ask; `/close` permanent,
`_ensure()` never restarts). Relative URL can't misdial; shared `Depends`
`terminal_origin_is_allowed` excludes `EXTENSION_SCHEMES` (shell ≠
`/api/analyze` consequence) + refuses `EXTENSION_PORT`.

---

## Interface State: what `app.sqlite` holds, and why it is not in the store

Engine store (`~/.kriko/knowledge.sqlite`) vs interface history/settings
(`~/.kriko/app.sqlite`, `src/app/web/state.py`) — by rule: pack uninstall
must not drop history; history must not move `content_digest`. `/api/health`
reports both.

| Table | What it holds |
|-------|---------------|
| `settings` | Mode/theme (reader prefs). |
| `lookups` | Every analysis request+response JSON (History, `#/result/<id>`). |
| `claim_notes` / `claim_checks` | Per-lookup reader note / question-sheet tick-offs. |
| `claim_marks` | Per-pack author verdicts (`wrong`, …; outlive lookups). |
| `jobs` | Row outliving the request (Jobs Plane). |
| `pipeline_runs` / `pipeline_stages` / `pipeline_events` | "What a run did" (sources, kept findings, refusals+reason). |
| `submissions` | Agent-door input + verdicts; only legible refusals. |
| `fact_checks` | Last "page still says this" per (pack, claim); dead link = signal, not retraction. |
| `extension_seen` | Extension origins/counts/versions (side effect of real work). |
| `research_runs` | Plane/API/provider names (`model` column; API says `llm`), budget vs spend, outcome. Install-local (else digest divergence breaks update refusal). |
| `research_run_claims` | Per-run claims + `removed_at` (per-claim: counts can't undo). |
| `operations` | Any-door work feed, open-before/close-after, 2000-row bound. |
| `job_messages` | Reader→run messages + handover flag; `taken_at` in-read-transaction (never twice/double-paid). Only `--input-format` CLIs hear it (Claude `stream-json`: brief-first pipe, `ANSWER_WAIT_SECONDS` hold on questions, one-shot fallback after `CONVERSATION_START_SECONDS` — B125 shim). |
| `local_adapters` | Self-taught site readers; lose to pack adapters; never travel/digest. |
| `site_requests` | Unreadable stood-on sites (host/count/sample) — "which site next". |
| `site_activation` | Browser's per-site verdict (Chrome permission only the extension sees; wholesale-replaced per report). |
| `documents` | Quote-proving page text per `source_id`, bounded ("never fetched" ≠ "page gone"; no digest move). |
| `unmapped_labels` | Browsing-found labels no adapter reads (survives history clears). |

**Schema migration:** `connect()` stamps `PRAGMA user_version` with
`schema_stamp(SCHEMA)` — reruns on any edit (new tables) but no-ops new
*columns*; `add_missing_columns()` reconciles `declared_columns()` vs
`PRAGMA table_info` (additions only, raises on refused). Declaration is truth;
history never dropped/rebuilt.

**Version handshake:** no poll/endpoint (a timer is a third clock). Requests
carry `X-Kriko-Extension`, responses `X-Kriko-Minimum-Extension`; one number
(`app.extension.MINIMUM_VERSION`); four states with `unknown` ≠ `too_old`;
`behind` still works.

---

## The plain CLI: `kriko`

**`src/app/cli.py`.** `packs`, `install`, `uninstall`, `enable`, `build`,
`lookup` open the store directly — no server/network/process. `prefs`,
`costs`, `sites`, `verify`, `drafts`, `operations`, `bench`, `tui` need
`app.sqlite`/runner → `app.tui.client.Engine` over HTTP (never a second
direct open: two writers vs a running app). Attach on `EXTENSION_PORT` or
start in-process (`--no-start` fails instead); `bench` measures in-process on
its own copy. All `EngineError`s → one stderr line + non-zero exit (in
`_with_engine` only).

```
kriko prefs [--harness ID] [--model NAME] [--search ID]
kriko costs
kriko sites [list|register HOST|forget HOST]
kriko verify [--list] [--pack ID] [--subject ID]
kriko drafts [list|show|amend|build|install|discard SLUG]
kriko operations [--limit N]
kriko bench [--plane ...] [--cases N] [--protocol ...]
```

---

## Operator Console: `kriko tui`

`src/app/tui/` — fourth interface (cli/web/mcp + this), for the operator.
**Same HTTP API as the dashboard**; anything needing a new endpoint means the
API wasn't exposing it. Exists because operations were invisible and six
B107/B109 releases had no working surface (the surface was broken) — a second
same-API client is cheap and webview-proof.

```
kriko tui                 # attach, or start an engine
kriko-sidecar --tui       # same console from the frozen binary
kriko tui --url http://127.0.0.1:8787
kriko tui --no-start      # attach only
```

**One Windows click:** installer `NSIS_HOOK_POSTINSTALL` writes a **Kriko
Console** Start-menu shortcut to `kriko-sidecar.exe --tui` (uninstall removes;
no second artifact — it's Tauri's `externalBin`). `console=True`
(`packaging/kriko-sidecar.spec`; Tauri spawns `CREATE_NO_WINDOW`, nothing
suppresses here — terminal is the UI). **Standalone:** in wheel/sidecar = one
`sidecar.py` branch, before `reserve`; works with no Python/Node/WebView2.
`main()` silences stderr first (`create_app`'s handler would paint under the
alternate-screen differ; file handler kept).

| Module | What it owns |
|---|---|
| `client.py` | discovery + calls (stdlib `urllib`; 127.0.0.1 needs no dependency) |
| `term.py` | raw mode, alternate screen, keys, frame differ |
| `screen.py` | frame as **pure function** of state (layout = unit tests) |
| `app.py` | loop: poller thread snapshots, UI thread renders + keys |

**Discovery:** `--url` → `KRIKO_URL` → `EXTENSION_PORT` (desktop app always
there → same store/jobs/shell) → own in-process engine. **Harness runs read
live:** `--output-format stream-json` (+ `--verbose`), stdout line-drained +
stderr separated (no pipe deadlock), killer-timer timeout; `narrate()` → one
line/event into the job's `progress.log` (bounded transcript + capped
narration). **Four tabs + shell:** *Planes* (`harness.locate()` binary/path
or search paths); *Agenda* (Enter researches); *Jobs* (followed-job tail);
*Ops* (any-door feed incl. in-flight MCP `submit_findings`). `s` yields the
real terminal to the PTY until Ctrl-] (pass-through, no emulator — where
`claude` login happens). `term.diff` rewrites changed rows only (idle writes
nothing; 20 Hz key polling free).

---

## Desktop Shell: one store, two front doors

**`src/app/sidecar.py`** — child-process server: binds port 0, holds socket,
prints `KRIKO_PORT <n>` first, passes bound socket as uvicorn `fd=` (no
parent-child port race). CLI-identical path resolution.
**`tauri/src-tauri/src/main.rs`** — ~180-line supervisor, no engine logic
(`test_the_shell_holds_no_engine_logic`). Hidden window → spawn → handshake →
`/api/health` poll → `kriko://ready` → show; failure emits `kriko://failed` +
stderr via `textContent` (output, not markup). Killed on `Destroyed` *and*
`RunEvent::Exit` (dock-quit orphans hold the WAL lock).
**`src/app/web/routers/focus.py`** — "Open in Kriko": extension `<a href>`
served the SPA in a *browser tab* beside the desktop app. Pages can't raise
native windows, so the extension **posts a route**: sidecar prints
`KRIKO_FOCUS` (free on the handshake pipe) → shell `show_window` → window
polls `GET /api/focus` and navigates. Closed-shape validation (name +
optional id — shell mustn't know SPA routes), in-memory, expiring,
consume-once (no stale jumps, no double-navigate). `test_sidecar.py` pins
`FOCUS_LINE` to the Rust constant.
**`packaging/kriko-sidecar.spec`** freezes it (`hiddenimports` for uvicorn's
string-resolved protocols; `datas` for the FS-read frontend);
`packaging/smoke_sidecar.py` gates handshake + health + frontend;
`.github/workflows/desktop.yml` builds unsigned installers (no Rust-toolchain
build as of 2026-09-01 — B52).

## Knowledge Plane: Pipeline

Ledger, not approval queue: `app.pipeline.ledger_run`, discovery → export, no
human sign-off (CLAUDE.md automation). Generic `src/kriko/ledger/` (loop,
ingest, budget) + cars policy in `packs/cars/pipeline/` (signal, distrusted
sources, evidence→component). Legacy per-part curated YAMLs
(`sources/curated/part_{part_id}.yaml`) = residual manual-add path.

**Acquisition** (`ledger/acquire.py`): discover → rank (part-code
specificity, B8) → fetch → ingest, no LLM.
**Chunking/extraction** (generic `src/kriko/ledger/chunking.py` /
`extraction.py`: loop, cache, budget; cars `ledger/chunking.py` gate: failure
lexicon + catalog code tokens; `ledger/extraction.py` + `langextract_client.py`:
grounded few-shot, quotes aligned to source spans; noise rules via
`kriko.gates.gate_reason` over `vocabulary/gates.yaml`).
`pipeline/extract.py` is offline-only, not in this loop.
**Resolution** (`ledger/resolve.py`): component from evidence text vs catalog
codes, never the finding query (design_flaws.md Flaw 1).
**Verdict** (`ledger/verdict.py`): one `deepseek-v4-flash` call per cluster
(replacing ministral five-gate + promotion, Flaw 5): attribution + support +
value + severity + EN/TR copy, input-hash cached; `eval_verdict.py` vs
`pipeline/gold/gold.yaml` (11 hand-judged).
**Export** (`ledger/export.py`): deterministic claim view → part-dict YAML
under `packs/cars/data/parts/**`, catalog-derived headers, unservable rows
dropped. **Regression** (`ledger/parity.py`): YAML-vs-export diff by stable
identity, not titles (B1 blocker 2). **DB sync** (`src/kriko/pack/build.py`):
YAML → SQLite (`python -m app.cli build packs/cars`); ledger DB never on the
request path.

---

## Data Formats

### Variants YAML (`packs/cars/data/variants/{make}_{model}_{gen}.yaml`)
```yaml
- id: megane4_h5h_140          # stable forever, never rename
  make: renault                 # lowercase canonical
  model: megane                 # lowercase canonical
  generation: "IV"
  engine_code: H5H
  fuel: petrol                  # petrol | diesel | hybrid | electric | lpg
  displacement_cc: 1332
  power_min_hp: 115
  power_max_hp: 140
  transmission: automatic       # manual | automatic
  year_from: 2018
  year_to: null                 # null = still in production
  market: TR
```

### Claims YAML (`packs/cars/data/parts/{part_type}/{part_id}.yaml`)
```yaml
- id: megane4_h5h_timingchain_v1      # {claim_key}_v{version}
  claim_key: megane4_h5h_timingchain  # stable across versions
  version: 1
  is_current: true
  title: "1.3 TCe (H5H) timing chain stretch and tensioner wear"
  domain: engine                      # engine|transmission|electrical|emissions|fuel system|brakes|suspension|general
  severity: high                      # high|medium|low
  confidence: 0.72                    # 0.0–1.0
  rationale: "..."
  inspection_advice: "..."
  status: verified                    # verified|draft|held|review|rejected
  promoted_by: human                  # human|auto|auto_audit
  variants:
    - variant_id: megane4_h5h_140
      grounding_note: "..."
  sources:
    - source_url: "https://..."
      site_or_channel: "Reddit r/Renault"
      quote: "verbatim quote..."
      independent: true
```

### Curated sources YAML (`packs/cars/pipeline/sources/curated/part_{part_id}.yaml`, legacy manual-add path)
```yaml
- type: youtube                   # youtube | page
  video_id: "abc123xyz"           # for youtube
  # url: "https://..."            # for page
  site_or_channel: "Auto Tanı TR"
  notes: "human note"
  status: pending                 # pending | processed | skipped
  added_at: "2026-06-26"
  processed_at: null
```

---

## Key Invariants

1. **Variant IDs are permanent** — claims reference them; renames break links silently.
2. **Pack YAML is source of truth** — rebuild (`python -m app.cli build
   packs/cars`), never edit the store.
3. **Serving store is generic and local** — no ledger/LLM on the request path.
4. **Verdicts are pipeline-owned** — no human sign-off in the data path.
5. **Serving never calls an LLM** — `/analyze` reads the DB; LLM work is offline.
6. **Vocabulary is pack-owned** — no car constants in the generic engine.
7. **Nothing is deployed** — one process, two SQLite files, no container/DB
   server (port 0 so copies never fight over 8000).
   `test_the_app_stays_standalone` fails on Dockerfile/compose/Postgres driver.
