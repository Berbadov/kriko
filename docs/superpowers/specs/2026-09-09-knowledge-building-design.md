# Building knowledge — the system, not the button

*2026-09-09. Design for the two doors through which a Kriko installation grows
its own packs: an agent harness, and a pair of API keys. Supersedes nothing;
this is the first design that treats knowledge-building as a system rather than
as one job handler.*

---

## The problem, stated as the reader stated it

> "I'm looking at the app itself and still couldn't figure out how I'm gonna
> build some knowledge with my agents."

That is not a missing feature. It is a missing *system*: the parts exist, none
of them meet, and the screen that should explain the whole thing explains one
third of it. This design's success criterion is that a reader who has just
installed Kriko can answer three questions from the app alone — what will do
the research, what it will cost, and what changed after it ran.

A second requirement arrived with it: the same machinery must run from **an
OpenAI key and an Exa key**, for people who have those rather than a coding-agent
subscription. And a third: **products are not names.** A car is a make, a model,
a year range, an engine code, a gearbox type, a fuel, a market. Searching for
"Golf 7" is not researching a subject; it is guessing. That delicacy needs to be
written down as a skill, not buried in a prompt string.

## What already exists (and is therefore not in scope to invent)

Read this section before proposing any change; four of the six pieces below are
already built and the design is mostly *wiring*.

| Piece | Where | State |
|---|---|---|
| The plane abstraction | `kriko/research/base.py` — `Researcher` with `brief`/`gather`/`extract`, `ResearchTask`, `Document`, `Finding` | **Done.** Two implementations. |
| The $0 plane | `kriko/research/agent.py` — `AgentResearcher`, `cost_basis = "subscription"`, `gather()` returns nothing by design | **Done.** |
| The paid plane | `kriko/research/api.py` — `ApiResearcher`, `cost_basis = "per_token"`, search/fetch/complete injected as callables, hard budget stop (`BudgetExceeded`), grounding enforced in `extract` | **Written, never wired.** No caller ever supplies the three callables. `get_researcher({"backend": "api"})` raises `TypeError` today. |
| The acceptance path | `app/findings.py` — `accept_findings`, `AGENT_CONFIDENCE = 0.6`, verbatim-quote grounding, pack gates | **Done.** Shared by MCP and the web job. |
| The ordering | `app/agenda.py` (B82) — ranked rows: `empty_subject`, `thin_claim`, `stale_fact_check`, `unknown_subject` | **Done.** |
| The job runner | `app/web/jobs.py` — single worker, cooperative cancel, rows in `app.sqlite`, `interrupted` recovery | **Done.** |
| The research job | `app/web/tasks.py::_research` — four named stages, one subject per job, `backend` already read from params | **Done, single-subject only.** |

So the missing pieces are exactly five, and none of them is the researcher
itself:

1. **Provider adapters** — nothing turns an Exa key into `search(query, limit)`
   or an OpenAI key into `complete(prompt)`.
2. **A way for a reader to supply keys** — the pipeline reads
   `EXA_API_KEY`/`DEEPSEEK_API_KEY` from the environment, and a double-clicked
   desktop app has no shell to set them in.
3. **A run that covers more than one subject** — the agenda exists, and nothing
   consumes it as work.
4. **Provenance and reversibility** — a claim does not record which plane,
   model or search provider produced it, so a bad run cannot be undone.
5. **The product-identity skill** — how to turn a subject's attributes into
   queries that are actually about that product, and how to refuse when the
   identity is too vague.

---

## 1. Provider adapters live in `app/`, not `kriko/`

`app/providers/exa.py`, `app/providers/llm.py`, `app/providers/fetch.py`. Each
exposes one plain function shaped exactly as `ApiResearcher.__init__` already
expects, and nothing else.

