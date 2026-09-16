"""Near-matching — what the engine says when the exact intersection is empty.

`match.py` resolves by intersecting identity attributes exactly. That is the
right *first* answer: when a page and a catalog agree on every key, there is
nothing to weigh up and the cheapest query wins. It is a terrible *only*
answer, and the reader found out how terrible in the one sentence this module
exists for — they built a pack, opened the product's page, and were told **no
pack recognised this product**.

Nothing was missing. One value read off the page differed from the catalog's
by a word, `_resolve_in_pack`'s `candidates &= matched` emptied the set, and an
empty set is indistinguishable from never having heard of the thing. The whole
pack — good facts, valid sources — became invisible because of a spelling.

So where the exact path finds nothing, this one scores. Three rules, and each
is a thing the exact path could not do:

**A score, not a verdict.** Every identity key the caller supplied contributes
between 0 and 1, weighted. The result is a number with the per-key reasons
attached, so "why did nothing match" has an answer a person can read instead of
a silence.

**Two thresholds, not one.** Above `match_floor` is a match. Between
`match_probable` and the floor is a *probable* match, which the client puts to
the reader as "this pack probably covers this — confirm?" rather than
discarding. Below `match_probable` is genuinely nothing, and saying so is fine.

**Both numbers are the pack's.** They ride in `gate_terms` as
`kind='limits'`, the same row shape `min_rationale_chars` already uses, and
per-key weights ride in `terms.match_json`. An engine that picked them would be
deciding how much one identity key matters relative to another, and how near is
near enough — both statements about a *product category*, which two categories
answer differently. Category statements are pack data. Undeclared falls back to
the constants below, which are the engine's opinion about arithmetic, not about
products.

This module never runs on the happy path. `resolve()` calls it only where it
was about to return `no_match`, so an installation whose pages and catalog
agree pays nothing for it.
"""

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

#: Used where the pack declares nothing. A candidate must agree on most of what
#: was supplied to be called a match, and on a fair slice of it to be worth
#: asking about. Deliberately not tuned to any category; a pack with an opinion
#: declares its own.
DEFAULT_FLOOR = 0.62
DEFAULT_PROBABLE = 0.38

#: What one key is worth when its term declares no `weight`. Equal weighting is
#: the honest default: the engine has no way to know that one key identifies a
#: product harder than another without the pack saying so.
DEFAULT_WEIGHT = 1.0

#: Below this, two strings are not the same value said differently — they are
#: different values. See `_closeness` for what is measured.
SIMILAR_ENOUGH = 0.25

#: What a *contradiction* costs, relative to a key simply being absent.
#:
#: Without this the two are the same — both contribute zero — and that is
#: wrong in the direction that matters. A subject that records nothing for a
#: key has not disagreed with a page that states one; a subject recording the
#: opposite value has. Scoring them alike is how a page agreeing on the maker
#: and contradicting the model comes out at 0.5 and gets offered to the reader
#: as probably that product — the confidently-wrong answer, which is worse than
#: the blank page this module replaced.
#:
#: Modelled in the denominator rather than as a negative score so the result
#: stays inside 0..1 and the thresholds keep meaning what they say.
CONFLICT_PENALTY = 2.0


def _closeness(supplied: str, held: str) -> float:
    """How nearly two identity values are the same value, 0..1.

    Three measures, best of. None of them is sufficient alone, and the ones
    that fail do so on exactly the cases this module was written for:

    * **Token overlap** (`_overlap`) reads a value against the same value with
      one extra qualifier on the end, which is the commonest disagreement of
      all. It reads an initialism against the word it stands for as zero, since
      they share no whole token.
    * **Character overlap** (`SequenceMatcher`) reads that initialism, which is
      the next commonest way a page and a catalog say one thing in two ways.
      Gated behind `_abbreviates`, because ungated it scores any two similarly
      spelled short words alike — and two opposite members of a small
      vocabulary are often one or two letters apart, so an enum judged on its
      spelling matches the wrong member.
    * **Containment** reads a value that is simply *less* specific than the one
      held. Token overlap punishes that as though it were a disagreement, and
      it is not: the narrowing terms exist to resolve the rest.

    Not a fourth, hand-maintained list of abbreviations. That is `_MAKE_MAP`
    again, and the pack's own `term_aliases` rows are where a real
    abbreviation belongs — this only has to stop the ones nobody declared from
    costing the reader the whole pack.
    """
    a, b = supplied.strip().casefold(), held.strip().casefold()
    if not a or not b:
        return 0.0
    tokens_a, tokens_b = _tokens(a), _tokens(b)
    contained = 0.0
    if tokens_a and tokens_b and (tokens_a <= tokens_b or tokens_b <= tokens_a):
        # Scaled by how much of the longer value the shorter one accounts
        # for, so one token inside two beats one token inside seven — the
        # latter really is the weaker reading.
        contained = 0.5 + 0.5 * (
            min(len(tokens_a), len(tokens_b)) / max(len(tokens_a), len(tokens_b))
        )
    letters = SequenceMatcher(None, a, b).ratio() if _abbreviates(a, b) else 0.0
    return max(_overlap(tokens_a, tokens_b), letters, contained)


