# The model benchmark

Which model should answer a question, how much does it cost to ask, and how
often does it invent something? This is the instrument for that decision, and
it exists because the phone will need it.

Run it with:

```bash
# what can this machine measure?
python -m app.modelbench list

# what would this sweep do?
python -m app.modelbench plan --candidates local:qwen3.5:4b,harness:mistral-vibe@glm-5-3

# measure, and write the report
python -m app.modelbench run \
    --candidates local:qwen3.5:4b,harness:mistral-vibe@glm-5-3 \
    --reps 2 --out benchmarks
```

Four files land in `--out`: a JSON document with everything, two CSVs (one row
per model, one row per run), and a Markdown report meant to be read.

A report is a *view* of the measurements, so correcting one never costs another
sweep — the JSON is enough to rebuild all four files:

```bash
python -m app.modelbench report --from benchmarks/modelbench-2026-10-18.json
```

## The charts

Five pictures are written beside the report and two of them are embedded in it.
They are hand-drawn SVG, not matplotlib, for three reasons that each cost
something real: the desktop build carries its dependencies and a plotting
library is a large one to add for five pictures; a chart that cannot be
regenerated from a saved run goes stale the moment a rate is corrected, and
`rerender` already rebuilds the report from its JSON; and SVG is text, so it
differs in a review, stays crisp on a HiDPI screen, and can carry a
`prefers-color-scheme` rule that makes one file readable on a light and a dark
page.

| Chart | The question it answers |
|---|---|
| `tradeoff` | **Which model should the phone use.** Tokens per run (log) against fabrication rate, bubble area is expected facts found, bars are the 95% intervals. Down and left is good. |
| `quality` | The five rates per model as a matrix, because a single score would hide that one model's problem is abstention and another's is invention |
| `tokens` | Where the tokens went — sent and returned — with a CLI's whole-session figure drawn as a different kind of number |
| `dimensions` | *Where* each model fails, case dimension by case dimension |
| `fabrication` | What kind of fabrication: an unsupported claim, a quotation that is not in the page, a figure under the wrong name |

Two rules in `charts.py` are worth knowing because each one is a bug it was
written to prevent. A model with no fabrication rate — because it claimed
nothing — is **named under the chart rather than dropped from it**, since an
unexplained absence reads as an oversight in that model's favour. And a log axis
is **scaled to its data**: the first version snapped outward to whole decades and
drew 100 → 100,000 for data spanning 862 → 8,081, which left 60% of the picture
empty and both interesting models in one corner.

The charts are drawn entirely from the document the tables are drawn from, so a
graph cannot disagree with the table beside it. `src/app/tests/test_modelbench_charts.py`
checks the parts a reader would never catch: that the Markdown's image links name
files that were actually written, that no placeholder text reaches a label, that
a model name containing `<` cannot break the document, and that the axis steps
are round numbers rather than artefacts of the largest value.

To look at a chart directly — there is no way to see an SVG through a text tool —
`tools/chart_preview.py` rasterises them with a headless browser. It is a
checking tool, not part of the report.

## Three things called "bench"

They answer different questions and should not be confused:

| Command | Question it answers | Module |
|---|---|---|
| `kriko model-bench` | Which **model**, on a fixed corpus: tokens, fabrication, abstention | `app/modelbench/` |
| `kriko bench` | How does the **research pipeline** do over the reader's installed packs, and how do planes fail | `app/bench.py` |
| `kriko agent-bench` | Does an **agent** resolve fixed *tasks*, obey settings, stay consistent | `app/agentbench/` |

Only the first is about a model choice. The second is superseded for that
purpose and says so in its own docstring; the third grades agent behaviour on
tasks, not model accuracy on evidence.

## The unit is a model, not a plane

The benchmark this replaces keyed every measurement by **plane** — `harness`,
`agent`, `api`, `local`. A plane is the application's plumbing. It answered
"how does Kriko's research pipeline do", which is a real question and a
different one, and it left the actual question — *which model* — spread across
rows that could not be compared.

