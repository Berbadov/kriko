"""B150: the agents settle the exact version from the listing, not the reader.

The reader's words: *"figure it out which more information agents needs by its
own from the product page? because i may not know which engine code is this"*.
Three things stood between that and the run:

* the research door sent the listing's title and nothing else, so the agent
  asked "233 hp or 211 hp?" about a page that printed the power;
* the first adapter whose globs hit a host read the page — an agent-written
  phone pack claiming the same marketplace read every car on it, with no
  context, and held the quick look to the phone pack's principle;
* the draft's line-up said the same car in another word order than its
  subject, and the subject was quarantined as off-category.
"""

import json
import textwrap
import threading
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import pagefacts, packauthor
from app.web.app import create_app
from app.web.settings import Settings
from kriko.pack import build
from kriko.store import packstore
from kriko.store.db import connect

HOST = "https://market.invalid/listing/*"
URL = "https://market.invalid/listing/42"


def _pack(root, pack_id, subjects, adapter, claims=""):
    for sub in ("vocabulary", "data", "research", "adapters"):
        (root / sub).mkdir(parents=True)
    (root / "pack.toml").write_text(textwrap.dedent(f"""
        [pack]
        id = "{pack_id}"
        name = "{pack_id}"
        version = "0.1.0"
        license = "CC0-1.0"
        [identity]
        product = ["brand", "model"]
    """), encoding="utf-8")
    (root / "vocabulary" / "terms.yaml").write_text(textwrap.dedent("""
        - {term_id: product, role: subject_kind}
        - {term_id: brand, role: attribute, datatype: text, match: {required: true}}
        - {term_id: model, role: attribute, datatype: text, match: {required: true}}
        - {term_id: usage_km, role: context_key, datatype: number, unit: km}
        - {term_id: mech, role: domain}
    """), encoding="utf-8")
    (root / "data" / "subjects.yaml").write_text(textwrap.dedent(subjects), encoding="utf-8")
    (root / "data" / "claims.yaml").write_text(textwrap.dedent(claims) or "[]\n",
                                               encoding="utf-8")
    (root / "research" / "principle.md").write_text(f"The {pack_id} bar.", encoding="utf-8")
    (root / "research" / "templates.yaml").write_text('- "{alias} faults"\n', encoding="utf-8")
    (root / "adapters" / "market.json").write_text(json.dumps(adapter), encoding="utf-8")
    return root


#: Sorts first, so the old first-match rule picked it. Reads a brand and a
#: model off any page — a car's too — but knows only phones.
PHONES = {
    "id": "market", "site": "market.invalid", "subject_kind": "product",
    "match": [HOST],
    "identity": {"brand": {"labels": ["brand"]}, "model": {"labels": ["series"]}},
}

MACHINES = {
    "id": "market", "site": "market.invalid", "subject_kind": "product",
    "match": [HOST],
    "identity": {"brand": {"labels": ["brand"], "vocabulary": "brand"},
                 "model": {"labels": ["series"], "vocabulary": "model"}},
    "context": {"usage_km": {"labels": ["km"], "parse": "int_range",
                             "min": 0, "max": 2000000}},
}

PAGE = {"brand": "Acme", "series": "Roadster", "km": "95.000", "power": "233 hp"}


@pytest.fixture
def client(tmp_path):
    store_path = tmp_path / "store.sqlite"
    conn = connect(store_path)
    for pack_id, subjects, adapter, claims in (
        ("aaa.phones", """
            - kind: product
              label: Apple iPhone 15
              identity: {brand: apple, model: iphone 15}
        """, PHONES, ""),
        ("zzz.machines", """
            - kind: product
              label: Acme Roadster
              identity: {brand: acme, model: roadster}
        """, MACHINES, """
            - subject: {kind: product, identity: {brand: acme, model: roadster}}
              kind: known_issue
              domain: mech
              severity: high
              text: {en: {title: Timing chain stretches early, body: b, advice: a}}
              evidence:
                - {url: "https://e.invalid/x", quote: Chains go at 80k.}
        """),
    ):
        root = _pack(tmp_path / pack_id, pack_id, subjects, adapter, claims)
        packstore.install(conn, build.build(root, tmp_path / f"{pack_id}.kpack"))
    conn.close()
    app = create_app(Settings(
        store_path=store_path,
        analysis_log_path=tmp_path / "analyses.jsonl",
        app_state_path=tmp_path / "app.sqlite",
    ))
    test_client = TestClient(app)
    try:
        yield test_client
    finally:
        app.state.jobs.shutdown(wait=True)