They belong in `app/` and this is not a style preference. `kriko/` owns no
socket — that is the rule that lets `kriko/pack/updates.py` decide about
updates while `app/packsource.py` fetches them. A provider adapter is an API
key plus an HTTP call, which is the definition of what the engine does not do.
`ApiResearcher` taking callables is the seam that already anticipated this;
the adapters are what finally plug into it.

The LLM adapter speaks the **OpenAI wire format with a configurable
`base_url`**, because `packs/cars/pipeline/ledger/verdict.py` already does
exactly that to reach DeepSeek. One adapter therefore serves OpenAI, DeepSeek,
OpenRouter and anything else compatible, and the reader picks with a base URL
rather than by us shipping an adapter per vendor. Search is Exa first because
`packs/cars/pipeline/ledger/acquire.py` already uses it and its `EXA_API_KEY`
is already a name in this codebase; Tavily is a second adapter later, and the
docstring in `api.py` already promises it.

**Cost is charged in one place and it is a hard stop.** `ApiResearcher._charge`
already raises before spending past `task.budget_usd`. The adapters must not
add their own accounting, and no code path may catch `BudgetExceeded` and
continue.

## 2. Keys: the environment is the truth, Settings is the door

The reader asked for environment keys *and* an easy place to set them. Both, in
that order:

- `~/.kriko/env` is a `KEY=value` file, mode `600`, and `app/sidecar.py` loads
  it into `os.environ` **before** the app imports anything that reads a key.
  The environment stays the single mechanism, so the same key serves the
  desktop app, `python -m app`, and the pipeline scripts with no second
  configuration concept.
- **Settings → Research** writes that file. It never reads a key back:
  `GET /api/keys` answers `{"openai": {"present": true, "hint": "…4f2a"}}`, and
  the UI renders a masked row with *Replace* and *Remove*. A key that can be
  read out of an HTTP endpoint on a fixed port is a key the browser extension's
  origin could read too.
- A key already in the real environment **wins** over the file and is reported
  as `source: "environment"`, so a developer's shell is never silently
  overridden by something a UI wrote months ago.

Not the OS keychain, in this version. It would be better, and it costs a
`keyring` dependency plus a fallback for Linux boxes with no secret service —
and on a single-user desktop where `~/.kriko/knowledge.sqlite` is already
readable, mode-600 in the same directory is the honest description of the
threat model rather than a worse one dressed up. Written down here so the
next person knows it was a decision. Revisit if Kriko ever runs multi-user.

**The trust sentence must change.** The Check screen says today: *"with no
account and nothing sent anywhere."* That stays true on the agent plane and
becomes false the moment an API run starts, so the API plane is off until a key
exists, and the Settings section states plainly which provider receives what
(a search query, and the text of pages it fetched — never the reader's history,
never a listing URL they looked at). This is a one-time policy decision by the
reader, which is the only kind of human decision `CLAUDE.md` allows.

## 3. Two doors, one job

### `research` — one subject

Unchanged in shape. Gains `backend: "agent" | "api"` (already read from
params), and on `api` the handler constructs `ApiResearcher` with the adapters
from §1 and the budget from params.

### `agenda_run` — the knowledge tree

A new job kind in `app/web/tasks.py`, and the one the reader meant by *"I just
wanna build a knowledge tree."* It reads `app/agenda.py`'s ordering and works
down it:

```
agenda_run(rows=10, budget_usd=0.40, backend="api")
  for row in agenda.rows[:rows]:
      if row.kind == "unknown_subject":  skip, loudly — see below
      research the row's subject, inline, reusing _research's stages
      accept findings through app/findings.py
      stop early on BudgetExceeded or cancel; report what was done
```

**It calls `_research`'s internals directly rather than submitting sub-jobs.**
`jobs.py` has a single worker: a job that submits jobs and waits for them
deadlocks. This is the kind of thing that is obvious in a design document and
invisible in a diff, which is why it is written here.

