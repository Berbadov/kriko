> TL;DR (archived 2026-09-25): Design (2026-09-15; steps 1–6 implemented 2026-09-16) for
ground-truth benchmarking: B111 acceptance-rate can't answer correctness/recall/significance,
so ship per-pack `gold.yaml` (`must_find`/`must_not_find`/`known_absent`), judge mechanically
(component+domain → quote overlap → `unlisted`), sweep batch/context/preamble/provider with
repetitions + Wilson intervals, output the best hallucination-adjusted protocol per model.
Three `tasks.bench()` gaps remain (no `search`/`kind` sweep, no param forwarding, readout
not split by provider).

# Benchmarks against ground truth — design

**Status:** steps 1–6 implemented 2026-09-16 (`app/{gold,bench,protocols}.py`, `Spend.preamble`, grounding hardening landed). **Not** landed — job-driver gaps — see bottom. **Date:** 2026-09-15. **Prompted by:** *"Benchmarks against ground truth … cost and hallucination at arbitrary rates, statistical methods … optimal batch sizes, api calls, precontext query."*

## 1. What B111 measures, and why it is not enough

A bench row (wall-clock, tokens, dollars, sources, gate-kept findings) permits one comparison — *which plane keeps a larger share of what it returns* (real signal: the grounding gate is mechanical). It cannot answer: (1) **was it right?** (quote-in-document ≠ true-of-subject; acceptance = plausibility discipline, not correctness); (2) **what was missed?** (two good of eight available scores perfectly — recall invisible); (3) **is it real?** (n=3 is an anecdote — "60% vs 45%" is noise with a decimal point).

## 2. Ground truth, without a human in the data path

Automation principle bans per-datum review; a **gold set** is a one-time authoring decision (like search templates or the principle), never touching live data. Ships **as pack data**: `packs/<name>/research/gold.yaml` — cases with pack-identity subjects, `kind`, `must_find[]` (recall: claim+domain), `must_not_find[]` (precision trap + why), `known_absent[]` (real trap: nothing credible says it). E.g. `golf7-dsg`: mechatronics + chain tensioner must-find; "check engine light" (generic) must-not; "turbo actuator" known-absent. Honest because: pack authors it (headphone truth ≠ car truth; `kriko/` stays ignorant); **`must_not_find` makes hallucination measurable** (confident claim of a declared-nonexistent + retained document (B120) = checkable-after-the-fact fabrication); versioned with the pack (stale gold = visible diff).

## 3. Three case kinds, because they fail differently

`specific` (one subject — per-claim precision/recall) | `bulk` (agenda run over N — throughput + whether quality *degrades with volume*, the unmeasured failure; the plane a reader actually has) | `validation` (re-check stored claims vs retained documents + fresh fetch — drift + willingness to say "no longer holds").

## 4. The metrics

Per (case, plane, model, protocol, repetition): **precision** (kept ∩ must_find or acceptable-unlisted, §6); **recall** (must_find produced); **hallucination rate** (must_not/known_absent hits ÷ produced — separate from precision: low precision = tighten gate, hallucination = don't trust unattended); **cost per accepted claim** (the only fair cross-plane dollar); wall-clock (+ claims/min for bulk).

## 5. Statistics, because n=3 is an anecdote

Repetitions (default r=3 — LLMs are stochastic; one run reports a sample as a constant) | **Wilson intervals on every rate** (60%-of-5 ≠ 60%-of-200) | comparison = non-overlapping intervals (replaces flat 5% `MIN_MARGIN`, which says so) | seeded case order (comparable sweeps; scheduling ≠ quality).

## 6. Judging a claim against ground truth, mechanically

Cheapest first, no human, no LLM-judging-its-own-family: (1) **component + domain** (pack's gate vocab — `mechatronics`+`transmission` matches); (2) **quote overlap** (`factcheck.py`'s flattened-text comparison); (3) **unmatched-but-grounded ⇒ `unlisted`** (gold is a floor, not a ceiling — novel finds mustn't teach timidity). Only must_not/known_absent hits are hallucination, each stored with its document (re-checkable).

## 7. What the sweep outputs

Reader's ask (batch size, call pattern, preamble): sweep **batch size + context-per-document** (`Spend`, exists) × **preamble** (new `Spend.preamble`: `terse`/`principled`/`worked-example` — the instruction, likeliest hallucination mover, unguessable) × (search provider, §8). Output: per-model table of best hallucination-adjusted yield-per-dollar + interval; `protocols.py` reads it instead of acceptance rate (picker shape unchanged).

## 8. Search providers are the same question

Exa wired, Tavily not; provider changes inputs before anything else applies ⇒ sweep axis (`gather` already takes a searcher: constructor arg + bench column, not redesign).

## 9. Order of work

`gold.yaml` contract + loader (nothing works without it) → judging + dependent metrics → repetitions/intervals + `protocols.choose` → `bulk` + `validation` kinds → `Spend.preamble` sweep → provider axis. Each shippable; each de-guesses the picker. Step 1 is smallest and turns all later numbers into correctness claims.

## Known gaps after 2026-09-16

Implemented + tested, no network/LLM (`test_gold.py`, `test_bench_kinds.py`, `test_protocols.py`, `test_the_benchmark.py`, `test_research.py`) — but not yet drivable end-to-end from one button; all three gaps in `src/app/web/tasks.py` (outside this plane's file list):

1. **`tasks.bench()` doesn't sweep `search`/`kind`** (loops case×plane×protocol×rep; `run_case` already takes `search=` + dispatches `kind`). Fix: `searches_asked` à la `protocols_asked` + one more loop + pass-through + per-row `kind` logging.
2. **`_researcher()` drops `search`/`model` params** (forwards `protocol` only; both accepted by `api_researcher` — two missing kwargs). Until landed, `run_case(search=…)` reaches nowhere on the real path.
3. **`/api/bench` readout not split by provider** (reads per-row `state.bench_runs()`, not `bench_summary()` — correct pre-data, but two-provider sweeps report the *most-common* provider, not per-provider). Split `readout()` by (model, protocol, provider) once gap 1 lands (single-provider rows until then).
