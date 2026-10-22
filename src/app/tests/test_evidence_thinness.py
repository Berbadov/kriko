"""Thin evidence is read off the claim, and the reader's setting only filters it.

*"info sensitivity setting, showing or not showing thin evidences, with an
indicator next to info cards."* Thinness is derived from the claim row itself
(how many sites, how far the best is trusted, whether the quote is whole,
whether a condition was left open), never from a list of products, and the
setting decides what is drawn: it never changes what is stored.
"""

import pytest
from fastapi.testclient import TestClient

from app import evidence, prefs
from app.web import state
from app.web.app import create_app
from app.web.settings import Settings


def source(domain="maker.example.com", tier="manufacturer", trust=1.0, **more):
    return {"url": f"https://{domain}/page", "domain": domain, "quote": "A whole quote.",
            "stance": "supports", "tier": tier, "trust": trust, **more}


def codes(claim):
    return [row["code"] for row in evidence.assess(claim)["reasons"]]


# ── what makes a claim thin ──────────────────────────────────────────────


def test_two_trusted_sites_with_whole_quotes_are_solid():
    claim = {"sources": [source(), source("review.example.net", "editorial", 0.7)]}
    assert evidence.assess(claim) == {"level": "solid", "reasons": []}


def test_one_site_alone_is_partial_not_thin():
    assessed = evidence.assess({"sources": [source()]})
    assert assessed["level"] == "partial"
    assert [r["code"] for r in assessed["reasons"]] == ["single_source"]
    assert assessed["reasons"][0]["text"], "the indicator says why on hover"


def test_three_pages_of_one_site_are_still_one_source():
    claim = {"sources": [source(), {**source(), "url": "https://maker.example.com/other"}]}
    assert codes(claim) == ["single_source"]


def test_a_lone_forum_post_is_thin_for_two_reasons():
    claim = {"sources": [source("forum.example.org", "forum_ugc", 0.45)]}
    assert codes(claim) == ["single_source", "low_trust"]
    assert evidence.assess(claim)["level"] == "thin"


def test_the_best_source_decides_trust_not_the_worst():
    claim = {"sources": [source("forum.example.org", "forum_ugc", 0.45), source()]}
    assert "low_trust" not in codes(claim), "one manufacturer page outweighs a forum"


def test_trust_falls_back_to_the_tier_when_a_saved_row_has_no_number():
    """A check saved before sources carried `trust` still reads its tier."""
    low = {"sources": [{"url": "https://a.example/x", "quote": "q", "tier": "seo_blog"},
                       {"url": "https://b.example/x", "quote": "q", "tier": "seo_blog"}]}
    assert codes(low) == ["low_trust"]
    unclassified = {"sources": [{"url": "https://a.example/x", "quote": "q", "tier": "unknown"},
                                {"url": "https://b.example/x", "quote": "q", "tier": "unknown"}]}
    assert codes(unclassified) == [], "unknown is neutral, not a penalty"


def test_a_quote_that_only_partly_matches_is_marked():
    for match in ("partial", 0.6, False):
        claim = {"sources": [source(quote_match=match), source("b.example.net", "editorial", 0.7,
                                                                quote_match=match)]}
        assert codes(claim) == ["partial_quote"], match
    whole = {"sources": [source(quote_match="exact"), source("b.example.net", "editorial", 0.7)]}
    assert codes(whole) == []


def test_one_whole_quote_among_partial_ones_is_enough():
    claim = {"sources": [source(quote_match="partial"),
                         source("b.example.net", "editorial", 0.7, quote_match="exact")]}
    assert codes(claim) == []


def test_a_citation_with_no_quote_cannot_be_whole():
    claim = {"sources": [source(quote=""), source("b.example.net", "editorial", 0.7, quote="")]}
    assert codes(claim) == ["partial_quote"]


def test_a_condition_left_open_is_marked_and_a_stated_one_is_not():
    solid = [source(), source("b.example.net", "editorial", 0.7)]
    assert codes({"sources": solid, "open_conditions": ["usage_km not stated"]}) == ["unmet_condition"]
    assert codes({"sources": solid, "open_conditions": []}) == []


def test_a_claim_that_cites_nothing_is_partial_at_most():
    """A due-unless-proven-otherwise item cites no page by nature: doubt, not thin."""
    assessed = evidence.assess({"sources": []})
    assert [r["code"] for r in assessed["reasons"]] == ["no_source"]
    assert assessed["level"] == "partial"


def test_a_refuting_source_is_not_support():
    claim = {"sources": [source(stance="refutes"), source("b.example.net", "editorial", 0.7)]}
    assert codes(claim) == ["single_source"]


def test_a_field_the_row_does_not_carry_is_no_doubt():
    """No tier, no trust, no quote verdict: nothing is invented to doubt."""
    bare = [{"url": "https://a.example/x", "quote": "q"}, {"url": "https://b.example/y", "quote": "q"}]
    assert evidence.assess({"sources": bare})["level"] in {"solid", "partial"}
    assert "partial_quote" not in codes({"sources": bare})


def test_thinness_reads_no_product_name():
    """The same evidence under any title or category is the same level."""
    base = {"sources": [source("forum.example.org", "forum_ugc", 0.45)]}
    assert (evidence.assess({**base, "title": "Lid hinge cracks"})
            == evidence.assess({**base, "title": "Chain tensioner fails", "subject": "Widget"}))


def test_annotate_adds_the_object_and_changes_nothing_else():
    rows = [{"claim_id": "c1", "title": "T", "sources": [source()]}]
    out = evidence.annotate(rows)
    assert out[0]["claim_id"] == "c1" and out[0]["evidence"]["level"] == "partial"
    assert "evidence" not in rows[0], "the input row is not mutated"


