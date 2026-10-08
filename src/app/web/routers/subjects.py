"""Browsing what a pack knows, subject by subject."""

from fastapi import APIRouter, Depends, HTTPException

from app.termlabel import term_label
from app.web.deps import get_store
from kriko.research import get_researcher, plan_task

router = APIRouter(prefix="/api", tags=["subjects"])


#: How well a subject's best claim is sourced, by distinct supporting sources.
#: A closed engine vocabulary like severity, so it may live here; the screen
#: is handed the words through `/subjects/filters` and types none of them.
_EVIDENCE = (
    ("none", "No sources", "= 0", "No claim on these has a source behind it."),
    ("single", "One source", "= 1", "The best-supported claim rests on a single source."),
    ("corroborated", "Two or more", ">= 2", "A claim on these is backed by two or more independent sources."),
)
_SEVERITY = (
    ("high", "Serious", "Holds at least one claim the engine ranks as serious."),
    ("medium", "Worth checking", "Holds at least one claim worth checking before buying."),
    ("low", "Minor", "Holds at least one claim that is minor."),
)

# Distinct supporting sources per claim, reduced to the best claim of each
# subject: one grouped read instead of a correlated subquery per row.
_BEST_SOURCES = (
    "SELECT c.subject_id AS subject_id, c.pack_id AS pack_id, MAX(n) AS n"
    " FROM (SELECT claim_id, pack_id, COUNT(DISTINCT source_id) AS n"
    "       FROM evidence WHERE stance = 'supports' GROUP BY claim_id, pack_id) ev"
    " JOIN claims c ON c.claim_id = ev.claim_id AND c.pack_id = ev.pack_id"
    " GROUP BY c.subject_id, c.pack_id"
)


def _label(value: str) -> str:
    return value.replace("_", " ").strip().capitalize() or value


@router.get("/subjects")
def list_subjects(
    pack_id: str = "",
    kind: str = "",
    q: str = "",
    severity: str = "",
    evidence: str = "",
    limit: int = 100,
    offset: int = 0,
    paged: bool = False,
    store=Depends(get_store),
):
    limit = min(max(limit, 1), 200)
    offset = max(offset, 0)
    clauses, args = ["p.enabled = 1"], []
    if pack_id:
        clauses.append("s.pack_id = ?")
        args.append(pack_id)
    if kind:
        clauses.append("s.kind = ?")
        args.append(kind)
    if severity:
        clauses.append(
            "EXISTS (SELECT 1 FROM claims x WHERE x.subject_id = s.subject_id"
            " AND x.pack_id = s.pack_id AND x.severity = ?)"
        )
        args.append(severity)
    if evidence:
        bound = {value: sql for value, _, sql, _ in _EVIDENCE}.get(evidence)
        # An unknown level matches nothing rather than everything: a stale
        # bookmark must not read as "no filter".
        clauses.append(
            f"COALESCE(sev.n, 0) {bound}" if bound else "0"
        )
    if q:
        # `%` and `_` are LIKE wildcards, not the literal characters a reader
        # typed — unescaped, a search for "%" reads as "match anything" and
        # returns every subject instead of none.
        escaped = q.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        clauses.append("LOWER(s.label) LIKE ? ESCAPE '\\'")
        args.append(f"%{escaped}%")
    from_where = (
        "FROM subjects s JOIN packs p USING (pack_id)"
        " LEFT JOIN claims c USING (subject_id, pack_id)"
        f" LEFT JOIN ({_BEST_SOURCES}) sev"
        "   ON sev.subject_id = s.subject_id AND sev.pack_id = s.pack_id"
        f" WHERE {' AND '.join(clauses)}"
    )
    items = [
        dict(r)
        for r in store.execute(
            f"SELECT s.subject_id, s.pack_id, s.kind, s.label,"
            f"       COUNT(c.claim_id) AS claims {from_where}"
            f" GROUP BY s.subject_id, s.pack_id"
            f" ORDER BY claims DESC, s.label LIMIT ? OFFSET ?",
            (*args, limit, offset),
        )
    ]
    if not paged:
        return items

    total = store.execute(
        "SELECT COUNT(*) FROM ("
        " SELECT s.subject_id, s.pack_id "
        f" {from_where} GROUP BY s.subject_id, s.pack_id"
        ")",
        args,
    ).fetchone()[0]
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/subjects/filters")
def subject_filters(store=Depends(get_store)) -> dict:
    """The filters Browse offers, as rows (B180).

    Each row names itself, says what it does, names the query parameter of
    `/subjects` it feeds, and lists the options that exist with how many
    subjects each holds. The screen types none of it, so a pack with a new
    kind of subject, or a new catalog, gains its filter option with no edit
    to `ui/`. Enabled packs only, like the list these filter.
    """
    enabled = "p.enabled = 1"
    packs = store.execute(
        "SELECT p.pack_id, p.name, COUNT(s.subject_id) AS n FROM packs p"
        f" JOIN subjects s USING (pack_id) WHERE {enabled}"
        " GROUP BY p.pack_id ORDER BY p.name"
    ).fetchall()
    kinds = store.execute(
        "SELECT s.kind, COUNT(*) AS n FROM subjects s JOIN packs p USING (pack_id)"
        f" WHERE {enabled} AND s.kind != '' GROUP BY s.kind ORDER BY n DESC, s.kind"
    ).fetchall()
    severities = {
        row["severity"]: row["n"]
        for row in store.execute(
            "SELECT c.severity, COUNT(DISTINCT c.subject_id || c.pack_id) AS n"
            " FROM claims c JOIN packs p USING (pack_id)"
            f" WHERE {enabled} GROUP BY c.severity"
        )
    }
    counts = [
        row["n"]
        for row in store.execute(
            "SELECT COALESCE(sev.n, 0) AS n FROM subjects s JOIN packs p USING (pack_id)"
            f" LEFT JOIN ({_BEST_SOURCES}) sev"
            "   ON sev.subject_id = s.subject_id AND sev.pack_id = s.pack_id"
            f" WHERE {enabled}"
        )
    ]
    by_level = {
        "none": sum(1 for n in counts if n == 0),
        "single": sum(1 for n in counts if n == 1),
        "corroborated": sum(1 for n in counts if n >= 2),
    }
    severity_options = [
        {"value": value, "label": label, "description": text, "count": severities[value]}
        for value, label, text in _SEVERITY
        if value in severities
    ] + [
        {"value": value, "label": _label(value), "description": "", "count": n}
        for value, n in severities.items()
        if value and value not in {v for v, _, _ in _SEVERITY}
    ]
    return {
        "filters": [
            {
                "id": "pack",
                "param": "pack_id",
                "label": "Catalog",
                "description": "Show products from one installed catalog.",
                "options": [
                    {"value": r["pack_id"], "label": r["name"], "count": r["n"]}
                    for r in packs
                ],
            },
            {
                "id": "kind",
                "param": "kind",
                "label": "Kind",
                "description": "The type of record a catalog holds, as its author named it.",
                "options": [
                    {"value": r["kind"], "label": _label(r["kind"]), "count": r["n"]}
                    for r in kinds
                ],
            },
            {
                "id": "evidence",
                "param": "evidence",
                "label": "Evidence",
                "description": "How well the best known risk of a product is sourced.",
                "options": [
                    {
                        "value": value,
                        "label": label,
                        "description": text,
                        "count": by_level[value],
                    }
                    for value, label, _, text in _EVIDENCE
                ],
            },
            {
                "id": "severity",
                "param": "severity",
                "label": "Severity",
                "description": "The most serious known risk a product carries.",
                "options": severity_options,
            },
        ]
    }


