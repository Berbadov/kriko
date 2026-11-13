# How Kriko works

This page explains four things: how a page finds its catalog, how a catalog
grows, what a check does, and where Kriko keeps its files.

## How a page finds its catalog

A page becomes a set of identity keys. An identity key is a pair such as
`make=Toyota`. Kriko never matches on the title of a listing.

1. A site adapter reads the page.
2. Kriko converts the values to the words of the catalog.
3. Kriko compares the keys with every product of the catalog.

The answer has one of four results.

| Result | Meaning |
|---|---|
| **Recognised** | The page and one product agree on every key. Kriko serves the problems of that product. |
| **One of several** | Every key fits more than one product. Kriko serves only what those products share, and it lists them. |
| **Probably** | The nearest product is close, but not exact. Kriko serves its problems and marks the answer as a question. |
| **Not recognised** | No product is close. Kriko names the nearest product and the key that disagrees. |

The catalog holds its own limits (`match_floor` and `match_probable` in its
`gates.yaml`). Kriko does not hide a failure. The route
`POST /api/diagnose/identity` returns the full comparison, and the panel shows
a short form of it.

## How a catalog grows

1. You name a product category.
2. An agent studies the category and proposes a draft.
3. Kriko writes the draft to disk. The draft contains data only.
4. You read the draft, then install it, extend it, or discard it.

An agent cannot put executable code in a draft. Kriko writes every draft file,
and the file names are fixed.

A quick look is also raw material for a catalog. A quick look already carries
its sources and its quotations. When its product is missing from the catalog,
Kriko files the quick look and keeps the sources.

When Kriko assigns a saved quick look to a catalog, its history keeps the
decision method, the evidence used, and the selected catalog's version and
content digest. An uncertain decision keeps the reason and the leading
candidates, so a later reader can see why it abstained. The MCP operations
`list_catalogs` and `classify_product` expose the same installed catalog
definitions and configured classification path to an agent.

The default classifier is the agent selected in **Agents**: a coding agent,
local model or API agent. When deterministic checks abstain, that agent reads
the saved product facts and installed catalog definitions and proposes a
category with exact evidence phrases. Kriko validates the installed catalog
id, title scope, confidence and quoted phrases before accepting it. This path
works for Quick Looks, recategorization and bulk filing without a TypeSafe key.
Unavailable agents leave the product uncategorized for retry or manual choice.
Already assigned products do not start another classification call during filing.

An MCP agent can also classify directly. An uncertain `classify_product` result
includes `agent_request` with the classification prompt and output schema. The
calling agent evaluates it and calls `classify_product` again with `decision`;
the same local evidence checks apply without starting a nested agent process.

Jev from TypeSafe is an optional alternative in **Settings → Research**. The
deterministic checks run first; Jev is called only when those checks abstain
and the reader explicitly selects it. The call sends the product title, saved
Quick Look facts, and the complete installed catalog roster to TypeSafe. It
does not search the web. The pinned model is `jev-1.14.0`; it returns a Choice
and a probability for every option. Kriko abstains if the full roster exceeds
the API's 255-option limit (including the uncertain option), if the response
is malformed or below the configured probability and confidence thresholds,
or if local title-scope and evidence checks fail. Those gates do not make a
model decision infallible: the reader can inspect its evidence and catalog
revision in the saved history.

