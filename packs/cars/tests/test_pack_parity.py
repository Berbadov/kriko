"""Does the cars pack still answer the way it did when parity was proved?

**The engine this was once compared against no longer exists.** Until
2026-08-26 these tests replayed 98 real listings through both the old
`backend/` serving stack and the new one and asserted agreement on the thing
that would actually hurt a buyer: nothing the old engine surfaced may vanish.
Those assertions ran green, and then `backend/` was deleted.

What survives is `fixtures/parity_golden.jsonl` — a recording of the new
engine's answers made *while* the comparison was still possible. It is now the
only regression net under the largest deletion in the project, which is why it
was captured two phases before the deletion rather than alongside it.

Three divergences from the old engine were deliberate and are recorded in
`README.md` and the backlog: status became rank (B26), year windows went soft
(B9), and part attribution got stricter. The golden encodes the behaviour
*after* those decisions.

Regenerate only for an intended serving change:

    pytest packs/cars --regenerate-golden

and read the diff. A golden regenerated without reading the diff is not a
regression net, it is a rubber stamp.
"""

import json
from datetime import date
from pathlib import Path

import pytest

from kriko.lookup import lookup
from kriko.lookup.query import Query
from kriko.store import packstore
from kriko.store.db import connect
from packs.cars.build import build

REPO = Path(__file__).resolve().parent.parent.parent.parent
GOLD = REPO / "backend" / "tests" / "fixtures" / "serving_gold"
ANALYSES = REPO / "logs" / "analyses.jsonl"
GOLDEN = Path(__file__).parent / "fixtures" / "parity_golden.jsonl"
CASES = Path(__file__).parent / "fixtures" / "replay_cases.jsonl"


# ── fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def new_engine(tmp_path_factory):
    out = tmp_path_factory.mktemp("dist")
    pack, report = build(out / "cars.kpack")
    store = connect(out / "store.sqlite")
    packstore.install(store, pack)
    yield store, {v: k for k, v in report["id_map"].items()}
    store.close()


@pytest.fixture(scope="module")
def cases():
    """The frozen replay corpus.

    Read from a committed file rather than from logs/analyses.jsonl, which keeps
    growing: a golden compared against a moving corpus fails for reasons that
    have nothing to do with the engine.
    """
    return [(r["case"], r["ad_metadata"]) for r in
            (json.loads(line) for line in
             CASES.read_text(encoding="utf-8").splitlines() if line.strip())]


# ── the two engines, driven the same way ─────────────────────────────────

def _new(store, meta, limit=1000):
    year = meta.get("year")
    identity = {"make": meta.get("make"), "model": meta.get("model"),
                "fuel": meta.get("fuel_type"),
                "displacement_cc": meta.get("engine_volume_cc"),
                "power_min_hp": meta.get("power_hp"),
                "transmission": meta.get("transmission"),
                "build_year": year}
    context = {"usage_km": meta.get("mileage_km"),
               "age_years": (date.today().year - year) if year else None,
               "build_year": year,
               "free_text": meta.get("description", ""),
               "equipment": meta.get("equipment") or []}
    return lookup(store, Query(
        kind="product",
        identity={k: v for k, v in identity.items() if v not in (None, "")},
        context={k: v for k, v in context.items() if v not in (None, "", [])},
        limit=limit))


# ── the gates ────────────────────────────────────────────────────────────

def test_the_gearbox_failures_are_still_covered_from_the_right_part(new_engine):
    """The other half of KNOWN_ATTRIBUTION_FIXES: the failures are not lost.

    The old engine served DC4 gearbox faults to a diesel Mégane out of the h5f
    *petrol engine's* part file — a car not fitted with that engine at all. The
    new engine reaches claims through fitment, so the same faults arrive from
    the DC4 part, where they belong.
    """
    store, _ = new_engine
    result = _new(store, {"make": "Renault", "model": "Megane",
                          "fuel_type": "Dizel", "engine_volume_cc": 1461,
                          "power_hp": 110, "transmission": "Otomatik",
                          "year": 2018, "mileage_km": 150_000}, limit=100)

    # Transmission-domain claims may legitimately come from several parts — the
    # body-electrics file carries gear-selector wiring, for instance. What
    # matters is that the DC4 gearbox itself is reached and answers.
    from_dc4 = [c for c in result.claims
                if "DC4" in c.subject_label or "EDC" in c.subject_label]
    assert len(from_dc4) >= 8, "the DC4 gearbox's own claims must reach this car"
    assert any("jerk" in c.title.lower() or "shift" in c.title.lower()
               for c in from_dc4), "the shift-quality failure must still surface"


def test_review_status_lowers_rank_instead_of_hiding_the_claim(new_engine):
    """B26, asserted. 696 of 699 claims are unreviewed; none may be hidden."""
    store, _ = new_engine
    total = store.execute("SELECT COUNT(*) FROM claims").fetchone()[0]
    assert total == 699, "every claim in the catalog must be exported"

    confidences = [r[0] for r in store.execute(
        "SELECT DISTINCT author_confidence FROM claims WHERE author_confidence IS NOT NULL")]
    assert confidences, "status must survive as rank"
    assert min(confidences) > 0, "no exported claim may be rank-zeroed"


# ── the frozen record ────────────────────────────────────────────────────

def test_golden_output_is_stable(new_engine, cases, request):
    """Freeze what the new engine answers, while the old one still exists.

    Phase 6 deletes `backend/`, and every test above dies with it. This one
    survives, because it compares the new engine against a recording of itself
    made while the comparison was still possible. Without this file the largest
    deletion in the project would have no regression net at all.

    Regenerate deliberately: `pytest --regenerate-golden` after an intended
    serving change, and read the diff.
    """
    store, to_legacy = new_engine
    actual = []
    for name, meta in cases:
        result = _new(store, meta, limit=8)
        actual.append({
            "case": name,
            "variants": sorted(to_legacy.get(s, s) for s in result.resolution.subject_ids),
            "method": result.resolution.method,
            "coverage": result.coverage,
            "claims": [c.title for c in result.claims],
        })

    if not GOLDEN.exists() or request.config.getoption("--regenerate-golden"):
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(
            "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True)
                      for row in actual) + "\n", encoding="utf-8")
        pytest.skip(f"recorded {len(actual)} golden rows at {GOLDEN.name}")

    expected = [json.loads(line) for line in
                GOLDEN.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(actual) == len(expected)

    drifted = [f"{a['case']}: {a} != {e}"
               for a, e in zip(actual, expected) if a != e]
    assert drifted == [], (
        f"{len(drifted)} case(s) drifted from the golden record:\n  "
        + "\n  ".join(drifted[:5]))
