"""The drill pack — the format's falsification test.

These are not tests about drills. Each one asserts that a shape the old
car-centric schema could not express now works, and that the engine needed no
change to express it.
"""

import pytest

from kriko.pack import build
from kriko.store import ids, packstore
from kriko.store.db import connect

PACK_ROOT = "packs/drill"


@pytest.fixture(scope="module")
def pack(tmp_path_factory):
    return build.build(PACK_ROOT, tmp_path_factory.mktemp("dist") / "drill.kpack")


@pytest.fixture
def store(pack, tmp_path):
    conn = connect(tmp_path / "store.sqlite")
    packstore.install(conn, pack)
    yield conn
    conn.close()


def _subject(store, kind, identity):
    return ids.subject_id(kind, identity)


def test_the_pack_builds_and_installs(store):
    assert packstore.enabled_pack_ids(store) == ["org.kriko.drill"]


def test_no_car_vocabulary_survives_into_the_store(store):
    """The engine holds a category whose vocabulary shares nothing with cars."""
    terms = {r[0] for r in store.execute("SELECT term_id FROM terms")}
    assert {"charge_cycles", "usage_hours", "chuck_size_mm"} <= terms
    assert not terms & {"engine_code", "fuel", "displacement_cc", "mileage_km",
                        "transmission_code"}


def test_a_product_with_no_components_still_carries_claims(store):
    """The Einhell has zero relations. That must be ordinary, not a special case."""
    subject = _subject(store, "product",
                       {"brand": "einhell", "model": "TC-CD-18-2"})
    rels = store.execute(
        "SELECT COUNT(*) FROM relations WHERE subject_id = ?", (subject,)).fetchone()[0]
    claims = store.execute(
        "SELECT COUNT(*) FROM claims WHERE subject_id = ?", (subject,)).fetchone()[0]
    assert rels == 0
    assert claims == 1


def test_absence_is_a_missing_row_not_a_null(store):
    """The Einhell has no chuck_size_mm. There is no NULL and no sentinel."""
    subject = _subject(store, "product",
                       {"brand": "einhell", "model": "TC-CD-18-2"})
    keys = {r[0] for r in store.execute(
        "SELECT key FROM attributes WHERE subject_id = ?", (subject,))}
    assert "chuck_size_mm" not in keys
    assert "voltage_v" in keys


def test_a_shared_platform_reaches_every_tool_on_it(store):
    """Same traversal that lets an engine-code claim reach every car fitted with it."""
    platform = _subject(store, "battery_platform",
                        {"brand": "makita", "platform": "LXT"})
    tools = {r[0] for r in store.execute(
        "SELECT s.label FROM relations r JOIN subjects s USING (subject_id, pack_id)"
        " WHERE r.object_id = ? AND r.predicate = 'part_of'", (platform,))}
    assert len(tools) == 2
    assert all("Makita DHP48" in t for t in tools)


def test_wear_is_measured_in_the_pack_s_own_units(store):
    """Cars use km; this pack uses cycles and hours, and the engine does not care."""
    keys = {r[0] for r in store.execute(
        "SELECT DISTINCT key FROM claim_conditions")}
    assert keys == {"charge_cycles", "usage_hours", "age_years"}
    units = dict(store.execute(
        "SELECT term_id, unit FROM terms WHERE role = 'context_key'"))
    assert units["charge_cycles"] == "cycles"
    assert units["usage_hours"] == "hours"


def test_a_disputed_claim_keeps_both_sides(store):
    """`refutes` is what makes 'no authority' usable rather than merely stored."""
    stances = {r[0] for r in store.execute(
        "SELECT DISTINCT stance FROM evidence")}
    assert stances == {"supports", "refutes"}

    (disputed,) = store.execute(
        "SELECT ct.title FROM evidence e"
        " JOIN claim_text ct USING (claim_id, pack_id)"
        " WHERE e.stance = 'refutes' AND ct.lang = 'en'").fetchone()
    assert "Cell imbalance" in disputed


def test_language_is_a_row_so_a_claim_can_carry_any_number(store):
    langs = {r[0] for r in store.execute("SELECT DISTINCT lang FROM claim_text")}
    assert {"en", "tr"} <= langs
    # And the columns that used to hold Turkish do not exist.
    cols = {r[1] for r in store.execute("PRAGMA table_info(claim_text)")}
    assert not any(c.endswith("_tr") for c in cols)


def test_all_evidence_is_marked_synthetic_by_its_domain(store):
    """Guard rail: this pack must never look like a real source.

    example.invalid is reserved by RFC 2606 and cannot resolve, so a reader who
    follows a link gets nothing rather than a plausible-looking page.
    """
    domains = {r[0] for r in store.execute("SELECT DISTINCT domain FROM sources")}
    assert domains == {"example.invalid"}


def test_uninstalling_the_drill_pack_empties_the_store(store):
    packstore.uninstall(store, "org.kriko.drill")
    for table in ("subjects", "claims", "attributes", "relations", "evidence"):
        assert store.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
