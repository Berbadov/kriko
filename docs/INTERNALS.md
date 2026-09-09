# Kriko — How It Works

This document explains every mechanism in detail: data flow, key functions, file paths,
and the invariants the system relies on. Read this before touching the pipeline.

---

## Architecture: Four Packages, a Frontend, and a Shell

Dependencies form a fan. Interfaces and pipeline drivers sit above the generic
engine; each category pack provides its own data, vocabulary, and evidence
ledger/extraction machinery under `packs/<name>/pipeline/`.

```
tauri/           desktop shell (Rust) — owns the sidecar's lifetime, nothing else
ui/              Svelte + Vite frontend source, built into src/app/web/static/
app/             CLI, local web dashboard, MCP server, job runner, sidecar
  └─ app/pipeline/  ledger and remediation drivers
                    └─ packs/     category data, builders, vocabulary, coverage
                                  └─ packs/cars/pipeline/  evidence ledger and
                                     grounded extraction for the cars pack
kriko/           generic pack store, lookup, ranking, and ledger primitives
extension/       Chrome client for the cars pack adapter
```

`kriko/` imports none of the other packages. `packs/` does not import `app/` or
`app/pipeline/`; only pipeline drivers coordinate the evidence pipeline and pack
data. The structural rules are enforced by
`src/app/pipeline/tests/test_repo_invariants.py`. The serving database is the local
SQLite pack store; the evidence ledger is a separate SQLite build database.

The cars source of truth is under `packs/cars/data/`. There is no `backend/`,
Postgres sync, or Docker-only serving layer in the current architecture.

The pack files are built into the serving SQLite store; the evidence ledger remains
separate from that read path. `app/pipeline/` is where operations that span packs
and their pipelines live; the generic ledger mechanics (chunking, ingest, cost
budgeting) live in `src/kriko/ledger/`, with each pack injecting its own policy.

---

## Serving Plane: Request Path

### 1. Content script extracts listing data
**`extension/content.js`** — `extractSahibindenMetadata()`

Queries the DOM of a Sahibinden listing page and returns a structured object:
```js
{
  make, model, year, fuel_type,  // from classifiedInfoList <ul>
  transmission, engine_volume_cc, power_hp,  // from #technical-details table
  trim,          // Sahibinden "Model" field (e.g. "1.5 dCi Joy")
  damage_info,   // parsed body damage silhouette
  equipment,     // parsed Donanım checkboxes
  url, title, ...
}
```

Key mapping in `mapTurkishKeys()`: Sahibinden uses "Yakıt Tipi"/"Benzinli" etc. The map
converts Turkish field names → English keys. "Benzinli" → `fuel_type: "Benzinli"`.

### 2. Background script POSTs to /analyze
**`extension/background.js`** — `requestAnalysis(adMetadata)`

Sends `POST http://127.0.0.1:8000/analyze` with the metadata as `ad_metadata`. Tries
two fallback URLs (`8000`, `8765`). Results are cached in `chrome.storage.session` for
6 hours by URL+metadata signature hash.

### 3. FastAPI /analyze endpoint
**`src/app/web/app.py`** — `create_app()` and the `/api/analyze` route

Always returns HTTP 200. Exceptions are caught and wrapped as `coverage_state: unavailable`.

```python
meta   = payload.ad_metadata or {}
match  = match_variant(meta, db)       # → MatchResult
claims = resolve_claims(match, db)     # → list[Claim]
```

### 4. Variant matcher
**`src/kriko/lookup/match.py`** — generic identity and attribute matching

Normalizes raw metadata → canonical values:
- `normalize_fuel("Benzinli")` → "petrol" (pack-declared vocabulary and adapter normalization)
- `normalize_make("Renault")` → `"renault"`
- `normalize_model("Megane")` → `"megane"`
- `normalize_transmission("Otomatik")` → `"automatic"`

