# Web research experiments

For the later accuracy-aware car/computer/shoe workload experiment, see
[Product search benchmark](PRODUCT_SEARCH_BENCHMARK.md).

Request: “stack is to bench some variations first” and “Full multi-step research agent”.
Done when the same research questions can be run across the selected models and
retrieval variants, producing inspectable answers, evidence, latency, tokens,
costs, failures, and statistical comparisons.

This is an experimental harness in `app.searchbench`. It does not select the
application's research plane. Run it from the project root with the pipeline
dependencies installed (`httpx`; HTTP/2 additionally needs `h2`).
application's research plane. Install its optional dependencies and run it from
the project root:

```powershell
.venv/Scripts/python.exe -m pip install -e ".[searchbench]"

.venv/Scripts/python.exe -m app.searchbench list

# Search latency and content availability, without an answer model.
.venv/Scripts/python.exe -m app.searchbench retrieval --reps 3 --http2

# Four small models, DeepSeek inline content versus snippets, two agent strategies.
.venv/Scripts/python.exe -m app.searchbench run --reps 2 --http2

# Include the expensive model explicitly.
.venv/Scripts/python.exe -m app.searchbench run --models mercury-3,mercury-2.5,ministral-14b,ministral-8b,mistral-large-4 --searches deepseek-content --reps 2 --http2

# Isolate orchestration using the same model and search provider.
.venv/Scripts/python.exe -m app.searchbench run --models mercury-3 --searches deepseek-content --strategies sequential,parallel,eager --reps 5 --http2

# Other search providers, once their keys are present.
.venv/Scripts/python.exe -m app.searchbench run --models mercury-3 --searches exa-lite,exa-auto,tavily-fast,tavily-ultra-fast --reps 2

# Rebuild a saved report without paying for requests again.
.venv/Scripts/python.exe -m app.searchbench report .local-evaluation/searchbench/searchbench-TIMESTAMP-ID.json
```

The default matrix has four models × two searches × two strategies × six
questions × repetitions. `--models all` includes Large 4 and an optional
`deepseek-control` answer model. A full sweep can take several minutes and makes
paid API requests. `--limit 2` is useful for a smoke run. `--timeout`, `--rounds`,
`--calls`, and `--max-tokens` bound each trial. Default ceilings are 60 seconds,
four tool rounds, twelve tool calls and 3,000 output tokens per model call.
`--results` (default 5) and `--page-chars` (default 6,000) control the evidence
budget. For a smaller-context ablation, try `--results 3 --page-chars 1500`;
compare its answer coverage as well as its speed and token bill.

Credentials are read from the process environment, then Windows user and
machine environment settings, then the project `.env` (or `--env-file PATH`,
before the command). An existing value wins. Only these names are imported:

| Component | Environment variable |
|---|---|
| Mercury 3 / Mercury 2.5 | `MERCURY_API_KEY` |
| Ministral 3 14B / 8B / Mistral Large 4 | `MISTRAL_AGENT_API_KEY` |
| DeepSeek search / fetch / optional control model | `DEEPSEEK_API_KEY` |
| Exa | `EXA_API_KEY` |
| Tavily | `TAVILY_API_KEY` |

`list` shows presence only and makes no API requests. A missing selected key
fails before the sweep starts. Credentials travel in HTTP headers and are
redacted from exported JSON. Evidence and queries are retained locally, so use
an appropriate output directory for sensitive research.
Exit status is 0 when every trial succeeds, 1 when a report contains failures,
and 2 for invalid selections, credentials or budgets. A reported timeout is a
measurement and is retained in the report.

## What changes between trials

All strategies use the same bounded native tool loop. The model chooses its
queries, pages, follow-up searches and stopping point. Page text included in a
search response can be used directly. Missing content can be fetched, and an
unreadable page is returned to the agent as a tool error so it can choose an
alternate source. The model receives source IDs for inline citations.

| Strategy | Behavior |
|---|---|
| `sequential` | Execute a model's tool batch one call at a time |
| `parallel` | Execute independent calls concurrently, at most four |
| `eager` | Search the literal question before the first model call, then use parallel tool execution |

Run-local memoization coalesces duplicate queries and reads. It never survives
between trials. HTTP connections are pooled between trials. HTTP/2 is an
explicit switch, and the negotiated protocol is recorded. Search and fetch
use separate pacing clocks for DeepSeek's account quotas. There are no hidden
retries; errors and timeouts are part of the measurement.

| Search variant | Evidence returned to the agent |
|---|---|
| `deepseek-content` | Results with inline page content |
| `deepseek-snippets` | Result snippets; page reading requires fetch |
| `exa-lite`, `exa-auto` | Search results and highlights; Exa Contents reads pages |
| `tavily-fast`, `tavily-ultra-fast` | Search content snippets; Tavily Extract reads pages |

