> TL;DR (archived 2026-09-25): Design (2026-09-09, B82, design-only) for the research agenda:
what-to-research-next as a derived read-time ordering (not scheduler/job/table) over four
kept-separate signals (demand from `app.sqlite` lookups, gap, thin, stale) with four row
kinds (`unknown_subject` never researched), delivered via MCP tool + `/api/agenda` + generated
skill. Recommended approach C (computed on read in `app/agenda.py`); 8-test gate incl. demand
beats alphabet and total deterministic order.

# The research agenda — what to research next, arriving unasked

*2026-09-09. Backlog **B82**. Design only; no code in this document ships.*

## The problem, stated narrowly

An agent is told much and asked nothing: `app/agentskill.py` already assembles per-pack principle, identity keys, domain/severity words, holdings, and a worked `submit_findings` — the *what* and *how*. Nobody answers **which subject first**. The two candidate surfaces fail: **`coverage_gaps` orders alphabetically** (`ORDER BY s.label` in `app/mcp_server.py` — first-ten-rows researches ten subjects starting with A, blind to the reader analysing one twice this week); **demand lives in the other database** (`app.sqlite` `lookups` with `coverage`: `RISKS_FOUND`/`MATCHED_NO_DATA`/`NOT_MATCHED` — the only want-record, unread by any research surface). Sharper: **`NOT_MATCHED` is invisible to `coverage_gaps`** (lists subjects with no claims; can only name existing subjects — a product we couldn't even name is the strongest signal, appearing nowhere). New signal, unconsumed by design: shipped claims whose page lost their quote (`fact_checks.verdict='missing'`) are re-research targets (`missing` must rank nothing in the *reader's* report; research ranking is separate).

## What this is not

Not scheduler/job/drainable queue — a **derived ordering** over existing rows serving one sentence: *research this subject next, for this reason.* No new human step (automation principle); nothing hand-enumerated (scalability/generalisation); `NOT_MATCHED` ⇒ "catalog missing this subject", never hand-YAML (onboarding stays pipeline-generated).

## Approaches considered

**A. Demand-ordered `coverage_gaps`** (one `ORDER BY` + cross-DB join): cheapest, fixes the alphabet — but can't carry `NOT_MATCHED` (no subject), staleness, or spare the agent combining three tools (the thing it doesn't do). **B. Agenda table written by a job** (pipeline-shaped, cheap reads): buys cache invalidation the size of the feature (lags ⇒ recommends researched-an-hour-ago subjects; write-time recompute = read cost + bookkeeping). **C. Computed on read, in `app/`, three doors ← recommended**: one module+function, no table/clock; four indexed `LIMIT`ed queries over small-by-nature tables (own history + one install's subjects); freshness free (nothing to invalidate). B becomes right only on measured slowness — then a content-digest cache (like `schema_stamp`), never TTL.

## Design

### Where it lives

`src/app/agenda.py` — must read **both** DBs (engine store + `app.sqlite`), and `app/` is the only layer allowed both (`kriko/` must never see browsing history or touch `content_digest`; MCP server already there with `_app_state_path`). Category-free (`subject/pack/claim/coverage` — pack-declared words, as `agentskill.py` does).

### The four signals, kept separate

`demand` (ask frequency+recency ← lookups), `gap` (subject ⟂ claims), `thin` (weakly supported ← `weakest_claims`), `stale` (quote missing from page ← `fact_checks`) — kept separate, as `subject_health` refuses a single score (one number hides weak-vs-old). Rows carry all four + rank (deterministic total order: demand desc, signal class, `subject_id` — replays must not reorder, or the gate is untestable).

### Four row kinds, and one of them is not research

`unknown_subject` (NOT_MATCHED, no `subject_id` — **catalog** gap; `submit_findings` can't accept it; an agent would invent/wrong-file — reported as pipeline input, never a task) | `empty_subject` (exists, no claims → `research_brief` → `submit_findings`) | `thin_subject` (corroborate with independent sources) | `stale_claim` (re-read; file what the page says now).

### Three doors, one computation

(1) `research_agenda(pack_id="", limit=20)` MCP tool — agent's first call (replaces coverage_gaps-and-hope); heads `STEPS` in `agentskill.py` (list stated once, both surfaces render it); (2) `GET /api/agenda` — Agents-screen Wiring lens shows what the agent will pick (copyable as a prompt for unwired harnesses); (3) generated skill embeds top rows **plus the tool pointer** (honest staleness fix: on-disk snapshot + live pointer, labelled which is which).

### Failure and emptiness

No packs ⇒ no agenda (as `agentskill.render` returns `None`); no lookups ⇒ demand *absent* not zero (gaps + thinness — correct for fresh installs, and what `coverage_gaps` alone would say); unreadable `app.sqlite` ⇒ demand-less agenda + `note` (worse ordering beats an error).

### What the harness sees of the reader

Rows name product identity (pack keys + label) — never URLs, adverts, notes, accounts; demand = identity *counts*, screenshot-unremarkable by construction.

## Testing — and the gate this row is not finished without

Fixture stores built in-test (as `test_factcheck.py` — direct row inserts, no pack install): (1) **the B82 gate** — twice-analysed-this-week empty subject outranks alphabetically-earlier unasked gap (fails today); (2) `NOT_MATCHED` ⇒ `unknown_subject`, no `subject_id`, never a research row; (3) `missing` check ⇒ `stale_claim`, engine store untouched; (4) byte-identical order across runs; (5) no packs ⇒ none; no lookups ⇒ gaps+thinness; (6) absent `app.sqlite` ⇒ noted agenda, not 500; (7) no URLs/reader free text in rows; (8) `STEPS`⇔skill agreement (existing skill tests, extended).

## Open questions

**Demand decay** — fixed window (explainable) vs half-life (better, indefensible constant); leaning window (reader-tellable). **Grounding refusals as fifth signal** — deferred (source-reliability view, not subject ordering). **UI row→job button** — second jobs-plane door; deferred until asked.
