# The research agenda — what to research next, arriving unasked

*2026-09-09. Backlog **B82**. Design only; no code in this document ships.*

## The problem, stated narrowly

An agent wired to this installation is told a great deal and asked nothing.
`app/agentskill.py` already assembles, per installed pack: the pack's own value
principle, its identity keys, its declared domain and severity words, how much
it holds, and a worked `submit_findings` call using a real subject. That is the
*what* and the *how*. What no surface answers is **which subject to open
first** — and the two places a reader would look for it answer it badly:

- **`coverage_gaps` orders alphabetically.** `ORDER BY s.label LIMIT ?`
  (`app/mcp_server.py`). An agent that takes the first ten rows researches ten
  subjects beginning with A. Nothing in the ordering knows that the reader
  analysed one of those cars twice this week and has never looked at the other
  nine.
- **The demand signal is in the other database.** Every analysis the reader ran
  is a row in `app.sqlite`'s `lookups`, with its `coverage` in the stored
  response: `RISKS_FOUND`, `MATCHED_NO_DATA`, `NOT_MATCHED`. That is the only
  record of what anyone actually wanted to know, and no research surface reads
  it.

There is a third thing, sharper than both. **`NOT_MATCHED` is invisible to
`coverage_gaps` by construction.** `coverage_gaps` lists subjects with no
claims — it can only name subjects that *exist*. A listing whose identity
resolved to no subject at all is the strongest possible signal (a reader
brought us a product and we could not even name it) and it appears in no gap
list, no coverage report, and no skill.

And one new signal, from the fact-check work that landed today: a shipped
claim whose cited page no longer contains its quote (`fact_checks.verdict =
'missing'`) is a re-research target. Nothing consumes it yet, which was
deliberate — `missing` must rank nothing in the *reader's* report. Ranking
research is a different question.

## What this is not

Not a scheduler, not a job, and not a queue anyone drains. It is a **derived
ordering**, computed on read from rows that already exist, in service of one
sentence an agent can act on: *research this subject next, for this reason.*

No new human step anywhere (automation principle). Nothing hand-enumerated,
no per-model or per-category ordering rule (scalability and generalisation
principles). A `NOT_MATCHED` identity produces "the catalog is missing this
subject", never a hand-authored YAML — onboarding stays pipeline-generated.

## Approaches considered

**A. Order `coverage_gaps` by demand and stop there.** One `ORDER BY` change
plus a join across two databases. Cheapest, and it fixes the alphabet. But it
cannot carry `NOT_MATCHED` (no subject to order), cannot carry staleness (not a
gap), and leaves the agent to combine three tools by itself — which is the
thing it currently does not know to do.

**B. A separate `agenda` table, written by a job.** Fits the pipeline's
existing shape (`pipeline_runs` etc.) and makes the computation cheap to read
many times. Buys a cache-invalidation problem the size of the feature: every
lookup, submission and fact check invalidates it, so either it lags by a clock
tick — an agenda that recommends a subject researched an hour ago is worse than
no agenda — or it is recomputed on every write, which is the read computation
plus bookkeeping.

**C. Computed on read, in `app/`, delivered through three doors. ← recommended**
One module, one function, no new table, no clock. The inputs are four indexed
queries with `LIMIT`s over tables that are small by nature (a reader's own
history and one installation's subjects). Freshness is free because there is
nothing to invalidate.

Recommendation is C. B's table is the right answer only if measurement says the
read is slow, and then it is a cache with a content digest — the same shape
`schema_stamp` already uses — never a TTL.

## Design

### Where it lives

`src/app/agenda.py`. It must read **both** databases — the engine store for
subjects, claims and evidence, `app.sqlite` for lookups and fact checks — and
`app/` is the only layer permitted to hold both. `kriko/` cannot: the interface's
history is not the engine's business, and a reader's browsing must never reach a
`content_digest`. The MCP server already lives in `app/` and already derives the
app-state path (`_app_state_path`), so no new layering is introduced.

The module knows no category. Its vocabulary is `subject`, `pack`, `claim`,
`coverage` — the pack-declared words, exactly as `agentskill.py` handles them.

### The four signals, kept separate

```
demand      how often the reader asked, and how recently        lookups
gap         the subject exists and holds no claims              subjects ⟂ claims
thin        the claims it holds are weakly supported            weakest_claims
stale       a shipped quote's page no longer contains it        fact_checks
```

Each agenda row carries all four as fields, plus the rank. This is not
decoration: `subject_health` already refuses to emit a single score, on the
grounds that "an agent that gets one number cannot tell a weak claim from an
old one". The same holds here — an agent that is told only *rank* cannot tell
"nobody has ever researched this" from "this was researched and the source
moved", and those call for different searches.

The rank itself is deterministic and total (demand desc, then signal class,
then `subject_id`), because a replay that reorders makes the gate below
untestable.

### Four row kinds, and one of them is not research

| kind | what it means | what the agent does |
|------|---------------|---------------------|
| `unknown_subject` | a lookup came back `NOT_MATCHED` — no subject row exists | nothing directly: this is a **catalog** gap, and the row says so |
| `empty_subject` | the subject exists, holds no claims (`MATCHED_NO_DATA` or a plain gap) | `research_brief` → `submit_findings` |
| `thin_subject` | holds claims, all weakly supported | corroborate: independent sources for existing claims |
| `stale_claim` | a claim whose cited page changed | re-read, and file what the page says now |

`unknown_subject` being a distinct kind is load-bearing. It has no
`subject_id`, so `submit_findings` cannot accept anything against it, and an
agent handed it as a research row would either invent a subject id or file
against the wrong one. It is reported as demand for coverage the catalog does
not have — which is a pipeline input, not an agent task.

### Three doors, one computation

1. **`research_agenda(pack_id="", limit=20)`** — a new MCP tool. The agent's
   first call, replacing "call `coverage_gaps` and hope". `STEPS` in
   `agentskill.py` gains it at the head of the loop, which is also what puts it
   in the UI's explanation of the protocol (the list is stated once and both
   surfaces render it).
