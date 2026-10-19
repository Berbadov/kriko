"""Deterministic evidence clustering per component.

Greedy single-pass in evidence-id order (stable, deterministic): an evidence
row joins the first existing cluster in the same domain whose representative
text has word-Jaccard >= 0.4 — the same threshold *and now the same tokeniser*
as the read-time dedup in `kriko.text.title_sim`, which this module imports
rather than reimplements — else it founds a new cluster. clusters/cluster_members
are derived tables — rebuilt wholesale, never migrated."""

from kriko.text.title_sim import similarity

#: Bumped with the tokeniser below: cluster membership changed, and the derived
#: tables are rebuilt wholesale, while verdicts stay content-addressed by
#: input_hash and so keep hitting their cache.
CLUSTER_VERSION = 2
_JACCARD_THRESHOLD = 0.4


def jaccard(a: str, b: str) -> float:
    """Token-set overlap, using the *read-time* tokeniser.

    This module used to carry its own, which dropped every digit
    (`[^\\W\\d_]{3,}`). "E90 timing chain" and "E91 timing chain" then tokenised
    identically and merged, while the same two titles arriving through a lookup
    — `kriko.text.title_sim` — stayed apart, because that tokeniser keeps digits
    and its own docstring calls discarding a number "catastrophic". Two dedup
    paths disagreeing about whether a part number matters is a worse defect than
    either threshold, so there is one tokeniser now.
    """
    return similarity(a, b)


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
