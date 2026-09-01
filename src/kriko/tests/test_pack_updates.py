"""The update decision, which is the half that must never guess."""

import json

import pytest

from kriko.pack import updates


def row(pack_id="cars", version="1.0.0", digest="d1"):
    return {"pack_id": pack_id, "version": version, "content_digest": digest}


def offer(**kw):
    base = dict(pack_id="cars", version="1.1.0", url="https://x/cars.kpack")
    return updates.Candidate(**(base | kw))


def test_a_newer_version_is_offered():
    d = updates.decide(row(), offer(content_digest="d2"))
    assert d.state == updates.AVAILABLE
    assert d.actionable
    assert "1.0.0 → 1.1.0" == d.reason


def test_the_same_version_and_digest_is_up_to_date():
    d = updates.decide(row(), offer(version="1.0.0", content_digest="d1"))
    assert d.state == updates.UP_TO_DATE


def test_republishing_a_version_with_different_content_is_refused():
    # Mirrors packstore.install's rule. Caught here so the refusal costs a
    # comparison rather than a download.
    d = updates.decide(row(), offer(version="1.0.0", content_digest="d2"))
    assert d.state == updates.REFUSED
    assert not d.actionable
    assert "may not be republished" in d.reason


def test_an_older_version_is_not_an_update():
    d = updates.decide(row(version="2.0.0"), offer(version="1.9.0"))
    assert d.state == updates.UP_TO_DATE


def test_ten_sorts_above_nine():
    assert updates._parts("0.10.0") > updates._parts("0.9.0")
    assert updates.decide(row(version="0.9.0"), offer(version="0.10.0")).actionable


def test_a_renumber_with_identical_knowledge_is_not_an_update():
    d = updates.decide(row(digest="same"), offer(version="1.2.0", content_digest="same"))
    assert d.state == updates.UP_TO_DATE
    assert "nothing new to learn" in d.reason


def test_a_pack_missing_from_the_index_is_unknown_not_stale():
    d = updates.decide(row(), None)
    assert d.state == updates.UNKNOWN


def test_a_blank_version_cannot_be_ordered():
    assert updates.decide(row(version=""), offer()).state == updates.UNKNOWN
    assert updates.decide(row(), offer(version="")).state == updates.UNKNOWN


def test_the_index_parses_both_shapes():
    entry = {"pack_id": "cars", "version": "1.1.0", "url": "u", "sha256": "abc"}
    assert updates.parse_index(json.dumps({"packs": [entry]}))[0].sha256 == "abc"
    assert updates.parse_index(json.dumps([entry]))[0].pack_id == "cars"


def test_a_malformed_row_is_skipped_not_fatal():
    text = json.dumps({"packs": [{"version": "1"}, {"pack_id": "cars", "url": "u"}]})
    got = updates.parse_index(text)
    assert [c.pack_id for c in got] == ["cars"]


def test_plan_keeps_installed_order_and_covers_every_pack():
    rows = [row(pack_id="drill"), row(pack_id="cars")]
    got = updates.plan(rows, [offer(content_digest="d2")])
    assert [d.pack_id for d in got] == ["drill", "cars"]
    assert [d.state for d in got] == [updates.UNKNOWN, updates.AVAILABLE]


def test_a_bad_index_raises_rather_than_returning_nothing():
    with pytest.raises(json.JSONDecodeError):
        updates.parse_index("not json")
