"""Does this claim apply, given what the reader could actually tell us?

One evaluator handles every gate a pack can declare: usage thresholds and
ceilings, age floors, production-window checks, equipment requirements,
maintenance intervals, and configuration-compatibility checks. They are
never really different mechanisms — each asks whether a claim applies to a
particular reading of a particular product.

The design point worth stating: **the answer has three states, not two.**

    met      the condition holds — the claim applies, at full rank
    unmet    the condition demonstrably fails — the claim is not served
    unknown  the reader could not supply the value

`unknown` is the interesting one, and getting it wrong is how a knowledge engine
starts lying. If a listing omits a usage figure a claim is gated on, that claim
is neither true nor false for this particular one. Hiding it loses a real risk;
showing it at full confidence invents certainty. So it is served and downranked
by the condition's `weight` — the fail-open rule from CLAUDE.md's automation
principle, made mechanical.
"""

import re
from dataclasses import dataclass

_NUMERIC = re.compile(r"^[+-]?[\d\s,.]*\d$")

#: A grouped integer in either convention: 1,395 or 1.395 or 1.234.567.
_THOUSANDS = re.compile(r"\d{1,3}(?:[.,]\d{3})+")


def _unseparate(text: str) -> str:
    """Rewrite a locale-formatted number into one `float()` can read.

    Scraped values arrive in whichever convention the listing used, and the
    ambiguity is not resolvable in general: `1.500` is fifteen hundred to a
    Turkish or German listing and one and a half to an American one. Two rules
    cover every case this app reads, and neither needs to know the page's
    locale:

      * with both separators present, the **rightmost** one is the decimal
        point and the other is grouping — `1.234,56` and `1,234.56` both give
        `1234.56`;
      * a lone separator is a decimal point **unless** it groups (once with
        exactly three digits after it, or more than once) — so `150,5` is
        `150.5` while `150.000` is `150000` and `1,395` is `1395`.

    A leading zero disables the grouping rule, because `0.125` is a decimal in
    every convention and `0125` is a number nobody writes.

    Before this, the second branch was a duplicate of the first: `150,5`
    parsed as `1505.0` and quietly satisfied an `lte`/`gte` gate, which is the
    worst kind of wrong answer here — a figure the reader never saw.
    """
    sign = ""
    body = text
    if body[:1] in ("+", "-"):
        sign, body = body[0], body[1:]
    if "," in body and "." in body:
        decimal = "," if body.rfind(",") > body.rfind(".") else "."
        grouping = "." if decimal == "," else ","
        return sign + body.replace(grouping, "").replace(decimal, ".")
    decimal = "," if "," in body else "."
    if decimal not in body:
        return sign + body
    leading = body.split(decimal, 1)[0]
    if body.count(decimal) > 1 or (
            _THOUSANDS.fullmatch(body) and leading.lstrip("0") != ""):
        return sign + body.replace(decimal, "")
    return sign + body.replace(decimal, ".")


@dataclass(frozen=True)
class Condition:
    key: str
    op: str
    value_num: float | None = None
    value_text: str = ""
    on_missing: str = "open"     # open | closed | ignore
    weight: float = 1.0


@dataclass(frozen=True)
class Outcome:
    state: str        # met | unmet | unknown
    served: bool      # may this claim still be shown?
    weight: float     # rank multiplier to apply
    reason: str       # human-readable, so why_shown can explain the downrank


OPERATORS = frozenset({
    "gte", "lte", "eq", "neq", "in", "has", "interval",
    # `mentions` and `not_mentions` take a comma-separated list and mean
    # "any of" / "none of". `not_mentions` is what expresses the
    # maintenance rule that made this whole table necessary: an interval item
    # is due *unless the listing proves otherwise*, so the claim applies
    # precisely when the description does NOT mention the work being done.
    # Absence of a description therefore means the claim applies — which is
    # why its on_missing must be `open`, not `closed`.
    "mentions", "not_mentions",
})


def _number(value) -> float | None:
    """Parse a scraped value into a number, or None if it genuinely is not one.

    Adapters pull values out of page text, so '150.000 km' and ' 150,000 ' both
    arrive. Returning None rather than 0 matters: a failed parse must read as
    *unknown*, never as a very low reading that quietly satisfies an `lte`.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text or not _NUMERIC.match(text):
        return None
    try:
        return float(_unseparate(text.replace(" ", "").replace("\u00a0", "")))
    except ValueError:
        return None


def _collection(value) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        return [str(v).strip().casefold() for v in value]
    return [part.strip().casefold() for part in str(value).split(",") if part.strip()]


def _missing(cond: Condition) -> Outcome:
    """What to do when the reader could not supply this condition's value."""
    if cond.on_missing == "closed":
        return Outcome("unknown", False, 1.0,
                       f"{cond.key} not stated, and this claim requires it")
    if cond.on_missing == "ignore":
        return Outcome("unknown", True, 1.0, f"{cond.key} not stated (not required)")
    return Outcome("unknown", True, cond.weight,
                   f"{cond.key} not stated in the listing — shown, ranked lower")


def evaluate(cond: Condition, context: dict) -> Outcome:
    if cond.op not in OPERATORS:
        raise ValueError(
            f"unknown operator {cond.op!r} on condition for {cond.key!r}; "
            f"expected one of {sorted(OPERATORS)}")

    if cond.key not in context or context[cond.key] in (None, ""):
        return _missing(cond)

    given = context[cond.key]

    if cond.op in {"gte", "lte", "interval"}:
        number = _number(given)
        if number is None:
            return _missing(cond)
        target = cond.value_num or 0.0
        if cond.op == "gte":
            held = number >= target
        elif cond.op == "lte":
            held = number <= target
        else:
            # An interval is due once the first service point is passed, and at
            # every multiple after — not only at exactly one reading.
            held = target > 0 and number >= target
    elif cond.op == "eq":
        held = str(given).strip().casefold() == cond.value_text.strip().casefold()
    elif cond.op == "neq":
        held = str(given).strip().casefold() != cond.value_text.strip().casefold()
    elif cond.op == "in":
        held = str(given).strip().casefold() in _collection(cond.value_text)
    elif cond.op == "has":
        held = cond.value_text.strip().casefold() in _collection(given)
    elif cond.op == "mentions":
        haystack = str(given).casefold()
        held = any(n in haystack for n in _collection(cond.value_text))
    else:  # not_mentions
        haystack = str(given).casefold()
        held = not any(n in haystack for n in _collection(cond.value_text))

    if held:
        return Outcome("met", True, 1.0, f"{cond.key} {cond.op} matches this listing")
    return Outcome("unmet", False, 1.0,
                   f"{cond.key} {cond.op} does not match this listing")


def evaluate_all(conditions, context: dict) -> tuple[bool, float, list[Outcome]]:
    """Evaluate every condition. Returns (served, rank multiplier, outcomes).

    Conditions are conjunctive — one unmet gate withdraws the claim. Weights of
    *unknown* conditions multiply, so a claim resting on two unstated values
    ranks below one resting on a single unstated value. Certainty compounds in
    both directions.
    """
    served = True
    weight = 1.0
    outcomes = []
    for cond in conditions:
        out = evaluate(cond, context)
        outcomes.append(out)
        if not out.served:
            served = False
        weight *= out.weight
    return served, weight, outcomes
