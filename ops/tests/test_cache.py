"""Candidate cache round-trip — write then read reproduces (claim, doc) pairs."""

import ops.process as process
from knowledge.extract import CandidateClaim
from knowledge.sources.base import Document


def test_cache_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(process, "CACHE_DIR", tmp_path)

    claim = CandidateClaim(
        title="K9K injector failure",
        domain="engine",
        severity="high",
        rationale="injectors fail",
        inspection_advice="check it",
        quote="verbatim",
        engine_or_variant_hint="K9K",
    )
    doc = Document(
        text="long source text",
        url="https://gaga.ba/k9k",
        site_or_channel="gaga.ba",
        meta={"make": "renault"},
    )

    process._write_candidate_cache("renault", "megane", "4", [(claim, doc)])
    restored = process._read_candidate_cache("renault", "megane", "4")

    assert restored is not None
    (rc, rd), = restored
    assert rc.title == claim.title
    assert rc.engine_or_variant_hint == "K9K"
    assert rd.text == doc.text
    assert rd.url == doc.url
    assert rd.meta == {"make": "renault"}


def test_read_missing_cache_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(process, "CACHE_DIR", tmp_path)
    assert process._read_candidate_cache("nope", "nope", "nope") is None
