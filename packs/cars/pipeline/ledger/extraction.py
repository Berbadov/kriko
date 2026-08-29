"""Cars' extraction: the engine's chunk loop with this pack's policy injected.

Orchestration — chunking, the cache, the budget charge, the evidence insert —
is generic and lives in ``kriko.ledger.extraction``. Three things here are cars
policy: langextract as the extractor, the code-token chunk gate, and the
low-value rules that decide which extracted claims get flagged.

``extract_grounded`` stays a module-level name because app/pipeline's tests
monkeypatch it by dotted path; the extractor resolves it at call time so the
patch is seen.
"""

from collections.abc import Iterable

from kriko.ledger import extraction as _engine
from kriko.ledger.costs import Budget
from kriko.ledger.extraction import (  # noqa: F401 — re-exported for callers
    EXTRACTION_MODEL,
    EXTRACTOR_VERSION,
    estimate_chunk_tokens,
)
from packs.cars.pipeline.langextract_client import extract_grounded
from packs.cars.pipeline.ledger.chunking import chunk_has_signal
from packs.cars.pipeline.stoplists import (
    GENERIC_MAINTENANCE_TERMS,
    WARNING_LIGHT_PATTERNS,
    has_specificity_signal,
)


def _extract(text: str) -> Iterable[dict]:
    """Run langextract, then map its claim shape onto the ledger's.

    Resolved through the module global so a monkeypatched extract_grounded is
    honoured (app/pipeline/tests/test_ledger_run.py patches this dotted path).
    """
    for claim in extract_grounded(text):
        mapped = dict(claim)
        mapped["component_hint"] = claim.get("engine_or_variant_hint")
        yield mapped


def _low_value_reason(claim: dict) -> str | None:
    text = f"{claim.get('title', '')} {claim.get('rationale', '')}".lower()
    for pat in WARNING_LIGHT_PATTERNS:
        if pat.search(text):
            return "warning-light pattern"
    hit = next((kw for kw in GENERIC_MAINTENANCE_TERMS if kw in text), None)
    if hit and not has_specificity_signal(text):
        return f"generic maintenance: {hit!r}"
    return None


_POLICY = dict(
    extractor=_extract,
    signal_detector=chunk_has_signal,
    gate_reason=_low_value_reason,
)


def extract_document(conn, doc_id: int, budget: Budget) -> int:
    return _engine.extract_document(conn, doc_id, budget, **_POLICY)


def extract_pending(conn, budget: Budget) -> int:
    return _engine.extract_pending(conn, budget, **_POLICY)


def pending_extraction_estimate(conn) -> tuple[int, float]:
    return _engine.pending_extraction_estimate(conn, signal_detector=chunk_has_signal)
