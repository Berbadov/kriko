# Four repos against the local quick look

Research note, 21 October 2026. Baseline: 6 of 8 pages read empty, one long quoted query
from a 2B planner, a source-kind label that refuses a correct fault, 30-55 s per look.

## PolyRAG

**What it is.** A modular agentic RAG framework for small models with small context
windows, demoed on MedRxiv. NLM Ingestor and Tika parse documents into a block tree;
Postgres TSVector searches it, no embeddings by default. Agents are LangChain tools over
SQL and that tree, the UI is Streamlit, deployment is Compose plus a Postgres dump.

**Language, licence, weight.** Python, MIT. Needs Postgres, NLM Ingestor, LangChain and
Streamlit: a service, a UI and a database. It cannot be imported into a desktop sidecar,
and taking it would put Postgres on the reader's machine. Not a fit.

**The one idea that maps.** `query_rag(keywords: List[str])` in `src/agents/tools_pg.py`:
the model gives keywords, the database composes the query (`plainto_tsquery`), the
docstring pins granularity with an example, and the tool carries its own budget (`limit`,
`count_only`). The model never writes a query string. Stage: **queries**. It would replace
the free text `_QUERY_ASK` returns and the rewrite in `local_pipeline.run` (strip quotes,
append " forum", then `"{name}" suffix`): the model fills slots and `local_search_plan`,
which already composes part queries from identity facets, composes the string, so quoting
and the angle each get one owner.

**What it would cost or risk.** Nothing to lift: the value is the schema's shape, and its
slots are just keywords. Cost is a prompt change plus a composer that exists. Risk is a
slot filled with a phrase, which the composer must reject.

**Verdict.** Borrow the idea, not the stack. Read:
https://github.com/QuentinFuxa/PolyRAG (README, tree), LICENSE, `src/agents/tools_pg.py`.

## crawl4ai

**What it is.** A Python crawler that turns pages into LLM-ready Markdown: an async
Playwright pool with stealth, three content filters (pruning, BM25, LLM), extraction by
CSS, XPath, regex or LLM, deep crawl with resume, caching, a token-guarded Docker REST
server and an MCP door. The README also sells a hosted cloud.

**Language, licence, weight.** Python, Apache-2.0, with a badge or one-line credit asked
for in the README. Heavy: Playwright plus a browser download, litellm, rank_bm25,
snowballstemmer, so as a dependency it is a second browser and a second process. Kriko
already drives headless Edge (`app/providers/browser.py`); the browser is not the gap.

**The one idea that maps.** `PruningContentFilter` in `crawl4ai/content_filter_strategy.py`
scores each DOM node from text density (0.4), link density (0.2), tag weight (0.2),
class/id (0.1) and log text length (0.1), against a 0.48 threshold; nodes under it are
removed, then what survives is measured. No model, no vocabulary, no host list. Stage:
**scrape**. It would replace `fetch.challenged` (short text plus `politeness.looks_blocked`
words) as the trigger for `fetch._climb`, and the 80-character floor in
`local_agent.MIN_PAGE_CHARS`: a 200-OK page whose prose is a shell is today a miss that
never climbs, while a density score says "shell" in any language and aims the ladder at
those six pages.

**What it would cost or risk.** Ported onto `htmlscan` or `selectolax` the score is about
150 lines and no new dependency. The risk is pruning a real forum post: `to_text` defines
the text a quote is checked against, so a cut post shortens evidence silently.

**Verdict.** Borrow the idea and its metrics, not the dependency. Read:
https://github.com/unclecode/crawl4ai (README), `crawl4ai/content_filter_strategy.py`.

## lightagent

**What it is.** An agent framework: one `LightAgent` with tools, detachable memory
(mem0), tree-of-thought, MCP; `LightSwarm` for role routing; `LightFlow` for fixed DAG
workflows; since v0.10 an event-sourced runtime (sessions, jobs, budgets) and in v0.11
`LightDAG` for task graphs a model proposes at run time. It speaks OpenAI-compatible
endpoints, so Ollama fits. Apache-2.0.

**Language, licence, weight.** Pure Python, pip installable, no service, so in principle
it runs in-process. In practice it would sit above `app/providers/local_agent.py` and
duplicate what Kriko has: jobs as rows (`app/web/jobs.py`), two SQLite files, cooperative
cancel, a spend ceiling. Not a dependency for this codebase.

