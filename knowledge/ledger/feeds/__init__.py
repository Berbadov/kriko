"""Structured feeds (spec §2.2 stage 2): near-zero-token corroboration.

Each ingester fetches a public structured source (recall registries, MOT
statistics) and writes `documents` rows with source_type='structured' plus
pre-structured evidence rows — no extraction LLM. Structured corroboration
raises testimony-derived claims to `verified` at export (see
export.disposition), and recall evidence seeds the highest-value claim class:
config-specific, high-consequence, predictable from the listing.

Feeds are fetched per catalog model (never hand-enumerated make/model lists —
the catalog drives coverage). A feed that has no data for a model simply
ingests nothing.
"""