This is a paid API call when used. Only input tokens are charged by TypeSafe;
the audit records token usage and an estimate when the response reports usage.
The API key is stored in the local key file, and the request sends it as a
Bearer token. See TypeSafe's [API reference](https://docs.typesafe.ai/api),
[Choice guide](https://docs.typesafe.ai/primitives/choice),
[model list](https://docs.typesafe.ai/models), and
[confidence guide](https://docs.typesafe.ai/confidence).

## What a check does

A check has four stages.

| Stage | Work |
|---|---|
| Discovery | Plan the searches and collect the pages. |
| Extraction | Read each page and copy each quotation. |
| Ingestion | Prove each quotation in its page, then apply the bar of the catalog. |
| Ledgering | Write down what Kriko refused, and the reason. |

Kriko refuses a quotation that is not in the page that the agent read. Kriko
refuses a figure with no source. Every refusal names the correction.

The refusals matter. Without them, a check that keeps nothing looks the same as
a check that keeps everything.

### The evidence gate: does the page say what the claim says?

The quote check proves a sentence is on a page. It cannot prove the claim is
what the sentence says, and the failure that matters sounds perfectly sourced:
the page says the part is available, the report says it is not, and the real
sentence is quoted under it. Every mechanical check passes.

So a claim that has a quote on its page is also read against that page by a
small entailment model — a cross-encoder trained for natural language
inference, premise = the quote widened to its passage in the page text,
hypothesis = the claim's title and body. It is asked in exactly one place,
`app.categorypack.ground`, which both an agent's "Add to a pack" and a job's
harvest reach, and again in `app.findings.accept_findings` for a research run's
findings. It decides three ways:

| Verdict | Decision | What happens |
|---|---|---|
| entailment, score at or above the threshold | **accept** | The claim enters the catalog, with the verdict and score kept on its evidence. |
| contradiction | **drop** | The claim does not enter, and the run says its source says the opposite. |
| neutral, or a weak entailment | **flag** | The claim is held out of the catalog and named in the run's log, the submit verdicts and the coverage report, so an automated retry or the agent can find a source that says it plainly. |

A held claim is not a claim waiting for a person. It is a gap with a reason,
and the submit answer tells the agent to re-source it — the same shape as a
quote that is not on its page.

The gate is **off** unless it is configured, and off is the ordinary case: the
desktop installer carries no model. With no `nli` extra, with
`KRIKO_NLI_MODEL=off`, or with a checkpoint that will not load, every claim
passes through unchanged and is marked `nli: unchecked`. Extraction never waits
on it.

| Variable | Meaning |
|---|---|
| `KRIKO_NLI_MODEL` | The checkpoint to load, or `off`. Empty means `cross-encoder/nli-deberta-v3-small`. |
| `KRIKO_NLI_ACCEPT` | The entailment probability a claim needs to enter. Default `0.70`. |

To turn it on, install the optional extra and set the variable:

```bash
pip install "kriko[nli]"
set KRIKO_NLI_MODEL=cross-encoder/nli-deberta-v3-small
```

The model's own label order is read from its config, never assumed: a
checkpoint that names its head in another order, or is not three-way NLI, is
refused rather than guessed at.

A check stops at its cost limit and keeps the work that it finished. A stopped
check is not a failure.

## Where Kriko keeps its files

| Path | Contents | Survives the removal of a catalog |
|---|---|---|
| `~/.kriko/knowledge.sqlite` | The catalogs: products, problems, sources | The rows of that catalog do not |
| `~/.kriko/app.sqlite` | Your history, your settings, and the saved pages | Yes |
| `~/.kriko/models.toml` | The price of each model. You can edit this file. | Yes |
| `~/.kriko/drafts/` | The drafts of agents, before an install | Yes |
| `~/.kriko/env` | The research keys from the Settings screen | Yes |
| `~/.kriko/extension/` | The prepared browser extension | Yes |

Kriko uses two databases on purpose. The removal of a catalog cannot remove
your history, and your history cannot change the digest of a catalog. The
route `/api/health` reports both files.

## Read more

- [Install Kriko on Windows](INSTALL_WINDOWS.md)
- [Use Kriko](USAGE.md)
- [The architecture](ARCHITECTURE.md)

## Later: AMIPS retrieval

*Not built, and not to be built yet. A note for whoever revisits lookup.*

A catalog holds a few thousand keys, and exact search over them is already
faster and more explainable than any index. AMIPS (Apple's approximate
nearest-neighbour work, `github.com/apple/ml-amips`) is worth revisiting at
roughly 100k+ keys and not before. The shape it would take then: a small net
as a query rewriter in front of FAISS IVF, or a SupportNet router over
clusters; retrained offline on each catalog refresh, never a fine-tuned LLM.