**The one idea that maps.** LightDAG's rule that a model's answer is a candidate and only
an application-owned verifier can publish it: a Worker returns `TaskOutcome.candidate`, a
`CallableVerifier` (a plain Python callable) returns a report bound to the input snapshot,
only `pass` publishes, and a failed candidate stays staged rather than deleted. Stage:
**verify**. It would replace the veto in `local_pipeline._verify`, where a separate
source-kind call (cached per quote set) returns early with "source passage is X, not
problem" before any mechanical check. Measured: a 4B model wrote correct faults and was
still refused. The borrow: make the model's kind a logged diagnostic, let one
deterministic verifier accept (quote in page, number in quote, identity in quote or URL,
all of which exist), and keep a rejected candidate with its reason instead of dropping it
in `_reject`.

**What it would cost or risk.** No dependency if only the pattern is taken; the change is
one function and removes calls. The risk is false accepts: those checks cover quote,
number and identity but not "an instruction phrased as a fault".

**Verdict.** Borrow the idea, ignore the framework. Read:
https://github.com/wanxingai/lightagent (README), `docs/lightdag.md`.

## WikiChat

**What it is.** A research chatbot that grounds answers in Wikipedia, from Stanford OVAL:
seven stages, each one or more LLM calls. In v2.1 a query stage writes one or more
searches (or None), a generate stage emits claims instead of prose, each passage is
filtered on its own in a batch, a draft with numbered citations follows, and a refine stage
rewrites it against the claims. Retrieval is Qdrant plus an embedding server; LiteLLM
reaches many providers; Chainlit and Cosmos DB cover multi-user.

**Language, licence, weight.** Python 3.11, Apache-2.0. Pixi, Docker for Qdrant and Text
Embedding Inference, Chainlite, LangGraph, Chainlit: server-side, GPU for indexing, so it
does not run inside a desktop app. The transferable part is the prompt files, plain text.

**The one idea that maps.** `pipelines/prompts/generate_split_claims.prompt`, read by
`generate_stage` in `pipelines/chatbot.py`: the model replies with a flat list of
self-contained facts, one per line, no pronouns, each carrying the context needed to be
checked alone, or "None". That is the shape Kriko's extract lacks: it asks for a `title`
and a `why`, then has to judge whether that sentence is a fault, an instruction or praise.
Stage: **extract**. It would replace that pair in `local_pipeline._extract` with one claim
per item; an instruction cannot be restated as a standalone adverse claim without becoming
false, so verification checks one sentence, not a paraphrase.

**What it would cost or risk.** Prompt and schema only, no dependency. But it changes
`quicklook.parse` and every screen that renders a card, and a 2B model drifts from "no
pronouns" unless the example set is short. The `title` + `why` split is also the card's
heading and body, so that mapping comes first.

**Verdict.** Borrow the idea, not the system: a chat product with a vector index, where
Kriko's need is extraction from six pages. Read:
https://github.com/stanford-oval/WikiChat (README), `pipelines/chatbot.py`,
`pipelines/prompts/generate_split_claims.prompt`.

## What to try first

Ranked by expected effect on the measured numbers, not by how interesting the repo is.

1. **Demote the source-kind label (lightagent, LightDAG verifier).** Stage: verify. First
   because the measurement names the gate, not the model: qwen 4B wrote correct faults and
   the pipeline refused them. Experiment: five looks on products already run, with
   `evidence_kind` demoted to a note, then read every newly kept risk and count the
   instructions. Cost: half a day, five local looks, no dependency.

2. **Aim the reader ladder with a density score (crawl4ai).** Stage: scrape. Second
   because six empty pages is the largest raw number, but the ladder measured its ceiling:
   two pages for 28 s, since it triggers on refusals and cannot see a shell. Experiment:
   score the raw HTML of one look's eight URLs, compare "shell" against what the model
   found, then use the score as the climb trigger for five looks. Cost: one to two days.

3. **Claim-first extraction (WikiChat).** Stage: extract. Third because it improves the
   input to 1 and 2 rather than the totals: fewer mislabels means fewer candidates for a
   gate to refuse. Experiment: ten fixed products, one brief, the claim list against
   `title`/`why`, comparing accepted risks, hand-read mislabels and calls per look, which
   should not move. Cost: half a day plus the parse and render change.

What not to do: adopt any of the four. PolyRAG and WikiChat are server stacks with a
database index, crawl4ai is a browser farm, lightagent is a framework. Kriko owns a store
and a reader, and lacks one predicate per stage: three of these four have a good one.
