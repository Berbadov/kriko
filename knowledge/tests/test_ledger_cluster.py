import pytest
from knowledge.ledger import cluster, db


@pytest.fixture
def conn(tmp_path):
    return db.connect(tmp_path / "l.db")


def _resolved_evidence(conn, title, rationale, component="ea888",
                       domain="engine", flagged=False, url=None):
    doc_id = db.insert_document(conn, url=url or f"https://x.test/{title[:12]}",
                                source_type="page", raw_text=title)
    ev_id = db.insert_evidence(conn, doc_id=doc_id, claim={
        "title": title, "domain": domain, "severity": "high",
        "rationale": rationale, "inspection_advice": "", "quote": "",
        "engine_or_variant_hint": None, "quote_grounded": False,
    }, span_start=None, span_end=None, extractor_version=2)
    conn.execute("INSERT INTO resolutions VALUES (?,?,?,?)",
                 (ev_id, component, "alias", 1))
    if flagged:
        db.flag_low_value(conn, ev_id, "test flag")
    conn.commit()
    return ev_id


def test_similar_claims_cluster_together(conn):
    a = _resolved_evidence(conn, "EA888 timing chain tensioner failure",
                           "timing chain tensioner wears causing chain stretch")
    b = _resolved_evidence(conn, "Timing chain stretch on EA888 engines",
                           "tensioner failure lets the timing chain stretch")
    _resolved_evidence(conn, "EA888 excessive oil consumption",
                       "piston rings allow oil burning at high mileage")
    n = cluster.rebuild_clusters(conn)
    assert n == 2
    cid = conn.execute("SELECT cluster_id FROM cluster_members WHERE evidence_id=?",
                       (a,)).fetchone()[0]
    members = {r[0] for r in conn.execute(
        "SELECT evidence_id FROM cluster_members WHERE cluster_id=?", (cid,))}
    assert members == {a, b}


def test_foreign_unresolved_and_flagged_excluded(conn):
    _resolved_evidence(conn, "BMW N47 chain failure", "wrong car", component="foreign")
    _resolved_evidence(conn, "vague issue", "no idea", component="unresolved")
    _resolved_evidence(conn, "ABS light", "generic", flagged=True)
    assert cluster.rebuild_clusters(conn) == 0


def test_rebuild_is_deterministic(conn):
    _resolved_evidence(conn, "EA888 timing chain tensioner failure", "stretch")
    _resolved_evidence(conn, "EA888 water pump leak", "coolant loss from pump")
    first = cluster.rebuild_clusters(conn)
    rows1 = conn.execute("SELECT * FROM cluster_members ORDER BY 1,2").fetchall()
    second = cluster.rebuild_clusters(conn)
    rows2 = conn.execute("SELECT * FROM cluster_members ORDER BY 1,2").fetchall()
    assert first == second and [tuple(r) for r in rows1] == [tuple(r) for r in rows2]
