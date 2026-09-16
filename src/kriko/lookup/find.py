"""Finding a product by typing its name, when recognition did not fire.

The panel recognises the page a reader is standing on. That is the product, and
it is also the whole of what it could do: *"I have to be standing on the right
page and hope recognition fires."* When it misses — a site with no adapter, a
listing that names the thing in words no pack declared, a reader comparing two
of something from their sofa — there was no way in at all.

So: type the name.

**Three places a name can live, and only one was searched.** A subject's
`label` is a display string, written to tell two rows apart in a list. Its
`subject_aliases` are the words people actually type, which is what that table
exists for. Its identity *values* are what the thing is made of — and somebody
typing a part number or a capacity is searching those, not a label. Matching
only labels found the subjects whose author happened to write the reader's
words into one field.

**Every result carries its identity, and that is the point rather than a
detail.** Two rows reading the same name are not a choice; the same name
followed by the two configurations that differ is. The reader asked for search
so they could tell one of a thing from another of it, which a list of labels
cannot do however well it matches.

Deliberately not the scoring in `score.py`. That answers "is this page this
product", against an identity read off a page, with thresholds and a verdict.
This answers "which of these did you mean", against words a person typed, and
the right response to a weak match here is to show it further down the list
rather than to withhold it — a person who typed something is already telling
you they want to see what there is.
"""

#: How many subjects one query may return. Enough that a broad word is still
#: useful, small enough that the panel is a list rather than a catalogue.
LIMIT = 20

#: What each kind of hit is worth. Ordering only — there is no threshold here
#: and nothing is ever withheld for scoring low.
#:
#: An alias beats a label on purpose: `subject_aliases` holds the phrases a
#: person would actually type, and a label holds whatever disambiguated two
#: rows in a list. When they disagree about which subject a typed word means,
#: the table built for typing is the one to believe.
WEIGHT = {"alias": 3.0, "label": 2.0, "identity": 1.0}


def _rows(conn, sql: str, args) -> list:
    return list(conn.execute(sql, args))


def search(conn, text: str, *, pack_ids=None, kind: str = "",
           limit: int = LIMIT) -> list[dict]:
    """Subjects whose name, alias or identity contains every word typed.

    Every word, not any: a reader typing two words has narrowed deliberately,
    and an `any` match returns everything matching either of them, which is
    always more than they asked for. The words may land in *different* fields —
    one on the label and one on an identity value is a match, and is in fact
    the common one.
    """
    words = [one for one in str(text or "").lower().split() if one]
    if not words:
        return []
    packs = list(pack_ids) if pack_ids else [
        row["pack_id"] for row in conn.execute(
            "SELECT pack_id FROM packs WHERE enabled = 1")
    ]
    if not packs:
        return []

    marks = ",".join("?" * len(packs))
    kind_clause = " AND s.kind = ?" if kind else ""
    kind_args = (kind,) if kind else ()

    # One pass per source of text, collected per subject. Three small queries
    # rather than one join with three LEFT JOINs: the join multiplies rows by
    # alias count times attribute count, and the de-duplication afterwards
    # costs more than the extra round trips on a store this size.
    found: dict[tuple, dict] = {}

    def note(subject_id, pack_id, where: str, word: str, value: str) -> None:
        key = (subject_id, pack_id)
        row = found.setdefault(key, {
            "subject_id": subject_id, "pack_id": pack_id,
            "matched": {}, "score": 0.0,
        })
        # Once per word per source: a word appearing in four aliases is not
        # four times the evidence, it is one alias table being thorough.
        if word in row["matched"].get(where, {}):
            return
        row["matched"].setdefault(where, {})[word] = value
        row["score"] += WEIGHT[where]

    for word in words:
        like = f"%{word}%"
        for row in _rows(conn,
                f"SELECT s.subject_id, s.pack_id, s.label FROM subjects s"
                f" WHERE s.pack_id IN ({marks}){kind_clause}"
                f"   AND LOWER(s.label) LIKE ?", (*packs, *kind_args, like)):
            note(row["subject_id"], row["pack_id"], "label", word, row["label"])
        for row in _rows(conn,
                f"SELECT a.subject_id, a.pack_id, a.alias FROM subject_aliases a"
                f" JOIN subjects s USING (subject_id, pack_id)"
                f" WHERE a.pack_id IN ({marks}){kind_clause}"
                f"   AND LOWER(a.alias) LIKE ?", (*packs, *kind_args, like)):
            note(row["subject_id"], row["pack_id"], "alias", word, row["alias"])
        for row in _rows(conn,
                f"SELECT a.subject_id, a.pack_id, a.key, a.value_text"
                f" FROM attributes a JOIN subjects s USING (subject_id, pack_id)"
                f" WHERE a.pack_id IN ({marks}){kind_clause}"
                f"   AND a.is_identity = 1 AND LOWER(a.value_text) LIKE ?",
                (*packs, *kind_args, like)):
            note(row["subject_id"], row["pack_id"], "identity", word,
                 f"{row['key']}={row['value_text']}")

    # Every word has to have landed somewhere. Checked here rather than in SQL
    # because a word may match a label while another matches an attribute, and
    # no single query sees both.
    kept = [
        row for row in found.values()
        if len({word for hits in row["matched"].values() for word in hits})
        == len(set(words))
    ]
    if not kept:
        return []

    detail = _describe(conn, [(one["subject_id"], one["pack_id"]) for one in kept])
    out = []
    for row in kept:
        extra = detail.get((row["subject_id"], row["pack_id"]), {})
        out.append({
            **row,
            **extra,
            # Flattened for a client that only wants to show why this matched.
            "why": sorted(
                value for hits in row["matched"].values() for value in hits.values()
            ),
        })
    # Score, then claim count, then label: a subject the packs actually know
    # something about beats an equally-named one they do not, and the order is
    # total so the same query does not reshuffle between two presses.
    out.sort(key=lambda one: (-one["score"], -one.get("claims", 0),
                              one.get("label", ""), one["subject_id"]))
    return out[:limit]


