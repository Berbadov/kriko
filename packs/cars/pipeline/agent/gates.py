"""Agent write gates — the product principle, enforced instead of requested.

The researcher agent's contract (`packs/cars/pipeline/agent/kriko_research.md`) tells it
what deserves an evidence row: config-specific, predictable from the ad,
high-consequence. That is a *prompt*, and a prompt is a request. Everything a
prompt asks for and nothing checks is something a model eventually does not do
— and Kriko's whole cost model depends on cheap subscription models doing the
research, i.e. exactly the models least able to hold a long contract in mind.

So the same rules run here, on the server, at write time:

  * generic dashboard-warning-light items, and anything a standard TR
    *ekspertiz* already catches (fluids, pads, compression, injector benches)
    — the product principle's explicit "do not surface" list;
  * DTC-code litanies and filler with no concrete failure mode;
  * quotes that are not in the document they cite (`server.add_evidence`).

Everything reuses `packs/cars/pipeline/stoplists.py`, so the agent path, the LLM
extraction path and the verdict gate all judge value by the same rules — a
second copy of "what counts as generic" is how the two paths drift apart.

Rejections are hard (nothing is written, the agent is told exactly why, in
words it can act on). Warnings are advisory and ride along in the response:
a single low-trust source is not a lie, it is just weak corroboration, and
failing open with a visible gap beats guessing (CLAUDE.md automation
principle).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from packs.cars.pipeline.sources.tiers import resolve_tier
from packs.cars.pipeline.stoplists import (
    AMBIGUOUS_INSPECTION_TERMS,
    GENERIC_MAINTENANCE_TERMS,
    INSPECTION_COVERED,
    WARNING_LIGHT_PATTERNS,
    has_specificity_signal,
    is_blocked_source_domain,
    title_has_dtc_code,
    title_is_verbose,
)

# A rationale shorter than this is not an explanation, it is a restated title.
# Set from the shortest genuinely useful rationale in the current catalog.
MIN_RATIONALE_CHARS = 60

# Tiers whose evidence, standing alone, should not read as corroborated fact.
WEAK_TIERS = frozenset({"seo_blog", "forum_ugc"})


@dataclass
class GateResult:
    rejections: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.rejections

    def as_dict(self) -> dict:
        return {"rejections": self.rejections, "warnings": self.warnings}


def _hit(text: str, needles) -> str | None:
    low = text.lower()
    return next((n for n in needles if n in low), None)


def check_evidence(title: str, rationale: str = "", inspection_advice: str = "",
                   component_hint: str | None = None,
                   source_url: str = "") -> GateResult:
    """Should this evidence row exist? Deterministic answer, with reasons.

    The specificity escape valve matters as much as the stoplists: "oil
    consumption" is both the routine dipstick check every used car needs AND
    the EA211 piston-ring chronic Kriko exists to surface. What separates them
    is whether the text names a code, a displacement+fuel-tech label or a
    mileage figure — so ambiguous terms only reject when nothing specific
    accompanies them (the same rule `stoplists` documents for the LLM gates).
    """
    res = GateResult()
    title = (title or "").strip()
    rationale = (rationale or "").strip()
    blob = f"{title} {rationale}".strip()
    specific = has_specificity_signal(blob) or bool(component_hint)

    if not title:
        res.rejections.append("title is empty — an evidence row must name a "
                              "concrete failure mode")
        return res

    if title_is_verbose(title):
        res.rejections.append(
            f"title is {len(title)} chars — it should be a brief phrase naming "
            f"the failure and the code, not a sentence")

    if title_has_dtc_code(title):
        res.rejections.append(
            "title leads with a DTC code — a buyer cannot act on a fault-code "
            "litany. Name the failure in words; put codes in inspection_advice")

    for pattern in WARNING_LIGHT_PATTERNS:
        if pattern.search(title) and not has_specificity_signal(title):
            res.rejections.append(
                "generic dashboard-warning-light item — true of any car, and "
                "the product principle drops these outright")
            break

    # Inspection-covered terms are judged on the TITLE, and only when the title
    # itself carries no config anchor. Scanning the rationale rejects real
    # chronics for describing their own mechanism ("clutch debris contaminates
    # the DQ381 mechatronics" mentions clutch wear because that is the failure
    # path), and "clutch wear" on a dual-clutch box is precisely what the
    # ekspertiz does NOT catch — the code in the title is what separates them.
    recall = "recall" in blob.lower()   # an official recall is authoritative,
    # not routine wear, even when it names a part the inspector also looks at.
    if not recall and not has_specificity_signal(title) \
            and (hit := _hit(title, INSPECTION_COVERED)):
        res.rejections.append(
            f"{hit!r} is routine pre-purchase inspection ground — the buyer "
            f"already pays an ekspertiz for it, so it is noise, not signal. "
            f"If this is config-specific (a dual-clutch box, a known weak "
            f"point), say which unit in the title")

    if not specific:
        if (hit := _hit(blob, GENERIC_MAINTENANCE_TERMS)):
            res.rejections.append(
                f"{hit!r} is generic used-car advice with nothing config-"
                f"specific attached (no engine/gearbox code, no mileage)")
        elif (hit := _hit(blob, AMBIGUOUS_INSPECTION_TERMS)):
            res.rejections.append(
                f"{hit!r} needs a config or mileage anchor to be a Kriko claim "
                f"— name the engine code or the mileage it starts at, or drop it")

    if len(rationale) < MIN_RATIONALE_CHARS:
        res.rejections.append(
            f"rationale is {len(rationale)} chars — write 2–3 plain sentences a "
            f"non-mechanic can act on (min {MIN_RATIONALE_CHARS})")

    if not specific:
        res.rejections.append(
            "nothing ties this to a specific config: no engine/gearbox code, no "
            "displacement+fuel label, no mileage figure, no component_hint. "
            "Kriko only surfaces what is specific to *this* car")

    if not inspection_advice.strip():
        res.warnings.append(
            "no inspection_advice — the buyer is told what to fear but not what "
            "to check at viewing")

    if source_url:
        tier, trust = resolve_tier(source_url)
        if tier in WEAK_TIERS:
            res.warnings.append(
                f"source tier {tier!r} (trust {trust}) — on its own this is a "
                f"report, not a corroborated chronic; find a second, better "
                f"source before treating it as established")

    return res


def check_document(url: str, raw_text: str, target_hint: str = "",
                   existing_for_target: int = 0,
                   max_per_target: int = 5) -> GateResult:
    """Should this source document be admitted to the ledger?

    Two rules the prompt used to carry alone: the per-part research budget (a
    cap the agent was asked to honour and could simply not) and the blocked
    source list (forums and spec content farms — `stoplists` documents why
    each class is untrustworthy).
    """
    res = GateResult()
    if not url.strip():
        res.rejections.append("url is required — an uncited document is not evidence")
    if len(raw_text.strip()) < 200:
        res.rejections.append(
            f"raw_text is {len(raw_text.strip())} chars — submit the cleaned "
            f"article text you actually read, not a snippet or a summary")
    if url and is_blocked_source_domain(url):
        res.rejections.append(
            f"{url} is a blocked source (owner forum, complaint board or spec "
            f"content farm) — a single anecdote reads exactly like a chronic "
            f"once extracted, and spec farms state confident wrong mechanicals")
    if target_hint and existing_for_target >= max_per_target:
        res.rejections.append(
            f"research budget for {target_hint!r} is spent ({existing_for_target}"
            f"/{max_per_target} documents). If the chronic is not established by "
            f"now, report the gap instead of adding sources")

    tier, trust = resolve_tier(url)
    if tier in WEAK_TIERS:
        res.warnings.append(f"source tier {tier!r} (trust {trust})")
    return res


# ── Duplication ──────────────────────────────────────────────────────────────
#
# The live catalog shows what happens without this: dq200 carries ~30 claims
# that are the same two chronics rephrased ("DQ200 dry clutch premature wear",
# "DQ200 dry clutch wear causes shudder", "DQ200 clutch pack and flywheel
# premature wear"). A buyer reads eight cards, so thirty near-identical rows
# are not coverage — they are the volume problem at its source (backlog B5).
# Cheap token overlap catches the rephrasings without an LLM call.

# Words that carry no discriminating signal in a claim title.
_STOPWORDS = frozenset({
    "the", "a", "an", "and", "or", "of", "in", "on", "at", "to", "for", "with",
    "from", "by", "is", "are", "can", "may", "causes", "cause", "caused",
    "issue", "issues", "problem", "problems", "failure", "failures", "fault",
    "faults", "premature", "chronic", "high", "low", "km",
})

DUPLICATE_THRESHOLD = 0.7


def _tokens(title: str) -> frozenset[str]:
    words = "".join(c if c.isalnum() else " " for c in title.lower()).split()
    return frozenset(w for w in words if w not in _STOPWORDS and len(w) > 2)


def duplicate_of(title: str, known_titles) -> str | None:
    """The existing claim this title merely rephrases, if there is one.

    Jaccard overlap on significant tokens: `>= DUPLICATE_THRESHOLD` means the
    two titles are made of the same words, which for claim titles means the
    same failure. Deliberately blunt — the cost of a false positive is one
    rejected row with the duplicate named in the message, and the agent can
    rewrite it to say what is actually different.
    """
    new = _tokens(title)
    if not new:
        return None
    best, score = None, 0.0
    for known in known_titles:
        other = _tokens(known)
        if not other:
            continue
        j = len(new & other) / len(new | other)
        if j > score:
            best, score = known, j
    return best if score >= DUPLICATE_THRESHOLD else None