`unknown_subject` rows are **skipped and reported, never researched.** B82 ships
them with no `subject_id` precisely so `submit_findings` cannot be aimed at a
neighbouring product, and an automated run guessing which subject a reader's
unrecognised car "probably" is would be the single worst thing this system
could do. They surface as *"3 rows need a subject before anyone can research
them"* with a link to the author flow.

### The extension door

hover_lite already renders zero-claim gaps and `background.js` already posts to
`POST /api/research`. So *"Kriko doesn't know this one — research it?"* is
mostly wiring: the panel asks, the engine returns a job id, the panel shows
progress in place and re-renders when the run lands. Two rules: the prompt
appears only when a subject exists and has no claims (never on
`NOT_MATCHED` — same reason as above), and on the `api` plane it names the cost
before it spends, because a panel that quietly bills someone for looking at a
car is a panel nobody keeps installed.

## 4. Provenance and undo

Every claim a run accepts is recorded against that run, so a run that produced
garbage can be removed wholesale.

**The mapping lives in `app.sqlite`, not in the engine's schema.** A
`research_runs` table (job id, plane, model, search provider, started, budget,
spent) and a `research_run_claims` table (run id → pack id, claim id). This
follows the two-SQLite-files rule literally: which *run* produced a claim is
interface history, and putting it in `knowledge.sqlite` would change a pack's
`content_digest` — meaning two installations that researched the same fact from
the same source would compute different digests, and pack update refusal is
built on digests matching.

- The claim's own evidence chain (source URL, quote, domain, confidence) stays
  in the engine store where it already is. Nothing about provenance-of-run
  changes what a claim *says*.
- **Undo** (`DELETE /api/research-runs/{id}`) removes exactly the claims that
  run added, as a job, and tolerates claims that are already gone — a pack
  uninstall or a fresh install legitimately breaks the mapping, and undo must
  degrade to "removed 4 of 6; 2 were already absent" rather than fail.
- The Activity screen grows a **Runs → provider** column and an *Undo this run*
  action. A run whose claims have all been superseded says so instead of
  offering an undo that would do nothing.

## 5. The product-identity skill

This is the part the reader flagged as delicate, and they are right: *"products
aren't just names, they have many attributes."*

It ships as **pack data** — `packs/<name>/research/skill.md` — beside the
`principle.md` that already lives there. The engine enforces ranking, never
taste; how to *identify* a product before searching for it is a property of the
category, exactly like the product principle is. `kriko/research/__init__.py`
already exposes `pack_asset(conn, pack_id, name)` for reading a pack's own
words, and `plan_task` already assembles query templates from pack data. So
this is a new named asset, not a new mechanism.

What the skill must cover, and what a harness reads it for:

1. **Resolve the identity before searching.** The attributes that matter come
   from `/api/identity-keys/{pack_id}` and the pack's vocabulary, at runtime —
   never a hardcoded list, per the scalability principle. For cars that is make,
   model, generation/year range, engine code, gearbox technology, fuel, market.
2. **Search the discriminating attribute, not the label.** An engine code finds
   the failure pattern; a model name finds a sales brochure. The skill states
   this as a rule with worked examples, and states which attribute is
   discriminating *per pack*, because for a cordless drill it is the battery
   platform and not the model line at all.
3. **Know the difference between a claim about this product and a claim about
   its family.** A sibling engine code sharing a timing chain design is
   relevant; the same nameplate with a different gearbox is not. `stance` and
   `component` on a `Finding` already exist to carry this.
4. **Refuse rather than guess.** If the identity is under-determined — no engine
   code, a year that spans two generations — the correct output is a narrowed
   question for the reader, not a claim. This is the same discipline
   `unknown_subject` encodes at the agenda level, one layer down.
5. **The bar for surfacing** stays `principle.md`'s, unchanged and quoted rather
   than restated, so the two documents cannot drift into two different bars.

