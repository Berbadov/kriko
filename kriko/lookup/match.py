"""Identity in, candidate subjects out.

The generic form of `backend/core/matcher.py`. Everything that file knew about
cars — that `make` and `model` are required, that displacement matches within
±100 cc, that power matches within a few hp — now arrives as `terms.match_json`
rows supplied by the pack.

Two rules carried over from the old matcher because they were hard-won:

**Matching is on attribute overlap, never on `subject_id` equality.** Two packs
whose authors disagreed about identity keys hash the same product differently.
If lookup keyed on the hash, their claims would never meet, and the pivot's
whole premise — install several packs, get the union — would quietly fail.

**Narrowing is soft.** A hint that matches no candidate must never turn a real
match into `no_match`. The old code learned this from listings whose stated
gearbox contradicted the catalog: dropping the car entirely served nothing,
while keeping it and flagging the contradiction surfaced a coverage gap.
"""

import json
from dataclasses import dataclass

import yaml

from kriko.lookup.query import Resolution


@dataclass(frozen=True)
class Term:
    term_id: str
    role: str
    datatype: str
    required: bool
    narrow_order: int | None
    tolerance: float | None
    # A `range` term is stored once per subject with valid_from/valid_to bounds
    # rather than one row per value — a production run of 2014-2020 is one fact,
    # not seven. The query supplies a point that must fall inside.
    is_range: bool = False


def _match_rules(raw: str) -> dict:
    """`match_json` is written by the builder as YAML; tolerate JSON too."""
    if not raw:
        return {}
    try:
        parsed = yaml.safe_load(raw)
    except yaml.YAMLError:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
    return parsed if isinstance(parsed, dict) else {}


def load_terms(conn, pack_ids) -> dict[str, Term]:
    """Vocabulary across the enabled packs, keyed by term id."""
    if not pack_ids:
        return {}
    marks = ",".join("?" * len(pack_ids))
    terms: dict[str, Term] = {}
    for row in conn.execute(
            f"SELECT term_id, role, datatype, match_json FROM terms"
            f" WHERE pack_id IN ({marks})", tuple(pack_ids)):
        rules = _match_rules(row["match_json"])
        terms[row["term_id"]] = Term(
            term_id=row["term_id"], role=row["role"], datatype=row["datatype"],
            required=bool(rules.get("required")),
            narrow_order=rules.get("narrow_order"),
            tolerance=rules.get("tolerance"),
            is_range=bool(rules.get("range")))
    return terms


def alias_map(conn, pack_ids) -> dict[str, str]:
    """alias -> term_id, so a caller may say 'make' where the pack says 'brand'.

    This is the mechanism that replaces normalize.py's hand-maintained
    `_MAKE_MAP` / `_MODEL_MAP`, which went stale exactly as design-flaw 1
    predicted. Aliases are rows; a pack extends them without touching code.
    """
    if not pack_ids:
        return {}
    marks = ",".join("?" * len(pack_ids))
    return {row["alias"].casefold(): row["term_id"] for row in conn.execute(
        f"SELECT alias, term_id FROM term_aliases WHERE pack_id IN ({marks})",
        tuple(pack_ids))}


def value_alias_map(conn, pack_ids) -> dict[str, dict[str, str]]:
    """parent term -> {alias -> canonical value}.

    The other half of the normalisation story. Key aliases let a caller say
    `make` where the pack says `brand`; value aliases let a scrape say
    "Benzinli" where the catalog says "petrol". Both were Python dicts in
    `normalize.py` (`_FUEL_MAP`, `_TX_MAP`) that a new market would have
    required someone to remember to edit.

    A canonical value is a term with `role='enum_value'` whose `parent_id` names
    the attribute it belongs to, so the same word can mean different things
    under different keys without collision.
    """
    if not pack_ids:
        return {}
    marks = ",".join("?" * len(pack_ids))
    out: dict[str, dict[str, str]] = {}
    rows = conn.execute(
        f"SELECT t.term_id, t.parent_id, a.alias FROM terms t"
        f" LEFT JOIN term_aliases a"
        f"   ON a.term_id = t.term_id AND a.pack_id = t.pack_id"
        f" WHERE t.pack_id IN ({marks}) AND t.role = 'enum_value'",
        tuple(pack_ids))
    for row in rows:
        bucket = out.setdefault(row["parent_id"], {})
        bucket[row["term_id"].casefold()] = row["term_id"]
        if row["alias"]:
            bucket[row["alias"].casefold()] = row["term_id"]
    return out