@router.get("/search")
def search_subjects(
    q: str = "",
    pack_id: str = "",
    kind: str = "",
    limit: int = 20,
    store=Depends(get_store),
) -> dict:
    """Find a product by typing its name. The panel's way in when recognition misses.

    "The extension has no way to search for a particular product. I have to be
    standing on the right page and hope recognition fires."

    Distinct from `/subjects?q=`, which is an author's filter over a list they
    are already looking at: that matches labels only, and a label is a display
    string rather than the words anybody types. This matches aliases and
    identity values too, and returns each subject's identity — because the ask
    was to *tell variants apart*, and two rows reading `Golf VII` cannot.
    """
    from kriko.lookup import find

    items = find.search(
        store, q,
        pack_ids=[pack_id] if pack_id else None,
        kind=kind,
        limit=max(1, min(int(limit), 50)),
    )
    return {"query": q, "items": items, "count": len(items)}


@router.get("/subjects/{subject_id}")
def get_subject(subject_id: str, store=Depends(get_store)):
    row = store.execute(
        "SELECT * FROM subjects WHERE subject_id = ?", (subject_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(404, f"no subject {subject_id}")
    return {
        "subject_id": subject_id,
        "pack_id": row["pack_id"],
        "kind": row["kind"],
        "label": row["label"],
        "attributes": [
            {**{k: v for k, v in dict(r).items() if k != "label_json"},
             "label": term_label(r["label_json"], r["key"])}
            for r in store.execute(
                # `label` and `datatype` are the pack's own words for the key
                # (its `terms` row), so a screen can name a specification
                # without knowing the category (B173). `source_url` is the
                # page the figure was read from, '' when the pack names none.
                "SELECT a.key, a.value_text, a.unit, a.valid_from, a.valid_to,"
                "       a.is_identity, a.source_url, t.label_json,"
                "       COALESCE(t.datatype, 'text') AS datatype"
                " FROM attributes a LEFT JOIN terms t"
                "   ON t.term_id = a.key AND t.pack_id = a.pack_id"
                "  AND t.role = 'attribute'"
                " WHERE a.subject_id = ? ORDER BY a.is_identity DESC, a.key",
                (subject_id,),
            )
        ],
        "relations": [
            dict(r)
            for r in store.execute(
                "SELECT r.predicate, r.note, s.label AS object_label, r.object_id"
                " FROM relations r LEFT JOIN subjects s"
                "   ON s.subject_id = r.object_id AND s.pack_id = r.pack_id"
                " WHERE r.subject_id = ?",
                (subject_id,),
            )
        ],
        "claims": [
            dict(r)
            for r in store.execute(
                "SELECT c.claim_id, c.kind, c.domain, c.severity, c.detection,"
                "       c.author_confidence, t.title"
                " FROM claims c LEFT JOIN claim_text t"
                "   ON t.claim_id = c.claim_id AND t.pack_id = c.pack_id"
                "  AND t.lang = 'en'"
                " WHERE c.subject_id = ? ORDER BY c.severity, t.title",
                (subject_id,),
            )
        ],
    }


@router.get("/subjects/{subject_id}/brief")
def research_brief(subject_id: str, store=Depends(get_store)):
    """The research brief, in the pack's own terms.

    This is the whole $0 plane from the browser: copy it into a coding-agent
    session, let the subscription do the searching, and the findings come back
    through MCP.
    """
    row = store.execute(
        "SELECT pack_id FROM subjects WHERE subject_id = ?", (subject_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(404, f"no subject {subject_id}")
    task = plan_task(store, subject_id, row["pack_id"])
    return {
        "subject": task.subject_label,
        "queries": list(task.rendered_queries()),
        "brief": get_researcher().brief(task),
    }
