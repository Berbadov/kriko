# Knowledge-tree observability — design

**Date:** 2026-08-31
**Branch:** to be created from `feat/knowledge-engine-pivot`
**Baseline:** the decontamination pass, 606 tests green
**Goal alignment:** G3 (no silent coverage holes), and a precondition for G1 (quality over quantity)

## Problem

Kriko's data path is **open**. Research produces claims, the gate admits or refuses
them, the store keeps them, the lookup serves them — and nothing flows back. There
is no way to ask *which of the things we ship are weakly supported*, so:

- A researcher cannot see what to work on next, only what is missing entirely
  (`coverage_gaps` answers absence, not weakness).
- An agent cannot notice its own mistake, because it never reads back what it
  wrote in a form that shows the shape of the evidence.
- Nothing can prioritise expensive re-verification, because nothing ranks
  confidence.
- A correctness signal from users would arrive with nowhere to land and no
  baseline to compare against.

The data to answer all of this is already stored and none of it is readable as a
graph:

| signal | where it already lives |
|---|---|
| how many sources back a claim | `evidence` rows per `claim_id` |
| whether they are independent | `evidence.independent` |
| whether any source **refutes** it | `evidence.stance` — `supports \| refutes \| qualifies` |
| how trustworthy the best source is | `sources.domain` → `source_tiers` → `tier_trust` |
| how stale the evidence is | `sources.retrieved_at`, `sources.published_at` |

`evidence.stance` matters more than it looks: **contradiction detection is already
in the data model.** No text similarity is needed for the basic case.

## Non-goals

Explicitly out of scope, and each for a reason:

- **No dispute buttons, no outcome logging, no reward signal.** That is the
  calibration work, and it needs this view to exist first. A thumbs-down with no
  baseline is a signal nobody can interpret.
- **No rerun triggers and no verification tier.** Same dependency: a priority
  queue needs something to sort on.
- **No changes to `lookup`'s ranking.** This pass reads; it does not alter what a
  buyer is shown. Feeding observed weakness back into `relevance()` is a later,
  separate decision.
- **No graph visualisation.** A ranked list with expandable rows conveys more per
  pixel than a force-directed layout, and it is testable.
- **No new writes of any kind.** Read-only over the installed store.

## The weakness ordering — no invented scalar

The four signals are shown **separately**, never collapsed into a score. A weighted
sum would require weights nobody can justify, and would hide which signal fired.

For ordering, sort **lexicographically by severity of concern**:

1. **Contradicted** — any `evidence.stance = 'refutes'` for this claim. First,
   always: a claim we ship while holding a rebuttal is the sharpest thing on the
   list.
2. **Uncorroborated** — fewest distinct independent supporting sources. One
   source is materially different from two.
3. **Low trust** — lowest *best* tier among supporting sources. A claim whose
   best source is an SEO blog ranks above one with a manufacturer bulletin.
4. **Stale** — oldest `max(retrieved_at)`. A quote grounded in a page fetched two
   years ago may no longer exist on that page.

Lexicographic, not weighted: the order is explainable in one sentence, and adding a
fifth signal later does not require re-tuning four numbers.

`published_at` is reported but **not** part of the ordering. An old source is not a
weak source — a 2015 manufacturer bulletin about a 2015 part is exactly right.
`retrieved_at` is about *our* staleness; `published_at` is about the world's.

## Architecture

Three pieces, one query.

### `src/kriko/lookup/tree.py` — the query (engine, category-free)

Public surface:

```python
def subject_tree(conn, subject_id: str, pack_ids: list[str]) -> SubjectTree
def weakest_claims(conn, pack_ids: list[str], limit: int = 20) -> list[ClaimHealth]
```

`ClaimHealth` carries the claim's identity plus the four signals as separate
fields — `refuted_by: int`, `independent_sources: int`, `best_tier: str`,
`best_trust: float`, `oldest_retrieved_at: str`, `newest_published_at: str` — and a
`concern: tuple` that is the lexicographic sort key, so the ordering is inspectable
rather than implicit.

**It reuses `rank.py`'s existing tier resolution** — `tier_lookup()`,
`trust_lookup()`, `tier_of()` — rather than reimplementing the domain→tier→trust
join. A second tier-resolution path is precisely the duplication the previous two
passes existed to delete.

`kriko/` may name no product category. The module queries `claims`, `evidence`,
`sources` and the tier tables generically; `domain`, `component` and `subsystem`
are pack vocabulary read as opaque strings. The prose gate applies.

### `src/app/web/routers/health.py` — the page you can open

Two routes, matching the shape of the existing `subjects.py` and `query.py`
routers (`@router.get`, `store=Depends(get_store)`):

- `GET /api/health/weakest?limit=20&pack_id=` — the repo-wide list
- `GET /api/health/subject/{subject_id}` — one subject's tree

Plus the rendered page in the dashboard. A row per claim showing the four signals
as columns, expandable to its evidence and sources with tier and stance per row.
Contradicted claims visually distinct — they are the actionable ones.

### `src/app/mcp_server.py` — the same query for agents

One tool, `subject_tree(subject_id, pack_id)`, returning the same structure. This
is what lets a research agent read back what it wrote and notice an asymmetry: its
new claim resting on one forum post, next to an existing claim with three
specialist sources.

## Testing

- **Unit, against a built fixture pack:** a claim with one forum source ranks
  above one with three specialist sources; a refuted claim outranks both; ordering
  is stable and the `concern` key is asserted directly rather than inferred from
  output order.
- **Two packs installed:** the tree unions across them and reports `pack_id` per
  claim, so a cross-pack contradiction is visible. This is the G6 case and the
  reason the query takes `pack_ids` rather than a single pack.
- **Empty store:** both entry points return empty structures rather than raising.
  A fresh install has no knowledge and that is not an error.
- **The engine stays category-free:** `test_core_is_domain_free.py` covers the new
  module, executable positions and prose.

## Verification — what "working" means

Rebuild and install the cars pack into a clean store, start the dashboard, open
the health page, and see the shipped claims ordered worst-first with their signals.
Then run the MCP tool against one subject and get the same numbers.

Concretely: `python -m app.cli build packs/cars && python -m app.cli install
dist/cars.kpack`, then `python -m app.web`, then the page.

## Risks

| Risk | Mitigation |
|---|---|
| A second tier-resolution path drifts from `rank.py`'s | Import and reuse `tier_lookup`/`trust_lookup`/`tier_of`; a test asserts both agree on the same source |
| The ordering looks arbitrary to a reader | Signals shown separately and the sort key exposed; no hidden weights to disagree with |
| Read-time computation is slow at scale | ~700 claims today; the schema's own comment says trust is computed at read time by design. If it becomes slow, a snapshot table is additive and needs no migration |
| The view invites acting on a bad signal | `independent` and `stance` are producer-supplied flags. The page must show them as *claims about the evidence*, not as verified facts |
| Scope creep into scoring | Non-goals are explicit: no change to `relevance()` in this pass |