def normalize_identity(identity: dict, aliases: dict[str, str],
                       values: dict[str, dict[str, str]] | None = None) -> dict:
    """Resolve caller-supplied keys and values onto the pack's own vocabulary."""
    values = values or {}
    out = {}
    for key, value in identity.items():
        term = aliases.get(str(key).casefold(), key)
        canonical = values.get(term, {}).get(str(value).strip().casefold())
        out[term] = canonical if canonical is not None else value
    return out


def _number(value):
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _subjects_matching(conn, pack_ids, kind, key, value) -> set[str]:
    marks = ",".join("?" * len(pack_ids))
    rows = conn.execute(
        f"SELECT a.subject_id FROM attributes a"
        f" JOIN subjects s USING (subject_id, pack_id)"
        f" WHERE a.pack_id IN ({marks}) AND s.kind = ? AND a.key = ?"
        f"   AND LOWER(a.value_text) = LOWER(?)",
        (*pack_ids, kind, key, str(value)))
    return {r["subject_id"] for r in rows}


def _narrow(conn, pack_ids, candidates, term, value) -> set[str]:
    """One soft narrowing step. Numeric terms use a tolerance, text terms equality."""
    marks = ",".join("?" * len(pack_ids))
    rows = conn.execute(
        f"SELECT subject_id, value_text, value_num FROM attributes"
        f" WHERE pack_id IN ({marks}) AND key = ?", (*pack_ids, term.term_id))

    wanted_num = _number(value)
    if wanted_num is not None:
        tolerance = float(term.tolerance or 0)
        return {r["subject_id"] for r in rows
                if r["subject_id"] in candidates and r["value_num"] is not None
                and abs(r["value_num"] - wanted_num) <= tolerance}

    wanted = str(value).strip().casefold()
    return {r["subject_id"] for r in rows
            if r["subject_id"] in candidates
            and r["value_text"].strip().casefold() == wanted}


def _within_range(conn, pack_ids, candidates, key, point: float) -> set[str]:
    """Subjects whose validity window contains `point`. Empty bound = unbounded."""
    marks = ",".join("?" * len(pack_ids))
    kept = set()
    for row in conn.execute(
            f"SELECT subject_id, valid_from, valid_to FROM attributes"
            f" WHERE pack_id IN ({marks}) AND key = ?", (*pack_ids, key)):
        if row["subject_id"] not in candidates:
            continue
        low = _number(row["valid_from"])
        high = _number(row["valid_to"])
        if (low is None or point >= low) and (high is None or point <= high):
            kept.add(row["subject_id"])
    return kept


def resolve(conn, query, pack_ids) -> Resolution:
    """Ask every enabled pack what it thinks this is, then union the answers.

    Resolution is PER PACK, and it has to be. A pack's vocabulary is
    self-contained: the cars pack calls the key `make` and accepts `brand` as an
    alias, while the drill pack does the exact opposite. Merging both alias
    tables into one map makes `brand -> make` and `make -> brand` fight, one
    wins, and whichever pack loses becomes unreachable — with both packs
    installed, neither answers. That is not a hypothetical; it is what happened
    the first time two packs were queried through one store.

    So each pack resolves the query in its own words, and the engine unions the
    results. Ambiguity — "which variant is this?" — stays a within-pack
    question; two packs each confidently answering is not ambiguity.
    """
    subjects: list[str] = []
    flags: list[str] = []
    notes: list[str] = []
    ambiguous = False

    for pack_id in pack_ids:
        one = _resolve_in_pack(conn, query, pack_id)
        if one.subject_ids:
            subjects.extend(one.subject_ids)
            if len(one.subject_ids) > 1:
                ambiguous = True
            if one.notes:
                notes.append(f"{pack_id}: {one.notes}")
        # A pack that does not know the word "fuel" and matched nothing is not
        # telling us anything — only a pack that answered can meaningfully
        # report which parts of the query it could not use.
        if one.subject_ids:
            flags.extend(f"{pack_id}/{f}" for f in one.flags)

    if not subjects:
        return Resolution((), "no_match",
                          "; ".join(notes) or "no pack recognised this",
                          tuple(dict.fromkeys(flags)))

    return Resolution(tuple(sorted(set(subjects))),
                      "ambiguous" if ambiguous else "exact",
                      "; ".join(notes), tuple(dict.fromkeys(flags)))


