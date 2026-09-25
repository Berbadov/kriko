> TL;DR (archived 2026-09-25): Design (2026-09-09) treating knowledge-building as a system:
reader's "how do I build knowledge with my agents" needs five missing pieces around existing
machinery — `app/` provider adapters (OpenAI-wire LLM + Exa search/fetch), `~/.kriko/env`
keys via Settings (masked, env wins), multi-subject `agenda_run` job, run provenance + undo
in `app.sqlite`, and a `skill.md` product-identity asset per pack. Plus Agents-screen rework,
failure-mode table, 6 phases (adapters+keys first, `agenda_run` nearly last — undo first).

# Building knowledge — the system, not the button

*2026-09-09. Two doors for growing packs — an agent harness and a pair of API keys. First design treating knowledge-building as a system, not one job handler. Supersedes nothing.*

## The problem, stated as the reader stated it

> "I'm looking at the app itself and still couldn't figure out how I'm gonna build some knowledge with my agents."

Missing *system*, not feature: parts exist, don't meet; the screen explaining it covers one third. Success = a fresh install answers from the app alone: what researches, what it costs, what changed. Plus: same machinery from **OpenAI + Exa keys** (no agent subscription), and **products are not names** (make/model/years/engine/gearbox/fuel/market — "Golf 7" is a guess) written as a skill, not a prompt string.

## What already exists (and is therefore not in scope to invent)

| Piece | Where | State |
|---|---|---|
| Plane abstraction | `kriko/research/base.py` (`Researcher`: brief/gather/extract; `ResearchTask`, `Document`, `Finding`) | **Done** (2 impls) |
| $0 plane | `kriko/research/agent.py` (`AgentResearcher`, `cost_basis="subscription"`, gather returns nothing) | **Done** |
| Paid plane | `kriko/research/api.py` (`ApiResearcher`, `cost_basis="per_token"`, injected search/fetch/complete, `BudgetExceeded` hard stop, `extract` grounding) | **Written, never wired** — no caller supplies the callables; `get_researcher({"backend":"api"})` raises `TypeError` today |
| Acceptance | `app/findings.py` (`accept_findings`, `AGENT_CONFIDENCE=0.6`, verbatim grounding, pack gates) | **Done** (MCP + web job share it) |
| Ordering | `app/agenda.py` (B82 rows: `empty_subject`, `thin_claim`, `stale_fact_check`, `unknown_subject`) | **Done** |
| Job runner | `app/web/jobs.py` (single worker, cooperative cancel, `interrupted` recovery) | **Done** |
| Research job | `app/web/tasks.py::_research` (4 stages, 1 subject/job, `backend` from params) | **Done, single-subject** |

Missing exactly five (none is the researcher): provider adapters; a reader key-supply path (desktop app has no shell for env); multi-subject runs; provenance/reversibility (no plane/model/provider recorded ⇒ bad runs un-undoable); the product-identity skill.

## 1. Provider adapters live in `app/`, not `kriko/`

