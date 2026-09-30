"""Browse filters and History categories come from API rows (B180, B182).

The reader asked for filters by pack, kind, evidence and severity, and for
History "categorised by the product". `ui/` may hold no pack vocabulary, so
the filter names, descriptions and options are rows the API returns, and a
check's category is the name of the pack that answered it.

Runs on `test_web.py`'s store, a tools pack: nothing here knows a category.
"""

from app.tests import test_web

#: The same store fixture, under this module's name.
client = test_web.client


def _filters(client):
    rows = client.get("/api/subjects/filters").json()["filters"]
    return {row["id"]: row for row in rows}


def test_the_filters_are_rows_each_with_a_description_and_counted_options(client):
    filters = _filters(client)
    assert list(filters) == ["pack", "kind", "evidence", "severity"]
    for row in filters.values():
        assert row["label"] and row["param"] and row["description"]
        assert row["options"], row["id"]
        assert all(o["value"] and o["label"] for o in row["options"])
    # The pack's own name, not its id, is what the reader picks.
    assert [o["label"] for o in filters["pack"]["options"]] == ["Tools"]
    assert sum(o["count"] for o in filters["kind"]["options"]) == 4


def test_subjects_filter_by_severity_and_evidence(client):
    high = client.get("/api/subjects?severity=high").json()
    assert [s["label"] for s in high] == ["LXT 18V"]
    single = client.get("/api/subjects?evidence=single").json()
    assert {s["label"] for s in single} == {"LXT 18V", "Widget Bit"}
    none = client.get("/api/subjects?evidence=none").json()
    assert {s["label"] for s in none} == {"Makita DHP484", "Orphan Tool"}
    both = client.get("/api/subjects?severity=low&evidence=single").json()
    assert [s["label"] for s in both] == ["Widget Bit"]


def test_a_filter_value_no_subject_has_returns_nothing_not_everything(client):
    assert client.get("/api/subjects?evidence=corroborated").json() == []
    assert client.get("/api/subjects?severity=nonsense").json() == []


def _history_item(client, identity):
    looked = client.post(
        "/api/lookup",
        json={"kind": "product", "identity": identity, "context": {}},
    ).json()
    return next(
        i
        for i in client.get("/api/history").json()["items"]
        if i["lookup_id"] == looked["lookup_id"]
    )


def test_history_carries_the_category_the_pack_names(client):
    item = _history_item(client, {"brand": "acme", "model": "widget"})
    assert item["category"] == "Tools"
    assert item["packs"] == [{"pack_id": "tools", "name": "Tools"}]


def test_a_check_no_pack_answered_has_no_category(client):
    item = _history_item(client, {"brand": "nobody", "model": "zz"})
    assert item["category"] == ""
    assert item["packs"] == []
