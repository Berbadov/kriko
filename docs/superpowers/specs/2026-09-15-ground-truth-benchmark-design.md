# Benchmarks against ground truth — design

**Status:** design. B111 shipped the *harness* (cases, runs, costs); this is what
it has to become to answer the question anyone actually has.
**Date:** 2026-09-15.
**Prompted by:** *"Benchmarks should be done against ground truth; specific cases
of bulk research, specific research, data validation etc. measuring cost and
hallucination at arbitrary rates, using statistical methods … benchmarks would
hopefully output the optimal batch sizes and api calls as well as the
precontext query."*

---

## 1. What B111 measures, and why it is not enough

Today a bench row carries wall-clock, tokens, dollars, sources, and how many
findings the gate kept. That makes one comparison possible — *this plane keeps a
larger share of what it returns than that one* — and it is a real signal,
because the grounding gate is mechanical.

It cannot answer three questions that matter more:

1. **Was what it kept actually right?** The gate proves a quote appears in a
   document. It does not prove the claim is true of the subject, and it cannot
   prove the document was not fabricated wholesale. Acceptance rate measures
   *plausibility discipline*, not correctness.
2. **What did it miss?** A run that returns two good claims when eight were
   available scores perfectly on acceptance. Recall is invisible.
3. **Is the difference real?** Three cases is an anecdote. "Plane A kept 60%,
   plane B kept 45%" on n=3 is noise with a decimal point.

## 2. Ground truth, without a human in the data path

The automation principle forbids per-datum review. A **gold set** is not that: it
is a one-time authoring decision, exactly like a pack's search templates or its
principle — and it never touches live data. The rule stays: nothing a reader
researches waits on a person.

So ground truth ships **as pack data**: `packs/<name>/research/gold.yaml`.

```yaml
cases:
  - id: golf7-dsg
    subject: {kind: variant, identity: {...}}      # pack's own identity keys
    kind: specific                                  # see §3
    must_find:                                      # recall
      - {claim: "dual-clutch mechatronics failure", domain: transmission}
      - {claim: "timing chain tensioner", domain: engine}
    must_not_find:                                  # precision / the trap
      - {claim: "check engine light", why: "generic — true of every car"}
    known_absent: ["turbo actuator"]                # a real trap: nothing credible says this
```

Three properties make this honest:

* **The pack authors it, not the engine.** Ground truth for headphones is not
  ground truth for cars, and `kriko/` may not know which is which.
* **`must_not_find` is where hallucination becomes measurable.** A claim the
  case declares does not exist, produced confidently with a quote, is a
  fabrication — and the retained document (B120) makes it checkable after the
  fact rather than at the moment of judging.
* **It is versioned with the pack**, so a gold set and the knowledge it judges
  move together and a stale gold set is a visible diff rather than a mystery.

## 3. Three case kinds, because they fail differently

| Kind | What it runs | What it is for |
|---|---|---|
| `specific` | one subject, the ordinary research operation | precision/recall per claim |
| `bulk` | an agenda run over N subjects | throughput, and whether quality *degrades* with volume — the failure nobody measures |
| `validation` | re-check claims that are already in the store, against their retained documents and a fresh fetch | drift, and whether the plane can say "this no longer holds" |

`bulk` is the one that justifies the whole design. A plane that is excellent on
one subject and sloppy across twenty is the plane a reader actually has, and a
single-case benchmark cannot see the difference.

## 4. The metrics

Per (case, plane, model, protocol, repetition):

* **precision** — of the claims kept, how many matched a `must_find` or were
  judged acceptable-but-unlisted (see §6).
* **recall** — of `must_find`, how many were produced.
* **hallucination rate** — claims matching `must_not_find` or `known_absent`,
  over claims produced. Reported separately from precision, because the two
  have different remedies: low precision is a gate to tighten, hallucination is
  a plane not to trust unattended.
* **cost per accepted claim** — dollars and tokens divided by what survived,
  which is the only cost number that compares two planes fairly.
* **wall-clock**, and for `bulk`, **claims per minute**.

## 5. Statistics, because n=3 is an anecdote

* **Repetitions.** Every (case × plane × protocol) runs `r` times (default 3,
  configurable). Language models are stochastic; a benchmark that runs once
  measures a sample and reports it as a constant.
* **Interval, not point.** Report a Wilson score interval on every rate. A
  60% acceptance from 5 findings and a 60% from 200 are different facts and
  must not print identically.
* **Comparison.** Two protocols differ only when their intervals do not
  overlap — which replaces `protocols.MIN_MARGIN`, a flat 5% that is a stand-in
  for exactly this and says so.
* **Seeded order.** Cases run in a fixed order from a seed, so two runs of the
  same sweep are comparable and a scheduling difference is not read as a
  quality difference.

## 6. Judging a claim against ground truth, mechanically

Matching a produced claim to a `must_find` entry cannot be a human reading a
list, and it should not be an LLM judging its own family's output either. The
rule, cheapest first:

1. **Component + domain match** — the pack's own vocabulary, already used by the
   gate. A claim anchored to `mechatronics` in `transmission` matches a gold
   entry naming both.
2. **Quote overlap** — the flattened-text comparison `app/factcheck.py` already
   does for re-checks.
3. **Unmatched, but grounded** — neither confirmed nor a fabrication: counted
   in its own bucket, `unlisted`. A gold set is a floor, not a ceiling, and
   counting a genuinely new find as an error would teach the benchmark to
   reward timidity.

Only `must_not_find` / `known_absent` hits count as hallucination, and each one
is stored with its document so the judgement is re-checkable.

## 7. What the sweep outputs

The reader's actual ask: *what batch size, what call pattern, what preamble.*

The sweep axes are:

* **batch size** and **context per document** — `kriko.research.Spend`, which
  exists.
* **the preamble** — the standing instruction sent ahead of the documents
  (OpenAI calls it the system message; Kriko's brief plays this role today and
  is not currently separable from the task). This design adds `Spend.preamble`
  as a *named* variant — `terse`, `principled`, `worked-example` — so the
  benchmark can measure the instruction, not only the geometry. It is the axis
  most likely to move hallucination, and the one nobody can guess.

Output is a table per model: the protocol with the best hallucination-adjusted
yield per dollar, with its interval. `app/protocols.py` reads that table instead
of the acceptance rate it reads now — the picker's shape does not change.

## 8. Search providers are the same question

Exa is wired; Tavily and the rest are not. A search provider changes what the
model sees before any of the above applies, so it belongs on the sweep as an
axis rather than in a call site — `gather` takes a searcher already, so this is
a constructor argument and a bench column, not a redesign.

## 9. Order of work

1. `gold.yaml` in the pack contract + a loader. Nothing else works without it.
2. Judging (§6) and the three metrics that need it.
3. Repetitions + intervals (§5), and `protocols.choose` reading them.
4. `bulk` and `validation` case kinds.
5. `Spend.preamble` and the preamble sweep.
6. Search provider as an axis.

Each step is shippable and each one makes the picker less of a guess. Step 1 is
also the smallest, and it is the one that turns every later number into a claim
about correctness rather than about discipline.
