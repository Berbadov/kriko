"""Cheap quote selection before asking a small model to generate a claim.

This catches explicit code exclusions and sibling-only sentences. It does
not claim to prove semantic entailment; the benchmark measures that separately.
"""

import re

from . import identity, triage


# Closed language cues, not a product/category vocabulary. These guards only
# reject explicit absence and descriptive fitment/measurements; they cannot
# establish entailment. Non-English and indirect phrasing remain benchmarked.
_ADVERSE = re.compile(r"\b(?:fail\w*|fault\w*|fractur\w*|crack\w*|break\w*|broken|"
                      r"leak\w*|seep\w*|melt\w*|overheat\w*|seiz\w*|shudder\w*|"
                      r"noise|defect\w*|hazard\w*|risk\w*|damage\w*)\b", re.I)


def eligible(quote: str, task: str, spec_names=()) -> bool:
    targets = identity.codes(task)
    quoted = identity.codes(quote)
    if any(re.search(r"\b" + re.escape(name) + r"\s*(?:is\b|:|=)\s*\d", quote, re.I)
           for name in spec_names):
        return False
    if targets and not any(identity.contains(quote, code) for code in targets):
        return False
    if re.search(r"\b(?:code|identifier)\s+(?:unknown|unspecified|missing)\b", identity.product_line(task), re.I) and not re.search(r"\ball (?:configurations|variants|units)\b", quote, re.I):
        return False
    years = set(re.findall(r"\b(?:19|20)\d{2}\b", identity.product_line(task)))
    # Dates in publication metadata are not fitment ranges. Only explicit
    # applicability language permits rejecting a quote on its year range.
    if years and re.search(r"\b(?:affects?|built|build years?|model years?)\b", quote, re.I):
        for start, end in re.findall(r"\b((?:19|20)\d{2})\s*(?:through|to|[-–])\s*((?:19|20)\d{2})\b", quote, re.I):
            if all(not int(start) <= int(year) <= int(end) for year in years):
                return False
    if re.search(r"\bno (?:(?:other|known|documented|reported|service) )*"
                 r"(?:faults?|failures?|service reports?|technical specifications?)\b", quote, re.I):
        return False
    if re.search(r"\bnot (?:a |the )?fault of\b", quote, re.I):
        return False
    if not _ADVERSE.search(quote):
        if re.search(r"\b(?:compatible with|fits?|fitment|designed for|intended for)\b", quote, re.I):
            return False
        if re.search(r"\b\d+(?:\.\d+)?\s*(?:[kmgt]?b|[kmgt]?hz|[km]?w|v|a|kg|g|mm|cm|ml|l)\b", quote, re.I):
            return False
    mentions_target = any(identity.contains(quote, code) for code in targets) or any(
        re.search(r"\b" + year + r"\b", quote) for year in years)
    if mentions_target and re.search(r"\b(?:exclud\w*|withdraw\w*|incorrect\w*|erroneous\w*|does not (?:affect|apply to))\b", quote, re.I):
        return False
    for target in targets:
        escaped = re.escape(target)
        if re.search(r"(?:exclud\w*|withdraw\w*|does not (?:affect|apply to))\s+"
                     + escaped + r"(?![\w./-])", quote, re.IGNORECASE):
            return False
        # Same spelling structure and a different digit/suffix is evidence
        # of a nearby identifier, not evidence for the requested identifier.
        stem = re.sub(r"\d+", "#", target)
        compact = re.sub(r"\W", "", target)
        sibling = any(re.sub(r"\d+", "#", code) == stem or
                      (len(compact) >= 4 and (compact.startswith(re.sub(r"\W", "", code))
                       or re.sub(r"\W", "", code).startswith(compact))) for code in quoted)
        if sibling and not identity.contains(quote, target):
            return False
    return True


def quotes(text: str, task: str, limit: int = 48, *, spec_names=()) -> list[str]:
    options = list(dict.fromkeys(part.strip() for part in
        re.split(r"(?<=[.!?])\s+|\n+", text)
        if 25 <= len(part.strip()) <= 600 and eligible(part.strip(), task, spec_names)))
    anchors = identity.codes(task)
    wanted = triage._words(identity.product_line(task))
    options.sort(key=lambda quote: (
        -sum(identity.contains(quote, code) for code in anchors),
        -len(triage._words(quote) & wanted)))
    return options[:limit]
