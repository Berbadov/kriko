"""The agent benchmark: what an agent does with evidence, graded by tests.

*"We need a testing mechanism for the agents. Benchmark reports aren't
adequate. They should be like Terminal-Bench, but for our purpose."*

Terminal-Bench is a set of **tasks**, each with an environment, an instruction
and a test that decides pass or fail, run end to end by the agent under test,
reported as a resolve rate per agent with the trajectories kept. This is that,
for the one thing Kriko asks of an agent: *given a product, what is known to go
wrong with this specific one?*

* **A task** (`suite.json`) is a listing, the fixed web behind it, the app
  settings it runs under, and an answer key: what a competent run delivers,
  what it must not deliver, and how it must behave.
* **The environment is hermetic.** `web.FakeWeb` replaces the search service and
  the page reader for the run, so the same pages come back to every agent on
  every machine, and a run cannot be lost to a search engine having a bad day.
  The thing under test is the real quick-look job (`tasks.quick_look`): real
  settings resolution, real queries, real pages handed to the real CLI, real
  grounding. Only the web is fixed.
* **The tests are deterministic** (`checks`). Quote on the page, claim matches
  the key, forbidden claim absent, abstains when it should, injection ignored,
  language right, and the app's settings obeyed. No model judges a model.
* **The report is a resolve rate** (`report`): per agent, per task and per
  check, with consistency over repeated runs (pass^k), because the same agent
  on the same task giving different answers is the failure the reader meets.

**Nothing here spends an agent unasked.** The simulated agents (`simulated`)
are scripted: they exercise the real code path for free, and they are how the
checks themselves are tested, since a grader nobody has watched fail is not a
grader. A real agent runs only when it is named and `--yes` is given.

The CLIs that can be graded are the ones Kriko reads pages for
(`harness.HOST_READ_HARNESSES`) and the local model. An agent that browses with
its own tools sees the real web, which no fixture can replace.
"""
