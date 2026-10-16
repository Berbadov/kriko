"""Conservative, category-neutral matching for measurable requirements.

This module only interprets an explicit numeric constraint when both sides
name compatible units. Anything ambiguous stays unknown; ordinary positive
text is left to the caller's existing lexical matcher.
"""

from __future__ import annotations

import re
from decimal import Decimal, DecimalException, InvalidOperation


# Unit aliases map to a dimension and a multiplier to its base unit. Keeping
# this physical-unit vocabulary here avoids assumptions about product kinds.
_UNITS: dict[str, tuple[str, Decimal]] = {}


def _unit(dimension: str, factor: str, *names: str) -> None:
    value = Decimal(factor)
    for name in names:
        _UNITS[name.casefold()] = (dimension, value)


_unit("length", "0.001", "mm", "millimeter", "millimeters", "millimetre", "millimetres")
_unit("length", "0.01", "cm", "centimeter", "centimeters", "centimetre", "centimetres")
_unit("length", "1", "m", "meter", "meters", "metre", "metres")
_unit("length", "1000", "km", "kilometer", "kilometers", "kilometre", "kilometres")
_unit("length", "0.0254", "in", "inch", "inches", '"')
_unit("length", "0.3048", "ft", "foot", "feet")
_unit("mass", "0.001", "mg", "milligram", "milligrams")
_unit("mass", "1", "g", "gram", "grams")
_unit("mass", "1000", "kg", "kilogram", "kilograms")
_unit("mass", "453.59237", "lb", "lbs", "pound", "pounds")
_unit("mass", "28.349523125", "oz", "ounce", "ounces")
_unit("time", "1", "s", "sec", "second", "seconds")
_unit("time", "60", "min", "minute", "minutes")
_unit("time", "3600", "h", "hr", "hour", "hours")
_unit("time", "86400", "d", "day", "days")
_unit("time", "604800", "wk", "week", "weeks")
_unit("volume", "1", "ml", "milliliter", "milliliters", "millilitre", "millilitres")
_unit("volume", "1000", "l", "liter", "liters", "litre", "litres")
_unit("volume", "0.001", "ul", "microliter", "microliters", "microlitre", "microlitres")
_unit("power", "1", "w", "watt", "watts")
_unit("power", "1000", "kw", "kilowatt", "kilowatts")
_unit("voltage", "1", "v", "volt", "volts")
_unit("voltage", "0.001", "mv", "millivolt", "millivolts")
_unit("current", "1", "a", "amp", "amps", "ampere", "amperes")
_unit("current", "0.001", "ma", "milliamp", "milliamps", "milliampere", "milliamperes")
_unit("frequency", "1", "hz", "hertz")
_unit("frequency", "1000", "khz", "kilohertz")
_unit("frequency", "1000000", "mhz", "megahertz")
_unit("data", "1", "b", "byte", "bytes")
_unit("data", "1000", "kb", "kilobyte", "kilobytes")
_unit("data", "1000000", "mb", "megabyte", "megabytes")
_unit("data", "1000000000", "gb", "gigabyte", "gigabytes")
_unit("data", "1000000000000", "tb", "terabyte", "terabytes")

_NUMBER = r"(?:\d+(?:[.,]\d+)?|[.,]\d+)"
_NUMBER_WITH_UNIT = re.compile(r"(?P<value>" + _NUMBER + r")\s*(?P<unit>[a-zA-Zµμ°]+|\")", re.I)
_SIGNED_NUMBER = re.compile(r"(?<![A-Za-z0-9_])[+-]\s*\d")
_NUMERIC_CUE = re.compile(r"\d|[<>≤≥=]|\b(?:under|below|above|over|between|from|at\s+least|at\s+most|no\s+more\s+than|no\s+less\s+than|less\s+than|more\s+than|up\s+to|minimum|maximum)\b", re.I)
_NEGATION = re.compile(r"\b(?:not|no(?!\s+(?:more|less)\s+than)|never|without|isn't|aren't|doesn't|don't|cannot|can't|won't|non[- ]\w+)\b", re.I)
_OPERATOR = re.compile(
    r"(?P<between>\bbetween\s+|\bfrom\s+)"
    r"(?P<low>" + _NUMBER + r")\s*(?P<unit1>[a-zA-Zµμ°]+|\")?\s+"
    r"(?:and|to|through)\s+(?P<high>" + _NUMBER + r")\s*(?P<unit2>[a-zA-Zµμ°]+|\")?"
    r"|(?P<symbol><=|>=|[<>≤≥])\s*(?P<symbol_value>" + _NUMBER + r")\s*(?P<symbol_unit>[a-zA-Zµμ°]+|\")?"
    r"|(?P<words>\b(?:under|below|less\s+than|fewer\s+than|at\s+most|no\s+more\s+than|up\s+to|maximum(?:\s+of)?|max(?:imum)?\s*:?|over|above|more\s+than|greater\s+than|at\s+least|no\s+less\s+than|minimum(?:\s+of)?|min(?:imum)?\s*:?)\b)\s*"
    r"(?P<word_value>" + _NUMBER + r")\s*(?P<word_unit>[a-zA-Zµμ°]+|\")?",
    re.I,
)
_UNIT_TOKEN = re.compile(r"\b(?:" + "|".join(sorted(map(re.escape, _UNITS), key=len, reverse=True)) + r")\b", re.I)
_WORD = re.compile(r"[a-z]+", re.I)


