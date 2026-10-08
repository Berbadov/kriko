"""B168, B169, B170: a product check lands in a category pack.

The reader's words: "Singular product searches must be addable to the DB",
"must not create a new pack each time", "must be turned into packages".

Everything here goes through the extension's door (`POST /api/extension/
research-plane`) with the real job runner. Only the edges are stubbed: the
agent (its prints, by prompt) and the page reader (a dict of pages). The
middle, which is what is being tested, is the real code: the quick look, the
deepen job, the pack resolver, the draft, the build, the install.
"""

import json
import time
from types import SimpleNamespace

import pytest
import yaml
from fastapi.testclient import TestClient

from app import categorypack, packauthor, packdraft
from app.web.app import create_app
from app.web.settings import Settings
from kriko.lookup import find
from kriko.research import Fetched
from kriko.store import packstore
from kriko.store.db import connect

V8_PAGE = "https://reviews.example.org/scyrox-v8"
V8_QUOTE = "the scroll wheel started skipping after four months"
V6_PAGE = "https://reviews.example.org/scyrox-v6"
V6_QUOTE = "the side buttons rattle on the V6"
FORUM = "https://forum.example.org/v8"
FORUM_QUOTE = "the coating peeled at the thumb rest"
SHOP_PAGE = "https://shop.example.org/v6-questions"
SHOP_QUOTE = "two buyers wrote that the buttons rattle"
CABLE_PAGE = "https://reviews.example.org/v6-cable"
CABLE_QUOTE = "the cable frayed at the connector by spring"

PAGES = {
    V8_PAGE: f"Long-term notes. After a while {V8_QUOTE}, but the sensor was fine.",
    V6_PAGE: f"Owner thread. Sadly {V6_QUOTE} once the paint wears.",
    FORUM: f"Forum reply: mine too, {FORUM_QUOTE} within a year.",
    SHOP_PAGE: f"Questions and answers: {SHOP_QUOTE} after a few weeks.",
    CABLE_PAGE: f"Follow-up: {CABLE_QUOTE}, so keep the receipt.",
}

MICE = {
    "pack_id": "gaming.mice",
    "name": "Gaming mice",
    "languages": ["en"],
    "markets": ["EU"],
    "identity": {"product": ["brand", "model"]},
    "principle": "Surface wear specific to one mouse model that a listing hides.",
    "templates": ["{label} common problems"],
    "domains": [{"id": "mechanical", "label": "Mechanical"}],
    "lineup": ["Scyrox V8", "Scyrox V6", "Logitech G Pro X Superlight"],
    "subjects": [{"kind": "product", "label": "Scyrox V8",
                  "identity": {"brand": "scyrox", "model": "v8"},
                  "aliases": ["V8 Scyrox"]}],
    "claims": [
        # No page named: a product check keeps a claim only with a source.
        {"subject": {"kind": "product", "identity": {"brand": "scyrox", "model": "v8"}},
         "title": "An unsourced hunch", "body": "Probably fine."},
        {"subject": {"kind": "product", "identity": {"brand": "scyrox", "model": "v8"}},
         "domain": "mechanical", "severity": "low", "title": "Coating peels",
         "body": "The coating wears off where the thumb rests.",
         "advice": "Look at the thumb rest.",
         "evidence": [{"url": FORUM, "quote": FORUM_QUOTE}]},
    ],
}


def _fenced(payload: dict) -> str:
    return "Done reading.\n```json\n" + json.dumps(payload) + "\n```"


def _risk(title, url, quote, *, why="It fails with use."):
    return {"title": title, "why": why, "check": "Ask the seller.",
            "severity": "medium", "url": url, "quote": quote}


