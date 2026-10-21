# Product research: accuracy, speed, cost and tokens

Request: “some products are heavy job some easy. think about a car or a computer and a shoe for example.”
Done when complete research workflows can be compared on identified products,
harder variant/scope questions, and incomplete listings, with correctness and
evidence requirements alongside latency and spending.

The product experiment is separate from the initial documentation benchmark.
It preserves old results as history instead of pooling incompatible tasks,
budgets, protocol versions and response formats into a single leaderboard.

```powershell
# Freeze the corpus/protocol and collect retrieval + end-to-end research runs.
.venv/Scripts/python.exe -m app.searchbench.mega run --workers 2 --reps 1

# Grade saved answers; this does not repeat their research calls.
.venv/Scripts/python.exe -m app.searchbench.mega judge PATH_TO_MEGA_FOLDER --workers 2

# Recompute deterministic citation gates from saved judge outputs, without API calls.
.venv/Scripts/python.exe -m app.searchbench.mega recompute PATH_TO_MEGA_FOLDER

# Rebuild reports, CSVs and figures without making paid requests.
.venv/Scripts/python.exe -m app.searchbench.mega report PATH_TO_MEGA_FOLDER

# Optional paid evaluator controls, kept separate from research measurements.
.venv/Scripts/python.exe -m app.searchbench.mega calibrate PATH_TO_MEGA_FOLDER --workers 4

# Combine report views, preserving separate experimental blocks.
.venv/Scripts/python.exe -m app.searchbench.mega combined FIRST_FOLDER SECOND_FOLDER

# Build plain tables with low/high sort links and expandable logs (no JavaScript).
.venv/Scripts/python.exe -m app.searchbench.listing FIRST_FOLDER SECOND_FOLDER --out .local-evaluation/searchbench/simple-results
```

The default corpus is `src/app/searchbench/products.json`: three categories
(shoe, computer, car), each with an easy lookup, a heavy research job and an
incomplete-identity job. Reference facts were checked against primary sources
on 20 October 2026. Product names and facts are benchmark data, not engine
rules. Each case declares its references, required facts and critical facts.
Agents receive only the question; evaluators receive the rubric afterwards.

The initial sample deliberately includes these distinctions:

- EVA material versus a classic cork footbed; a membrane specification versus
  what isolated wet-feet reviews can establish about failure rates.
- Native display support for an exact Apple generation; integrated RAM and a
  removable SSD on a Dell clamshell versus its similarly named 2-in-1.
- A recall's exact model-year/transmission scope versus a different listing;
  campaign-level information versus a VIN's open-recall/completion status.
- Missing identity that requires a targeted question, rather than a guessed
  product configuration. Asking a necessary question is a successful outcome.

The corpus is small and intentionally adversarial. It cannot represent the
market distribution of all cars, computers or shoes. Use a larger held-out
JSON corpus and additional repetitions before making a production decision.

## Profiles and execution

The common baseline uses eager DeepSeek search with each of Mercury 2.5,
Mercury 3, Ministral 3 8B, Ministral 3 14B and Mistral Large 4. Other profiles
test Mercury 2.5 with Exa Lite, Tavily Fast, parallel orchestration, federated
retrieval, and Mercury 3 verification of a Mercury 2.5 draft.
`m25-federated-verify-m3` combines all three search providers with that two-model
workflow. When adding a profile after examining initial results, run a separate
randomized block with contemporary control profiles; retain the block boundary
instead of treating the new runs as an untouched hold-out experiment.

Federation queries DeepSeek, Exa and Tavily concurrently, merges canonical URLs
under global source IDs and retains at most twice the per-provider result
count. All requests are charged to that candidate. It does not pretend that
waiting for three providers has the latency of the fastest one. A source read
can recover through another provider that returned the same URL.

