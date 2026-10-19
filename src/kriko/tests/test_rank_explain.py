"""extension-10: `explain()`'s reasons read as prose, not as a diagnostic dump.

Found in the B145 audit: "applies through the part of it shares" was the
`via="part_of:..."` reason shown on every claim reached through a shared part
— ungrammatical on 7 of 8 risks in the audit's fixtures. The panel renders
each `why` entry as its own chip, so the sentence has to stand on its own.
"""

from kriko.lookup.rank import explain


def test_a_claim_reached_through_a_shared_part_reads_as_prose():
    why = explain(
        severity="high", detection="documented", trust=0.5, tier="unknown",
        disputed=False, condition_reasons=(), via="part_of:golf7_body",
        pack_id="org.kriko.cars",
    )
    assert "applies through a part it shares" in why
    assert "of it shares" not in " ".join(why)


def test_a_claim_reached_some_other_way_names_that_kind():
    why = explain(
        severity="high", detection="documented", trust=0.5, tier="unknown",
        disputed=False, condition_reasons=(), via="sibling_code:ea288",
        pack_id="org.kriko.cars",
    )
    assert "applies through its sibling code" in why