def _decimal(raw: object) -> Decimal | None:
    # A comma may be a decimal or a thousands separator. Without a locale, do
    # not silently turn (for example) 1,200 into the wrong magnitude.
    text = str(raw).strip()
    if "," in text:
        return None
    try:
        value = Decimal(text)
        return value if value.is_finite() else None
    except (InvalidOperation, ValueError):
        return None


def _unit_info(raw: str | None) -> tuple[str, Decimal] | None:
    if not raw:
        return None
    # SI prefix case can change the scale. Unknown mega/milli forms must not
    # inherit a different unit through case folding; likewise bits != bytes.
    symbol_case = {"mv": {"mv", "mV"}, "ma": {"ma", "mA"},
                   "khz": {"khz", "kHz"}, "mhz": {"mhz", "MHz"}}
    folded = raw.casefold()
    if folded in symbol_case and raw not in symbol_case[folded]:
        return None
    if folded in {"b", "kb", "mb", "gb", "tb"} and raw.endswith("b") and raw != folded:
        return None
    return _UNITS.get(folded)


def _unknown() -> dict[str, str]:
    return {"status": "unknown", "evidence": "", "source": ""}


def _field_tokens(phrase: str, match: re.Match[str]) -> set[str]:
    # Remove the operator/value and unit, leaving only a possible field name.
    left = phrase[:match.start()]
    right = phrase[match.end():]
    text = f"{left} {right}"
    text = re.sub(r"\b(?:under|below|less|fewer|than|at|most|no|more|up|to|over|above|greater|least|minimum|maximum|min|max|between|from|and|through)\b", " ", text, flags=re.I)
    text = _UNIT_TOKEN.sub(" ", text)
    tokens = {token.casefold() for token in _WORD.findall(text)}
    return tokens - {"a", "an", "the", "is", "of", "for", "with", "on", "in", "to", "my", "your", "product"}


def _fact_number(fact: dict) -> tuple[Decimal, tuple[str, Decimal]] | None:
    if fact.get("identity"):
        return None
    raw_value = fact.get("value")
    value = _decimal(raw_value)
    unit_name = str(fact.get("unit") or "").strip()
    # Unit is schema metadata. Do not mine a numeric-looking model/value text.
    unit = _unit_info(unit_name)
    if value is None or unit is None:
        return None
    return value, unit


def evaluate_requirement(phrase: str, facts: list[dict]) -> dict[str, str] | None:
    """Treat unusable numeric evidence as unknown, including arithmetic overflow."""
    try:
        return _evaluate_requirement(phrase, facts)
    except DecimalException:
        return _unknown()