#: Identity values are not prose, and the one general-purpose tokeniser in the
#: tree treats them as though they were. `title_sim.title_tokens` drops
#: stopwords and anything under two characters, which is right for a claim
#: title and catastrophic here: where two values differ only in a number, it
#: throws away the number and calls them identical. In an identity value the
#: digits are usually the whole distinction. So this keeps every token, numbers
#: included, and only the punctuation between them goes.
_SPLIT = re.compile(r"[^a-z0-9.]+")


def _tokens(text: str) -> set[str]:
    return {one for one in _SPLIT.split(text) if one}


def _overlap(a: set[str], b: set[str]) -> float:
    """Jaccard over identity tokens. Empty either side is no evidence, not 1.0."""
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _abbreviates(a: str, b: str) -> bool:
    """Is one of these plausibly a short form of the other?

    Two conditions, both needed. The short one must be *substantially* shorter
    — an abbreviation that saves nothing is not one — and its letters must
    appear in the long one **in order**, which is what an abbreviation is and
    what two same-length words with a couple of letters in common is not.
    """
    short, long = sorted((a, b), key=len)
    short, long = short.replace(" ", ""), long.replace(" ", "")
    if not short or len(short) > 0.6 * len(long):
        return False
    walk = iter(long)
    return all(letter in walk for letter in short)


@dataclass(frozen=True)
class KeyScore:
    """One identity key's contribution, and why it is what it is.

    `held` is what the catalog has, which is the half a reader cannot see and
    the half that explains everything: "the page said X, this subject says Y"
    is a debuggable sentence, and "no match" is not.
    """

    key: str
    supplied: str
    held: str
    score: float
    weight: float
    #: exact | similar | conflict | absent — how the two values met.
    how: str

    @property
    def why(self) -> str:
        if self.how == "exact":
            return f"{self.key}: {self.supplied!r} matches"
        if self.how == "similar":
            return (f"{self.key}: {self.supplied!r} ≈ {self.held!r} "
                    f"({self.score:.2f})")
        if self.how == "conflict":
            return f"{self.key}: {self.supplied!r} against {self.held!r}"
        return f"{self.key}: {self.supplied!r} — this subject does not say"


@dataclass(frozen=True)
class Candidate:
    """A subject that might be the thing on the page, and how sure we are."""

    subject_id: str
    pack_id: str
    label: str
    score: float
    per_key: tuple[KeyScore, ...]

    @property
    def why(self) -> tuple[str, ...]:
        return tuple(one.why for one in self.per_key)


def thresholds(conn, pack_id: str) -> tuple[float, float]:
    """`(floor, probable)` for one pack, its own if it declared them.

    Read through the same `gate_terms` rows `load_gates` reads, rather than a
    second table, because a pack author who has already written a `limits` row
    should not have to learn a second mechanism to write another one. A value
    that will not parse, or sits outside 0..1, is treated as undeclared: a
    typo must not make a pack unmatchable, which is the failure this whole
    module was written to end.
    """
    floor, probable = DEFAULT_FLOOR, DEFAULT_PROBABLE
    for row in conn.execute(
        "SELECT pattern, note FROM gate_terms"
        " WHERE pack_id = ? AND kind = 'limits'"
        "   AND pattern IN ('match_floor', 'match_probable')",
        (pack_id,),
    ):
        try:
            value = float(row["note"])
        except (TypeError, ValueError):
            continue
        if not 0.0 < value <= 1.0:
            continue
        if row["pattern"] == "match_floor":
            floor = value
        else:
            probable = value
    # A probable band above the floor is a pack that has them the wrong way
    # round. Keep the floor — the stricter of the two readings — rather than
    # silently admitting everything.
    return floor, min(probable, floor)