Provider-side retrieval handles page access. Blocked content, alternate sources
and fetch failures remain visible in the trace. There is no local browser or
CAPTCHA handling in this experiment.

## Metrics and interpretation

Each trial stores the question, complete answer, model/tool transcript,
retrieved evidence, request durations and statuses, reported model identifier,
raw usage, normalized tokens, and request costs. It records time to the first
usable search result, first text of the accepted final answer, and full
completion. Planning text and thinking blocks do not count as answer text.

Input tokens **include** cached input; output tokens **include** reasoning.
Do not add either subset a second time. A missing usage component is `null`,
with separately named known-token subtotals. A failed or truncated model call
still contributes its reported usage and estimated charge. A timeout can leave
usage and billing unknown.

Token cost is estimated as:

```text
((input - cached_input) × input_rate
 + cached_input × cache_rate
 + output × output_rate) / 1,000,000
```

Rates are USD per million tokens, dated in the experiment record. An absent
cache counter is priced at the uncached rate; the normalized cache count stays
unknown. DeepSeek search/fetch uses its documented per-successful-request
charge. Exa's reported `costDollars` is retained. Tavily credits are recorded
without inventing a dollar conversion. The optional DeepSeek answer control
retains tokens but leaves model dollar cost unknown because its rates vary by
time. Consequently an incomplete total is a known lower bound, never “free”.

Reports include per-configuration sample counts, failures, successful latency
mean/median/standard deviation/maximum, first-answer latency, mean cost per
attempt, and all token components. p95 is withheld until there are twenty
successful observations in that configuration. Failure costs remain in cost
totals even though unsuccessful trials are excluded from latency summaries.

Mean confidence intervals use 2,000 bootstrap draws of **whole question
clusters**, keeping their repetitions together. At least two distinct
questions are required. The first selected model/search/strategy is the paired
baseline. Candidate differences are paired by question and repetition;
unpaired or failed observations are counted explicitly. Latency, cost and token
delta intervals are saved in JSON. Negative deltas favor the candidate. Wilson
success intervals are nominal binomial diagnostics; clustered repetitions can
violate their independence assumption.

The bundled six-case set is a screening corpus covering documentation,
comparison, freshness, multi-hop history, Turkish sources and an invented
product. Use `--cases PATH` for a JSON array of `{id, question}` records;
optional `answer_terms` is an array of acceptable-alias arrays. Keyword coverage,
source diversity, available page content and citation-ID validity are useful
diagnostics. They do **not** measure factual correctness or citation entailment;
both remain unscored. Successful execution does not imply a correct answer.
No Google baseline is measured, so these results cannot establish Google parity.

Order is seeded and shuffled; the full configuration, dated price table,
platform, interpreter, HTTP library version, corpus hash and harness source
hash are retained. Compare within an experiment: providers may change caches,
rankings, load and prices between experiments. The first trial may include
connection setup. Small pilot intervals should not be read as production SLOs.

## Files

The default directory is ignored `.local-evaluation/searchbench`. Every sweep
uses a unique name. JSON and Markdown are checkpointed after every completed
trial, and JSONL is flushed after each trial. The JSON retains evidence for
auditing and supports rebuilding the report without another API call.
Flat `trials.csv`, `requests.csv`, `summary.csv`, and `comparisons.csv` exports
are generated alongside the report. `source.zip` preserves the harness source
used for that experiment.
For standalone PNG/SVG charts, run `python tools/plot_searchbench.py PATH.json`
with matplotlib installed. This reads saved results and makes no API calls.

## Provider references, checked 20 October 2026

- [DeepSeek Search and Fetch](https://api-docs.deepseek.com/guides/search/): endpoints, billing, query syntax and quotas.
- [Mercury models](https://docs.inceptionlabs.ai/get-started/models): IDs, launch prices and reasoning controls.
- [Mercury streaming API](https://docs.inceptionlabs.ai/api-reference/chat/create-a-chat-completion): streaming, usage and tool calls.
- [Ministral 3 14B](https://docs.mistral.ai/models/ministral-3-14b-25-12), [Ministral 3 8B](https://docs.mistral.ai/models/ministral-3-8b-25-12), [Mistral Large 4](https://docs.mistral.ai/models/mistral-large): pinned IDs and prices.
- [Mistral reasoning](https://docs.mistral.ai/studio/conversations/reasoning): Large 4 uses `none` for the latency experiment.
- [Exa Search](https://exa.ai/docs/reference/search): Lite, Auto, highlights and reported costs.
- [Tavily Search](https://docs.tavily.com/documentation/api-reference/endpoint/search): latency variants, snippets and credit usage.
