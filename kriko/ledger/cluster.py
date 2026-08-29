"""Deterministic evidence clustering per component.

Greedy single-pass in evidence-id order (stable, deterministic): an evidence
row joins the first existing cluster in the same domain whose representative
text has word-Jaccard >= 0.4 (same threshold as packs.cars.pipeline.dedup.same_claim),
else it founds a new cluster. clusters/cluster_members are derived tables —
rebuilt wholesale, never migrated."""

import re

CLUSTER_VERSION = 1
_JACCARD_THRESHOLD = 0.4


def _tokens(s: str) -> set[str]:
    return set(re.findall(r"[^\W\d_]{3,}", (s or "").lower()))


def jaccard(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def rebuild_clusters(conn) -> int:
    # Derived tables, rebuilt wholesale. Verdicts are content-addressed by
    # input_hash (db.py), decoupled from cluster ids, so the rebuild leaves the
    # verdict cache untouched — an unchanged cluster still hits cache under its
    # reassigned id. cluster_members must go before clusters (FK).
    conn.execute("DELETE FROM cluster_members")
    conn.execute("DELETE FROM clusters")
    components = [r[0] for r in conn.execute(
        "SELECT DISTINCT component_id FROM resolutions"
        " WHERE component_id NOT IN ('foreign','unresolved') ORDER BY 1")]
    total = 0
    for comp in components:
        rows = conn.execute(
            "SELECT e.id, e.title, e.rationale, e.domain FROM evidence e"
            " JOIN resolutions r ON r.evidence_id = e.id"
            " LEFT JOIN evidence_flags f ON f.evidence_id = e.id"
            " WHERE r.component_id = ? AND f.evidence_id IS NULL ORDER BY e.id",
            (comp,),
        ).fetchall()
        reps: list[tuple[int, str, str]] = []  # (cluster_id, domain, representative text)
        for row in rows:
            text = f"{row['title']} {row['rationale']}"
            for cid, dom, rep in reps:
                if dom == row["domain"] and jaccard(rep, text) >= _JACCARD_THRESHOLD:
                    conn.execute("INSERT INTO cluster_members VALUES (?,?)",
                                 (cid, row["id"]))
                    break
            else:
                cur = conn.execute(
                    "INSERT INTO clusters (component_id, domain, cluster_version)"
                    " VALUES (?,?,?)", (comp, row["domain"], CLUSTER_VERSION))
                cid = cur.lastrowid
                conn.execute("INSERT INTO cluster_members VALUES (?,?)",
                             (cid, row["id"]))
                reps.append((cid, row["domain"], text))
                total += 1
    conn.commit()
    return total