def _resolve_in_pack(conn, query, pack_id) -> Resolution:
    pack_ids = (pack_id,)
    terms = load_terms(conn, pack_ids)
    identity = normalize_identity(query.identity, alias_map(conn, pack_ids),
                                  value_alias_map(conn, pack_ids))

    given = {k: v for k, v in identity.items() if k in terms}
    unknown_keys = sorted(set(identity) - set(given))
    flags = [f"unknown_key:{k}" for k in unknown_keys]

    required = [k for k, t in terms.items() if t.required]
    missing_required = [k for k in required if k not in given]

    # Hard filter: intersect on the identity-bearing keys the caller supplied.
    # A term that declares a `narrow_order` is a soft hint BY DEFINITION and is
    # excluded here — a stated power of 148 hp should pick the 150 hp variant,
    # not demand a subject whose recorded power is literally "148". Treating
    # hints as hard filters turns every approximate reading into no_match.
    hard_keys = [k for k in given
                 if terms[k].role == "attribute"
                 and terms[k].narrow_order is None and not terms[k].is_range]
    if not hard_keys:
        return Resolution((), "no_match",
                          "no identity attributes supplied", tuple(flags))

    candidates: set[str] | None = None
    for key in hard_keys:
        matched = _subjects_matching(conn, pack_ids, query.kind, key, given[key])
        candidates = matched if candidates is None else (candidates & matched)
        if not candidates:
            return Resolution((), "no_match",
                              f"nothing matches {key}={given[key]!r}", tuple(flags))

    candidates = candidates or set()
    if missing_required:
        flags.append("partial_identity:" + ",".join(missing_required))

    # Soft narrowing, in the pack's declared order. Each step may shrink the set
    # but never empty it — a contradiction is a flag, not a rejection.
    narrowers = sorted(
        (t for t in terms.values()
         if t.narrow_order is not None and t.term_id in given),
        key=lambda t: t.narrow_order or 0)

    for term in narrowers:
        if len(candidates) <= 1:
            continue
        kept = _narrow(conn, pack_ids, candidates, term, given[term.term_id])
        if kept:
            candidates = kept
        else:
            # The listing contradicts every candidate. Keep them all and say so:
            # dropping the car serves nobody, while the flag is a coverage
            # signal that something in the catalog or the ad is wrong.
            flags.append(f"soft_narrow_fallback:{term.term_id}")

    # Range terms (a production window, a build year) are applied last and are
    # equally soft. Backlog B9 settled this: an out-of-window listing still
    # matches and is logged as demand, because a year that is one off is far
    # more often a catalog gap than a different car.
    for key in [k for k in given if terms[k].is_range]:
        point = _number(given[key])
        if point is None or not candidates:
            continue
        kept = _within_range(conn, pack_ids, candidates, key, point)
        if kept:
            candidates = kept
        else:
            flags.append(f"out_of_range:{key}")

    ordered = tuple(sorted(candidates))
    if not ordered:
        return Resolution((), "no_match", "no candidates", tuple(flags))
    method = "exact" if len(ordered) == 1 else "ambiguous"
    notes = "" if method == "exact" else f"{len(ordered)} subjects match equally"
    return Resolution(ordered, method, notes, tuple(flags))


def expand(conn, subject_ids, pack_ids, max_hops: int = 2) -> dict[str, str]:
    """Every subject whose claims apply, mapped to how it was reached.

    From a matched product, follow `part_of` outward to the components and
    platforms it is built from: a claim about a chain, an engine code or a
    battery line applies to everything fitted with it. `same_as` is followed in
    both directions, so packs that hashed a subject differently still meet.

    A subject with no relations yields nothing extra. That is the drill case, and
    it must fall out of an empty result rather than a branch — the moment the
    engine needs `if has_components`, it has learned about cars again.
    """
    if not subject_ids or not pack_ids:
        return {}

    reached = {sid: "direct" for sid in subject_ids}
    frontier = set(subject_ids)
    marks = ",".join("?" * len(pack_ids))

    for _ in range(max_hops):
        if not frontier:
            break
        fmarks = ",".join("?" * len(frontier))
        rows = list(conn.execute(
            f"SELECT subject_id, predicate, object_id FROM relations"
            f" WHERE pack_id IN ({marks})"
            f"   AND (subject_id IN ({fmarks}) OR object_id IN ({fmarks}))",
            (*pack_ids, *frontier, *frontier)))

        nxt = set()
        for row in rows:
            src, pred, dst = row["subject_id"], row["predicate"], row["object_id"]
            if pred == "part_of" and src in frontier and dst not in reached:
                reached[dst] = f"part_of:{src}"
                nxt.add(dst)
            elif pred == "same_as":
                for a, b in ((src, dst), (dst, src)):
                    if a in frontier and b not in reached:
                        reached[b] = f"same_as:{a}"
                        nxt.add(b)
        frontier = nxt

    return reached
