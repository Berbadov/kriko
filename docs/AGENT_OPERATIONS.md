# Agent operations — the words, the caveats, the open questions

Written 2026-09-14 from a working conversation, so it is a **note, not a
design**. Nothing here is implemented except where it says so. It exists
because these ideas are easy to lose and expensive to rediscover.

The premise, in the reader's words: *"the data operations by agents are the
strong side of the app; in a pre-LLM era this app wouldn't exist."* Everything
below follows from taking that seriously.

## 1. Naming: an **operation**

One unit of agent-driven work on the knowledge — named, planned, costed, and
recorded. Kinds, all of which already exist in some form:

| Operation | What it does | Today |
|---|---|---|
| `research` | Grow one subject's claims from sources | implemented (three planes) |
| `agenda` | A batch of `research`, ordered by what is weakest | implemented |
| `author` | Write a whole pack for a category | implemented |
| `recheck` | Ask whether a cited page still says it | implemented (`app/factcheck.py`) |
| `adapt` | Author or repair a site adapter | B115, not implemented |

"Operation" rather than "job": a job is the *row* that makes long work
durable, and one operation may be many jobs or none. Prefer "the research
operation" over "the agent" (see `docs/GLOSSARY.md` — "agent" already means
three things).

## 2. Where an operation is watched

Settled in this conversation: **the terminal is for you, the app is for the
operations.** Opening Claude Code yourself in Kriko's terminal panel and doing
knowledge work through the MCP server is a *feature*, not a workaround — it
keeps your own workflow intact and it is the door that already exists.

What is missing is the other half: the app must show those MCP operations **as
they happen** — what arrived, what was asked, what was answered, what was
refused and why. Today an MCP submission is visible only afterwards, in
`submissions`. Filed as **B122**.

Note what this implies: the live view is not about the harness plane. It is
about *any* door, including the one where the agent is you.

## 3. Protocols — the thing with no name yet

The danger is two-sided and the middle is narrow:

* **Burning tokens.** Re-sending context, oversized batches, re-reading what
  was already read.
* **Hallucinating from a context pile.** A model handed too much at once stops
  quoting and starts composing — which this codebase catches at the grounding
  gate, so the cost is a refused batch and the tokens are still spent.

A **protocol** is how one operation spends one model: context window per call,
batch size, what is re-sent, what is summarised, when to stop. It is a property
of *the model*, not of the operation — "qwen3.5 27b holds together under ~80k
at this batch size; opus 4.6 takes Z at that one" is a ratio, and the ratio is
what a picker needs.

So: **an algorithm that picks the protocol from measured ratios**, per model.
Built (B123, 0.8.5) as `kriko.research.Spend` — the shape, in the engine, three
numbers: a name, characters of a document per call, documents per call — and
`app/protocols.py`, the picker, which reads this installation's own `bench_runs`
and returns `STANDARD` whenever it cannot justify anything else. Two rules keep
it honest: a protocol is never promoted on fewer than two runs, and it is
compared against the *default measured on the same model*, never against
nothing. The paid plane batches accordingly, and a batched extraction checks
each quote against the text of the URL the model named — the attribution slip a
batch makes possible.

The benchmark (B111, 0.8.5) is the input the picker cannot invent: `kriko bench`,
`POST /api/bench`, cases derived from the installed store rather than
enumerated, every run against a throwaway copy of the knowledge.

Search providers are the same shape: Exa is implemented, Tavily and the others
are not, and the choice between them belongs to the protocol rather than to a
hardcoded call site.

## 4. The suspicion worth testing

*"Code agent harnesses do not like to be used as functions; otherwise we would
fix it easily."*

This is a real hypothesis and it has a cheap test. A coding-agent CLI is built
for a person in a loop: it wants a terminal, it carries the reader's whole
configuration, it decides when it is finished, and it answers in prose it was
free to shape. Kriko asks it to be a function — one prompt in, one JSON object
out, no configuration, no follow-up questions. Every defect this plane has had
is that mismatch: the variadic `--allowedTools` swallowing the prompt, the
reader's own MCP servers loading from their home directory, an envelope shape
that differed between builds, OAuth that only a human can complete.

The instrument is built (B124, 0.8.5) and **the experiment has not been run** —
it needs a real CLI, a real subscription and a machine the reader owns.
`bench.verdict()` reports, per plane, how many runs failed and *how*: `auth`
(only a human can log in), `start` (not where a launcher's PATH says), `shape`
(answered in prose the caller could not read), `timeout` (kept working past a
ceiling a function needs), `limit`, `other`.

How to read it: failures spread across classes mean the plane was unlucky.
Failures concentrated in one class mean the plane is being **mis-used**, and
that is the hypothesis confirmed — the harness is a door for a person (§2) and
the unattended path belongs to the API plane with a protocol (§3).

Run it with `kriko bench --cases 5`, or from the app.

## 5. Known compromises

* Documents are kept but nothing surfaces them (`regrounded()` has no caller).
* The retention bound is 5000 rows, not bytes.
* Refused findings keep no document — the cases most worth inspecting.
* **The harness plane has never been run end-to-end against a real `claude`.**
  The gates use fake CLIs plus one free flag check, and §4's experiment is
  unrun. Everything this file says about the harness plane's behaviour is
  therefore a hypothesis with an instrument attached, not a finding.
* The benchmark has no screen in the app; it is `kriko bench` and
  `GET /api/bench`.
* `narrow` and `wide` are two settings of one dial. A model whose real limit is
  somewhere else needs a third row in `protocols.CATALOGUE` — and the evidence
  for adding it is a measurement, not a preference.