Verification can reopen search/read tools using the same evidence store. It
does not see the answer key. Draft latency and final-answer latency are distinct;
the verifier's tokens, requests and charges count towards the same end-to-end
trial. A clarification with no substantive claims skips a second research pass.
An unsuccessful verifier is not silently called a verified answer.

Case budgets are fixed before execution: 20 seconds for easy jobs, 45 for heavy
jobs and 12 for incomplete identity. They are experimental ceilings, not
production SLOs. A model timeout under these settings is evidence about this
bounded workflow, not proof that the model cannot solve the question.

`--workers 2` measures two simultaneous research runs with shared account pacing;
this load is recorded. Use `--workers 1` for serial latency measurements. The
retrieval screen runs serially. No local response cache survives between trials;
provider-side caches can still apply. Reports split first-observed and repeated
identical retrieval queries by chronology, not shuffled repetition labels.

## Accuracy assessment

Mistral Large 4 and Mercury 3 independently judge saved answers, blinded to
candidate identity, latency and price. They receive the frozen rubric and only
the bounded evidence actually supplied to the researcher, never hidden full
page text. The judgement protocol hash is recorded separately.

An answer is accepted only if both judges find:

- At least 80% of the required-fact credit, with every critical fact fully
  correct. Missing information and false information are distinguished.
- No audited false claim or variant/year/market scope violation.
- Adequate primary citations and at least 80% supported audited material
  claims for factual research tasks. Easy tasks require one primary URL;
  heavy tasks require two. Correct clarification can pass without citations.
- No invented source ID. Related URLs and keyword overlap alone do not prove
  that a citation supports a claim. Truncated evidence can be insufficient.

These are model-assisted acceptance estimates, not human-adjudicated truth.
Publisher-hosted community posts do not count as manufacturer documentation,
and translated GUID/locale copies of the same document count once. A judge's
"supported" label with no supporting source ID is downgraded to "not cited".
Conditional factual assertions still require support even on identity tasks.
The audit is bounded to twelve material claims per answer. Disagreements,
missing grades and evaluator failures remain visible. The raw answer, source
text, criterion credits and short explanations are retained for inspection.
Offline grading has its own `judge --timeout` budget; changing it does not
change candidate research deadlines. Resuming retries failed grading calls
without repeating completed research or successful grades.

The optional calibration checks three correct and three deliberately wrong
answers against curated primary-fact summaries. Both evaluators score these
controls. Passing them shows simple discrimination, not open-web reliability
or the absence of correlated judge errors. Calibration spending is separate.

## Metrics and statistics

Reports show results overall and within each category × job-type stratum.
Equal representation is used for this screening corpus; no traffic mix is
invented. A tiny stratum displays accepted/attempted counts rather than hiding
its sample size behind a percentage.

Mean wait includes failed attempts. Accepted-answer latency is reported
separately. Cost per accepted answer includes spending on timeouts and rejected
answers. Unknown usage remains a lower bound. A partly priced profile cannot
dominate a fully priced one in the cost-aware Pareto calculation.

Confidence intervals use 2,000 bootstrap draws of whole product-question
clusters. Paired differences match case and repetition, retaining failures in
time comparisons. Dollar/token differences omit pairs whose corresponding
totals are unknown, and export the number of usable pairs. p95 is withheld
until a profile has twenty accepted answers. The narrow corpus and small
sample prevent confident claims about the wider product population.

Every model call retains input, cached input, output, reasoning and total
tokens. Cached input is a subset of input, and reasoning is a subset of output.
Do not count those subsets twice. Candidate research, retrieval screening and
offline evaluation have separate ledgers. Failed grading attempts remain in
`audit_history` and count towards grading spend when retrying evaluation.

Exa uses its reported dollar cost. Tavily records raw credits and uses the
explicit comparison rate `--tavily-credit-usd` (default $0.008/credit, published
pay-as-you-go pricing). This is not the account's actual invoice or free-tier
cash expenditure. DeepSeek and model price assumptions are frozen in results.

