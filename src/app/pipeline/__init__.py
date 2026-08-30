"""Operator layer — the pipeline drivers that fill a pack with packs.cars.pipeline.

After the knowledge-engine pivot (goal G6) Kriko is four packages, and the
dependency arrows no longer form one column:

    app/       CLI, local web dashboard, MCP server — the interfaces
      |
      v
    kriko/      the engine: pack store, generic lookup, ranking.
      ^         Knows nothing about cars, or about any other category.
      |
    packs/      one directory per product category: data, vocabulary,
      |         trust tiers, a builder, and the coverage report for its
      |         own catalog shape. This is what a third party authors.
      v
    packs/cars/pipeline/  the evidence ledger and grounded extraction — the machinery
                that turns sources into claims a pack can ship.

    app/pipeline/        this package: ledger_run, remediate, panel, process.
                Drives the pipeline. Sits above packs/cars/pipeline/ and packs/,
                and is the only place allowed to reach into both.

app/pipeline/ may import from packs/cars/pipeline/ and packs/. Neither may import from app/pipeline/, and
nothing at all may import from app/. `kriko/` imports none of them — that is
the load-bearing invariant of the pivot, because the moment the engine knows
what a car is, adding a category stops being a data-only change.

All four rules are enforced mechanically in app/pipeline/tests/test_repo_invariants.py.

Function-local imports still appear here (app/pipeline/process.py defers the extraction
stack). Those are deliberate — they keep CLI startup cheap — and are not cycle
workarounds. The tell is direction: a deferred import pointing *downward* is a
cost decision, one pointing *upward* was a cycle being dodged. There are no
upward ones left.
"""
