> TL;DR (archived 2026-09-25): Design (2026-08-31) for knowledge-tree observability: the data
path is open (no feedback on weak claims), though all signals exist unreadably. Read-only
worst-first view over four separate signals (contradicted → uncorroborated → low-trust →
stale; lexicographic, no scalar): engine query `tree.py` reusing `rank.py` tiers, health
router + dashboard page, MCP tool. Baseline: decontamination pass, 606 tests; G3 + G1 precondition.

# Knowledge-tree observability — design

**Date:** 2026-08-31 · **Branch:** from `feat/knowledge-engine-pivot` · **Baseline:** decontamination pass, 606 tests green · **Goal alignment:** G3 (no silent coverage holes); precondition for G1 (quality over quantity)

## Problem

The data path is **open**: research → gate → store → lookup, nothing flows back. Unaskable: *which shipped claims are weakly supported?* So researchers see absence (`coverage_gaps`) but not weakness; agents can't read back their work's shape; re-verification can't prioritise; user correctness signals would land nowhere. The data exists, unreadable as a graph:

| signal | where it already lives |
|---|---|
| source count | `evidence` rows per `claim_id` |
| independence | `evidence.independent` |
| refutation | `evidence.stance` (`supports \| refutes \| qualifies`) |
| best-source trust | `sources.domain` → `source_tiers` → `tier_trust` |
| staleness | `sources.retrieved_at`, `sources.published_at` |

`stance` matters most: **contradiction detection is already modelled** — no text similarity needed for the basic case.

## Non-goals

No dispute buttons/outcome logging/reward (calibration needs this view first — a thumbs-down with no baseline is uninterpretable) | no rerun triggers/verification tier (priority queue needs a sort key) | no `lookup` ranking changes (reads only; feeding weakness into `relevance()` is later) | no graph visualisation (ranked expandable list beats force-directed per pixel, and is testable) | no new writes (read-only over the installed store).

## The weakness ordering — no invented scalar

Four signals shown **separately**, never summed (unjustifiable weights hiding which signal fired). Lexicographic by concern severity: (1) **Contradicted** (any `stance='refutes'` — shipping a rebutted claim is the sharpest item, always first); (2) **Uncorroborated** (fewest distinct independent supporters — one vs two is material); (3) **Low trust** (lowest *best* tier — SEO-blog-best outranks bulletin-best... i.e. ranks *above = worse*); (4) **Stale** (oldest `max(retrieved_at)` — page may no longer contain the quote). Explainable in one sentence; a fifth signal needs no re-tuning. `published_at` reported but **unordered** (a 2015 bulletin about a 2015 part is exactly right — `retrieved_at` is *our* staleness, `published_at` the world's).

## Architecture

Three pieces, one query.

### `src/kriko/lookup/tree.py` — the query (engine, category-free)

`subject_tree(conn, subject_id, pack_ids)`, `weakest_claims(conn, pack_ids, limit=20)`; `ClaimHealth` carries identity + four separate fields (`refuted_by`, `independent_sources`, `best_tier/trust`, `oldest_retrieved_at`, `newest_published_at`) + public `concern` tuple sort key (inspectable ordering). **Reuses `rank.py`'s `tier_lookup`/`trust_lookup`/`tier_of`** — a second tier path is the duplication the last two passes deleted. Pack vocab (`domain`, `component`, `subsystem`) read as opaque strings; prose gate applies.

### `src/app/web/routers/health.py` — the page you can open

`GET /api/health/weakest?limit=&pack_id=`, `GET /api/health/subject/{id}` (mirroring `subjects.py`/`query.py` shape) + dashboard page (four signals as columns, expandable evidence/sources with tier+stance, contradicted visually distinct).

### `src/app/mcp_server.py` — the same query for agents

`subject_tree(subject_id, pack_id)` tool — lets an agent notice its one-forum-post claim beside a three-specialist one.

## Testing

Fixture-pack unit tests: forum-only outranks triple-specialist; refuted outranks both; stable order; `concern` asserted directly. Two packs: union with per-claim `pack_id` (cross-pack contradiction visible — the G6 case for the `pack_ids` parameter). Empty store ⇒ empty structures, not errors. `test_core_is_domain_free.py` covers the module (executable + prose).

## Verification — what "working" means

`python -m app.cli build packs/cars && install dist/cars.kpack`, `python -m app.web`, open health page: shipped claims worst-first with signals; MCP tool returns the same numbers for one subject. Concretely the build/install/run commands above.

## Risks

Second tier path drifts (import + reuse; agreement test) | ordering looks arbitrary (separate signals, exposed key, no hidden weights) | read-time cost at scale (~700 claims today; schema intends read-time trust; snapshot table later, additive, no migration) | acting on producer-supplied flags (`independent`/`stance` shown as *claims about evidence*, not facts) | scope creep into scoring (non-goals explicit).
