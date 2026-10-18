"""The model benchmark: which model, reached which way, costs what and lies how.

This replaces a benchmark that keyed every measurement by **plane** — harness,
agent, api, local. A plane is the application's plumbing. The reader's question
is narrower and more useful than that, and it is the question the phone will
ask: *given the same brief and the same documents, which model finds the right
facts, how many tokens did it burn to do it, and how often did it invent
something?*

So the unit here is a **candidate**: one model, reached one way, with the
settings that reach it. `local:qwen3.5:4b` — a 4B model on this machine through
Ollama — and `harness:mistral-vibe@glm-5-3` — GLM-5.3 behind the Mistral CLI —
are two candidates. They are comparable *by construction*, because everything
else is held identical:

* one **corpus** (`corpus.py`), versioned, and the same on every machine;
* one **brief**, byte-identical for every candidate (`corpus.prompt`), including
  the documents — no candidate gets to search, and none gets more context;
* one **scorer** (`metrics.py`), mechanical and deterministic, never a model
  grading a model.

What is *not* held identical is deliberate and reported: a harness CLI brings
its own system prompt, its own tool belt and its own token accounting, and a
local model brings its own context window. Those differences are the finding,
not a confound to hide — so every row carries the model, the harness, the
finish reason and whether the token count was *reported* or *estimated*.

Three properties are non-negotiable, each because its absence made the old
benchmark unusable:

**A failure is a measurement.** A candidate that cannot start, times out or
refuses is the thing this exists to discover. It becomes a row with an `error`,
it stays in the denominator of the failure rate, and it is never silently
dropped from a mean.

**Tokens are never invented.** A count is `reported` (the endpoint sent a usage
block), `estimated` (nothing did, and the estimate is labelled as one) or
absent. A partial count is never allowed to read as a full one, because "tokens
per correct answer" is the number the model choice turns on.

**Nothing is graded by a model.** `metrics.py` compares against an answer key
with string and span tests. A model asked to score another model's output
agrees with it far too often to be evidence.
"""
