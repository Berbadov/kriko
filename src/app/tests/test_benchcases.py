"""The fixed test set (B185, D6): versioned, shipped, identical everywhere."""

from app import benchcases


def test_the_set_loads_and_names_itself():
    found = benchcases.load()
    assert len(found) >= 3
    for case in found:
        assert case["product"]
        assert case["queries"], f"{case['id']} names no queries"
        assert case["must_find"], f"{case['id']} has no ground truth"
        assert case["kind"] == "fixed"


def test_every_case_is_stamped_with_the_sets_identity():
    rows = benchcases.case_rows(3)
    assert len(rows) == 3
    for row in rows:
        assert row["set_id"] == benchcases.SET_ID
        assert row["set_version"] == benchcases.SET_VERSION


def test_the_limit_is_applied_in_file_order():
    """Stable on purpose: a versioned set promises the same first cases."""
    whole = benchcases.load()
    limited = benchcases.case_rows(2)
    assert [one["id"] for one in limited] == [one["id"] for one in whole[:2]]


def test_the_set_mentions_no_installed_pack():
    """D6: fixed tests, never the reader's own catalogs. The cases name
    products and ground truth, never a pack id."""
    for case in benchcases.load():
        assert "pack" not in case or not case.get("pack")