## Output and inspection

Open `simple-results/index.html` for the compact results table. Every metric has
low-to-high and high-to-low links. Expand a stack's logs to see the original
answers, individual request timings and usage, citations, and evaluator results.
Copy the whole folder when sharing; sorting navigates between static HTML pages.

The table labels its fact F1 as a **proxy**, not standard classification F1.
For each factual research attempt and evaluator, precision is correct audited
material claims divided by all audited claims (including unknowns); recall is
the mean required-criterion credit. Their harmonic mean is averaged over both
evaluators, then over factual attempts. Runtime failures score zero, missing
grades remain unscored, and identity/clarification tasks use the acceptance
column instead. Source-grounding and critical-fact gates remain separate from
this descriptive composite. A high proxy can coexist with a rejected answer.

Each experiment folder contains:

- `results.json`: questions, rubrics, raw answers/evidence, request ledgers,
  source and protocol hashes, and every grading attempt.
- `source.zip`: the research implementation and corpus used at execution.
- `analysis.html` and `analysis.md`: overall, workload and paired comparisons,
  metering assumptions, earlier experiment history and rejected-answer audits.
- `profiles.csv`, `workloads.csv`, `paired.csv`: statistical comparison tables.
- `trials.csv`, `requests.csv`, `retrieval.csv`: candidate and search measurements.
- `retrieval-publishers.csv`: manufacturer/regulator retrieval coverage; this
  is an authority diagnostic, not an accuracy score.
- `grading.csv`, `grading-requests.csv`: separate evaluation spending and usage.
- `quality-speed.png/svg`, `workloads.png/svg`: standalone figures.

Runtime results are checkpointed atomically after each trial; grading can be
resumed without paying for the research again. Do not run grading against a
folder while its research process is still writing it. The command stages are
explicit to keep those mutations separate.

Primary reference URLs live beside each case. Provider interface and pricing
references are in [the original benchmark guide](SEARCH_BENCHMARK.md).

## Tuning the engine on real cases (`tune`)

The benchmark above compares search providers. `tune` asks a different
question: does a change to the engine make the answers your own agent and
search provider give better or worse? It answers each case with the preferred
agent and search provider read from Settings (`app.sqlite`), then a different
agent grades the answer against fetched evidence.

```
python -m app.searchbench tune list
python -m app.searchbench tune run --label before            # prints the plan and cost, exits 2
python -m app.searchbench tune run --label before --yes      # spends
# change the engine, then
python -m app.searchbench tune run --label after --yes
python -m app.searchbench tune compare <before-folder> <after-folder>
```

- Without `--yes`, `run` prints how many answers and gradings it would make
  and exits without spending.
- The grader is never the answerer, and never the same model. If Settings
  holds no second agent the command stops and says so. The grader sees the
  question, the rubric, the final answer, link results and the evidence pages,
  never the answerer's reasoning.
- Each case is checked for required facts, supported citations (a quote that
  is not on its page is downgraded), product identity, links that open, and
  whether a clarifying question was the right move. Every answer and grading
  names the agent that produced it.
- The ledger and the sortable HTML report are scrubbed of credentials; the
  grader's reasoning is expandable per case.
- `compare` pairs the same case and repetition, reports the pass-rate
  difference with a bootstrap interval over whole cases and an exact sign
  test, and flags a different grader, answerer, case set, protocol, or an
  identical engine commit at the top.
- Every failed trial carries a class from a closed list (timeout,
  malformed_json, paraphrased_quote, invented_quote, invented_link,
  wrong_identity, missed_fact, and so on); the report counts them.
- `tune propose --thread ID` proposes cases from the saved chats you name.
  Nothing leaves the machine; the output is a file to edit before it is used.

Caveat: a rehearsal (`--limit`) is not a verdict, a small case set gives a
wide interval, and no before/after quality figure is claimed here. Measure
with your own keys.
