"""Operator layer — tools that drive and inspect the other two layers.

Kriko is three layers with dependencies flowing one way:

    ops/        this package: hub, mcp, reports, swap, remediate, panel
      |         operates and inspects the layers below
      v
    backend/    sync ETL, api, resolver, db, matcher
      |         ingests the catalog, serves risk to the extension
      v
    knowledge/  catalog, extraction, ledger, parts, sources
                produces the YAML catalog — imports nothing above it

ops/ may import from backend/ and knowledge/. Neither may import from ops/.
Before this package existed the operator tools lived under backend/tools/ and
knowledge/, so knowledge/ had to reach up into backend/ — 11 of those imports
were written inside function bodies to dodge the resulting import cycle.
"""
