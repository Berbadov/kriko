# Configuration accuracy and measurement

The Rust/GPUI desktop owns the benchmark screen. The Python sidecar runs the
experiments and stores their observations; the browser extension recognizes
the page and passes its identity and facts to that engine.

The engineering sequence is identity, evidence, measurement, then inspection.
An apparently grounded answer can still describe another revision, year or
market. Copying a real quote does not establish configuration applicability.

1. Preserve the full listing identifier through recognition, planning and
   retrieval. Match whole codes and rank exact identifiers ahead of general
   product-family matches. Ambiguous primary products remain ambiguous.
2. Give a small local model a bounded selection task. Quick Look can select
   verbatim evidence with the title and explanation tied to that quotation.
   Explicit exclusions, withdrawn statements and missing identifiers reduce
   the eligible evidence. Reserve output space using the runtime's context
   window; fail clearly when a controlled corpus cannot fit.
3. Grade raw proposals before delivery filtering. Measure wrong applicability,
   invented quotations, missed supported facts, exact specification values,
   and correct abstention separately. Record every attempt's wall time and
   reported input/output tokens, including repair and self-check calls.
4. Inspect those errors on Rust's Benchmark screen, together with the measured
   protocol, test version, search provider, token coverage and stage durations.
   Compare historical batches only when their configuration and cases match.

The default Configuration accuracy suite uses ten fictional cases with
fixed documents. It includes revision and suffix collisions, long identifiers,
market and year boundaries, missing fitment, withdrawn notices, distracting
tables, absent evidence and faults of a compatible host mistaken for faults
of the item sold. Requested field names are visible to the model;
expected values and failure labels are held out of its prompt.

Local runs use the local agent with supplied evidence. Hosted runs use direct
completions over those same documents, with an output ceiling and conservative
budget preflight. These are different protocols and are labeled separately.
This measures the resulting systems; it does not isolate intrinsic model
quality. Live web research is a separate suite for local or CLI agents. Its
legacy keys need source auditing and its search results change over time.

Run installed local models against an isolated history from PowerShell:

```powershell
$env:PYTHONPATH = 'src'
.venv/Scripts/python.exe -m app.precisionrun --model <installed-name> --reps 2 --output reports/my-experiment
```

Reports are saved after each attempt. The experiment directory contains its
own settings/history SQLite database and `results.json`; the reader's history
is untouched. Run models sequentially on machines with limited memory.

Unknown prices, absent usage and incomplete totals are not zero-cost results.
The p50/p95 readout includes failed attempts. It reports end-to-end duration,
not time to first token or a controlled GPU throughput measurement. The
independent raw proposals remain available when the delivery parser drops
them, so delivery acceptance cannot conceal benchmark errors.

The eligibility rules are conservative English heuristics, not an entailment
proof. They can lose evidence whose identifier appears only in a heading or
whose applicability is expressed differently. Extractive output keeps the
source language and can select an ordinary specification as a risk. Runtime
schema support is optional: a server may reject it and fall back to plain
completion. The same model's self-check is advisory and can itself be wrong.

The ten cases were used during development. Repeated deterministic answers
are correlated; their intervals are descriptive, not population guarantees.
Before claiming broad product coverage, extend the suite with independently
audited held-out documents, additional languages and new product families,
then collect genuine provider measurements with the installation's keys.
Keep the failure cases and recall loss visible when changing the protocol.
