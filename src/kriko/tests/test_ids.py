"""Content-addressed IDs — the mechanism two packs dedupe by.

The honest scope of these hashes (see backlog G6): they give *exact-agreement*
dedup. Two authors who normalise a value the same way collapse to one row; two
authors who disagree about what makes a subject distinct do not, and that is
correct — those really are two different assertions. Near-agreement is the
lookup path's job, not the hash's.
"""

import pytest

from kriko.store import ids


def test_hash_is_stable_across_calls():
    a = ids.subject_id("product", {"make": "volkswagen", "model": "golf"})
    b = ids.subject_id("product", {"make": "volkswagen", "model": "golf"})
    assert a == b


def test_hash_is_order_independent():
    """Identity is a set of key/value pairs, not a sequence of them."""
    a = ids.subject_id("product", {"make": "volkswagen", "model": "golf"})
    b = ids.subject_id("product", {"model": "golf", "make": "volkswagen"})
    assert a == b


def test_hash_normalises_case_and_whitespace():
    a = ids.subject_id("product", {"make": "Volkswagen", "model": "  Golf "})
    b = ids.subject_id("product", {"make": "volkswagen", "model": "golf"})
    assert a == b


def test_hash_normalises_numeric_punctuation():
    """'1,395' and '1395' and 1395 are the same displacement."""
    a = ids.subject_id("product", {"cc": "1,395"})
    b = ids.subject_id("product", {"cc": "1395"})
    c = ids.subject_id("product", {"cc": 1395})
    assert a == b == c


def test_different_kind_is_a_different_subject():
    """A component named 'golf' is not the product named 'golf'."""
    a = ids.subject_id("product", {"model": "golf"})
    b = ids.subject_id("component", {"model": "golf"})
    assert a != b


def test_extra_identity_key_yields_a_different_subject():
    """This is the documented limit of hash-dedup, pinned so nobody 'fixes' it.

    An author who considers `trim` part of identity is making a different
    assertion from one who does not. The lookup path unions them by attribute
    overlap; the hash must not pretend they are the same row.
    """
    five = ids.subject_id("product", {"make": "vw", "model": "golf"})
    seven = ids.subject_id("product", {"make": "vw", "model": "golf", "trim": "gti"})
    assert five != seven


def test_attribute_id_covers_value_and_validity_window():
    base = dict(subject_id="s1", key="power_hp", value="105", unit="hp")
    plain = ids.attribute_id(**base)
    assert plain == ids.attribute_id(**base)
    assert plain != ids.attribute_id(**base, valid_from="2014")
    assert ids.attribute_id(**base, valid_from="2014") != ids.attribute_id(
        **base, valid_from="2014", valid_to="2020")


def test_source_id_ignores_tracking_parameters_and_fragments():
    """The same page reached two ways is one source, so quotes corroborate."""
    plain = ids.source_id("https://example.com/a/b")
    assert plain == ids.source_id("https://example.com/a/b?utm_source=x&utm_campaign=y")
    assert plain == ids.source_id("https://example.com/a/b#section-3")
    assert plain == ids.source_id("HTTPS://Example.com/a/b/")
    assert plain != ids.source_id("https://example.com/a/c")


def test_source_id_keeps_meaningful_query_parameters():
    """A YouTube video id lives in the query string — dropping it merges videos."""
    a = ids.source_id("https://www.youtube.com/watch?v=abc123")
    b = ids.source_id("https://www.youtube.com/watch?v=zzz999")
    assert a != b


def test_evidence_id_is_source_plus_quote():
    q = "The timing chain tensioner fails around 150,000 km."
    a = ids.evidence_id("src1", q)
    assert a == ids.evidence_id("src1", "  The timing chain tensioner   fails around 150,000 km.  ")
    assert a != ids.evidence_id("src2", q)


def test_claim_id_is_stable_but_title_sensitive():
    """Pins the known weakness: three LLM titles for one failure hash three ways.

    The live catalog already contains exactly this. Read-time title-similarity
    clustering is what a reader experiences as dedup — this test exists so the
    limitation is documented in code, not discovered in production.
    """
    a = ids.claim_id("s1", "known_issue", "engine", "EGR valve carbon buildup")
    assert a == ids.claim_id("s1", "known_issue", "engine", "egr valve   carbon buildup")
    assert a != ids.claim_id("s1", "known_issue", "engine", "Carbon-clogged EGR valve")


def test_relation_id_is_directional():
    assert ids.relation_id("a", "part_of", "b") != ids.relation_id("b", "part_of", "a")


def test_ids_are_hex_and_fixed_width():
    got = ids.subject_id("product", {"make": "vw"})
    assert len(got) == 32
    assert all(c in "0123456789abcdef" for c in got)


def test_content_digest_is_order_independent_and_change_sensitive():
    a = ids.content_digest(["z", "a", "m"])
    assert a == ids.content_digest(["a", "m", "z"])
    assert a != ids.content_digest(["a", "m"])


def test_empty_identity_is_rejected():
    """A subject with no identity attributes would hash every product together."""
    with pytest.raises(ValueError):
        ids.subject_id("product", {})
