"""How deep to go, as one dial rather than twenty knobs.

"Fifteen sources burn far more tokens than three. That decision belongs to me,
per run." It already did, technically — `max_documents`, `budget_usd`,
`context_chars`, `batch_size` and the preamble were all settable. That is
exactly the problem: five numbers with no relationship anybody could see, and
no answer to the only question actually being asked, which is *what will this
cost me*.

So: four names, each a bundle, each with an estimate attached.

**The presets are shapes, not tuning.** `quick` is a look, `deep` is a proper
read; the numbers below are the *relationship* between them — a Deep run reads
about five times what a Quick one does — and they are starting values the
reader is expected to move. Which is why `custom` exists and why the underlying
knobs stay reachable: a dial that hides the machine from somebody who wants it
is a dial they route around.

**The estimate comes from measurement, never from a price list.** `app/costs.py`
already refuses to invent a number where nothing has been measured, and this
inherits that refusal: a Deep estimate on an installation that has never run
one says so rather than multiplying a guess. An estimate is a promise about
somebody's money, and one the app cannot keep is worse than none.

**The ceiling is the honest half.** A cap that truncates silently, or crashes,
teaches the reader that the number does nothing. Hitting it stops the run
cleanly, keeps everything gathered so far (`Progress.partial`), and says what
was skipped — so the reader ends up with a small pack and an explanation rather
than a failure.
"""

from dataclasses import dataclass, replace

#: The per-run cost cap when the reader has not set one, in dollars. Roughly a
#: Deep run and change: high enough that the ordinary case never meets it, low
#: enough that a run gone wrong stops before it is a story. A proposal — the
#: reader's own number belongs in settings, and 0 means no cap at all.
DEFAULT_CAP_USD = 3.00

#: Where the reader is warned on the way up. Not one threshold, because the
#: difference between "this is going to be expensive" and "this is about to
#: stop" is the difference between a decision and a notification.
WARN_AT = (0.5, 0.8)


@dataclass(frozen=True)
class Preset:
    """One position on the dial, and everything it sets."""

    id: str
    label: str
    #: How many sources a run may read. The knob that dominates both cost and
    #: quality, which is why it is the one the labels are written around.
    max_documents: int
    #: Characters of each document handed to the model. Deeper reads more of
    #: each page, not just more pages — a Deep run that still truncated every
    #: source at a Quick run's length would cost more for the same blindness.
    context_chars: int
    #: Documents per completion call. Larger batches cost fewer tokens overall
    #: and make grounding harder, so the cheap end batches and the careful end
    #: does not.
    batch_size: int
    #: The per-run ceiling this preset proposes. `0` means "use the reader's
    #: setting", which is the only thing `custom` can honestly say.
    cap_usd: float
    note: str


PRESETS = (
    Preset(
        id="quick", label="Quick", max_documents=3, context_chars=8000,
        batch_size=3, cap_usd=0.30,
        note="Three sources, batched. A look, not a read — enough to find the "
             "loudest problem, not enough to be sure there is only one.",
    ),
    Preset(
        id="standard", label="Standard", max_documents=7, context_chars=12000,
        batch_size=2, cap_usd=1.00,
        note="Seven sources. The default, and what most subjects are worth.",
    ),
    Preset(
        id="deep", label="Deep", max_documents=15, context_chars=20000,
        batch_size=1, cap_usd=3.00,
        note="Fifteen sources, one per call, more of each page read. For a "
             "subject you are actually buying — several times the cost of "
             "Quick, and it should be.",
    ),
    Preset(
        id="custom", label="Custom", max_documents=0, context_chars=0,
        batch_size=0, cap_usd=0.0,
        note="Your own numbers. Nothing here is hidden from you — the presets "
             "above are bundles of exactly these knobs.",
    ),
)

BY_ID = {one.id: one for one in PRESETS}
DEFAULT = "standard"


def preset(name: str) -> Preset:
    """The named preset, or the default. An unknown name is never an error.

    A run started with a scale this version does not know — an older client, a
    stored request, a typo — should run at the default and say so, not refuse.
    """
    return BY_ID.get(str(name or "").strip().lower(), BY_ID[DEFAULT])


def applied(name: str, overrides: dict | None = None) -> dict:
    """The settings a run should use: the preset, with anything explicit winning.

    Custom is not a special case here, and that is the design — it is a preset
    whose numbers are all zero, so every override lands. One code path, so
    "custom" cannot drift into meaning something the dial does not.
    """
    chosen = preset(name)
    overrides = {k: v for k, v in (overrides or {}).items() if v}
    if chosen.id == "custom":
        # Nothing to fall back to but the default's shape, or a custom run with
        # no numbers would read nothing at all.
        chosen = replace(BY_ID[DEFAULT], id="custom", label="Custom")
    return {
        "scale": name if name in BY_ID else DEFAULT,
        "max_documents": int(overrides.get("max_documents") or chosen.max_documents),
        "context_chars": int(overrides.get("context_chars") or chosen.context_chars),
        "batch_size": int(overrides.get("batch_size") or chosen.batch_size),
        "cap_usd": float(overrides.get("cap_usd") or chosen.cap_usd),
    }


def estimate(conn, name: str, *, plane: str = "api") -> dict:
    """What this preset is likely to cost here, scaled from what has been measured.

    The scaling is by source count, because that is what the run's cost is
    mostly linear in and it is the knob the presets differ most on. It is an
    approximation and says so — an estimate that presented itself as arithmetic
    would be the `raised: true` mistake in a new place.

    Returns `usd: None` where nothing has been measured, inherited from
    `costs.estimate` rather than papered over.
    """
    from app import costs

    chosen = preset(name)
    if chosen.id == "custom":
        chosen = replace(BY_ID[DEFAULT], id="custom")
    measured = costs.estimate(conn, plane=plane)
    baseline = BY_ID[DEFAULT].max_documents
    factor = chosen.max_documents / baseline

    usd, tokens = measured.get("usd"), measured.get("tokens")
    return {
        "scale": chosen.id,
        "sources": chosen.max_documents,
        "usd": round(usd * factor, 4) if isinstance(usd, (int, float)) else None,
        "tokens": int(tokens * factor) if isinstance(tokens, (int, float)) else None,
        "basis": measured.get("basis", 0),
        "cap_usd": chosen.cap_usd,
        "note": measured.get("note", ""),
    }


def offered(conn, *, plane: str = "api") -> list[dict]:
    """Every position on the dial with its estimate, for the screen.

    Assembled here rather than in the client so the labels, the numbers and the
    estimate cannot disagree — a preset described in one place and priced in
    another is a preset that eventually lies about itself.
    """
    return [
        {
            "id": one.id,
            "label": one.label,
            "note": one.note,
            "max_documents": one.max_documents,
            "context_chars": one.context_chars,
            "batch_size": one.batch_size,
            **{k: v for k, v in estimate(conn, one.id, plane=plane).items()
               if k in ("usd", "tokens", "basis", "cap_usd")},
        }
        for one in PRESETS
    ]


def over_cap(spent: float, cap: float) -> bool:
    return bool(cap) and spent >= cap


def warning(spent: float, cap: float) -> str:
    """What to say on the way up, or "" while there is nothing to say."""
    if not cap or spent <= 0:
        return ""
    share = spent / cap
    if share >= 1.0:
        return f"stopped at the ${cap:.2f} cap for this run"
    for mark in sorted(WARN_AT, reverse=True):
        if share >= mark:
            return (f"${spent:.2f} of this run's ${cap:.2f} cap "
                    f"({share:.0%})")
    return ""