Hard filter: DB query on `(make, model, fuel, year_from ≤ year ≤ year_to)`.
Narrowing (never eliminates all): by cc tolerance ±100, hp ±10, transmission exact.

Returns `MatchResult(variant_ids, method, notes)` where method is:
- `"exact"` — single match
- `"ambiguous"` — multiple matches (all returned, all their claims served)
- `"no_match"` — missing required field or nothing found
- `"inconsistent_listing"` — cc/hp don't match any real variant

Missing required fields check (line 25):
```python
if not make or not model or not fuel or not year:
    missing = [k for k, v in [...] if not v]
    return MatchResult([], "no_match", f"Missing required fields: {missing}")
```

### 5. Claim resolver
**`src/kriko/lookup/__init__.py`** — `lookup(query, conn)`

Queries `claim_variants` join table for all matched variant IDs, returns only
`status='verified'` and `is_current=True` claims.

Visual-detection suppression (payload v2): a claim whose registry component
(`claims.component_id`, filled by sync from `packs/cars/pipeline/catalog/components.yaml`)
has `detection: visual` gets `ClaimResult.detection_factor = 0.35` — but ONLY
when the claim has a component_id and a listing context exists. The claim is
never dropped (fail-open); the API layer multiplies the factor into
`relevance_score`.

### 5b. Ranking & payload v2
**`src/app/web/routers/analyze.py`** — the `/api/analyze` route

`relevance_score = severity weight (low 0.3 / medium 0.6 / high 1.0)
× mileage-gate match (satisfied 1.0 / unknown 0.7, fail-open)
× detection factor (visual 0.35 / else 1.0)
× source-trust weight (best tier across sources, NULL = neutral)`