So the unit is a **candidate**: one model, reached one way.

```
local:qwen3.5:4b                  Ollama on this machine
local:gemma3n:e2b                 the same, a different model
harness:mistral-vibe@glm-5-3      the Mistral CLI, driving GLM-5.3
harness:claude-code               the Claude CLI on its own default model
api:gpt-4o-mini                   a paid endpoint, when a key is present
```

That string is the candidate's identity everywhere — the CLI, the CSV, the
report — so a result can be reproduced by pasting it. `list` prints what this
machine can reach right now; nothing is ever invented, and a name nobody owns
still parses and fails loudly at run time rather than being refused at the door.

## Everything except the model is held identical

Three things are pinned, and a run that breaks any of them is not comparable.

**One corpus.** Ten fictional products (`kriko-configuration`, versioned in
`src/app/benchprecision.json`), each with a document that is the entire world of
the case and a named measurement dimension: a revision not to be confused with
its neighbour, a market, an excluded build year, a superseded bulletin, a
missing identity, 32 distractors around one true line, a case with no evidence
at all, and a consumable blamed for its host's fault.

**One brief.** `corpus.prompt` is the only way a case becomes text, and it is
built from the case and nothing else. The documents are *in* the brief, so no
candidate can search — a case measures what a model does with evidence, never
how lucky its search was. Every run records the brief's fingerprint, checked
**per case**, and the report says so at the top: a sweep whose candidates saw
different text for the same case is not a ranking and says as much in bold.

**One scorer.** `metrics.py` compares against the answer key with string and
span tests. No model grades another model: a model asked to score a peer agrees
with it far too often to be evidence, and the one thing this must be is
independent of what it measures.

Everything that is *not* held identical is the finding and is reported: a
harness CLI brings its own system prompt and its own tool belt, a local model
brings its own context window. Hiding that would be the easiest way to make the
table lie.

## Reading the numbers

| Column | What it is | How it can mislead |
|---|---|---|
| **Answered in shape** | How often the reply was even the requested JSON object | A model that never produces the shape has no recall and *no* hallucination rate. Two dashes that must not read as "nothing was wrong" |
| **Claimed** | How many items it put forward in total | The denominator the hallucination column divides by. Without it, "0%" and "no data" look alike |
| **Correct facts** | Share of the case's expected facts that were found, pooled across cases | A model that answers nothing scores 0% here and looks fine everywhere else — which is why it is its own column |
| **Hallucinated** | Share of *produced* items the key could not support: an invented quote, a claim the documents do not make, a wrong specification | Not the same as low recall. Low recall is a better brief; hallucination is a model not to trust unattended |
| **Specs found** | Share of requested specifications answered with the key's exact name, value and URL | A right figure under a wrong name is not a right figure |
| **Wrong specs** | Share of the specifications it *did* return that were wrong | A model that returns no figures scores no wrong specs. Read it beside *Specs found*, never alone |
| **Abstained** | On cases where the corpus holds *no* answer, whether the model produced an empty answer instead of a plausible invention | The safety property. On a phone it matters more than recall |
| **Tokens/fact** | Counted tokens divided by **expected facts found** — cost per correct answer | The only cost column that punishes both overspending and under-delivering |
| **Tokens/accepted** | Counted tokens divided by **accepted claims** | On this corpus the two denominators coincide; they come apart on the pack-derived suites, where a genuine new finding is accepted without being in the key |
| **Median time** | End to end, including process start for a CLI | Not the model's latency alone |

The two cost figures are kept apart because the app's own readout
(`protocols.readout`) reports cost per *accepted claim*, and a screen and a
report publishing two different efficiencies for one model is how a benchmark
loses its reader. `tokens_per_claim` — cost per item put forward at all — is in
the CSV for the same reason: it separates a model that answers cheaply from one
that answers little.

Every rate carries a **95% Wilson interval**. A 60% from five items and a 60%
from two hundred are different facts, and the interval is the honest part of
the table. Where two models' intervals overlap, the report says they are not yet
separable instead of crowning one.