def _reachable(conn, subject_id: str, pack_id: str) -> int:
    """How many claims this subject would actually serve, relations included.

    **Not a count of the claims attached to its own row**, and the difference
    is not academic — it is the whole number. A pack may hang its claims on
    shared component subjects and reach them through a relation, so a product
    row can carry zero of its own and still answer with eight. Measured against
    a real installed pack, every product row reported `0 claim(s)` while the
    panel for the same product showed a full page.

    So this counts what `lookup()` counts, through the same `expand` — a search
    result promising nothing about a product the reader is about to be shown
    eight risks for is worse than no number.
    """
    from kriko.lookup.match import expand

    reached = set(expand(conn, (subject_id,), (pack_id,))) | {subject_id}
    marks = ",".join("?" * len(reached))
    row = conn.execute(
        f"SELECT COUNT(*) AS n FROM claims"
        f" WHERE pack_id = ? AND subject_id IN ({marks})",
        (pack_id, *reached),
    ).fetchone()
    return int(row["n"] or 0)


def _describe(conn, keys) -> dict[tuple, dict]:
    """Label, kind, claim count and identity for each hit.

    The identity is the half that makes a result list usable: two rows reading
    the same label are not a choice, and the reader asked for search precisely
    to tell one of a thing from another of it.
    """
    if not keys:
        return {}
    marks = ",".join("?" * len(keys))
    ids = [one[0] for one in keys]
    out: dict[tuple, dict] = {}
    for row in conn.execute(
        f"SELECT s.subject_id, s.pack_id, s.kind, s.label FROM subjects s"
        f" WHERE s.subject_id IN ({marks})", ids
    ):
        out[(row["subject_id"], row["pack_id"])] = {
            "kind": row["kind"], "label": row["label"],
            "claims": _reachable(conn, row["subject_id"], row["pack_id"]),
            "identity": {},
        }
    for row in conn.execute(
        f"SELECT subject_id, pack_id, key, value_text FROM attributes"
        f" WHERE subject_id IN ({marks}) AND is_identity = 1"
        f" ORDER BY key", ids
    ):
        entry = out.get((row["subject_id"], row["pack_id"]))
        if entry is not None:
            entry["identity"][row["key"]] = row["value_text"]
    return out
