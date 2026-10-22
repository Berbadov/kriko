"""Engine tuning: real questions, answered by the reader's own stack, graded by another.

*"tuning engine, set of real cases answered by preferred llm and search
provider, assessed by an other independent agent."*

A change to the brief, the mode rules or the ranking is a claim that answers
got better. This package is how that claim is tested instead of felt:

* `cases`    the questions: the benchmark corpus and, only when the reader opts
             a conversation in, questions proposed from saved chats.
* `agents`   who answers (the *preferred* agent and search provider, read from
             Settings) and who grades (never the same agent).
* `answer`   one case through the real chat turn, in a throwaway app state.
* `evidence` the pages the answer cites, fetched again, and whether links open.
* `grade`    the independent grader, which sees the question, the rubric, the
             final answer text and the fetched evidence, and never the
             answerer's reasoning or identity.
* `failures` automatic classes of failure, counted in every report.
* `run`      the sweep and its ledger; `report` the plain sortable HTML;
             `compare` the paired differences between two runs.

Nothing here spends an agent unasked: `cli` prints the plan and the cost, and
stops until the reader presses with `--yes`.
"""
