# Part compatibility benchmark

The suite checks whether an answer compares the exact supplied PC or vehicle
variants, cites the constraints it uses, and returns `compatible`,
`incompatible`, or `unknown`. Its five fictional cases cover a complete PC
match, a same-socket CPU blocked by BIOS version, a same-family motherboard
with the wrong DDR generation, a vehicle listing missing VIN, engine and market,
and a vehicle fitment match whose OE authenticity and seller evidence remain
unverified.

Expected verdicts are computed from source-backed fixture facts and generic
comparison rules (`equal`, `at_least`, and `member`). The prompt contains the
question and source pages but omits the fact map, comparison operands and
answer key. The grader checks each returned constraint, confirms each
supporting quote against its supplied page, derives the overall verdict, and
requires unknowns when a decisive source fact is absent. A single unverified
forum account cannot establish counterfeit authenticity or a seller rating.

Run the deterministic fixture and grader check offline:

```sh
PYTHONPATH=src python -m app.compatbench verify
```

This validates every fixture quote and comparison, checks the reference
control against the grader, and requires examples of all three verdicts. It
uses no model, key, network, or paid service.

To score a configured API completion model, opt into requests explicitly:

```sh
PYTHONPATH=src python -m app.compatbench run \
  --model gpt-4o-mini --budget-usd 0.02 --yes \
  --out /tmp/compatbench-results.json
```

`CompletionAsker` applies the conservative cost ceiling separately to each
case using the configured model price. `--budget-usd 0` explicitly removes
that ceiling. The CLI requires `--yes` before it calls a model; the command
without it prints the planned case count and exits without a request. Results
include the model's answers, per-case verdict checks, errors, and token/cost
figures only when the provider reports complete usage.

This is a controlled reasoning check over fictional supplied pages. It does
not measure search quality, real-world part databases, or whether the source
pages themselves are true. The mechanical comparator is intentionally
conservative: unknown decisive facts remain unknown, and evidence citations
must be exact spans from the fixture pages.

A local OpenAI-compatible model can run the same cases through
`OpenAICompatSocket`:

```sh
PYTHONPATH=src python -m app.compatbench run \
  --model qwen3.5:4b --local-url http://127.0.0.1:11434/v1 --yes \
  --out /tmp/compatbench-local.json
```

Local rows are labelled `self_hosted`; USD is always null, and input/output
tokens are included only when the server reports complete usage. This path
uses the same prompt and grader as the API runner. No model is contacted by
`verify`, and neither runner is invoked by the benchmark tests.
