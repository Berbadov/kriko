"""The payload reader: what an agent's reply becomes before it is a pack.

`read_payload` replaced a `_payload` that demanded either a fence ending
exactly in `}` or nothing before/after it. `raw_decode` is what changed —
an object followed by prose is a completed run now, not a lost one — and
this file is the acceptance test for that plus the fence-pairing bug it
shipped with: a greedy `.*` between the first fence and the *last* triple
backtick in the whole reply, which merges unrelated fenced blocks into one
capture whenever a reply carries more than one fence.
"""

import json

from app import packauthor


def _fence(obj: dict) -> str:
    return "```json\n" + json.dumps(obj) + "\n```"


def test_a_fenced_object_is_read():
    payload, note = packauthor.read_payload(_fence({"a": 1}))
    assert payload == {"a": 1}
    assert note == ""


def test_an_unfenced_object_is_read_just_as_well():
    payload, note = packauthor.read_payload('{"a": 1}')
    assert payload == {"a": 1}
    assert note == ""


def test_prose_before_and_after_the_fence_does_not_lose_the_object():
    text = ("I read a dozen threads on this.\n\n" + _fence({"a": 1}) +
            "\n\nLet me know if you want more detail.")
    payload, note = packauthor.read_payload(text)
    assert payload == {"a": 1}
    assert note == ""


def test_prose_before_and_after_an_unfenced_object():
    payload, _ = packauthor.read_payload(
        "Here is the pack: {\"a\": 1} — hope that helps.")
    assert payload == {"a": 1}


def test_two_fenced_objects_the_later_one_wins():
    """A model that reconsiders prints the correction after the draft."""
    text = _fence({"a": 1}) + "\n\nActually, better:\n\n" + _fence({"a": 2})
    payload, _ = packauthor.read_payload(text)
    assert payload == {"a": 2}


def test_two_unfenced_objects_the_later_one_wins():
    text = '{"a": 1} then I reconsidered and meant {"a": 2}'
    payload, _ = packauthor.read_payload(text)
    assert payload == {"a": 2}


def test_two_separate_fences_are_not_merged_into_one_swallowed_span():
    """The regression this file exists to pin down.

    A greedy `.*` between the opening of the *first* fence and the closing of
    the *last* triple-backtick anywhere in the reply would capture straight
    through an intervening fence's own backticks — still recoverable here
    because `_objects` rescans for `{` regardless, but only by accident. The
    real hazard is a fence that is not JSON at all sitting between two JSON
    fences: a swallowed span can smuggle characters from an unrelated fence
    into what looks like one match, so the fence boundaries have to be exact.
    """
    text = (
        _fence({"a": 1})
        + "\n\nAnd for reference, here is some code:\n\n"
        + "```python\nprint('not json, but has a { in a string too')\n```\n"
        + "\n\nNow the pack:\n\n"
        + _fence({"a": 2})
    )
    matches = packauthor._FENCE.findall(text)
    assert matches == ['{"a": 1}', '{"a": 2}']
    payload, _ = packauthor.read_payload(text)
    assert payload == {"a": 2}


def test_a_fenced_object_outranks_a_later_unfenced_one():
    text = _fence({"a": 1}) + '\n\nfor reference: {"schema": "example"}'
    payload, _ = packauthor.read_payload(text)
    assert payload == {"a": 1}


def test_a_truncated_object_is_repaired_and_says_so():
    text = '{"pack_id": "x", "lineup": ["a", "b", "c'
    payload, note = packauthor.read_payload(text)
    assert payload["pack_id"] == "x"
    assert payload["lineup"] == ["a", "b"]
    assert "stopped mid-object" in note


def test_a_truncated_object_cut_mid_string_falls_back_to_the_last_comma():
    text = '{"a": 1, "b": [1, 2, 3], "c": "half a str'
    payload, note = packauthor.read_payload(text)
    assert payload == {"a": 1, "b": [1, 2, 3]}
    assert "stopped mid-object" in note


def test_garbage_comes_back_empty_not_raising():
    payload, note = packauthor.read_payload("I could not find much, sorry.")
    assert payload == {}
    assert note == ""


def test_empty_string_comes_back_empty():
    assert packauthor.read_payload("") == ({}, "")


def test_none_like_input_is_tolerated():
    assert packauthor.read_payload(None) == ({}, "")


def test_a_huge_string_value_round_trips():
    big = "x" * 200_000
    payload, _ = packauthor.read_payload(_fence({"a": big}))
    assert payload["a"] == big


def test_unicode_survives_the_fence_and_the_repair_path():
    payload, _ = packauthor.read_payload(_fence({"name": "café ☃️ 東京"}))
    assert payload["name"] == "café ☃️ 東京"

    truncated = _fence({"name": "café ☃️ 東京", "note": "extra"})[:-15]
    payload, note = packauthor.read_payload(truncated)
    assert payload.get("name") == "café ☃️ 東京" or note


def test_a_nested_object_used_as_an_example_inside_the_real_one_is_not_split():
    """`_objects` walks with `raw_decode`, so a nested `{...}` must not be
    mistaken for a second top-level object."""
    nested = {"pack_id": "x", "coverage": {"note": "n", "out_of_scope": []}}
    payload, _ = packauthor.read_payload(_fence(nested))
    assert payload == nested


def test_author_still_refuses_a_reply_with_no_json_at_all(tmp_path):
    import pytest

    from app import packauthor as pa

    with pytest.raises(pa.PackRefused, match="no JSON"):
        pa.author(tmp_path / "k.sqlite", "nothing here", category="drills")