class Script:
    """What the stubbed agent prints, keyed by which brief it was handed."""

    def __init__(self):
        self.quick = {}      # product title -> the quick look's JSON
        self.author = {}     # product title -> the authoring JSON
        self.amend = {}      # product title -> the amend JSON
        self.prompts = []

    def reply(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if prompt.startswith("# Is this product identity unambiguous?"):
            return _fenced({"ambiguous": False})
        for title, payload in self.quick.items():
            if prompt.startswith("# Quick look") and f"    {title}\n" in prompt:
                return _fenced(payload)
        for title, payload in self.author.items():
            if prompt.startswith("# Author a Kriko knowledge pack") and title in prompt:
                return _fenced(payload)
        for title, payload in self.amend.items():
            if prompt.startswith("# Extend an existing Kriko pack") and title in prompt:
                return _fenced(payload)
        raise AssertionError(f"no scripted reply for: {prompt[:80]!r}")

    def asked(self, start: str) -> list[str]:
        return [one for one in self.prompts if one.startswith(start)]


@pytest.fixture
def world(tmp_path, monkeypatch):
    from app import keys, providers
    from app.providers import harness
    from app.web import tasks

    script = Script()

    class Agent:
        search_provider = "fixture-harness"

        def ask(self, prompt):
            return script.reply(prompt)

    monkeypatch.setattr(keys, "ready", lambda *_, **__: True)
    monkeypatch.setattr(harness, "available", lambda: [SimpleNamespace(id="fixture-harness")])
    monkeypatch.setattr(providers, "harness_researcher", lambda **_: Agent())
    monkeypatch.setattr(tasks, "_page_reader", lambda: (lambda url: Fetched(PAGES.get(url, ""))))
    monkeypatch.setattr(tasks, "QUICK_POLL_SECONDS", 0.02)

    store = connect(tmp_path / "knowledge.sqlite")
    store.execute(
        "INSERT INTO packs (pack_id, name, version, schema_version, built_at,"
        " content_digest, enabled, installed_at)"
        " VALUES ('probe', 'Probe', '1', 1, '2026-09-17', 'd', 1, '2026-09-17')")
    store.commit()
    store.close()
    settings = Settings(
        store_path=tmp_path / "knowledge.sqlite",
        app_state_path=tmp_path / "app.sqlite",
        analysis_log_path=tmp_path / "analyses.jsonl",
    )
    client = TestClient(create_app(settings))
    client.script = script
    client.settings = settings
    try:
        yield client
    finally:
        client.app.state.jobs.shutdown(wait=True)


def _wait(client, job_id):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        row = client.get(f"/api/jobs/{job_id}").json()
        if row["done"]:
            return row
        time.sleep(0.02)
    pytest.fail(f"job {job_id} did not finish")


def _check(client, title):
    """One press of "Research this product", then "Add to a pack"."""
    response = client.post("/api/extension/research-plane", json={
        "q": title, "allow_draft": True})
    assert response.status_code == 200, response.text
    body = response.json()
    quick = _wait(client, body["job_id"])
    assert quick["state"] == "succeeded", quick["message"]
    # A quick look is saved on its own; "Add to a pack" files it (#129).
    added = client.post(f"/api/extension/quick-looks/{body['job_id']}/pack")
    assert added.status_code == 200, added.text
    deepen = _wait(client, added.json()["job_id"])
    return quick, deepen


def _packs(client):
    return {one["pack_id"]: one for one in client.get("/api/packs").json()}


def _store(client):
    return connect(client.settings.store_path)


def _claims_of(client, label):
    """Each claim on a subject, with the url and quote of its evidence."""
    store = _store(client)
    try:
        rows = store.execute(
            "SELECT t.title, s.url, e.quote FROM subjects sub"
            " JOIN claims c ON c.subject_id = sub.subject_id AND c.pack_id = sub.pack_id"
            " JOIN claim_text t ON t.claim_id = c.claim_id AND t.pack_id = c.pack_id"
            " LEFT JOIN evidence e ON e.claim_id = c.claim_id AND e.pack_id = c.pack_id"
            " LEFT JOIN sources s ON s.source_id = e.source_id AND s.pack_id = e.pack_id"
            " WHERE sub.label = ? ORDER BY t.title, s.url", (label,)).fetchall()
        return [tuple(r) for r in rows]
    finally:
        store.close()


def _script_v8(script):
    script.quick["Scyrox V8 Gaming Mouse"] = {
        "assumed": "the wireless V8", "category": "gaming mouse", "pack": "",
        "risks": [_risk("Scroll wheel wears", V8_PAGE, V8_QUOTE)]}
    script.author["Scyrox V8 Gaming Mouse"] = MICE


def _script_v6(script):
    script.quick["Scyrox V6 Gaming Mouse"] = {
        "assumed": "the V6", "category": "gaming mouse", "pack": "gaming.mice",
        "risks": [_risk("Side buttons rattle", V6_PAGE, V6_QUOTE)]}
    script.amend["Scyrox V6 Gaming Mouse"] = {
        "subjects": [{"kind": "product", "label": "Scyrox V6",
                      "identity": {"brand": "scyrox", "model": "v6"}}],
        "lineup": ["Scyrox V6"]}


# ── B168: the check lands in the store, with its sources ──────────────────


def test_a_first_check_puts_the_product_and_its_sourced_risks_in_browse(world):
    _script_v8(world.script)
    quick, deepen = _check(world, "Scyrox V8 Gaming Mouse")

    assert deepen["state"] == "succeeded", deepen["message"]
    assert deepen["result"]["installed"] is True
    assert deepen["result"]["joined"] is False
    assert deepen["result"]["category"] == "gaming mouse"

    found = world.get("/api/search", params={"q": "Scyrox V8"}).json()
    assert [one["label"] for one in found["items"]] == ["Scyrox V8"]
    assert found["items"][0]["claims"] == 2

    assert _claims_of(world, "Scyrox V8") == [
        ("Coating peels", FORUM, FORUM_QUOTE),
        ("Scroll wheel wears", V8_PAGE, V8_QUOTE),
    ]


def test_a_claim_that_names_no_page_is_left_out(world):
    _script_v8(world.script)
    _check(world, "Scyrox V8 Gaming Mouse")
    titles = {row[0] for row in _claims_of(world, "Scyrox V8")}
    assert "An unsourced hunch" not in titles


def test_a_quote_that_is_not_on_its_page_is_dropped_and_named(world):
    _script_v8(world.script)
    world.script.quick["Scyrox V8 Gaming Mouse"]["risks"].append(
        _risk("Invented failure", V8_PAGE, "the sensor exploded on day two"))
    world.script.quick["Scyrox V8 Gaming Mouse"]["risks"].append(
        _risk("Unreadable page", "https://blocked.example.org/x", "anything at all"))
    _, deepen = _check(world, "Scyrox V8 Gaming Mouse")

    assert deepen["state"] == "succeeded", deepen["message"]
    titles = {row[0] for row in _claims_of(world, "Scyrox V8")}
    assert "Invented failure" not in titles
    assert "Unreadable page" not in titles
    assert "Scroll wheel wears" in titles
    assert "the quote is not on the page" in deepen["log"]
    assert "the page could not be read" in deepen["log"]


def test_the_stored_quote_is_the_pages_own_text(world):
    _script_v8(world.script)
    world.script.quick["Scyrox V8 Gaming Mouse"]["risks"][0]["quote"] = (
        V8_QUOTE.upper().replace("  ", " "))
    _check(world, "Scyrox V8 Gaming Mouse")
    [(_, _, stored)] = [row for row in _claims_of(world, "Scyrox V8")
                        if row[0] == "Scroll wheel wears"]
    assert stored in PAGES[V8_PAGE]


def test_a_check_with_no_sourced_risk_still_adds_the_product(world):
    _script_v8(world.script)
    world.script.quick["Scyrox V8 Gaming Mouse"]["risks"] = []
    world.script.author["Scyrox V8 Gaming Mouse"] = {**MICE, "claims": []}
    _, deepen = _check(world, "Scyrox V8 Gaming Mouse")
    assert deepen["state"] == "succeeded", deepen["message"]
    assert [one["label"] for one in world.get(
        "/api/search", params={"q": "Scyrox V8"}).json()["items"]] == ["Scyrox V8"]
    assert _claims_of(world, "Scyrox V8") == []


# ── B169: products join a category pack ───────────────────────────────────


def test_a_second_product_joins_the_pack_instead_of_making_another(world):
    _script_v8(world.script)
    _check(world, "Scyrox V8 Gaming Mouse")
    before = set(_packs(world))

    _script_v6(world.script)
    _, deepen = _check(world, "Scyrox V6 Gaming Mouse")

    assert deepen["state"] == "succeeded", deepen["message"]
    assert deepen["result"]["joined"] is True
    assert set(_packs(world)) == before == {"probe", "gaming.mice"}

    listed = world.get("/api/subjects", params={"pack_id": "gaming.mice"}).json()
    assert sorted(one["label"] for one in listed) == ["Scyrox V6", "Scyrox V8"]
    assert _claims_of(world, "Scyrox V6") == [("Side buttons rattle", V6_PAGE, V6_QUOTE)]
    # The agent was shown the installed pack, and asked to add to it.
    [quick_brief] = [p for p in world.script.asked("# Quick look") if "V6" in p]
    assert "gaming.mice" in quick_brief and "Gaming mice" in quick_brief
    assert world.script.asked("# Extend an existing Kriko pack: Gaming mice")


def test_the_same_product_checked_twice_succeeds_and_adds_nothing_twice(world):
    _script_v8(world.script)
    _check(world, "Scyrox V8 Gaming Mouse")
    _script_v6(world.script)
    _check(world, "Scyrox V6 Gaming Mouse")
    version = _packs(world)["gaming.mice"]["version"]
    claims = _packs(world)["gaming.mice"]["claims"]

    _, again = _check(world, "Scyrox V6 Gaming Mouse")

    assert again["state"] == "succeeded", again["message"]
    assert again["result"]["claims_added"] == 0
    assert _packs(world)["gaming.mice"]["version"] == version
    assert _packs(world)["gaming.mice"]["claims"] == claims
    assert sorted(one["label"] for one in world.get(
        "/api/subjects", params={"pack_id": "gaming.mice"}).json()) == ["Scyrox V6", "Scyrox V8"]


def test_a_repeat_check_adds_what_is_new_to_the_same_subject(world):
    _script_v8(world.script)
    _check(world, "Scyrox V8 Gaming Mouse")
    _script_v6(world.script)
    _check(world, "Scyrox V6 Gaming Mouse")

    world.script.quick["Scyrox V6 Gaming Mouse"]["risks"] = [
        _risk("Side buttons rattle", SHOP_PAGE, SHOP_QUOTE),   # same claim, a second source
        _risk("Cable fraying", CABLE_PAGE, CABLE_QUOTE),       # a new claim
    ]
    _, again = _check(world, "Scyrox V6 Gaming Mouse")

    assert again["state"] == "succeeded", again["message"]
    assert again["result"]["claims_added"] == 1
    assert again["result"]["evidence_added"] == 2
    assert _claims_of(world, "Scyrox V6") == [
        ("Cable fraying", CABLE_PAGE, CABLE_QUOTE),
        ("Side buttons rattle", V6_PAGE, V6_QUOTE),
        ("Side buttons rattle", SHOP_PAGE, SHOP_QUOTE),
    ]


def test_a_quote_that_already_backs_one_claim_does_not_open_a_second_bare_one(world):
    _script_v8(world.script)
    _check(world, "Scyrox V8 Gaming Mouse")
    _script_v6(world.script)
    world.script.quick["Scyrox V6 Gaming Mouse"]["risks"] = [
        _risk("Side buttons rattle", V6_PAGE, V6_QUOTE),
        _risk("Same words, other title", V6_PAGE, V6_QUOTE),
    ]
    _, deepen = _check(world, "Scyrox V6 Gaming Mouse")

    assert deepen["state"] == "succeeded", deepen["message"]
    assert deepen["result"]["claims_added"] == 1
    assert _claims_of(world, "Scyrox V6") == [("Side buttons rattle", V6_PAGE, V6_QUOTE)]
    assert "its quote already backs another claim" in deepen["log"]


def test_an_id_the_agent_invents_does_not_join_anything(world):
    _script_v8(world.script)
    _check(world, "Scyrox V8 Gaming Mouse")
    _script_v6(world.script)
    world.script.quick["Scyrox V6 Gaming Mouse"]["pack"] = "not.a.pack"
    world.script.quick["Scyrox V6 Gaming Mouse"]["category"] = "keyboard"
    world.script.author["Scyrox V6 Gaming Mouse"] = {
        **MICE, "pack_id": "other.things", "name": "Other things",
        "subjects": [{"kind": "product", "label": "Scyrox V6",
                      "identity": {"brand": "scyrox", "model": "v6"}}]}
    _, deepen = _check(world, "Scyrox V6 Gaming Mouse")
    assert deepen["state"] == "succeeded", deepen["message"]
    assert deepen["result"]["joined"] is False
    assert set(_packs(world)) == {"probe", "gaming.mice", "other.things"}


def test_a_chosen_id_that_already_has_a_draft_is_merged_not_refused(world):
    _script_v8(world.script)
    _check(world, "Scyrox V8 Gaming Mouse")
    # The quick look does not recognise the pack, so the agent authors again
    # and picks the id that is taken. Before B169 this was FileExistsError.
    _script_v6(world.script)
    world.script.quick["Scyrox V6 Gaming Mouse"]["pack"] = ""
    world.script.quick["Scyrox V6 Gaming Mouse"]["category"] = "esports pointer"
    world.script.author["Scyrox V6 Gaming Mouse"] = {
        **MICE, "claims": [],
        "subjects": [{"kind": "product", "label": "Scyrox V6",
                      "identity": {"brand": "scyrox", "model": "v6"}}]}
    _, deepen = _check(world, "Scyrox V6 Gaming Mouse")
    assert deepen["state"] == "succeeded", deepen["message"]
    assert deepen["result"]["joined"] is True
    assert set(_packs(world)) == {"probe", "gaming.mice"}
    assert sorted(one["label"] for one in world.get(
        "/api/subjects", params={"pack_id": "gaming.mice"}).json()) == ["Scyrox V6", "Scyrox V8"]


def test_a_new_pack_is_told_which_ids_are_taken_and_to_name_the_category(world):
    _script_v8(world.script)
    _check(world, "Scyrox V8 Gaming Mouse")
    [brief] = world.script.asked("# Author a Kriko knowledge pack")
    assert "`probe`" in brief
    assert '"gaming mouse"' in brief and "never of a brand or a model" in brief
    assert "Do not expand" not in brief   # the old one-product-per-pack wording is gone


# ── B170: the pack grows as a package ─────────────────────────────────────


def test_each_join_advances_the_version_and_the_digest(world):
    _script_v8(world.script)
    _check(world, "Scyrox V8 Gaming Mouse")
    first = _packs(world)["gaming.mice"]
    _script_v6(world.script)
    _check(world, "Scyrox V6 Gaming Mouse")
    second = _packs(world)["gaming.mice"]

    assert first["version"] == "0.1.0"
    assert second["version"] == "0.1.1"
    assert second["digest"] != first["digest"]
    assert second["subjects"] == first["subjects"] + 1


def test_the_exported_artifact_installs_elsewhere_with_the_new_product(world, tmp_path):
    _script_v8(world.script)
    _check(world, "Scyrox V8 Gaming Mouse")
    _script_v6(world.script)
    _check(world, "Scyrox V6 Gaming Mouse")

    slug = next(one["slug"] for one in world.get("/api/packs/drafts").json()["items"]
                if one["pack_id"] == "gaming.mice")
    download = world.get(f"/api/packs/drafts/{slug}/artifact")
    assert download.status_code == 200
    assert f'{slug}.kpack' in download.headers["content-disposition"]
    artifact = tmp_path / "carried.kpack"
    artifact.write_bytes(download.content)
    assert world.get("/api/packs/drafts/nothing-here/artifact").status_code == 404
    elsewhere = connect(tmp_path / "another-machine.sqlite")
    try:
        assert packstore.install(elsewhere, artifact) == "gaming.mice"
        labels = sorted(one["label"] for one in find.search(elsewhere, "scyrox"))
        assert labels == ["Scyrox V6", "Scyrox V8"]
        [row] = elsewhere.execute(
            "SELECT s.url, e.quote FROM evidence e JOIN sources s"
            " ON s.source_id = e.source_id WHERE e.quote = ?", (V6_QUOTE,)).fetchall()
        assert row["url"] == V6_PAGE
    finally:
        elsewhere.close()


def test_a_finding_accepted_before_a_join_survives_the_reinstall(world):
    from app.findings import accept_findings

    _script_v8(world.script)
    _check(world, "Scyrox V8 Gaming Mouse")

    store = _store(world)
    try:
        subject = store.execute(
            "SELECT subject_id FROM subjects WHERE label = 'Scyrox V8'").fetchone()[0]
        text = "Reader research: the receiver dongle overheats in a laptop USB port."
        verdicts = accept_findings(store, subject, "gaming.mice", [{
            "title": "Dongle overheats",
            "rationale": "The receiver gets hot enough to disconnect in a laptop port.",
            "quote": "the receiver dongle overheats", "document_text": text,
            "source_url": "https://research.example.org/dongle"}])
        store.commit()
        assert [one["title"] for one in verdicts["accepted"]] == ["Dongle overheats"]
    finally:
        store.close()

    _script_v6(world.script)
    _check(world, "Scyrox V6 Gaming Mouse")

    assert ("Dongle overheats", "https://research.example.org/dongle",
            "the receiver dongle overheats") in _claims_of(world, "Scyrox V8")


def test_an_amended_draft_installs_again_at_a_raised_version(world):
    """The reader's Install press on a draft that was amended after install."""
    settings = world.settings
    packauthor.author(settings.store_path, _fenced(MICE), category="gaming mouse",
                      payload={**MICE, "claims": []})
    first = world.post("/api/packs/drafts/gaming-mice/install")
    assert first.status_code == 200, first.text
    assert first.json()["version"] == "0.1.0"
    assert _packs(world)["gaming.mice"]["version"] == "0.1.0"

    packauthor.amend(settings.store_path, "gaming-mice", _fenced({
        "subjects": [{"kind": "product", "label": "Scyrox V6",
                      "identity": {"brand": "scyrox", "model": "v6"}}]}))
    # The engine's own rule stays: an amended 0.1.0 cannot replace 0.1.0.
    artifact = packdraft.build_artifact(settings.store_path, "gaming-mice")
    store = _store(world)
    try:
        with pytest.raises(ValueError, match="immutable"):
            packstore.install(store, artifact)
    finally:
        store.close()

    second = world.post("/api/packs/drafts/gaming-mice/install")
    assert second.status_code == 200, second.text
    assert second.json()["version"] == "0.1.1" and second.json()["bumped"] == "0.1.1"
    assert second.json()["digest"] != first.json()["digest"]
    assert _packs(world)["gaming.mice"]["version"] == "0.1.1"
    # And pressing it again with nothing new changes nothing.
    third = world.post("/api/packs/drafts/gaming-mice/install")
    assert third.status_code == 200
    assert _packs(world)["gaming.mice"]["version"] == "0.1.1"


# ── the resolver, on its own ──────────────────────────────────────────────


def _cand(pack_id, name):
    return {"pack_id": pack_id, "slug": pack_id, "name": name, "version": "0.1.0",
            "identity": {}, "subjects": [], "blurb": ""}


def test_an_answer_naming_an_installed_id_resolves_and_an_invented_one_does_not():
    cands = [_cand("gaming.mice", "Gaming mice"), _cand("wireless.earbuds", "Earbuds")]
    assert categorypack.resolve(cands, pack="Gaming.Mice")["pack_id"] == "gaming.mice"
    assert categorypack.resolve(cands, pack="made.up") is None
    assert categorypack.resolve([], pack="gaming.mice") is None


def test_the_category_words_only_join_a_pack_that_clearly_holds_them():
    cands = [_cand("wireless.earbuds", "Wireless earbuds"),
             _cand("wireless.keyboards", "Wireless keyboards")]
    assert categorypack.resolve(cands, category="wireless earbud")["pack_id"] == "wireless.earbuds"
    # "wireless" alone fits two packs, so it fits neither: a new pack, not a guess.
    assert categorypack.resolve(cands, category="wireless") is None
    assert categorypack.resolve(cands, category="") is None
    assert categorypack.resolve(cands, category="drill") is None


def test_a_pack_with_no_draft_is_never_a_candidate(world):
    # `probe` is installed and enabled but was not authored from a draft.
    assert categorypack.candidates(world.settings.store_path) == []


def test_a_disabled_pack_is_not_a_candidate(world):
    _script_v8(world.script)
    _check(world, "Scyrox V8 Gaming Mouse")
    assert [one["pack_id"] for one in categorypack.candidates(world.settings.store_path)] == [
        "gaming.mice"]
    assert world.post("/api/packs/gaming.mice/enabled", params={"enabled": False}).status_code == 200
    assert categorypack.candidates(world.settings.store_path) == []


@pytest.mark.parametrize("seen,expected", [
    (("0.1.0",), "0.1.1"),
    (("0.1.0", "0.1.4"), "0.1.5"),
    (("1",), "2"),
    (("1.2",), "1.3"),
    (("0.9.9",), "0.9.10"),
    (("beta",), "beta.1"),
    ((), "0.1.0"),
])
def test_the_next_version_is_the_patch_above_every_one_seen(seen, expected):
    assert categorypack.next_version(*seen) == expected


def test_grounding_keeps_only_claims_whose_quote_is_on_the_page():
    pages = {"https://a.example.org/x": "One two. Three   four\nfive."}
    kept, dropped = categorypack.ground(
        [{"title": "kept", "evidence": [{"url": "https://a.example.org/x",
                                         "quote": "three four five"}]},
         {"title": "already checked", "evidence": [
             {"url": "https://b.example.org/y", "quote": "seen by the plane",
              "grounded": True}]},
         {"title": "not there", "evidence": [{"url": "https://a.example.org/x",
                                              "quote": "six"}]},
         {"title": "no url", "evidence": [{"url": "", "quote": "One two"}]},
         {"title": "no evidence"}],
        lambda url: Fetched(pages.get(url, "")))
    assert [one["title"] for one in kept] == ["kept", "already checked"]
    assert kept[0]["evidence"][0]["quote"] == "Three   four\nfive"
    assert sorted(one["title"] for one in dropped) == ["no evidence", "no url", "not there"]


def test_a_claim_the_packs_own_gate_refuses_is_left_out(world, tmp_path):
    from kriko.gates import vocabulary_from_rows

    packauthor.author(world.settings.store_path, "", category="gaming mouse",
                      payload={**MICE, "claims": []})
    strict = vocabulary_from_rows({}, {"min_rationale_chars": "200"})
    done = categorypack.attach(
        world.settings.store_path, "gaming-mice", "Scyrox V8",
        [{"title": "Too thin", "body": "Short.",
          "evidence": [{"url": V8_PAGE, "quote": V8_QUOTE}]}],
        vocab=strict)
    assert done["claims_added"] == 0
    assert [one["title"] for one in done["refused"]] == ["Too thin"]
    assert yaml.safe_load(
        (packdraft.open_draft(world.settings.store_path, "gaming-mice").root
         / "data" / "claims.yaml").read_text(encoding="utf-8")) in (None, [])
