"""Cars' ingest: the engine's ledger ingest with this pack's source policy.

Ingest — inserting documents, backfilling evidence, flagging rows out of
clustering — is generic and lives in ``kriko.ledger.ingest``. What is car
policy is *which* sources are untrustworthy, *which* language is foreign to
this pack's market, and *which* claim key this pack's cached candidates use
for the engine/variant hint — those arrive as injected predicates/mappers.
"""

from pathlib import Path

from kriko.ledger.ingest import (  # noqa: F401 — re-exported
    backfill_claims_dir,
    ingest_document,
)
from kriko.ledger import ingest as _engine
from packs.cars.pipeline.stoplists import is_blocked_source_domain, is_german_text


def _map_cached_claim(claim: dict) -> dict:
    """Cars' cached candidates name the hint in this pack's own vocabulary."""
    mapped = dict(claim)
    mapped["component_hint"] = claim.get("engine_or_variant_hint")
    return mapped


def backfill_cache_dir(conn, cache_dir: Path) -> tuple[int, int]:
    """Backfill from extraction-cache JSON, remapping this pack's hint key."""
    return _engine.backfill_cache_dir(conn, cache_dir, claim_mapper=_map_cached_claim)


def flag_blocked_sources(conn) -> int:
    """Flag evidence whose source document is on cars' blocked-domain list."""
    return _engine.flag_blocked_sources(
        conn, is_blocked_source_domain=is_blocked_source_domain
    )


def flag_foreign_language(conn) -> int:
    """Flag evidence written in a language outside this pack's market."""
    return _engine.flag_foreign_language(conn, is_foreign_language=is_german_text)
