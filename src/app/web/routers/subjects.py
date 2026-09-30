"""Browsing what a pack knows, subject by subject."""

from fastapi import APIRouter, Depends, HTTPException

from app.termlabel import term_label
from app.web.deps import get_store
from kriko.research import get_researcher, plan_task

router = APIRouter(prefix="/api", tags=["subjects"])


@router.get("/subjects")
def list_subjects(
    pack_id: str = "",
    kind: str = "",
    q: str = "",
    limit: int = 100,
    store=Depends(get_store),
):
    clauses, args = ["p.enabled = 1"], []
    if pack_id:
        clauses.append("s.pack_id = ?")
        args.append(pack_id)
    if kind:
        clauses.append("s.kind = ?")
        args.append(kind)
    if q:
        # `%` and `_` are LIKE wildcards, not the literal characters a reader
        # typed — unescaped, a search for "%" reads as "match anything" and
        # returns every subject instead of none.
        escaped = q.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        clauses.append("LOWER(s.label) LIKE ? ESCAPE '\\'")
        args.append(f"%{escaped}%")
    return [
        dict(r)
        for r in store.execute(
            f"SELECT s.subject_id, s.pack_id, s.kind, s.label,"
            f"       COUNT(c.claim_id) AS claims"
            f" FROM subjects s JOIN packs p USING (pack_id)"
            f" LEFT JOIN claims c USING (subject_id, pack_id)"
            f" WHERE {' AND '.join(clauses)}"
            f" GROUP BY s.subject_id, s.pack_id"
            f" ORDER BY claims DESC, s.label LIMIT ?",
            (*args, limit),
        )
    ]


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
