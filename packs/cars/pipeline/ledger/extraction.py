"""Cars' extraction: the engine's chunk loop with this pack's policy injected.

Orchestration — chunking, the cache, the budget charge, the evidence insert —
is generic and lives in ``kriko.ledger.extraction``. Three things here are cars
policy: langextract as the extractor, the code-token chunk gate, and the
low-value rules that decide which extracted claims get flagged.

``extract_grounded`` stays a module-level name because app/pipeline's tests
monkeypatch it by dotted path; the extractor resolves it at call time so the
patch is seen.
"""

import functools
from collections.abc import Iterable

import yaml

from kriko.gates import GateVocabulary, gate_reason, vocabulary_from_rows
from kriko.ledger import extraction as _engine
from kriko.ledger.costs import Budget
from packs.cars.pipeline.langextract_client import extract_grounded
from packs.cars.pipeline.ledger.chunking import chunk_has_signal
from packs.cars.pipeline.paths import PACK_ROOT


def _extract(text: str) -> Iterable[dict]:
    """Run langextract, then map its claim shape onto the ledger's.

    Resolved through the module global so a monkeypatched extract_grounded is
    honoured (app/pipeline/tests/test_ledger_run.py patches this dotted path).
    """
    for claim in extract_grounded(text):
        mapped = dict(claim)
        mapped["component_hint"] = claim.get("engine_or_variant_hint")
        yield mapped


@functools.lru_cache(maxsize=1)
def _vocabulary() -> GateVocabulary:
    """Cars' gate vocabulary, read from the rows this pack ships.

    The same vocabulary/gates.yaml that packs/cars/build.py turns into
    gate_terms rows at install time. Reading it directly is what lets the
    offline pipeline and the serving path answer "is this worth surfacing"
    from one source. Cached: the ledger asks once per extracted claim and the
    file does not change inside a run. Fails open — a missing or unreadable
    file gates nothing, per CLAUDE.md's automation principle.
    """
    path = PACK_ROOT / "vocabulary" / "gates.yaml"
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return GateVocabulary()
    rows = {
        kind: [e["pattern"] if isinstance(e, dict) else e for e in (entries or [])]
        for kind, entries in raw.items()
        if isinstance(entries, list)
    }
    return vocabulary_from_rows(rows)


def _low_value_reason(claim: dict) -> str | None:
    text = f"{claim.get('title', '')} {claim.get('rationale', '')}"
    return gate_reason(text, _vocabulary())


def extract_document(conn, doc_id: int, budget: Budget) -> int:
    return _engine.extract_document(
        conn,
        doc_id,
        budget,
        extractor=_extract,
        signal_detector=chunk_has_signal,
        gate_reason=_low_value_reason,
    )


def extract_pending(conn, budget: Budget) -> int:
    return _engine.extract_pending(
        conn,
        budget,
        extractor=_extract,
        signal_detector=chunk_has_signal,
        gate_reason=_low_value_reason,
    )


def pending_extraction_estimate(conn) -> tuple[int, float]:
    return _engine.pending_extraction_estimate(conn, signal_detector=chunk_has_signal)