def test_each_source_is_served_with_where_it_stands():
    rows = [{"claim_id": "c1", "sources": [
        source("maker.example.com", trust=1.0),
        source("blog.example.com", tier="seo_blog", trust=0.3),
        source("shop.example.com", tier="unknown", trust=0.55),
        {"domain": "x.example.com", "quote": "q", "stance": "supports"},
    ]}]
    out = evidence.annotate(rows)[0]["sources"]
    assert [s.get("standing") for s in out] == ["trusted", "low", "neutral", None], "no number or tier, no mark"
    assert "standing" not in rows[0]["sources"][0], "the input row is not mutated"


def test_a_claim_with_no_sources_list_is_left_as_it_was():
    out = evidence.annotate([{"claim_id": "c1", "title": "T"}])[0]
    assert "sources" not in out


# ── what the setting does ────────────────────────────────────────────────


@pytest.mark.parametrize("setting, drawn", [
    ("all", {"solid": True, "partial": True, "thin": True}),
    ("hide_thin", {"solid": True, "partial": True, "thin": False}),
    ("strict", {"solid": True, "partial": False, "thin": False}),
])
def test_the_three_steps_draw_what_they_say(setting, drawn):
    assert {level: evidence.shown(level, setting) for level in evidence.LEVELS} == drawn


def test_a_missing_or_unknown_setting_draws_everything():
    for value in (None, "", "bogus", "ALL "):
        assert evidence.normalise(value) == "all"
        assert evidence.shown("thin", value)


def test_hidden_findings_are_counted():
    levels = ["solid", "thin", "partial", "thin"]
    assert evidence.hidden_count(levels, "hide_thin") == 2
    assert evidence.hidden_count(levels, "strict") == 3
    assert evidence.hidden_count(levels, "all") == 0


# ── the setting through the API, which the extension reads ───────────────


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(Settings(
        store_path=tmp_path / "k.sqlite", app_state_path=tmp_path / "app.sqlite",
        analysis_log_path=tmp_path / "a.jsonl")))


def test_settings_always_carry_the_sensitivity(client):
    assert client.get("/api/settings").json()["info_sensitivity"] == "all"


def test_the_choice_is_stored_and_read_back_by_settings(client):
    assert client.put("/api/prefs", json={"info_sensitivity": "hide_thin"}).status_code == 200
    assert client.get("/api/settings").json()["info_sensitivity"] == "hide_thin"
    assert client.get("/api/prefs").json()["chosen"][prefs.INFO_SENSITIVITY] == "hide_thin"
    client.put("/api/prefs", json={"info_sensitivity": "strict"})
    assert client.get("/api/settings").json()["info_sensitivity"] == "strict"


def test_a_step_that_does_not_exist_is_refused_and_changes_nothing(client):
    client.put("/api/prefs", json={"info_sensitivity": "strict"})
    refused = client.put("/api/prefs", json={"info_sensitivity": "paranoid"})
    assert refused.status_code == 422
    assert client.get("/api/settings").json()["info_sensitivity"] == "strict"


def test_clearing_the_choice_returns_to_everything(client):
    client.put("/api/prefs", json={"info_sensitivity": "strict"})
    client.put("/api/prefs", json={"info_sensitivity": ""})
    assert client.get("/api/settings").json()["info_sensitivity"] == "all"


def test_a_stored_value_that_is_not_a_step_reads_as_everything(tmp_path):
    conn = state.connect(tmp_path / "app.sqlite")
    state.put_settings(conn, {"info_sensitivity": "something old"})
    assert prefs.info_sensitivity(conn) == "all"


# ── the claim rows the extension and the app both receive ────────────────


def test_a_lookup_serves_each_claim_with_its_evidence(tmp_path):
    from kriko.store import packstore
    from kriko.store.db import connect
    from kriko.tests.test_lookup import ALPHA_CLAIMS, ALPHA_SUBJECTS, ALPHA_TOML, _pack

    store_path = tmp_path / "knowledge.sqlite"
    conn = connect(store_path)
    packstore.install(conn, _pack(tmp_path, "alpha", toml=ALPHA_TOML,
                                  subjects=ALPHA_SUBJECTS, claims=ALPHA_CLAIMS))
    conn.close()
    client = TestClient(create_app(Settings(
        store_path=store_path, app_state_path=tmp_path / "app.sqlite",
        analysis_log_path=tmp_path / "a.jsonl")))
    body = {"kind": "product", "identity": {"brand": "acme", "model": "w100"}, "context": {}}
    posted = client.post("/api/lookup", json=body).json()
    by_title = {c["title"]: c for c in posted["claims"]}

    rattle = by_title["Trim rattle"]  # one forum post
    assert rattle["evidence"]["level"] == "thin"
    assert {r["code"] for r in rattle["evidence"]["reasons"]} == {"single_source", "low_trust"}
    assert rattle["sources"][0]["trust"] < 0.5
    chain = by_title["Chain tensioner fails"]  # one maker page, mileage not stated
    assert [r["code"] for r in chain["evidence"]["reasons"]] == ["single_source", "unmet_condition"]
    assert chain["evidence"]["level"] == "thin"

    # A saved check reopens with the same object, and nothing stored changed.
    reopened = client.get(f"/api/lookup/{posted['lookup_id']}").json()["response"]["claims"]
    assert {c["title"]: c["evidence"] for c in reopened} == {t: c["evidence"] for t, c in by_title.items()}
