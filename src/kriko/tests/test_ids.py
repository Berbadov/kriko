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
    a = ids.subject_id("product", {"brand": "makita", "model": "dhp484"})
    b = ids.subject_id("product", {"brand": "makita", "model": "dhp484"})
    assert a == b


def test_hash_is_order_independent():
    """Identity is a set of key/value pairs, not a sequence of them."""
    a = ids.subject_id("product", {"brand": "makita", "model": "dhp484"})
    b = ids.subject_id("product", {"model": "dhp484", "brand": "makita"})
    assert a == b


def test_hash_normalises_case_and_whitespace():
    a = ids.subject_id("product", {"brand": "Makita", "model": "  DHP484 "})
    b = ids.subject_id("product", {"brand": "makita", "model": "dhp484"})
    assert a == b


def test_hash_normalises_numeric_punctuation():
    """'1,200' and '1200' and 1200 are the same charge-cycle count."""
    a = ids.subject_id("product", {"charge_cycles": "1,200"})
    b = ids.subject_id("product", {"charge_cycles": "1200"})
    c = ids.subject_id("product", {"charge_cycles": 1200})
    assert a == b == c


def test_different_kind_is_a_different_subject():
    """A component named 'chuck' is not the product named 'chuck'."""
    a = ids.subject_id("product", {"model": "chuck"})
    b = ids.subject_id("component", {"model": "chuck"})
    assert a != b


def test_extra_identity_key_yields_a_different_subject():
    """This is the documented limit of hash-dedup, pinned so nobody 'fixes' it.

    An author who considers `platform` part of identity is making a different
    assertion from one who does not. The lookup path unions them by attribute
    overlap; the hash must not pretend they are the same row.
    """
    five = ids.subject_id("product", {"brand": "makita", "model": "dhp484"})
    seven = ids.subject_id(
        "product", {"brand": "makita", "model": "dhp484", "platform": "lxt"})
    assert five != seven


def test_attribute_id_covers_value_and_validity_window():
    base = dict(subject_id="s1", key="max_torque_nm", value="54", unit="nm")
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
    q = "The battery pack degrades noticeably after about 1,200 charge cycles."
    a = ids.evidence_id("src1", q)
    assert a == ids.evidence_id(
        "src1", "  The battery pack degrades   noticeably after about 1,200 charge cycles.  ")
    assert a != ids.evidence_id("src2", q)


def test_claim_id_is_stable_but_title_sensitive():
    """Pins the known weakness: three LLM titles for one failure hash three ways.

    The live catalog already contains exactly this. Read-time title-similarity
    clustering is what a reader experiences as dedup — this test exists so the
    limitation is documented in code, not discovered in production.
    """
    a = ids.claim_id("s1", "known_issue", "mechanical", "keyless chuck bearing wear")
    assert a == ids.claim_id("s1", "known_issue", "mechanical", "keyless chuck   bearing wear")
    assert a != ids.claim_id("s1", "known_issue", "mechanical", "chuck bearing seizure")


def test_relation_id_is_directional():
    assert ids.relation_id("a", "part_of", "b") != ids.relation_id("b", "part_of", "a")


def test_ids_are_hex_and_fixed_width():
    got = ids.subject_id("product", {"brand": "makita"})
    assert len(got) == 32
    assert all(c in "0123456789abcdef" for c in got)


MAN = {"pack": {"id": "p", "name": "P", "version": "0.1.0"}}


def test_content_digest_is_order_independent_and_change_sensitive():
    a = ids.content_digest(["z", "a", "m"], MAN)
    assert a == ids.content_digest(["a", "m", "z"], MAN)
    assert a != ids.content_digest(["a", "m"], MAN)


def test_content_digest_covers_what_the_pack_declares_itself_to_be():
    """A manifest-only change must move the digest.

    It did not, and that shipped: two releases published one pack under two
    different names at the same version with the same digest, so
    `updates.decide` said "newest version installed" and the corrected name
    reached nobody. Identity keys live in the same manifest, and they decide
    which of a pack's rows can ever merge with another author's — a silent
    change there is worse than a wrong name.
    """
    rows = ["a", "m", "z"]
    renamed = {"pack": {**MAN["pack"], "name": "P, corrected"}}
    rekeyed = {**MAN, "identity": {"product": ["brand"]}}
    assert ids.content_digest(rows, MAN) != ids.content_digest(rows, renamed)
    assert ids.content_digest(rows, MAN) != ids.content_digest(rows, rekeyed)


def test_content_digest_will_not_be_computed_without_a_manifest():
    """Required, not optional, because packs bring their own builders.

    An argument a pack author may omit is one a pack author will omit — and the
    omission is invisible until a metadata fix fails to travel. TypeError at
    build time is the whole mechanism.
    """
    with pytest.raises(TypeError):
        ids.content_digest(["a"])


def test_manifest_ordering_does_not_move_the_digest():
    """Two spellings of the same declaration are the same declaration.

    Otherwise reordering keys in a pack.toml would look like new knowledge, and
    every reader would be handed a download for nothing.
    """
    a = {"pack": {"id": "p", "name": "P"}, "identity": {"product": ["brand"]}}
    b = {"identity": {"product": ["brand"]}, "pack": {"name": "P", "id": "p"}}
    assert ids.content_digest(["r"], a) == ids.content_digest(["r"], b)


def test_empty_identity_is_rejected():
    """A subject with no identity attributes would hash every product together."""
    with pytest.raises(ValueError):
        ids.subject_id("product", {})
