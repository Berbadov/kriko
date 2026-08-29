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
    # Text that waives every other gate outright — an official recall is
    # authoritative even when it names a part an inspection also covers.
    exempt: frozenset[str] = frozenset()
    noise_patterns: tuple[re.Pattern, ...] = ()
    specificity_patterns: tuple[re.Pattern, ...] = ()
    # Structural limits the pack declares. Zero means "not declared": the
    # engine has no opinion about how long a good title is, only about the
    # shape of the rule.
    max_title_chars: int = 0
    min_rationale_chars: int = 0


def _compile(patterns) -> tuple[re.Pattern, ...]:
    compiled = []
    for pattern in patterns:
        try:
            compiled.append(re.compile(pattern, re.IGNORECASE))
        except re.error:
            # A malformed optional rule must not disable the other gates.
            continue
    return tuple(compiled)


def vocabulary_from_rows(
    rows: dict[str, list[str]],
    limits: dict[str, str] | None = None,
) -> GateVocabulary:
    """Build a vocabulary from raw {kind: [pattern]} rows.

    ``load_gates`` reads those rows from an installed store; a pack's offline
    pipeline has only the YAML it will later ship. Both end up here, so the
    compilation and the fail-open behaviour cannot diverge.

    ``limits`` carries the numeric declarations, which ride in gate_terms as
    kind='limits' with the value in the note column. An unparseable or absent
    limit becomes 0, which means "not declared" and gates nothing.
    """
    def literals(kind: str) -> frozenset[str]:
        return frozenset(p.casefold() for p in rows.get(kind, ()))

    def limit(name: str) -> int:
        try:
            return int((limits or {}).get(name, 0))
        except (TypeError, ValueError):
            return 0

    return GateVocabulary(
        covered=literals("covered"),
        generic=literals("generic"),
        ambiguous=literals("ambiguous"),
        exempt=literals("exempt"),
        noise_patterns=_compile(rows.get("noise", ())),
        specificity_patterns=_compile(rows.get("specificity", ())),
        max_title_chars=limit("max_title_chars"),
        min_rationale_chars=limit("min_rationale_chars"),
    )


def load_gates(conn, pack_id: str) -> GateVocabulary:
    """Load one pack's gate rows, returning an empty vocabulary if absent."""
    rows: dict[str, list[str]] = {}
    limits: dict[str, str] = {}
    for row in conn.execute(
        "SELECT kind, pattern, note FROM gate_terms WHERE pack_id = ?", (pack_id,)
    ):
        if row["kind"] == "limits":
            limits[row["pattern"]] = row["note"]
        else:
            rows.setdefault(row["kind"], []).append(row["pattern"])
    return vocabulary_from_rows(rows, limits)


def structural_reasons(
    title: str,
    rationale: str,
    vocab: GateVocabulary,
    *,
    has_anchor: bool = False,
) -> list[str]:
    """Rejections that are about a claim's shape rather than its vocabulary.

    Every rule here is generic — a title should be a phrase, a rationale
    should explain, a claim should be tied to something specific. What each
    means numerically is the pack's declaration, and an undeclared limit is
    not checked at all.

    ``has_anchor`` lets a caller assert specificity the text cannot show, such
    as a component identifier carried in a separate field.
    """
    title = (title or "").strip()
    rationale = (rationale or "").strip()
    reasons: list[str] = []

    if not title:
        return ["title is empty — a claim must name a concrete failure mode"]

    if vocab.max_title_chars and len(title) > vocab.max_title_chars:
        reasons.append(
            f"title is {len(title)} chars — it should be a brief phrase naming "
            f"the failure, not a sentence (max {vocab.max_title_chars})"
        )

    if vocab.min_rationale_chars and len(rationale) < vocab.min_rationale_chars:
        reasons.append(
            f"rationale is {len(rationale)} chars — write 2–3 plain sentences a "
            f"non-expert can act on (min {vocab.min_rationale_chars})"
        )

    if vocab.specificity_patterns and not has_anchor:
        if not is_specific(f"{title} {rationale}", vocab):
            reasons.append(
                "nothing ties this to a specific configuration — name the "
                "identifier, specification or usage figure it applies to"
            )

    return reasons


def is_specific(text: str, vocab: GateVocabulary) -> bool:
    """Return whether a pack-declared pattern anchors text to a configuration."""
    return any(pattern.search(text) for pattern in vocab.specificity_patterns)


def gate_reason(
    text: str, vocab: GateVocabulary, *, subject: str | None = None
) -> str | None:
    """Return the rejecting rule name, or ``None`` when the claim is kept.

    ``subject`` is the part of the claim that names what it is *about* — a
    title, typically — as distinct from ``text``, which is everything the
    claim says, including a rationale that may mention routine-inspection
    vocabulary while explaining a specific failure's mechanism ("clutch
    debris contaminates the mechatronics" says "clutch" without being a
    routine clutch-wear claim). ``covered`` only judges what the claim is
    about, so it reads ``subject``; ``generic``, ``noise`` and ``ambiguous``
    read the full ``text``. When a caller has no natural subject/text split,
    omitting ``subject`` makes every rule read the same string — ``covered``
    and ``generic`` still keep their specificity escapes either way, so this
    is not simply the pre-split behaviour, just a coarser subject.

    ``exempt`` waives ``covered`` alone — an official recall is authoritative
    even when it names a part an inspection also covers, but that says
    nothing about a warning-light title or generic filler riding along with
    it, so ``noise``/``generic``/``ambiguous`` still apply.
    """
    text = text or ""
    subject = text if subject is None else (subject or "")
    lowered = text.casefold()
    exempt = any(term in lowered for term in vocab.exempt)

    if (
        not exempt
        and any(term in subject.casefold() for term in vocab.covered)
        and not is_specific(subject, vocab)
    ):
        return "covered"
    if any(term in lowered for term in vocab.generic) and not is_specific(text, vocab):
        return "generic"
    if any(pattern.search(text) for pattern in vocab.noise_patterns):
        return "noise"
    if any(term in lowered for term in vocab.ambiguous) and not is_specific(
        text, vocab
    ):
        return "ambiguous"
    return None
