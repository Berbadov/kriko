"""Operator layer — the pipeline drivers that fill a pack with knowledge.

After the knowledge-engine pivot (goal G6) Kriko is four packages, and the
dependency arrows no longer form one column:

    apps/       CLI, local web dashboard, MCP server — the interfaces
      |
      v
    kriko/      the engine: pack store, generic lookup, ranking.
      ^         Knows nothing about cars, or about any other category.
      |
    packs/      one directory per product category: data, vocabulary,
      |         trust tiers, a builder, and the coverage report for its
      |         own catalog shape. This is what a third party authors.
      v
    knowledge/  the evidence ledger and grounded extraction — the machinery
                that turns sources into claims a pack can ship.

    ops/        this package: ledger_run, remediate, panel, process.
                Drives the pipeline. Sits above knowledge/ and packs/,
                and is the only place allowed to reach into both.

ops/ may import from knowledge/ and packs/. Neither may import from ops/, and
nothing at all may import from apps/. `kriko/` imports none of them — that is
the load-bearing invariant of the pivot, because the moment the engine knows
what a car is, adding a category stops being a data-only change.

All four rules are enforced mechanically in ops/tests/test_repo_invariants.py.

Function-local imports still appear here (ops/process.py defers the extraction
stack). Those are deliberate — they keep CLI startup cheap — and are not cycle
workarounds. The tell is direction: a deferred import pointing *downward* is a
cost decision, one pointing *upward* was a cycle being dodged. There are no
upward ones left.
"""
