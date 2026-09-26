# Kriko — the words

Terms already used across code and docs, collected because *in situ*
definitions drift between sessions. One line each + owner.

## The knowledge

| Word | Definition |
|---|---|
| **pack** | One product category as data (subjects, claims, vocabulary, trust, adapters, surfacing bar). Third-party-authored, never engine code. (`packs/<name>/`, `docs/PACK_CONTRACT.md`) |
| **subject** | One manufactured thing the store answers about (variant, engine, part); what lookups resolve *to*. (`kriko/store/`) |
| **claim** | One known failure on a subject, with evidence. (`kriko/store/`) |
| **evidence** | Verbatim quote + source behind a claim; unfound quotes refused, documents kept in `app.sqlite` for offline re-check. (`app/findings.py`, `app/web/state.py`) |
| **identity** | `key=value` pairs naming a product. Pack-declared; engine knows no keys. (`kriko/lookup/match.py`) |
| **adapter** | Reading one site: selectors, label mappings, `local_panel`. **Data, not code** — shippable JS would run on every page the extension sees. (`kriko/adapters.py`) |
| **agenda** | What to research next, computed on read from four signals. A list, not a queue. (`app/agenda.py`) |
| **store** | `~/.kriko/knowledge.sqlite`; uninstalling a pack drops its rows. (`kriko/store/db.py`) |
| **document** | Quote-proving page text, per-install in `app.sqlite` — never the store (one reader's browsing must not move `content_digest`). (`app/web/state.py`) |

## The machinery

| Word | Definition |
|---|---|
| **engine** | `src/kriko/`: store, lookup, ranking, research interface. Category-free, imports nothing (load-bearing G6 invariant). |
| **interface** | Anything in `src/app/` a person/agent talks to: CLI, dashboard, MCP server, TUI. |
| **job** | Long work as a durable row (research, builds, updates): id now, log/result/failure outlive the process. (`app/web/jobs.py`, `app/web/tasks.py`) |
| **sidecar** | Engine as child process: OS-chosen port, prints `KRIKO_PORT <n>`, shell-supervised. (`app/sidecar.py`) |
| **interface state** | `~/.kriko/app.sqlite`: history, settings, job rows — never the store (pack uninstall must not drop history). (`app/web/state.py`) |
| **operation** | Agent-driven work via any door (MCP/job/HTTP); coarser than a job; recorded live, `running` in flight. (`app/operations.py`, `docs/AGENT_OPERATIONS.md`) |
| **quarantine** | Draft subject neither in `lineup` nor `coverage.out_of_scope`: set aside with reason, never shipped/dropped. (`app/packauthor.py`) |
| **readout** | Benchmark's per-model row: runnable protocol, cost/accepted claim, hallucination rate + interval. (`app/protocols.py::readout`) |
| **grounded / ungrounded / not_kept** | Offline per-evidence verdicts of `GET /api/factcheck/grounding` vs kept text; `not_kept` distinct ("never checked" ≠ "fine"). (`app/findings.py::regrounded`) |

## The three planes

A **plane** turns a question into claims; the choice decides cost.

| Plane | Who does the work | Cost |
|---|---|---|
| **agent** | You, by hand; Kriko writes the brief | nothing |
| **harness** | Kriko starts your coding-agent CLI headlessly | existing subscription only |
| **api** | Kriko searches/reads unattended | per token — **never chosen by omission** |

## Words that mean more than one thing

- **"agent" = three things**: the `agent` plane (by-hand); the **harness** (a
  CLI Kriko *starts*); a **coding agent** on Kriko's source (neither). Prefer
  "harness plane"/"CLI".
- **"shell" = two things**: **desktop shell** (`tauri/`, ~180 Rust lines,
  owns sidecar lifetime, no engine logic) vs **terminal's shell** (PTY on
  `cmd.exe`/`$SHELL` passed to the operator's terminal).
- **"ledger" = two things**: **evidence ledger** (`src/kriko/ledger/`,
  build-time: documents, chunks, extractions, clusters, verdicts) vs job
  **"ledgering"** stage (verdicts to `app.sqlite` via `log_submission`).
  Prefer "evidence ledger" / "submissions log".
- **"risk" retired as a code word**: engine stores/sends/renders **claim**;
  screen copy still says *risk* ("8 known risks" for a buyer).
- **"extension"** = `extension/` browser client only. **"reader"** = the buyer
  reading a listing (not dev/operator).

## Naming rules for new things

1. Name for the user, not the mechanism (`agenda` > `priority_queue`).
2. One word, one meaning. 3. UI words belong here. 4. Pack vocabulary is never
   an engine/client identifier (no `make`/`fuel` in `src/kriko/` or `ui/src/`
   — `test_core_is_domain_free.py`, `test_ui_contains_no_pack_vocabulary`).
