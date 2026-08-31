"""The interface's own store, deliberately not the engine's.

Lookup history is an app/ concern. Putting it in knowledge.sqlite would add the
first tables in kriko/store/schema.sql that nothing in kriko/ reads — a layering
violation expressed as schema rather than as an import. The practical version:
uninstalling a pack must not drop your history, and a history table must never
appear in a .kpack diff.
"""

from app.web import state
from app.web.settings import Settings


def test_records_and_reads_back_a_lookup(tmp_path):
    conn = state.connect(tmp_path / "app.sqlite")
    lookup_id = state.record_lookup(
        conn,
        source="ask",
        label="Bench Grinder 8in",
        request={"kind": "product", "identity": {"brand": "acme"}},
        response={"method": "exact", "claims": [{"title": "A"}, {"title": "B"}]},
    )
    row = state.get_lookup(conn, lookup_id)
    assert row["label"] == "Bench Grinder 8in"
    assert row["source"] == "ask"
    assert row["request"]["kind"] == "product"
    assert len(row["response"]["claims"]) == 2


def test_recent_is_newest_first_and_counts_claims(tmp_path):
    conn = state.connect(tmp_path / "app.sqlite")
    for name in ("first", "second"):
        state.record_lookup(
            conn,
            source="ask",
            label=name,
            request={},
            response={"claims": [{"title": "x"}]},
        )
    rows = state.recent(conn)
    assert [r["label"] for r in rows] == ["second", "first"]
    assert rows[0]["claim_count"] == 1


def test_recent_honours_its_limit(tmp_path):
    conn = state.connect(tmp_path / "app.sqlite")
    for n in range(5):
        state.record_lookup(
            conn, source="ask", label=str(n), request={}, response={"claims": []}
        )
    assert len(state.recent(conn, limit=2)) == 2


def test_missing_lookup_is_none_not_an_error(tmp_path):
    conn = state.connect(tmp_path / "app.sqlite")
    assert state.get_lookup(conn, "nope") is None


def test_delete_reports_whether_it_deleted_anything(tmp_path):
    conn = state.connect(tmp_path / "app.sqlite")
    lookup_id = state.record_lookup(
        conn, source="ask", label="x", request={}, response={"claims": []}
    )
    assert state.delete_lookup(conn, lookup_id) is True
    assert state.delete_lookup(conn, lookup_id) is False


def test_settings_keeps_ui_state_beside_the_store_but_separate(tmp_path):
    settings = Settings()
    assert settings.app_state_path != settings.store_path
    assert settings.app_state_path.name == "app.sqlite"
