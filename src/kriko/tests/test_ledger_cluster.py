import pytest

from kriko.ledger import cluster, db


@pytest.fixture
def conn(tmp_path):
    return db.connect(tmp_path / "l.db")


def _resolved_evidence(
    conn, title, rationale, component="keyless_chuck_13", domain="mechanical",
    flagged=False, url=None
):
    doc_id = db.insert_document(
        conn,
        url=url or f"https://x.test/{title[:12]}",
        source_type="page",
        raw_text=title,
    )
    ev_id = db.insert_evidence(
        conn,
        doc_id=doc_id,
        claim={
            "title": title,
            "domain": domain,
            "severity": "high",
            "rationale": rationale,
            "inspection_advice": "",
            "quote": "",
            "engine_or_variant_hint": None,
            "quote_grounded": False,
        },
        span_start=None,
        span_end=None,
        extractor_version=2,
    )
    conn.execute(
        "INSERT INTO resolutions VALUES (?,?,?,?)", (ev_id, component, "alias", 1)
    )
    if flagged:
        db.flag_low_value(conn, ev_id, "test flag")
    conn.commit()
    return ev_id


def test_similar_claims_cluster_together(conn):
    a = _resolved_evidence(
        conn,
        "Keyless chuck bearing wear on the DHP484",
        "the chuck bearing wears causing runout",
    )
    b = _resolved_evidence(
        conn,
        "Chuck bearing runout on DHP484 drills",
        "bearing wear lets the chuck develop runout",
    )
    _resolved_evidence(
        conn,
        "DHP484 battery pack capacity loss",
        "cells degrade allowing less runtime at high charge cycles",
    )
    n = cluster.rebuild_clusters(conn)
    assert n == 2
    cid = conn.execute(
        "SELECT cluster_id FROM cluster_members WHERE evidence_id=?", (a,)
    ).fetchone()[0]
    members = {
        r[0]
        for r in conn.execute(
            "SELECT evidence_id FROM cluster_members WHERE cluster_id=?", (cid,)
        )
    }
    assert members == {a, b}


def test_foreign_unresolved_and_flagged_excluded(conn):
    _resolved_evidence(conn, "Dyson digital motor failure", "wrong product", component="foreign")
    _resolved_evidence(conn, "vague issue", "no idea", component="unresolved")
    _resolved_evidence(conn, "LED indicator flicker", "generic", flagged=True)
    assert cluster.rebuild_clusters(conn) == 0


def test_rebuild_is_deterministic(conn):
    _resolved_evidence(conn, "Keyless chuck bearing wear on the DHP484", "runout")
    _resolved_evidence(conn, "DHP484 motor housing crack", "housing cracks near the motor mount")
    first = cluster.rebuild_clusters(conn)
    rows1 = conn.execute("SELECT * FROM cluster_members ORDER BY 1,2").fetchall()
    second = cluster.rebuild_clusters(conn)
    rows2 = conn.execute("SELECT * FROM cluster_members ORDER BY 1,2").fetchall()
    assert first == second and [tuple(r) for r in rows1] == [tuple(r) for r in rows2]


def test_rebuild_preserves_content_addressed_verdicts(conn):
    # Regression: verdicts are keyed by input_hash, not cluster_id. A rebuild
    # with a live verdict row must neither raise a FOREIGN KEY error nor evict
    # the cached verdict (that is what makes reruns cost $0).
    _resolved_evidence(conn, "Keyless chuck bearing wear on the DHP484", "runout")
    cluster.rebuild_clusters(conn)
    conn.execute(
        "INSERT INTO verdicts (input_hash, llm, verdict_json, tokens_in,"
        " tokens_out, usd, created_at) VALUES ('h1','m','{}',1,1,0.0,'now')"
    )
    conn.commit()
    cluster.rebuild_clusters(conn)  # must not raise
    assert conn.execute("SELECT COUNT(*) FROM verdicts").fetchone()[0] == 1
