"""Apply a pack's vocabulary of claims that are not worth surfacing.

The engine supplies the rule shape, not the judgement. A pack declares its
literal terms and regular expressions in ``gate_terms``; this module only
loads and evaluates those rows. Missing vocabulary fails open.
"""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class GateVocabulary:
    covered: frozenset[str] = frozenset()
    generic: frozenset[str] = frozenset()
    ambiguous: frozenset[str] = frozenset()
    noise_patterns: tuple[re.Pattern, ...] = ()
    specificity_patterns: tuple[re.Pattern, ...] = ()


def _compile(patterns) -> tuple[re.Pattern, ...]:
    compiled = []
    for pattern in patterns:
        try:
            compiled.append(re.compile(pattern, re.IGNORECASE))
        except re.error:
            # A malformed optional rule must not disable the other gates.
            continue
    return tuple(compiled)


def vocabulary_from_rows(rows: dict[str, list[str]]) -> GateVocabulary:
    """Build a vocabulary from raw {kind: [pattern]} rows.

    ``load_gates`` reads those rows from an installed store; a pack's offline
    pipeline has only the YAML it will later ship. Both end up here, so the
    compilation and the fail-open behaviour cannot diverge.
    """
    def literals(kind: str) -> frozenset[str]:
        return frozenset(p.casefold() for p in rows.get(kind, ()))

    return GateVocabulary(
        covered=literals("covered"),
        generic=literals("generic"),
        ambiguous=literals("ambiguous"),
        noise_patterns=_compile(rows.get("noise", ())),
        specificity_patterns=_compile(rows.get("specificity", ())),
    )


def load_gates(conn, pack_id: str) -> GateVocabulary:
    """Load one pack's gate rows, returning an empty vocabulary if absent."""
    rows: dict[str, list[str]] = {}
    for row in conn.execute(
        "SELECT kind, pattern FROM gate_terms WHERE pack_id = ?", (pack_id,)
    ):
        rows.setdefault(row["kind"], []).append(row["pattern"])

    return vocabulary_from_rows(rows)


def is_specific(text: str, vocab: GateVocabulary) -> bool:
    """Return whether a pack-declared pattern anchors text to a configuration."""
    return any(pattern.search(text) for pattern in vocab.specificity_patterns)


def gate_reason(text: str, vocab: GateVocabulary) -> str | None:
    """Return the rejecting rule name, or ``None`` when the claim is kept."""
    text = text or ""
    lowered = text.casefold()
    if any(term in lowered for term in vocab.covered):
        return "covered"
    if any(term in lowered for term in vocab.generic):
        return "generic"
    if any(pattern.search(text) for pattern in vocab.noise_patterns):
        return "noise"
    if any(term in lowered for term in vocab.ambiguous) and not is_specific(
        text, vocab
    ):
        return "ambiguous"
    return None