# ── the fullest reading wins ───────────────────────────────────────────────


def test_two_packs_on_one_site_the_pack_that_knows_the_product_reads_it(client):
    r = client.post("/api/analyze", json={
        "url": URL, "origin": "extension", "fields": PAGE, "title": "Acme Roadster"})
    body = r.json()
    assert {k: v.lower() for k, v in body["identity"].items()} == {"brand": "acme", "model": "roadster"}, body
    assert body["context"]["usage_km"] == 95000
    assert [c["title"] for c in body["claims"]] == ["Timing chain stretches early"]


def test_the_phone_on_the_same_site_is_still_read_by_the_phone_pack(client):
    from app.web.routers.extension import _listing_pack

    store = connect(client.app.state.settings.store_path)
    try:
        assert _listing_pack(store, None, URL, {"brand": "Apple", "series": "iPhone 15"},
                             "Apple iPhone 15") == "aaa.phones"
        assert _listing_pack(store, None, URL, PAGE, "Acme Roadster") == "zzz.machines"
    finally:
        store.close()


# ── the listing's facts reach every agent ──────────────────────────────────


def test_facts_are_trimmed_to_what_a_prompt_can_carry():
    many = {f"row {n}": "x" * 500 for n in range(100)}
    page = pagefacts.clean({"ld:@type": "car", **many}, "d" * 9000)
    assert len(page["facts"]) == pagefacts.MAX_FACTS
    assert "ld:@type" not in page["facts"]
    assert all(len(v) == pagefacts.MAX_VALUE for v in page["facts"].values())
    assert len(page["description"]) == pagefacts.MAX_DESCRIPTION
    assert pagefacts.block(pagefacts.clean({}, "")) == ""
    assert pagefacts.block(None) == ""


def test_the_block_tells_the_agent_to_settle_codes_itself():
    text = pagefacts.block(pagefacts.clean({"Motor Gücü": "233 hp"}, "BUG motor"))
    assert "* Motor Gücü: 233 hp" in text
    assert "BUG motor" in text
    assert "never ask them for a code" in text


def test_research_this_product_sends_the_listing_to_all_three_passes(client, monkeypatch):
    from app import providers
    from app.providers import harness

    prompts = {"quick": [], "check": [], "author": []}
    done = threading.Event()

    class FakeHarness:
        search_provider = "fixture"

        def ask(self, prompt):
            if prompt.startswith("# Quick look"):
                prompts["quick"].append(prompt)
                return '```json\n{"assumed": "", "risks": []}\n```'
            if prompt.startswith("# Is this product identity"):
                prompts["check"].append(prompt)
                return json.dumps({"ambiguous": False})
            prompts["author"].append(prompt)
            done.set()
            return "not a pack"

    monkeypatch.setattr(harness, "available", lambda: [SimpleNamespace(id="fixture")])
    monkeypatch.setattr(providers, "harness_researcher", lambda **kw: FakeHarness())
    r = client.post("/api/extension/research-plane", json={
        "q": "Zephyr Tourer 3.0", "allow_draft": True, "url": URL,
        "facts": {"Motor Gücü": "233 hp", "Yıl": "2008"},
        "description": "Sahibinden temiz, BUG motor.",
    })
    assert r.status_code == 200, r.text
    assert done.wait(10)
    deadline = time.time() + 10
    while not prompts["quick"] and time.time() < deadline:
        time.sleep(0.05)
    for name in ("quick", "check", "author"):
        assert prompts[name], name
        assert "* Motor Gücü: 233 hp" in prompts[name][0], name
        assert "BUG motor" in prompts[name][0], name
    assert "Never a technical fact" in prompts["check"][0]


# ── the same product in another word order is in scope ─────────────────────


def test_the_line_up_names_the_subject_in_another_order():
    lineup = {packauthor._flat(
        "Audi Q7 4L (2005-2015) 3.0 TDI Quattro Tiptronic, 2008 model year, "
        "BUG engine code (233 hp)")}
    assert packauthor._in_scope(
        packauthor._flat("2008 Audi Q7 3.0 TDI Quattro Tiptronic (BUG)"), lineup)


def test_a_different_model_from_the_same_maker_is_still_quarantined():
    lineup = {packauthor._flat("Audi Q7 4L 3.0 TDI Quattro Tiptronic 2008")}
    assert not packauthor._in_scope(packauthor._flat("Audi A4 2.0 TDI"), lineup)