`app/providers/{exa,llm,fetch}.py` — one plain function each, shaped exactly as `ApiResearcher.__init__` expects. `app/` because adapters are key + HTTP socket, which the engine never owns (same rule as `packsource.py` fetching what `updates.py` decides). LLM speaks **OpenAI wire + configurable `base_url`** (as `verdict.py` already does for DeepSeek) — one adapter serves OpenAI/DeepSeek/OpenRouter; reader picks by URL. Search = Exa first (already in `acquire.py`, `EXA_API_KEY` already named); Tavily later (promised in `api.py`'s docstring). **Cost charged once, hard stop:** `ApiResearcher._charge` raises past `task.budget_usd`; adapters add no accounting; nothing catches `BudgetExceeded` to continue.

## 2. Keys: the environment is the truth, Settings is the door

`~/.kriko/env` (`KEY=value`, mode `600`), loaded by `app/sidecar.py` **before** anything reads a key — one mechanism for desktop, `python -m app`, and pipeline scripts. **Settings → Research** writes it, never reads back: `GET /api/keys` ⇒ `{openai: {present, hint: "…4f2a"}}` (masked row + Replace/Remove — a fixed-port HTTP-readable key is extension-origin-readable). Real-environment keys **win** over the file (`source: "environment"` — never silently override a dev shell). Not the OS keychain (better, but `keyring` + headless-Linux fallback; on a single-user desktop mode-600 beside a readable `knowledge.sqlite` is the honest threat model — revisit if multi-user). **Trust sentence changes:** Check's *"no account, nothing sent anywhere"* stays true on the agent plane, false the moment an API run starts ⇒ API plane off until a key exists; Settings states plainly what goes where (query + fetched page text; never history/listing URLs). One-time reader policy decision (the only human kind `CLAUDE.md` allows).

## 3. Two doors, one job

### `research` — one subject

Unchanged in shape: gains `backend: "agent"|"api"` (already in params); on `api`, handler builds `ApiResearcher` from §1 adapters + params budget.

### `agenda_run` — the knowledge tree

New job kind (*"I just wanna build a knowledge tree"*): walks `agenda.py` rows (`rows=10, budget_usd=0.40, backend="api"` default shape): skip `unknown_subject` **loudly** (below), research inline reusing `_research` stages, accept via `findings.py`, stop early on budget/cancel with a done-report. **Inline, not sub-jobs** — single worker deadlocks on submit-and-wait (obvious in design, invisible in diff; hence written here + gated by test). `unknown_subject` rows **never auto-researched** (no `subject_id` ⇒ `submit_findings` can't aim; guessing is the worst this system could do) — surface as *"N rows need a subject first"* + author-flow link.

### The extension door

hover_lite's zero-claim gaps + existing `POST /api/research` ⇒ *"Kriko doesn't know this one — research it?"* with in-place progress; only when a subject exists with no claims (never `NOT_MATCHED`); on `api` it names the cost first (a panel that silently bills for looking dies uninstalls).

## 4. Provenance and undo

Run→claims mapping in **`app.sqlite`** (`research_runs`: job, plane, model, provider, started, budget, spent; `research_run_claims`: run → pack+claim) — **not** the engine schema (run provenance in `knowledge.sqlite` would perturb `content_digest` ⇒ same-fact installs disagree ⇒ update refusal breaks). Claim evidence chains stay in the engine store. **Undo** (`DELETE /api/research-runs/{id}`, as a job) removes exactly that run's additions, tolerating absent claims ("removed 4 of 6; 2 already absent" — uninstall/reinstall legitimately breaks mappings). Activity gains Runs→provider column + *Undo this run* (superseded runs say so instead of offering a no-op).

## 5. The product-identity skill

Ships as **pack data** — `packs/<name>/research/skill.md` beside `principle.md` (identification is category property, like the principle; read via existing `pack_asset()`; new named asset, no new mechanism). Covers: (1) **resolve identity first** from runtime `/api/identity-keys/{pack_id}` + vocabulary (cars: make/model/years/engine/gearbox/fuel/market — never hardcoded lists); (2) **search the discriminating attribute** (engine code finds failure patterns; model names find brochures — per-pack: drill = battery platform, not model line); (3) **product vs family** (sibling engine sharing a chain design = relevant; same nameplate, different gearbox = not; carried on `Finding.stance`/`component`); (4) **refuse over guess** (under-determined ⇒ narrowed question for the reader — `unknown_subject` discipline, one layer down); (5) **surfacing bar stays `principle.md`'s**, quoted not restated (no drift). Generated agent skill composes this asset with the agenda (ordering + method, one doc); tools beat snapshots on disagreement (existing wording, kept).

## 6. What the Agents screen becomes

Answers the three questions: **two planes side by side** with existing `cost_basis` strings (`subscription`/`per_token`; API card inert + *Set up keys* until keyed — choice visible pre-decision); **what it will do** (agenda, already here via B82); **cost + changes** (last runs: provider, spend, additions → Activity links).

## Failure modes this design is built against

$40 run (unattended, no ceiling → required `budget_usd` + uncatchable `BudgetExceeded`) | invented quotes (dropped twice: `api.py::extract` + `findings.py::is_grounded`) | wrong-car research (`unknown_subject` never auto-run; skill rule 4) | unremovable bad run (`research_run_claims` + job undo) | agenda deadlock (inline stages; test-gated) | key leak to extension origin (no endpoint returns keys — presence + 4-char hint only) | digest disagreement (provenance in `app.sqlite`) | trust promise silently false (`agent` default; API needs explicit backend *and* key).

## Testing

No test requires a key (injected-callable seam; adapters vs fake transport, researcher vs fake callables) | budget stop tested by overshoot + no-catch assertion | `agenda_run`: skips `unknown_subject` w/ notice, stops on cancel/budget, never `jobs.submit` | undo vs partly-gone claims | keys endpoint never emits the key (incl. error paths — body must not contain the fixture string) | `skill.md` exists for every pack declaring research templates.

## Phases

1. **Adapters + keys** (providers, `~/.kriko/env`, Settings → Research, `/api/keys`) — ends at paste-two-keys-see-masked. 2. **API plane runs** (one subject, budgeted, end-to-end). 3. **Provenance + undo** (tables, Activity column, DELETE). 4. **`agenda_run`** (depends on 3 — unattended multi-row runs without undo are a liability). 5. **Skill** (cars `skill.md` → generated agent skill). 6. **Extension prompt** (wire `POST /api/research` into gap rendering). Phases 1–2 answer the question; phase 4 is the ask, deliberately late (safety before scale).