Two rules of arithmetic are worth knowing because breaking them is how these
tables usually go wrong:

- **Rates are pooled, never averaged.** Recall is `sum(found) / sum(wanted)`,
  so a case with one fact cannot outvote a case with four.
- **A failure stays in the denominator.** A candidate that failed four of ten
  cases has a 40% failure rate and a recall computed from the six it managed,
  with the failure rate printed beside it. Failures are never dropped and never
  scored as zero recall.

## Tokens are never invented

The three transports report cost very differently, and the report says which one
produced each number:

| Word | Meaning |
|---|---|
| `reported` | The endpoint sent a usage block, so the in/out split is real and a price can be computed from it |
| `reported_total` | A coding-agent CLI metered its **whole session** — its own system prompt, its tool descriptions, every turn. A large number here is the harness's cost, not the brief's |
| `estimated` | Nobody counted; in and out were approximated from characters. **Never** used by the measured means |
| `none` | Nobody counted, and no estimate was safe to make |

An estimate is only ever offered where the whole prompt is visible — `local` and
`api`. A harness's real input is mostly its own, so an estimate of it would be a
fabricated number indistinguishable from a measured one; there, no count is
reported and the character counts carry the comparison instead.

## What it does not measure

- **Search or reading.** Documents are supplied. A model that searches well and
  extracts badly is not measured here — deliberately, since on a phone the
  evidence will come from Kriko, not from the model's own tools.
- **The application around the model.** The local candidate is the plain
  OpenAI-compatible socket, not Kriko's local pipeline (triage, evidence
  selection, the grounding gate). A pipeline that rescues a weak model must not
  be scored as a strong one.
- **Real product knowledge.** The corpus is explicitly fictional. It measures
  whether a model follows a configuration argument under a fixed brief, which is
  the thing that transfers; it does not measure whether the model knows about
  cars.
- **The live-web suite.** `benchcases.json` (the legacy `web` suite) is refused
  by name, because its documents change between runs and a case whose world
  moves cannot support a token comparison.

## Adding a case

Cases are generated, not hand-edited:

1. Add the case in `src/app/precisioncases.py` with a `dimension`, its
   documents, and its answer key.
2. Bump `SET_VERSION`.
3. Regenerate: `python -m app.precisioncases`.
4. `python -m pytest src/app/tests/test_modelbench.py src/app/tests/test_precision_benchmark.py`

`corpus.problems` runs before every sweep and refuses a corpus that would make a
score a lie — a case with no documents, or one with no supported facts that is
not marked as expecting abstention, because recall there is unhittable and every
candidate would score zero for a reason that has nothing to do with any
candidate.

### The key can be wrong, and the report is built to show it

An answer key is authored by a person, and the first real sweep found a defect in
one. On `car-market` the key demanded the value `belt` for the specification
`timing drive`; GLM-5.3 answered `timing belt`, which is the same answer under a
different name, and was recorded as a **wrong specification** on both
repetitions. The corpus already used an alias for exactly this case elsewhere
(`clutch type` accepts `wet clutch`), so the fix was one line and a version bump
— `2026.10.18`.

Two things in the design are why that took minutes rather than a re-read of the
raw replies:

* every run stores the case's **answer key** beside its score, so a surprising
  number can be checked against the bar that produced it;
* the **Wrong specs** column sits next to **Specs found**, so a model is never
  scored as fabricating without the report also showing whether it omitted the
  figure instead.

The version bump is not paperwork. The corrected corpus measures a slightly
different task, so a run on `2026.10.18` is never ranked against one on
`2026.10.10` — the report prints the version it measured, and the two are kept
apart on purpose.

## Keeping the numbers trustworthy

`src/app/tests/test_modelbench.py` is written about the ways a number could be
wrong rather than about function return values. Each of these has a test:
rates pooled instead of averaged; a failure dropped from a denominator; an
estimate folded into a measured mean; `tokens/fact` rewarding a model that found
nothing; prose instead of JSON crashing the run rather than scoring zero; and
two candidates being given different text for the same case.