Risks sort by `-relevance_score` (strength → consequence → severity as
tiebreak), then are capped to `MAX_RISKS_PER_LISTING`. Each risk carries
`why_shown`: human-readable reasons the card is shown — config match (variant
label), mileage gate ("187.000 km > 120.000 km threshold" or "mileage unknown
— shown by default"), visual-detection suppression, source trust. The
response also carries `subsystems: [{name, display_tr, risks}]` — the same
risks grouped by registry subsystem (`claims.subsystem`) for the v2 UI; the
flat `risks` array stays for the current extension.

### Claim health — reading the evidence back out

`kriko/lookup/tree.py` answers the question the serving path cannot: *how well
supported is what we ship?* Four signals, never combined into a score —
contradiction (`evidence.stance = 'refutes'`), corroboration (distinct
independent supporting sources), the best source's trust tier, and staleness
(`sources.retrieved_at`).

Ordering is lexicographic and ascending on every element, exposed as
`ClaimHealth.concern`, so the order is inspectable rather than implied by a
weight nobody can justify. Two deliberate asymmetries:

- **A claim with no evidence is not weak, it is uncovered.** It is excluded
  from `weakest_claims()` and reported by the coverage report instead, matching
  `rank.py`'s treatment of source-free interval claims as trust-neutral.
- **An absent `retrieved_at` sorts LAST, not first.** No timestamp is not
  evidence of staleness. Before 2026-08-31 all three producers wrote `''`
  here; they now derive it (`documents.fetched_at` in the ledger, the
  submission time over MCP), and legacy rows stay honestly blank. One
  consequence follows from that choice: a claim with a known, fresh date
  ranks *worse* on this element than a claim with no date at all, because
  blank is deliberately treated as carrying no information rather than as
  maximally stale. Until B45–B47 land and the other three signals stop
  being near-universally inert, that makes the better-documented half of the
  catalog look worse than the undocumented half on this one column.
- **The three producers agree on the column, not on the semantic.** The
  ledger exporter writes `MAX(d.fetched_at)` — "the last time we saw the
  page." `mcp_server.py` and `packs/cars/build.py` both write it with
  `INSERT OR IGNORE`, so a URL that is resubmitted, or shared by two claims,
  keeps whatever stamp it was *first* given. `EvidenceRow.retrieved_at`'s
  comment ("when WE last saw the page") is exactly true for the ledger path
  and only approximately true for the other two.

Served read-only via `GET /api/health/weakest` and `GET /api/health/subject/{id}`
(`src/app/web/routers/health.py`) and the `subject_health`/`weakest_claims` MCP
tools (`src/app/mcp_server.py`); the dashboard's Health tab
(`src/app/web/static/`) renders the same JSON.

### 6. Response rendering
**`extension/hover_lite/hover_lite.js`**

Reads `coverage_state`, `risks[]`, `summary`, `disclaimer` from the API response.
Renders the panel overlay with severity-colored risk cards.
Risk cards are in `hover_lite/risk_card.js`. Icons in `hover_lite/icons.js`.
When the response carries `subsystems[]`, groups render per subsystem with the
Turkish label (`display_tr`) instead of per domain; `why_shown` renders as
small muted chips under each card title.

---

## Jobs Plane: long work with a state a browser can see

Two operations grow the knowledge base — researching a subject and building a
pack — and both used to be reachable only from a terminal, which contradicted
G6's delivery constraint directly.

**`src/app/web/state.py`** — the `jobs` table in `~/.kriko/app.sqlite` (never in
the engine's store). Columns: `state`, `progress`, `message`, `log`,
`result_json`, `cancel_requested`, plus the three timestamps. States are
`queued`, `running`, and the terminal set `succeeded | failed | cancelled |
interrupted`.

**`src/app/web/jobs.py`** — `JobRunner` over a `ThreadPoolExecutor(max_workers=1)`.

- *Rows first, thread second.* Every transition is a row write. `recover()`
  runs from the app's lifespan and turns `running`/`queued` rows left by a dead
  process into `interrupted` — a killed server leaves an explanation, not a row
  that claims forever to be working.
- *One worker.* Two concurrent builds writing the same pack directory is a bug
  that should not be expressible.
- *Cooperative cancel.* `Progress.check()` raises `Cancelled` between steps.
  Killing a thread mid-write is how a half-installed pack happens.
- Each job opens its own sqlite connection: connections are thread-bound and
  the submitting request is long gone by the time the worker starts.

**`src/app/web/tasks.py`** — the two handlers, signature
`(settings, params, progress) -> dict`. `research` drives `kriko.research`'s
`Researcher` protocol (`plan_task` → `brief` → `gather` → `extract`) and hands
findings to `app/findings.py`'s `accept_findings` — the *same* grounding and
gate path the MCP `submit_findings` tool uses, so a claim's provenance does not
depend on which door it came in. On the default `agent` plane `gather()` returns
nothing by design; the brief is the output, and that is the $0 path, not a
degraded one. `pack_build` mirrors `kriko pack build`, including "a pack with
its own `build.py` uses it" and "an artifact with no subjects and no claims is
refused rather than installed".

**`src/app/web/routers/jobs.py`** — `POST /api/research`, `POST /api/packs/build`,
`GET /api/jobs`, `GET /api/jobs/{id}`, `POST /api/jobs/{id}/cancel`, and
`GET /api/jobs/{id}/stream`. The stream is SSE over a *poll of the row*, not a
push from the worker: a queue would need plumbing through the pool and would
still lose everything on reconnect, so the row stays the single source of
truth. `ui/src/lib/jobs.ts` falls back to plain polling when `EventSource` is
absent or the stream dies mid-job.

---

## The other API surfaces

Eight doors that the planes above do not open. Listed here because a surface
nobody wrote down is a surface the next change treats as private —
`test_docs_match_the_code.py` fails until each one names an endpoint.

**`GET /api/history`, `GET /api/lookup/{id}`** (`routers/history.py`) — the
reader's own record, out of `app.sqlite`'s `lookups`. Also the per-lookup
annotations: `POST /api/lookups/{id}/notes` (a note the reader wrote),
`GET|POST /api/lookups/{id}/checked` (claims ticked off on the question sheet)
and `GET /api/lookups/{id}/triage`. All *per lookup* on purpose — a note is
about the answer that was given, not about the knowledge. Mode and theme ride
here too (`GET|POST /api/settings`), because they are interface state in the
same file.

**`GET|POST /api/marks`, `DELETE /api/marks/{pack_id}/{claim_id}`,
`GET /api/marks/signals`** (`routers/marks.py`) — an author's verdict on a
claim: `wrong`, `outdated`, and the rest. Keyed by pack rather than by lookup,
because the judgement is about the knowledge and outlives the lookup that
surfaced it, and a withdrawal is a `DELETE` rather than a flag — a mark that
is gone should read as never made. `signals` aggregates them for the Knowledge
screen's "what is marked" lens.

**`GET /api/subjects`, `GET /api/subjects/{id}`, `GET /api/subjects/{id}/brief`**
(`routers/subjects.py`) — what a pack knows about one subject, and the research
brief for it. The brief is the $0 path's actual output: on the default `agent`
plane nothing is gathered by the engine, so the brief *is* the deliverable
rather than a degraded version of one.

**`GET /api/pipeline/runs`, `GET /api/pipeline/runs/{id}`,
`GET /api/pipeline/stream`** (`routers/pipeline.py`) — the event spine over
`pipeline_runs` / `pipeline_stages` / `pipeline_events`. A job log answers
"did long work happen and what did it print"; this answers "what came of it" —
sources read, findings kept, refusals with a reason. A run that gathered
nothing and a run that lost everything at the grounding check look identical in
a job log, which is why this is a second surface rather than a column on the
first. The stream is SSE over a poll of the rows, for the same reason the job
stream is.

**`GET /api/agenda`** (`routers/agenda.py`) — what to research next, ranked.
`app/agenda.py` computes it on read from four signals kept separate: demand
(how often the analyses log was asked about a subject), gaps, thinness, and a
`fact_checks` verdict of `missing`. No table and no clock, because an agenda
that recommended a subject researched an hour ago would be worse than none.
Demand comes from the JSONL log rather than from `lookups` — the log is the
demand corpus and survives a reader clearing their history, which is why
`routers/analyze.py` writes both. One of its four row kinds is not an agent
task: `unknown_subject` is a product this installation was asked about that no
subject exists for, so it has no `subject_id`, nothing can be filed against it,
and it is demand for *catalog* coverage. The MCP tool `research_agenda` is the
same computation through the other door, and the generated skill embeds the
top five with the sentence that the tool, not the file, is authoritative.

**`GET|POST /api/factcheck`** (`routers/factcheck.py`) — one press: does the
page a claim cites still contain the quote the pack shipped? The `POST` takes a
`(pack_id, claim_id)` and nothing else, because the quote is read out of the
store rather than taken from the caller — the browser extension can reach this
surface, and a door that accepted "does this URL contain this string" would be
an open fetch oracle. Four verdicts, `quoted / missing / unreadable /
unreachable`, and `missing` says the page changed, never that the claim is
false: pages get rewritten and Kriko has no authority to retract anything, so
the verdict ranks nothing, hides nothing, and lives in `app.sqlite`'s
`fact_checks`. The `GET` returns the whole screen's verdicts in one request,
which is what keeps a report of forty claims from opening forty requests.

**`GET /api/submissions`** (`routers/submissions.py`) — what came in through
the agent door and what the gate did with it. The only place a *refusal* is
legible: `app/findings.py` rejects on grounding, and without this the rejection
is a log line nobody reads.

**`GET /api/extension`, `POST /api/extension/stage`,
`POST /api/extension/reveal`** (`routers/extension.py`) — where the unpacked
extension is on disk, staged into a stable directory the reader can point
Chrome at, plus the version compatibility verdict described below. `reveal`
opens the staged folder in the file manager — a convenience with a fallback,
never a requirement: the response carries the path either way, because if the
open fails the reader's next action is pasting it.

---

## Interface State: what `app.sqlite` holds, and why it is not in the store

Two SQLite files, on purpose. `~/.kriko/knowledge.sqlite` is the engine's
store; `~/.kriko/app.sqlite` (`src/app/web/state.py`) is the *interface's* own
history and settings. The split is a rule, not a convenience: uninstalling a
pack must not drop your history, and a history row must not move a pack's
`content_digest`. `/api/health` reports both paths.

Every table, and the question it answers:

| Table | What it holds |
|-------|---------------|
| `settings` | Mode and theme. The reader's preferences, not the engine's config. |
| `lookups` | Every analysis, request and response as stored JSON. The History panel and `#/result/<id>` read it; nothing else is the record of what the app actually answered. |
| `claim_notes` | A note the reader wrote against one claim of one lookup. |
| `claim_checks` | The reader ticking off a claim on the question sheet — inspection-day state, per lookup. |
| `claim_marks` | An author's verdict on a claim (`wrong`, `outdated`, …), per pack rather than per lookup, because the judgement is about the knowledge and outlives the lookup that surfaced it. |
| `jobs` | The row that outlives the request. See the Jobs Plane above. |
| `pipeline_runs`, `pipeline_stages`, `pipeline_events` | The event spine: what a knowledge run *did*, stage by stage, with sources read, findings kept, and refusals with a reason. A job log says whether work happened; this says what came of it. |
| `submissions` | What came in through the agent door and what the gate did with it — the only place a refusal is legible. |
| `fact_checks` | The last answer to "does the cited page still say this", per (pack, claim). A reader's fetch of someone else's web page: it cannot move a `content_digest`, must not travel to the next install, and a dead link is a signal here rather than a retraction in the pack. |
| `extension_seen` | Which extension origin has called, how often, and the version it announced. A sighting is a side effect of the extension doing its real work, so it cannot be true while the install is broken. |
| `unmapped_labels` | Labels a reader's browsing found on a site that the pack's adapter reads nothing from. A pack's adapter is content; what a reader's browsing revealed about a site is not — so it lives here, never moves a `content_digest`, and survives clearing history. |

**Schema changes reach an existing file.** `connect()` stamps `PRAGMA
user_version` with `schema_stamp(SCHEMA)` — a content fingerprint, so any edit
re-runs `executescript(SCHEMA)`. That handles a new *table* and does nothing at
all for a new *column*, because `CREATE TABLE IF NOT EXISTS` is a no-op on a
table that exists. Every schema change before 2026-09-08 happened to be a new
table, which is why nobody noticed. So `add_missing_columns()` parses the
`CREATE TABLE` blocks out of `SCHEMA` itself (`declared_columns()`) and
reconciles them against `PRAGMA table_info`: additions only, and it raises on
anything SQLite refuses rather than papering over it. The declaration is
already the truth — the same rule the catalog follows. `app.sqlite` is history,
not a cache: it can never be dropped and rebuilt.

**The version handshake.** The extension and the app update on separate clocks,
and neither waits for the other. Every request out carries
`X-Kriko-Extension`; every response back carries `X-Kriko-Minimum-Extension`.
No poll and no endpoint — a check-in on a timer is a third clock to keep wound,
and one that is stale between winds is the failure being fixed. The rule is one
number in one place, `app.extension.MINIMUM_VERSION`. Four states, because
`unknown` (nothing has ever called) has to be separate from `too_old`: telling
a reader who never installed the extension that theirs is out of date is worse
than saying nothing. `behind` still works.

---

## Desktop Shell: one store, two front doors

**`src/app/sidecar.py`** — the server as a child process. It binds port 0,
holds the socket, prints `KRIKO_PORT <n>` as its first line of stdout, and
passes the bound socket to uvicorn as `fd=`. The child chooses the port because
a parent that finds a free one has already lost it by the time the child binds;
handing over the socket means uvicorn cannot rebind and serve elsewhere. Paths
resolve exactly as the CLI resolves them, so a pack installed in the app is
visible to `python -m app.cli`.

**`tauri/src-tauri/src/main.rs`** — ~180 lines of process supervisor and no
engine logic (`test_the_shell_holds_no_engine_logic` fails if that changes).
The window is created hidden; Rust spawns the sidecar, reads the handshake,
polls `/api/health`, then emits `kriko://ready` and shows it. On failure it
emits `kriko://failed` with the captured stderr, which `tauri/shell-ui/index.html`
renders through `textContent` — a blank window is a bug, and stderr is
subprocess output, not markup. The child is killed on window `Destroyed` *and*
on `RunEvent::Exit`: a quit from the dock destroys no window, and the orphan
would hold the store's WAL lock into the next launch.

**`src/app/web/routers/focus.py`** — "Open in Kriko", which is the one handoff
that cannot be a link. The extension's button was an `<a href>` at the app's
own HTTP port: the route resolves, the SPA is served over HTTP, and the reader
gets the report *in a browser tab* beside the desktop app they already have
running. They asked for the app and got a web page that looks like it. A page
cannot raise a native window, so the handoff runs the other way — the extension
**posts a route** and the two processes that can act on it each take their half.
The sidecar prints `KRIKO_FOCUS` on stdout (the shell is already reading that
pipe for the port handshake, so it costs nothing) and the shell calls
`show_window`; the window polls `GET /api/focus` and navigates. The shell can
raise a window but has no business knowing the SPA's route table, and this
module must not hold it either — so the posted route is validated as a *closed
shape* (a name, optionally one `/`-separated id) rather than against a list of
routes. It is in memory and expires: a nudge between two live processes is not
history, and a route persisted across a restart resurfaces as the window
jumping to a stale report days later. Consume-once on read, or two windows both
navigate. `test_sidecar.py` fails if `FOCUS_LINE` and the Rust constant drift,
because a renamed constant here reads as a dead button.

**`packaging/kriko-sidecar.spec`** freezes it (the `hiddenimports` list exists
because uvicorn resolves its protocol implementations by string, and the `datas`
entry because the frontend is read from the filesystem, not imported).
`packaging/smoke_sidecar.py` checks handshake + health + a served frontend
between freeze and bundle. `.github/workflows/desktop.yml` builds unsigned
installers on three runners. As of 2026-09-01 none of these have been built on
a machine with a Rust toolchain — see backlog B52.

## Knowledge Plane: Pipeline

The pipeline is a ledger, not a curated-YAML approval queue: `app.pipeline.ledger_run`
drives discovery through export with no human sign-off step (automation principle,
CLAUDE.md). Each stage splits into a generic half in `src/kriko/ledger/` (orchestration —
chunking loop, ingest, cost budgeting) and a cars-specific half in
`packs/cars/pipeline/` (policy — what counts as signal, which sources are
untrustworthy, which component an evidence chunk describes). A handful of legacy
per-make/model curated YAMLs remain under
`packs/cars/pipeline/sources/curated/part_{part_id}.yaml` (one file per *part*, not
per make+model) as a residual manual-add path; they are not required by the live flow.

### Acquisition
**`packs/cars/pipeline/ledger/acquire.py`** — discover → rank → fetch → ingest for a
part, no LLM involved. Results are ranked by part-code specificity before fetching
(backlog B8), rather than taking the first N results in discovery order.

### Chunking and extraction
**`src/kriko/ledger/chunking.py`** / **`src/kriko/ledger/extraction.py`** — generic chunk loop,
cache, and budget charge. **`packs/cars/pipeline/ledger/chunking.py`** supplies the cars
chunk gate (the failure lexicon plus catalog-derived engine/gearbox code tokens — a
chunk is worth extracting if it names a failure word or a code, so a new part is
covered the moment its stub exists). **`packs/cars/pipeline/ledger/extraction.py`**
supplies langextract as the extractor via **`packs/cars/pipeline/langextract_client.py`**
(grounded/few-shot extraction — each claim's quote is aligned to an exact character span
in the source rather than trusted as a self-reported string) plus the low-value rules
(`kriko.gates.gate_reason` over this pack's `vocabulary/gates.yaml`) that flag which
extracted claims are noise. `packs/cars/pipeline/extract.py` is a separate, offline-only
module (its own docstring: "never on the /analyze request path") — it is not part of
this ledger loop.

### Entity resolution
**`packs/cars/pipeline/ledger/resolve.py`** — decides which component a piece of
evidence describes, from the evidence's own text against catalog-derived codes, never
from the search query that found the document (design_flaws.md Flaw 1).

### Verdict
**`packs/cars/pipeline/ledger/verdict.py`** — one strong-model (`deepseek-v4-flash`)
verdict per claim-cluster. This replaced the old five-gate ministral stack
(`gate_generic`/`gate_variant`/`gate_support`/`gate_refute`) and the separate scored
promotion step (design_flaws.md Flaw 5): a single call sees the whole cluster, the
component, its sibling codes, and the product principle, and returns attribution +
support + value + severity + bilingual (EN/TR) copy in one JSON object. Verdicts are
cached by input hash. **`packs/cars/pipeline/ledger/eval_verdict.py`** runs the
acceptance eval against `packs/cars/pipeline/gold/gold.yaml` (11 hand-judged entries).

### Export
**`packs/cars/pipeline/ledger/export.py`** — claims as a deterministic view over
verdicts, written as the part-dict YAML schema under `packs/cars/data/parts/**`. Part
headers come from the served catalog itself, never hand-enumerated. The pack builder
validates references and avoids shipping rows that cannot be served.

### Regression check
**`packs/cars/pipeline/ledger/parity.py`** — diffs existing claim YAMLs against a fresh
ledger export; matching is by stable identity, not title text, because the verdict
stage rewrites titles (backlog B1 blocker 2).

### DB sync
**`src/kriko/pack/build.py`** — build the pack into SQLite

Builds the pack YAML into the local SQLite serving store. Rebuild explicitly with
`python -m app.cli build packs/cars`.

The serving store contains generic subjects, attributes, claims, evidence and
relations. The evidence ledger uses its own SQLite database and is never read by
the request path.

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

1. **Variant IDs are permanent.** Once a variant is in the DB, its ID never changes.
   Claims reference variant IDs — renaming breaks the link silently.

2. **Pack YAML is the source of truth, not the serving DB.** Rebuild the local
   SQLite pack from YAML with `python -m app.cli build packs/cars`; never edit the
   generated store directly.

3. **The serving store is generic and local.** Pack data is compiled into SQLite;
   the request path does not call the evidence ledger or an LLM.

4. **Verdicts are pipeline-owned.** Deterministic gates and verdict stages decide
   what can be exported; no human sign-off is part of the data path.

5. **The serving plane never calls an LLM.** `/analyze` only reads the DB. All LLM
   work happens offline in the knowledge plane.

6. **Category vocabulary is pack-owned.** Cars-specific labels and aliases live
   under `packs/cars/`; the generic engine does not contain car constants.

7. **Nothing is deployed.** Kriko is a standalone app: one process, two SQLite
   files, no container and no database server. The desktop shell's sidecar binds
   an OS-chosen port precisely so two copies cannot fight over 8000, which is
   what the retired Docker stack used to do to a `uvicorn` started in WSL.
   `test_the_app_stays_standalone` fails if a Dockerfile, a compose file, or a
   Postgres driver reappears.
