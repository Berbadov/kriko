# Kriko, the words

Look a word up here before you use it. One line each, plus the file that owns
it. Definitions drift between sessions, so this is the one place they are held.
Words are grouped by what they are about, then listed in the order a reader
meets them.

## The knowledge

| Word | Definition |
|---|---|
| **pack** | One product category as data: subjects, claims, vocabulary, trust tiers, adapters, and its own bar for what is worth showing. A third party writes it; it is never engine code. The screen calls it a **Catalog**. (`packs/<name>/`, `docs/PACK_CONTRACT.md`) |
| **subject** | One manufactured thing the store answers about. What a lookup resolves *to*. A pack decides what a subject is; the engine does not. (`kriko/store/`) |
| **claim** | One known failure on a subject, with evidence. (`kriko/store/`) |
| **evidence** | A verbatim quote plus its source, behind a claim. The engine refuses a quote that is not in the cited document, and it keeps the document in `app.sqlite` so the check can run again offline. (`app/findings.py`, `app/web/state.py`) |
| **identity** | `key=value` pairs that name a product. The pack declares them; the engine knows no key by name. (`kriko/lookup/match.py`) |
| **adapter** | How to read one site: selectors, label mappings, `local_panel`. **Data, not code**, because shippable JavaScript would run on every page the extension ever sees. (`kriko/adapters.py`) |
| **lineup** | Every product in a category the agent can name, covered or not, asked for *before* any claim is written. Naming is cheap; research is what costs. Kriko subtracts what it wrote and records the remainder as coverage. (`app/packauthor.py`) |
| **bar** | What a pack considers worth showing, in its own `research/principle.md`. The engine enforces ranking, never taste. |
| **quarantine** | A draft subject in neither the lineup nor `coverage.out_of_scope`: set aside with its reason, never shipped and never silently dropped. (`app/packauthor.py`) |
| **store** | `~/.kriko/knowledge.sqlite`. To uninstall a pack drops its rows. (`kriko/store/db.py`) |
| **document** | Quote-proving page text, kept per install in `app.sqlite` and never in the store, because one reader's browsing must not move a `content_digest`. (`app/web/state.py`) |

## The machinery

| Word | Definition |
|---|---|
| **engine** | `src/kriko/`: the store, lookup, ranking, and the research interface. It knows no category and imports nothing above it. That is the invariant the whole layout holds on. |
| **interface** | Anything in `src/app/` that a person or an agent talks to: the CLI, the dashboard, the MCP server, the operator console. |
| **plane** | Who does the reading. See the table below. |
| **job** | Long work as a durable row (research, builds, updates): the id now, and the log, result and failure outlive the process. (`app/web/jobs.py`, `app/web/tasks.py`) |
| **sidecar** | The engine as a child process: an OS-chosen port, `KRIKO_PORT <n>` printed first, monitored by the desktop app. (`app/sidecar.py`) |
| **interface state** | `~/.kriko/app.sqlite`: history, settings, job rows. Never the store, because to uninstall a pack must not drop history. (`app/web/state.py`) |
| **operation** | Agent-driven work through any door (MCP, a job, HTTP). Coarser than a job, and recorded live, `running` while it is in flight. (`app/operations.py`, `docs/AGENT_OPERATIONS.md`) |
| **readout** | The benchmark's per-model row: the protocol that ran, the cost per accepted claim, and the hallucination rate with its interval. (`app/protocols.py`) |
| **grounded / ungrounded / not_kept** | The offline per-evidence verdicts of `GET /api/factcheck/grounding` against the kept text. `not_kept` is its own answer, because "never checked" is not "fine". (`app/findings.py`) |

## The planes

A **plane** turns a question into claims. The choice decides what it costs.

| Plane | Who does the work | Cost |
|---|---|---|
| **local** | A model server on this machine, addressed in Settings | nothing beyond the machine |
| **agent** | You, by hand; Kriko writes the brief | nothing |
| **harness** | Kriko starts a coding agent's CLI with no window | an existing subscription |
| **api** | Kriko searches and reads unattended, on a metered API | per token, and **never chosen by omission** |

A run that does not name a plane takes the first one that is ready, and it
says which one in its log.

## Words that mean more than one thing

- **"agent" is four things**: the **agent** plane (by hand); the **harness**
  (a CLI Kriko *starts*); a **coding agent** that works on Kriko's own
  source; and the research agent file each pack ships. Say "harness plane"
  or "CLI".
- **"shell" is two things**: the **desktop shell** (`kriko-gpui/`, the
  native app that owns the sidecar's lifetime and reads the engine only over
  HTTP) and the terminal's own shell (the PTY handed to the operator's
  terminal).
- **"ledger" is two things**: the **evidence ledger** (`src/kriko/ledger/`,
  build time: documents, chunks, extractions, clusters, verdicts) and the
  job's **ledgering** stage, which records verdicts into `app.sqlite`
  through `log_submission`. Say "evidence ledger" and "submissions log".
- **"risk" is retired as a code word.** The engine stores, sends and renders
  a **claim**; the screen still says *risk*, which is the reader's word.
- **"extension"** is the browser client in `extension/` and nothing else.
  **"reader"** is the person reading a listing, not a developer or an
  operator.
- **"pack" and "catalog"** are the same thing in two registers: the code says
  `pack`, the screen says Catalog. Both are in `docs/GLOSSARY.md` on purpose,
  so the bridge is written down once.

## Naming rules for new things

Before a new word enters the code or the screen:

1. Name it for the user, not for the mechanism (`lineup` over
   `priority_queue`).
2. One word, one meaning.
3. A word the UI shows belongs in this table.
4. A pack's vocabulary is never an engine or client identifier. No category
   word appears in `src/kriko/` or `ui/src/`, and two tests hold that:
   `test_core_is_domain_free.py` walks the engine's AST and
   `test_ui_contains_no_pack_vocabulary` reads the frontend's source.