def weights(terms) -> dict[str, float]:
    """Per-key weight from the pack's own `match_json`, defaulting to equal."""
    out = {}
    for term_id, term in terms.items():
        weight = getattr(term, "weight", None)
        try:
            out[term_id] = float(weight) if weight is not None else DEFAULT_WEIGHT
        except (TypeError, ValueError):
            out[term_id] = DEFAULT_WEIGHT
    return out


def _held_values(conn, pack_id: str, kind: str) -> dict[str, dict[str, str]]:
    """`subject_id -> {key: value}` for every identity attribute in the pack.

    One query rather than one per candidate. A pack is thousands of rows, not
    millions, and this runs only where the exact path already failed — so the
    cost is paid on the page that was about to show nothing, never on the ones
    that work.
    """
    out: dict[str, dict[str, str]] = {}
    for row in conn.execute(
        "SELECT a.subject_id, a.key, a.value_text FROM attributes a"
        " JOIN subjects s USING (subject_id, pack_id)"
        " WHERE a.pack_id = ? AND s.kind = ? AND a.is_identity = 1",
        (pack_id, kind),
    ):
        out.setdefault(row["subject_id"], {})[row["key"]] = row["value_text"]
    return out


def _labels(conn, pack_id: str) -> dict[str, str]:
    return {
        row["subject_id"]: row["label"]
        for row in conn.execute(
            "SELECT subject_id, label FROM subjects WHERE pack_id = ?", (pack_id,)
        )
    }


def _one_key(key: str, supplied, held: str | None, weight: float) -> KeyScore:
    """Score one supplied value against what one subject holds for that key.

    `absent` scores zero but is deliberately not a *conflict*: a catalog that
    records nothing for a key has not contradicted a page that states one, and
    treating silence as disagreement is how a thin-but-correct pack loses to a
    wrong-but-complete one.
    """
    text = str(supplied).strip()
    if held is None:
        return KeyScore(key, text, "", 0.0, weight, "absent")
    if text.casefold() == held.strip().casefold():
        return KeyScore(key, text, held, 1.0, weight, "exact")
    close = _closeness(text, held)
    if close >= SIMILAR_ENOUGH:
        return KeyScore(key, text, held, round(close, 4), weight, "similar")
    return KeyScore(key, text, held, 0.0, weight, "conflict")


def candidates(conn, kind: str, identity: dict, pack_id: str, terms,
               limit: int = 5) -> list[Candidate]:
    """Every subject in one pack, scored against a supplied identity.

    `identity` must already be normalised onto the pack's vocabulary — the
    caller has an `alias_map` and a `value_alias_map` in hand by the time it
    gets here, and re-deriving them per pack would do the same work twice and
    risk doing it differently. What survives normalisation is exactly what the
    aliases could not fix, which is what this scores.
    """
    given = {k: v for k, v in identity.items() if k in terms}
    if not given:
        return []

    per_weight = weights(terms)
    labels = _labels(conn, pack_id)
    scored: list[Candidate] = []

    for subject_id, held in _held_values(conn, pack_id, kind).items():
        keys = tuple(
            _one_key(key, value, held.get(key), per_weight.get(key, DEFAULT_WEIGHT))
            for key, value in sorted(given.items())
        )
        # A contradiction weighs more against a candidate than silence does —
        # see CONFLICT_PENALTY. Everything else counts once.
        total = sum(
            one.weight * (CONFLICT_PENALTY if one.how == "conflict" else 1.0)
            for one in keys
        )
        if not total:
            continue
        score = sum(one.score * one.weight for one in keys) / total
        if score <= 0:
            continue
        scored.append(
            Candidate(subject_id, pack_id, labels.get(subject_id, ""),
                      round(score, 4), keys)
        )

    # Score first, then subject_id: a tie must not resolve at random, or one
    # page recognises a different subject on a reload and the reader is right
    # to stop trusting it.
    scored.sort(key=lambda one: (-one.score, one.subject_id))
    return scored[:limit]


def verdict(found: list[Candidate], floor: float, probable: float) -> str:
    """`match` | `probable` | `no_match` for a scored list, best-first."""
    if not found:
        return "no_match"
    best = found[0].score
    if best >= floor:
        return "match"
    if best >= probable:
        return "probable"
    return "no_match"