2. **`GET /api/agenda`** — the Agents screen's Wiring lens shows the same rows,
   so the reader can see what the agent will pick before it picks, and can copy
   a row as a prompt for a harness that is not wired to MCP at all.
3. **The generated skill** embeds the top handful *and names the tool*. A skill
   file written to a harness's config directory goes stale the moment the store
   changes; a snapshot with a pointer beside it does not mislead, because the
   pointer is live and the text says which is which. This is the honest fix for
   staleness: do not pretend a file on disk is current, tell the agent where
   current lives.

### Failure and emptiness

No packs installed → no agenda, exactly as `agentskill.render` returns `None`
rather than a skill about nothing. No lookups yet → the demand signal is
absent, not zero: the agenda falls back to gaps and thinness, which is the
correct answer for a fresh install and is also what `coverage_gaps` alone would
have said. An unreadable `app.sqlite` → the agenda computes without demand and
says so in a `note`, because an agent with a worse ordering is strictly better
than an agent with an error.

### What the harness sees of the reader

An agenda row names a **product identity** — the pack's own identity keys and
the subject label. It never carries the listing URL, the advert, the reader's
notes, or anything from their account. The demand signal is *counts of
identities*, derived from history and not the history itself. Worth stating
because the MCP server hands these rows to a harness the reader wired
themselves: the bar is that a row would be unremarkable in a screenshot.

## Testing — and the gate this row is not finished without

The 1.0.0 audit's rule applies: each behaviour names the gate that would have
caught its absence. Fixture stores are built in-test, as
`src/app/tests/test_factcheck.py` does — rows inserted directly, no pack
installed, because installing a pack to test an ordering tests the installer.

1. **The gate B82 states.** A subject the reader analysed twice in the last
   week that holds nothing outranks an alphabetically-earlier gap nobody has
   ever asked about. This is the whole point of the row, and it is the test
   that fails today.
2. `NOT_MATCHED` appears as `unknown_subject`, carries no `subject_id`, and
   never appears as a research row.
3. A `missing` fact check appears as `stale_claim` and changes nothing in the
   engine store — the same invariant the fact-check tests hold, re-asserted
   from the consumer side.
4. Order is total and byte-identical across two runs on the same store.
5. No packs → no agenda. No lookups → gaps and thinness, no error.
6. `app.sqlite` absent or unreadable → an agenda with a note, not a 500.
7. A row's fields contain no URL and no free text the reader typed.
8. `STEPS` and the skill body still agree, which the existing skill tests
   already assert — extended to the new first step.

## Open questions

1. **Demand decay.** A fixed window ("the last 30 days") is one line and
   explainable to a reader; a half-life ranks better and is a constant nobody
   can defend. Leaning fixed window, on the grounds that the reader can be told
   what it is.
2. **Grounding refusals as a fifth signal.** `submissions` records what
   `app/findings.py` rejected; a source that keeps failing the quote check is
   information about the *source*, not the subject. Deferred — it belongs in a
   source-reliability view, not in an ordering of subjects.
3. **Whether a row can start work from the UI.** The Agents screen could turn a
   row into a research job. That is a second door onto the jobs plane and it is
   not needed for the gate above; deferred to its own row if the reader asks
   for it.
