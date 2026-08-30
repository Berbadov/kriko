"""Browsing what a pack knows, subject by subject."""

from fastapi import APIRouter, Depends, HTTPException

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
        clauses.append("LOWER(s.label) LIKE ?")
        args.append(f"%{q.lower()}%")
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
            dict(r)
            for r in store.execute(
                "SELECT key, value_text, unit, valid_from, valid_to, is_identity"
                " FROM attributes WHERE subject_id = ? ORDER BY is_identity DESC, key",
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