def _evaluate_requirement(phrase: str, facts: list[dict]) -> dict[str, str] | None:
    """Return a structured evaluation, or ``None`` for safe text fallback.

    Numeric/operator and negated phrases are always consumed here, even when
    unsupported, so the caller cannot accidentally mark them met by word
    overlap. Evidence is returned only for one unambiguous matching fact.
    """
    phrase = str(phrase or "").strip()
    if not _NUMERIC_CUE.search(phrase) and not _NEGATION.search(phrase):
        return None
    if _NEGATION.search(phrase):
        return _unknown()
    if _SIGNED_NUMBER.search(phrase):
        return _unknown()
    match = _OPERATOR.search(phrase)
    if match and len(re.findall(_NUMBER, phrase)) != (2 if match.group("between") else 1):
        return _unknown()
    if not match:
        # A bare measurement such as "18V" is an exact-value requirement.
        # Require one explicit, recognized unit and a single compatible fact.
        exact = _NUMBER_WITH_UNIT.search(phrase)
        if not exact or len(re.findall(_NUMBER, phrase)) != 1:
            return _unknown()
        exact_value = _decimal(exact.group("value"))
        exact_unit = _unit_info(exact.group("unit"))
        if exact_value is None or exact_unit is None:
            return _unknown()
        exact_target = exact_value * exact_unit[1]
        exact_fields = _field_tokens(phrase, exact)
        exact_candidates: list[tuple[dict, Decimal]] = []
        for fact in facts:
            parsed = _fact_number(fact)
            if not parsed:
                continue
            fact_value, (fact_dimension, fact_factor) = parsed
            if fact_dimension != exact_unit[0]:
                continue
            key_tokens = {token.casefold() for token in _WORD.findall(str(fact.get("key") or ""))}
            if exact_fields and not exact_fields <= key_tokens:
                continue
            exact_candidates.append((fact, fact_value * fact_factor))
        if len(exact_candidates) != 1 or exact_candidates[0][1] != exact_target:
            return _unknown()
        fact, _ = exact_candidates[0]
        return {"status": "met", "evidence": str(fact.get("text") or ""),
                "source": str(fact.get("source") or "")}

    operator: str
    query_dimension: str
    values: list[Decimal]
    if match.group("between"):
        low = _decimal(match.group("low"))
        high = _decimal(match.group("high"))
        first_unit = match.group("unit1")
        second_unit = match.group("unit2")
        if not first_unit:
            first_unit = second_unit
        if not second_unit:
            second_unit = first_unit
        query_unit = _unit_info(first_unit)
        high_unit = _unit_info(second_unit)
        if low is None or high is None or not query_unit or not high_unit or query_unit[0] != high_unit[0]:
            return _unknown()
        lower = low * query_unit[1]
        upper = high * high_unit[1]
        if lower > upper:
            return _unknown()
        operator = "range"
        query_dimension = query_unit[0]
        values = [lower, upper]
    else:
        raw_value = match.group("symbol_value") or match.group("word_value")
        raw_unit = match.group("symbol_unit") or match.group("word_unit")
        value = _decimal(raw_value)
        query_unit = _unit_info(raw_unit)
        if value is None or not query_unit:
            return _unknown()
        operator_text = (match.group("symbol") or match.group("words") or "").casefold()
        if operator_text in {"<", "under", "below", "less than", "fewer than"}:
            operator = "<"
        elif operator_text in {"<=", "≤", "at most", "no more than", "up to", "maximum", "maximum of", "max", "max:", "max :"}:
            operator = "<="
        elif operator_text in {">", "over", "above", "more than", "greater than"}:
            operator = ">"
        elif operator_text in {">=", "≥", "at least", "no less than", "minimum", "minimum of", "min", "min:", "min :"}:
            operator = ">="
        else:
            return _unknown()
        query_dimension = query_unit[0]
        values = [value * query_unit[1]]

    field_tokens = _field_tokens(phrase, match)
    candidates: list[tuple[dict, Decimal]] = []
    for fact in facts:
        parsed = _fact_number(fact)
        if not parsed:
            continue
        fact_value, (fact_dimension, fact_factor) = parsed
        if fact_dimension != query_dimension:
            continue
        key_tokens = {token.casefold() for token in _WORD.findall(str(fact.get("key") or ""))}
        if field_tokens and not field_tokens <= key_tokens:
            continue
        candidates.append((fact, fact_value * fact_factor))

    # Without a field name, only a single compatible measurement is safe.
    if len(candidates) != 1:
        return _unknown()
    fact, actual = candidates[0]
    if operator == "<":
        met = actual < values[0]
    elif operator == "<=":
        met = actual <= values[0]
    elif operator == ">":
        met = actual > values[0]
    elif operator == ">=":
        met = actual >= values[0]
    else:
        met = values[0] <= actual <= values[1]
    if not met:
        return _unknown()
    return {"status": "met", "evidence": str(fact.get("text") or ""),
            "source": str(fact.get("source") or "")}
