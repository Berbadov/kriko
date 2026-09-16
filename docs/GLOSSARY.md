# Kriko — the words

Every term below is already used throughout the code and the docs. Nothing here
is new; what is new is that it is written down in one place, because until now
each one was defined *in situ* — you learned what a plane was by reading the
module that has three of them. Inference drifts, and two sessions inferring
separately end up with two vocabularies.

One line each, the module that owns it, and where the word is ambiguous, what
it is **not**.

---

## The knowledge

| Word | What it is | Owned by |
|---|---|---|
| **pack** | One product category as data: subjects, claims, vocabulary, trust tiers, adapters, and its own bar for what is worth surfacing. The thing a third party authors. Never code that runs inside the engine. | `packs/<name>/`, `docs/PACK_CONTRACT.md` |
| **subject** | One specific manufactured thing the store can answer about — a variant, an engine, a part. What a lookup resolves *to*. | `kriko/store/` |
| **claim** | One thing known to go wrong, attached to a subject, with evidence behind it. | `kriko/store/` |
| **evidence** | The verbatim quote a claim rests on, and the source it came from. A claim whose quote cannot be found in its document is refused, and the document is kept in `app.sqlite` so that check can be made again offline (`regrounded`). | `app/findings.py`, `app/web/state.py` |
| **identity** | The `key=value` pairs that name a product (`make=volkswagen model=golf`). Pack-declared — the engine never knows which keys exist. | `kriko/lookup/match.py` |
| **adapter** | How to read one website: selectors, label mappings, and the `local_panel` block the extension draws from the reader's own page. **Pack data, not code** — a pack that could ship JavaScript would be granted the right to run it on every page the extension sees. | `kriko/adapters.py` |
| **agenda** | What to research next, computed on read from four signals. A list of rows, not a queue. | `app/agenda.py` |
| **store** | `~/.kriko/knowledge.sqlite` — the engine's database. Uninstalling a pack drops its rows. | `kriko/store/db.py` |
| **document** | The page text a quote was proved against, kept per install in `app.sqlite` — never in the store, or a page one reader happened to read would change a pack's `content_digest`. | `app/web/state.py` |

## The machinery

| Word | What it is | Owned by |
|---|---|---|
| **engine** | `src/kriko/`. Pack store, lookup, ranking, research interface. Knows no category and imports none of the other packages — the load-bearing invariant of G6. | `src/kriko/` |
| **interface** | Anything in `src/app/` that a person or an agent talks to: the CLI, the web dashboard, the MCP server, the operator TUI. | `src/app/` |
| **job** | Long work as a durable row rather than a request: research, pack builds, updates. A `POST` returns an id immediately; the log, result and failure outlive the process. | `app/web/jobs.py`, `app/web/tasks.py` |
| **sidecar** | The engine as a child process. Binds an OS-chosen port, prints `KRIKO_PORT <n>`, and is supervised by the desktop shell. | `app/sidecar.py` |
| **interface state** | `~/.kriko/app.sqlite` — history, settings, job rows. Deliberately *not* in the store: uninstalling a pack must not drop your history. | `app/web/state.py` |
| **operation** | One unit of agent-driven work, whichever door it came in by (MCP, a job, HTTP). Coarser than a job: it also covers an MCP `submit_findings` call that never went through the job runner at all. Recorded live, before the work is done, so it reads `running` while it is in flight. | `app/operations.py`, `docs/AGENT_OPERATIONS.md` |
| **quarantine** | A subject an agent proposed in a pack draft that its own `lineup` never named and its `coverage.out_of_scope` never excluded either — set aside with a reason, never shipped and never silently dropped. | `app/packauthor.py` |
| **readout** | The benchmark's one row per model: the protocol (batch size, context, preamble) it would run with right now, its measured cost per accepted claim, and its hallucination rate with interval. What the sweep is *for*. | `app/protocols.py::readout` |
| **grounded / ungrounded / not_kept** | The three per-evidence verdicts `GET /api/factcheck/grounding` can return, offline, against the page text kept at acceptance time. `not_kept` is its own verdict rather than folded into a pass, because "never checked" and "checked and fine" must never read the same. | `app/findings.py::regrounded` |

## The three planes

A **plane** is a way of turning a question into claims. Which one runs decides
what it costs, and that is the whole reason they are named separately.

| Plane | Who does the work | What it costs |
|---|---|---|
| **agent** | You do, by hand. Kriko writes the brief; your own harness reads it. | nothing |
| **harness** | Kriko starts your coding-agent CLI headlessly and reads its answer. | nothing beyond the subscription you already pay for |
| **api** | Kriko searches and reads by itself, unattended. | per token — and it is **never chosen by omission** |

## Words that mean more than one thing

Four, all of which already cause confusion in this repository's own prose.

**"agent" means three things.** Disambiguate every time:

- the **`agent` plane** — the by-hand one in the table above;
- the **harness** — a coding-agent CLI (`claude`, `opencode`) that Kriko
  *starts*, which is the `harness` plane, not the `agent` plane;
- a **coding agent** working on Kriko's own source, which is neither.

Prefer "the harness plane" or "the CLI" over "the agent" wherever a plane is
meant.

**"shell" means two things.**

- the **desktop shell** — `tauri/`, ~180 lines of Rust that owns the sidecar's
  lifetime and holds no engine logic;
- the **shell** in the terminal panel — a PTY running `cmd.exe` or `$SHELL`.

`installer.nsh` has to stop both, which is why its comment "the shell first,
then the engine" is about the desktop one and reads oddly otherwise. Prefer
"the desktop shell" and "the terminal's shell".

**"ledger" means two things, and one of them is a job-log label.** The
*evidence ledger* is `src/kriko/ledger/` — documents, chunks, extractions,
clusters, verdicts — and it is build-time machinery. The research job's
**"ledgering"** stage is not it: that writes verdicts to `app.sqlite` through
`log_submission`, a different database doing interface bookkeeping. Prefer "the
evidence ledger" and "the submissions log" (B120 found this one).

**"extension" is singular but lives in two directories.** `extension/` is the
browser client that ships; `extension_ui/` holds its manifest. Both are the one
extension.

**"reader"** is this project's word for the person using Kriko — a buyer
looking at a listing. Not a developer, not an operator. When a doc says "the
reader has no terminal", that is why.

---

## Naming rules for new things

1. **Name it for what it is to the person using it**, not for its mechanism.
   `agenda` rather than `priority_queue`; `plane` rather than `backend`.
2. **One word, one meaning.** If a word already means something here, pick
   another — the entries above cost more than a longer name would have.
3. **A word that appears in the UI belongs here**, because that is the word the
   reader will use when they report something.
4. **Pack vocabulary is never an identifier in the engine or the client.** No
   `make`, no `fuel`, anywhere in `src/kriko/` or `ui/src/` — enforced by
   `test_core_is_domain_free.py` and `test_ui_contains_no_pack_vocabulary`.
   This is a naming rule with a test behind it.
