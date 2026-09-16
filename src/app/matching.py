"""How a page met a pack, in words a person can act on.

`kriko.lookup.score` decides *whether* a page and a subject are the same
product. This decides what the reader is told about it, and the two are
deliberately separate: the engine may not hold an opinion about phrasing, and
an interface may not hold one about matching.

It exists because "no pack recognised this product" is a sentence with no next
move in it. The reader who saw it had a good pack installed, for that exact
product, and no way to find out which of four completely different things had
gone wrong — a pack that was never installed, a page that was misread, a
catalog that spells a value differently, or a genuine gap in coverage. Each
wants a different response, and the panel said the same nine words to all of
them.

So every answer here carries three things: the verdict, *what was weighed*, and
what to do next. A near miss is a question rather than a silence; a real miss
names the closest thing it found and why it was not close enough.
"""

#: The reader-facing reading of each method the engine can return. Keyed by
#: `Resolution.method`, and deliberately not by coverage — coverage says how
#: much is known about the thing, this says how sure we are it *is* the thing,
#: and running them together is how "we have nothing on this car" and "we do
#: not know what car this is" became one message.
VERDICTS = {
    "exact": "recognised",
    "ambiguous": "recognised",
    "probable": "probably",
    "no_match": "unrecognised",
}


def verdict(resolution) -> str:
    return VERDICTS.get(resolution.method, "unrecognised")


def _candidate(one) -> dict:
    return {
        "subject_id": one.subject_id,
        "pack_id": one.pack_id,
        "label": one.label,
        "score": round(one.score, 4),
        "keys": [
            {
                "key": key.key,
                "supplied": key.supplied,
                "held": key.held,
                "score": round(key.score, 4),
                "weight": key.weight,
                "how": key.how,
                "why": key.why,
            }
            for key in one.per_key
        ],
    }


def scoring(resolution) -> dict:
    """The scoring half of a resolution, for any caller that serialises one.

    One function rather than the same four keys written out at each of the
    call sites that already serialise `method` and `flags`. They had drifted
    once before this — `query.py` reported three fields where `analyze.py`
    reported five — and a panel and a report disagreeing about how a match was
    made is a bug nobody can reproduce from either one.
    """
    return {
        "verdict": verdict(resolution),
        "score": round(resolution.score, 4),
        "considered": [_candidate(one) for one in resolution.considered],
    }


def next_step(resolution, coverage: str, url: str = "") -> dict:
    """What the reader can do about this answer. Never an empty hand.

    The `action` words are a closed vocabulary the client renders as buttons;
    the sentence is what it says above them. Both are here rather than in the
    client because they have to agree with the verdict, and a client that
    writes its own copy from a status code writes copy that stops agreeing the
    first time the engine gains a method.
    """
    if resolution.method in {"exact", "ambiguous"}:
        if coverage == "MATCHED_NO_DATA":
            return {
                "action": "research",
                "say": "This one is recognised, but the installed packs hold "
                       "nothing about it yet. That is a gap, not a clean bill "
                       "of health.",
            }
        return {"action": "none", "say": ""}

    if resolution.method == "probable":
        best = resolution.considered[0] if resolution.considered else None
        name = (best.label if best else "") or "a product in an installed pack"
        return {
            "action": "confirm",
            "say": f"This looks like {name}, but the page and the pack do not "
                   f"agree on everything. Is that the same one?",
            "subject_id": best.subject_id if best else "",
        }

    # Unrecognised, and the whole point is that this is where the dead end was.
    if not resolution.considered:
        return {
            "action": "install",
            "say": "No installed pack covers this kind of product at all. "
                   "Install one that does, or write one.",
        }
    best = resolution.considered[0]
    disagreed = [one for one in best.per_key if one.how == "conflict"]
    if disagreed:
        which = ", ".join(one.key for one in disagreed)
        say = (f"The nearest thing installed is {best.label}, and it disagrees "
               f"with this page on {which}. Either this is a variant no pack "
               f"covers yet, or the page was read wrong.")
    else:
        say = (f"The nearest thing installed is {best.label}, and the page did "
               f"not say enough to tell whether it is the same one.")
    return {"action": "research", "say": say, "url": url}


def diagnosis(mapped, result, spec=None) -> dict:
    """Everything behind one answer, for somebody debugging it rather than reading it.

    The reader asked to be able to work this out without reading source, and
    that is the whole specification: what came off the page, what the adapter
    made of it, which subjects were weighed, what each key scored, and which
    threshold the winner cleared or missed.

    Deliberately assembled from the same objects the live answer is built from
    — not re-derived. A diagnostic that computes its own version of the answer
    tells you about the diagnostic.
    """
    resolution = result.resolution
    return {
        "adapter": {
            "id": (spec or {}).get("id", ""),
            "site": (spec or {}).get("site", ""),
            "source": "local" if (spec or {}).get("local") else "pack",
        },
        "page": {
            "identity": mapped.identity,
            "context": mapped.context,
            "kind": mapped.kind,
            # The labels the page carried that no rule claimed. A key the
            # adapter never learned to read is the commonest reason an
            # identity is too thin to match, and it is invisible in the
            # answer itself.
            "unmapped_labels": list(mapped.unmapped),
        },
        "outcome": {
            "method": resolution.method,
            "verdict": verdict(resolution),
            "score": round(resolution.score, 4),
            "coverage": result.coverage,
            "notes": resolution.notes,
            "flags": list(resolution.flags),
            "subjects": list(resolution.subject_ids),
        },
        "considered": [_candidate(one) for one in resolution.considered],
    }
