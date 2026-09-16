"""The acceptance boundary a brief cannot enforce by itself.

The reader's report: a Samsung headphones pack came back with a *watch* in
it, covering 19 of 20 products, named as a sentence. The brief was rewritten
to demand the full line-up, the right scope, and a real name — but advice is
not a mechanism, and an agent can talk past a brief. These tests are for the
code that catches it instead:

* a subject the agent's own line-up never named is quarantined, not shipped
  and not silently dropped;
* a pack with no `lineup` at all is refused, because a gap nobody can see is
  worse than one that is visible;
* the amend path's cross-check uses the *existing* draft's line-up too, so
  quarantine still applies to an addition that never repeats the original
  line-up.
"""

import json

import pytest
import yaml

from app import packauthor, packdraft


def _pack(**over) -> dict:
    base = {
        "pack_id": "samsung.earbuds",
        "name": "Samsung earbuds",
        "lineup": ["Galaxy Buds Pro", "Galaxy Buds2 Pro"],
        "identity": {"product": ["brand", "series"]},
        "principle": "What owners report going wrong, not spec opinions.",
        "templates": ["{label} battery drain"],
        "domains": [{"id": "battery", "label": "Battery"}],
        "subjects": [
            {"kind": "product", "label": "Galaxy Buds Pro",
             "identity": {"brand": "samsung", "series": "galaxy buds pro"}},
            {"kind": "product", "label": "Galaxy Watch6",
             "identity": {"brand": "samsung", "series": "galaxy watch6"}},
        ],
        "claims": [
            {"subject": {"kind": "product",
                         "identity": {"brand": "samsung",
                                      "series": "galaxy watch6"}},
             "domain": "battery", "severity": "medium",
             "title": "Watch battery degrades", "body": "b", "advice": "a"},
        ],
    }
    return {**base, **over}


def _reply(payload: dict) -> str:
    return "```json\n" + json.dumps(payload) + "\n```"


def _store(tmp_path):
    return tmp_path / "k.sqlite"


def test_a_subject_outside_the_line_up_is_quarantined_not_shipped(tmp_path):
    written = packauthor.author(_store(tmp_path), _reply(_pack()),
                                category="samsung headphones")
    assert written["subjects"] == 1
    quarantined = written["quarantined"]
    assert len(quarantined) == 1
    assert quarantined[0]["label"] == "Galaxy Watch6"
    assert "line-up" in quarantined[0]["reason"]

    draft = packdraft.open_draft(_store(tmp_path), written["slug"])
    subjects = yaml.safe_load(
        (draft.root / "data" / "subjects.yaml").read_text(encoding="utf-8"))
    assert all(row["label"] != "Galaxy Watch6" for row in subjects)


def test_a_claim_about_the_quarantined_subject_is_dropped_too(tmp_path):
    written = packauthor.author(_store(tmp_path), _reply(_pack()),
                                category="samsung headphones")
    assert written["claims"] == 0


def test_the_reason_is_recorded_in_the_coverage_file_not_only_the_response(
    tmp_path
):
    written = packauthor.author(_store(tmp_path), _reply(_pack()),
                                category="samsung headphones")
    draft = packdraft.open_draft(_store(tmp_path), written["slug"])
    coverage = yaml.safe_load(
        (draft.root / "research" / "coverage.yaml").read_text(encoding="utf-8"))
    assert coverage["quarantined"][0]["label"] == "Galaxy Watch6"


def test_a_subject_matching_the_line_up_by_fuzzy_text_is_kept(tmp_path):
    """The match is the same one `_coverage` already uses, so a subject
    written slightly differently from its own line-up entry is not punished
    for it."""
    pack = _pack(lineup=["Galaxy Buds Pro (2024)", "Galaxy Buds2 Pro"],
                subjects=[_pack()["subjects"][0]], claims=[])
    written = packauthor.author(_store(tmp_path), _reply(pack),
                                category="samsung headphones")
    assert written["subjects"] == 1
    assert written["quarantined"] == []


def test_a_subject_declared_out_of_scope_is_quarantined_with_that_reason(
    tmp_path
):
    pack = _pack(coverage={"out_of_scope": ["Galaxy Watch6"]})
    written = packauthor.author(_store(tmp_path), _reply(pack),
                                category="samsung headphones")
    assert written["quarantined"][0]["reason"].startswith(
        "the pack's own coverage.out_of_scope")


def test_a_pack_with_no_lineup_is_refused_rather_than_reporting_full_coverage(
    tmp_path
):
    pack = _pack()
    pack.pop("lineup")
    with pytest.raises(packauthor.PackRefused, match="lineup"):
        packauthor.author(_store(tmp_path), _reply(pack), category="drills")
    assert not packdraft.drafts_root(_store(tmp_path)).exists()


def test_an_empty_lineup_list_is_refused_the_same_way(tmp_path):
    with pytest.raises(packauthor.PackRefused, match="lineup"):
        packauthor.author(_store(tmp_path), _reply(_pack(lineup=[])),
                          category="drills")


def _drafted(tmp_path):
    pack = _pack(subjects=[_pack()["subjects"][0]], claims=[])
    return packauthor.author(_store(tmp_path), _reply(pack),
                             category="samsung headphones")


def test_an_amendment_outside_the_original_line_up_is_quarantined(tmp_path):
    """The original line-up never went away just because the amend reply
    forgot to repeat it — the agent adding a watch to an earbuds pack is the
    same defect whether it happens on the first run or the fifth."""
    drafted = _drafted(tmp_path)
    addition = {
        "subjects": [
            {"kind": "product", "label": "Galaxy Watch6",
             "identity": {"brand": "samsung", "series": "galaxy watch6"}},
        ],
    }
    with pytest.raises(packauthor.PackRefused, match="quarantined"):
        packauthor.amend(_store(tmp_path), drafted["slug"], _reply(addition))


def test_an_amendment_can_still_extend_the_line_up_and_add_to_it(tmp_path):
    drafted = _drafted(tmp_path)
    addition = {
        "lineup": ["Galaxy Buds Live"],
        "subjects": [
            {"kind": "product", "label": "Galaxy Buds Live",
             "identity": {"brand": "samsung", "series": "galaxy buds live"}},
        ],
    }
    result = packauthor.amend(_store(tmp_path), drafted["slug"], _reply(addition))
    assert result["subjects_added"] == 1
    assert result["quarantined"] == []