A generated `skill.md` for agent harnesses (the one the Agents screen already
hands out) composes this pack asset with the agenda, so an agent gets the
ordering *and* the method in one document. When the generated snapshot and the
live tools disagree, the tools are right — the existing wording already says
this and it keeps saying it.

## 6. What the Agents screen becomes

Today it explains one plane. It should answer the reader's three questions:

- **Two planes, side by side, with their cost bases** — `subscription` and
  `per_token`, using the `cost_basis` strings that already exist rather than
  new copy. The API plane's card is inert with a *Set up keys* link until a key
  is present, so the reader sees the choice exists before they have made it.
- **What it will do** — the agenda, which is already on this screen (B82).
- **What it cost and what changed** — the last runs, their provider, their
  spend, and what they added, linking into Activity.

---

## Failure modes this design is built against

| Failure | Why it happens | What stops it |
|---|---|---|
| A run bills someone $40 | An unattended loop with no ceiling | `ApiResearcher._charge` raises before spending; `budget_usd` is required on the API plane, not defaulted |
| A model invents a quote | LLMs asked for verbatim text sometimes produce plausible text | Already enforced twice: `api.py::extract` drops a quote absent from the document, and `findings.py` re-checks with `is_grounded` |
| A run researches the wrong car | A subject guessed from a vague identity | `unknown_subject` rows are never auto-researched; the skill's rule 4 refuses under-determined identities |
| A bad run cannot be removed | No record of what a run added | `research_run_claims` + undo as a job |
| The agenda run deadlocks | Submitting sub-jobs to a single-worker queue | It calls the research stages inline; stated in §3 and gated by a test |
| A key leaks to the extension's origin | The engine serves a fixed port a web page can reach | No endpoint ever returns a key; only `present` and a 4-char hint |
| Two installations disagree on a digest | Run provenance written into the engine store | Provenance lives in `app.sqlite` |
| The trust promise silently becomes false | An API plane that turns itself on because a key exists | `get_researcher` already defaults to `agent` on purpose; the API plane needs an explicit backend *and* a key |

## Testing

The repository's rule is that every fix ships the gate that was missing, and
this is new work rather than a fix, so the gates come with it:

- **No test may require an API key.** `api.py`'s docstring already commits to
  this and the injected-callable seam is what makes it possible: the adapters
  are tested against a fake transport, and `ApiResearcher` against fake
  callables, as it is today.
- The budget stop is tested by overshooting it, and by asserting no caller
  catches `BudgetExceeded`.
- `agenda_run` is tested for: it skips `unknown_subject` and says so; it stops
  on cancel mid-row; it stops on budget; it never calls `jobs.submit`.
- Undo is tested against a run whose claims are partly gone.
- The keys endpoint is tested to never return a key, including in its error
  paths — the test asserts the response body does not contain the fixture key
  string anywhere.
- The `skill.md` asset is tested to exist for every installed pack that
  declares research templates, so a pack cannot ship queries without a method.

## Phases

1. **Adapters + keys.** `app/providers/`, `~/.kriko/env`, Settings → Research,
   `GET /api/keys`. Ends when a reader can paste two keys and see them masked.
2. **The API plane runs.** `research` with `backend: "api"` end to end on one
   subject, budgeted. Ends when a single car can be researched for a known,
   capped cost.
3. **Provenance + undo.** `research_runs`, `research_run_claims`, the Activity
   column, `DELETE /api/research-runs/{id}`.
4. **`agenda_run`.** The knowledge tree. Depends on 3, because an unattended
   multi-row run without an undo is a liability.
5. **The skill.** `packs/cars/research/skill.md`, composed into the generated
   agent skill.
6. **The extension prompt.** Wiring `POST /api/research` into hover_lite's
   existing gap rendering.

Phases 1–2 are the smallest thing that answers the reader's question. Phase 4
is the thing they actually asked for, and it is deliberately last but one,
because the undo it depends on is what makes an unattended run safe to offer.
