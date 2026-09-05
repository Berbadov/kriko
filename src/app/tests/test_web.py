"""The local dashboard.

The app is built by a factory taking `Settings`, which is what makes these tests
possible at all: each builds an app pointed at its own temporary store. The old
hub computed its paths as import-time module constants, so its endpoints could
not be tested without monkeypatching the module and two tests could not run
against two stores. That coupling is what blocked backlog B28's router split.
"""

import json
import re
import textwrap

import pytest
from fastapi.testclient import TestClient

from app import mcp_server
from app.web.app import create_app
from app.web.settings import Settings
from kriko.pack import build
from kriko.store import ids, packstore
from kriko.store.db import SCHEMA_VERSION, connect

PACK = {
    "toml": """
        [pack]
        id = "tools"
        name = "Tools"
        version = "0.2.0"
        license = "CC0-1.0"
        [identity]
        product = ["brand", "model"]
        platform = ["brand", "platform"]
    """,
    "terms": """
        - {term_id: product, role: subject_kind}
        - {term_id: platform, role: subject_kind}
        - {term_id: part_of, role: predicate}
        - {term_id: brand, role: attribute, datatype: text, match: {required: true}}
        - {term_id: model, role: attribute, datatype: text, match: {required: true}}
        - {term_id: platform, role: attribute, datatype: text}
        - {term_id: usage_hours, role: context_key, datatype: number, unit: hours}
        - {term_id: mech, role: domain}
    """,
    "subjects": """
        - kind: platform
          label: LXT 18V
          identity: {brand: makita, platform: LXT}
        - kind: product
          label: Makita DHP484
          identity: {brand: makita, model: DHP484}
          relations:
            - {predicate: part_of, object: {kind: platform, identity: {brand: makita, platform: LXT}}}
        - kind: product
          label: Orphan Tool
          identity: {brand: acme, model: orphan}
        - kind: product
          label: Widget Bit
          identity: {brand: acme, model: widget}
    """,
    "claims": """
        - subject: {kind: platform, identity: {brand: makita, platform: LXT}}
          kind: known_issue
          domain: mech
          severity: high
          text: {en: {title: Cell imbalance trips protection, body: b, advice: a}}
          conditions:
            - {key: usage_hours, op: gte, value: 400, on_missing: open, weight: 0.7}
          evidence:
            - {url: "https://e.invalid/x", quote: Packs past 400 hours drift.}
            - {url: "https://f.invalid/y", quote: Mine is fine at 900., stance: refutes}
        - subject: {kind: product, identity: {brand: acme, model: widget}}
          kind: known_issue
          domain: mech
          severity: low
          text: {en: {title: Bit shank corrodes in storage, body: b, advice: a}}
          evidence:
            - {url: "https://g.invalid/z", quote: Rust after a damp winter.}
    """,
}


#: A second pack's worth of site knowledge, in the format the browser plane
#: consumes. Nothing here is category-specific to the engine — the labels and
#: the vocabulary attribute are the pack author's words.
ADAPTER = {
    "id": "toolshop",
    "site": "toolshop.invalid",
    "subject_kind": "product",
    "match": ["*toolshop.invalid/item/*"],
    "identity": {
        "brand": {"labels": ["brand", "marke"], "from": "title", "vocabulary": "brand"},
        "model": {"labels": ["model no", "model"]},
    },
    "context": {
        "usage_hours": {
            "labels": ["hours used"],
            "parse": "int_range",
            "min": 0,
            "max": 100000,
        },
        "free_text": {"from": "description"},
    },
    "ignore_labels": ["price", "colour", "hours until service"],
}


@pytest.fixture
def client(tmp_path):
    root = tmp_path / "p"
    for sub in ("vocabulary", "data", "research"):
        (root / sub).mkdir(parents=True)
    (root / "pack.toml").write_text(textwrap.dedent(PACK["toml"]), encoding="utf-8")
    (root / "vocabulary" / "terms.yaml").write_text(
        textwrap.dedent(PACK["terms"]), encoding="utf-8"
    )
    (root / "data" / "subjects.yaml").write_text(
        textwrap.dedent(PACK["subjects"]), encoding="utf-8"
    )
    (root / "data" / "claims.yaml").write_text(
        textwrap.dedent(PACK["claims"]), encoding="utf-8"
    )
    (root / "research" / "principle.md").write_text(
        "Only the expensive.", encoding="utf-8"
    )
    (root / "research" / "templates.yaml").write_text(
        '- "{alias} faults"\n', encoding="utf-8"
    )
    (root / "adapters").mkdir()
    (root / "adapters" / "toolshop.json").write_text(
        json.dumps(ADAPTER), encoding="utf-8"
    )

    store_path = tmp_path / "store.sqlite"
    conn = connect(store_path)
    packstore.install(conn, build.build(root, tmp_path / "p.kpack"))
    conn.close()
    tc = TestClient(
        create_app(
            Settings(
                store_path=store_path, analysis_log_path=tmp_path / "analyses.jsonl"
            )
        )
    )
    # Exposed so tests that need to point another surface (e.g. the MCP
    # server) at this exact store can do so without rebuilding it.
    tc.store_path = store_path
    return tc


# ── the page itself ──────────────────────────────────────────────────────


def test_the_page_and_its_assets_are_served(client):
    """Every asset the page asks for resolves.

    The views used to be asserted here as markup — `data-tab="dashboard"` and
    friends. They are rendered by the Svelte bundle now, so the server-side
    thing worth checking is not which tabs exist but that nothing the built
    index references 404s. That catches a stale or half-copied bundle, which
    the old markup assertions never could.
    """
    assert client.get("/").status_code == 200
    page = client.get("/").text
    assert '<div id="app">' in page

    referenced = re.findall(r'(?:src|href)="(/static/[^"]+)"', page)
    assert referenced, "the built index references no assets at all"
    for asset in referenced:
        assert client.get(asset).status_code == 200, f"{asset} is referenced but not served"


def test_health_reports_which_store_it_is_looking_at(client):
    body = client.get("/api/health").json()
    assert body["ok"] is True
    assert body["store"].endswith("store.sqlite")


def test_status_and_activity_are_control_plane_snapshots(client):
    status = client.get("/api/status").json()
    assert status["ok"] is True
    assert status["counts"]["packs"] == 1
    assert client.get("/api/activity").json() == {"items": [], "malformed": 0}


# ── packs ────────────────────────────────────────────────────────────────


def test_packs_lists_what_is_installed_with_its_contents(client):
    (pack,) = client.get("/api/packs").json()
    assert pack["pack_id"] == "tools"
    assert pack["subjects"] == 4
    assert pack["claims"] == 2
    assert pack["license"] == "CC0-1.0"
    assert pack["enabled"] is True


def test_disabling_a_pack_hides_it_from_reads_without_deleting_it(client):
    client.post("/api/packs/tools/enabled?enabled=false")
    assert client.get("/api/subjects").json() == []
    # ...but the rows are still there, so re-enabling is free.
    assert client.get("/api/packs").json()[0]["subjects"] == 4
    client.post("/api/packs/tools/enabled?enabled=true")
    assert client.get("/api/subjects").json()


def test_uninstalling_an_absent_pack_is_a_404(client):
    assert client.delete("/api/packs/nope").status_code == 404


def test_the_vocabulary_endpoint_reports_the_packs_own_words(client):
    vocab = client.get("/api/packs/tools/vocabulary").json()
    assert {t["term_id"] for t in vocab["context_key"]} == {"usage_hours"}
    assert vocab["context_key"][0]["unit"] == "hours"


# ── the form builds itself from pack data ────────────────────────────────


def test_identity_keys_come_from_the_pack_not_from_the_page(client):
    """Nothing in the UI knows what a drill or a car is.

    It asks which attributes identify a subject in the chosen pack and builds
    inputs for those, so a new category changes the form without changing a line
    of the page.
    """
    keys = {k["key"] for k in client.get("/api/identity-keys/tools").json()}
    assert keys == {"brand", "model", "platform"}


def test_kinds_are_reported_per_pack(client):
    kinds = client.get("/api/kinds").json()
    assert {k["kind"] for k in kinds} == {"product", "platform"}


# ── asking ───────────────────────────────────────────────────────────────


def test_a_lookup_returns_claims_with_their_reasons_and_sources(client):
    body = client.post(
        "/api/lookup",
        json={
            "kind": "product",
            "identity": {"brand": "makita", "model": "DHP484"},
            "context": {"usage_hours": 900},
        },
    ).json()

    assert body["method"] == "exact"
    assert body["coverage"] == "RISKS_FOUND"
    (claim,) = body["claims"]
    assert claim["title"] == "Cell imbalance trips protection"
    assert claim["subject"] == "LXT 18V"  # reached through part_of
    assert claim["why"], "every claim must explain its own rank"
    assert {s["stance"] for s in claim["sources"]} == {"supports", "refutes"}
    assert claim["disputed"] is True


def test_an_unknown_thing_answers_rather_than_erroring(client):
    body = client.post(
        "/api/lookup",
        json={"kind": "product", "identity": {"brand": "nobody", "model": "nothing"}},
    ).json()
    assert body["method"] == "no_match"
    assert body["claims"] == []


def test_an_unstated_context_value_still_returns_the_claim(client):
    """Fail-open, visible through the API."""
    body = client.post(
        "/api/lookup",
        json={"kind": "product", "identity": {"brand": "makita", "model": "DHP484"}},
    ).json()
    (claim,) = body["claims"]
    assert any("usage_hours not stated" in reason for reason in claim["why"])


# ── browsing ─────────────────────────────────────────────────────────────


def test_subject_detail_shows_attributes_relations_and_claims(client):
    subjects = client.get("/api/subjects?q=DHP484").json()
    detail = client.get(f"/api/subjects/{subjects[0]['subject_id']}").json()
    assert detail["label"] == "Makita DHP484"
    assert {a["key"] for a in detail["attributes"]} == {"brand", "model"}
    assert detail["relations"][0]["object_label"] == "LXT 18V"


def test_an_unknown_subject_is_a_404(client):
    assert client.get("/api/subjects/nope").status_code == 404


def test_the_brief_endpoint_carries_the_packs_principle(client):
    subjects = client.get("/api/subjects?q=DHP484").json()
    brief = client.get(f"/api/subjects/{subjects[0]['subject_id']}/brief").json()
    assert "Only the expensive." in brief["brief"]
    assert brief["queries"] == ["Makita DHP484 faults"]


# ── coverage ─────────────────────────────────────────────────────────────


def test_a_gap_is_a_subject_nothing_reaches_even_through_relations(client):
    """Counting direct claims alone would call every car unresearched.

    A car's claims live on its engine and gearbox, not on the car. The Makita
    has no claims of its own but reaches one through `part_of`; only the
    genuinely orphaned tool is a gap.
    """
    gaps = client.get("/api/packs/tools/gaps").json()
    assert [g["label"] for g in gaps] == ["Orphan Tool"]


# ── the browser plane ────────────────────────────────────────────────────
#
# This endpoint is the extension's entire contract, and the one place where a
# page the engine has never seen becomes a query. Nothing car-shaped appears
# below: the site, the labels and the identity keys are all the pack's.


def test_a_scraped_page_becomes_a_query_through_the_packs_adapter(client):
    r = client.post(
        "/api/analyze",
        json={
            "url": "https://toolshop.invalid/item/dhp484",
            "title": "Makita DHP484 combi drill",
            "fields": {"Model No": "DHP484", "Hours Used": "900", "Price": "£129"},
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["adapter"] == "toolshop"
    assert body["identity"] == {"brand": "makita", "model": "DHP484"}
    assert body["context"]["usage_hours"] == 900
    assert [c["title"] for c in body["claims"]] == ["Cell imbalance trips protection"]


def test_a_site_no_installed_pack_can_read_is_a_404_not_an_empty_answer(client):
    """Silence would look identical to "this product has no known issues"."""
    r = client.post(
        "/api/analyze", json={"url": "https://elsewhere.invalid/item/1", "fields": {}}
    )
    assert r.status_code == 404


def test_analysis_is_visible_in_recent_activity(client):
    client.post(
        "/api/analyze",
        json={
            "url": "https://toolshop.invalid/item/dhp484",
            "fields": {"Model No": "DHP484"},
        },
    )
    activity = client.get("/api/activity").json()
    assert len(activity["items"]) == 1
    assert activity["items"][0]["url"].endswith("dhp484")


def test_revision_history_and_lifecycle_events_are_visible(client):
    revisions = client.get("/api/packs/tools/revisions")
    assert revisions.status_code == 200
    assert revisions.json()[0]["active"] is True
    events = client.get("/api/packs/tools/events").json()
    assert events[0]["action"] == "install"


def test_the_adapters_endpoint_tells_the_client_where_it_is_worth_scraping(client):
    rows = client.get("/api/adapters").json()
    assert [a["id"] for a in rows] == ["toolshop"]
    assert rows[0]["match"] == ["*toolshop.invalid/item/*"]


def test_the_adapters_endpoint_hands_the_client_the_labels_to_look_for(client):
    """The content script keeps no vocabulary of its own.

    Its fallback scraper — the one that anchors on label *text* when the
    page's markup has been redesigned out from under the selectors — needs to
    know which labels are worth finding. That list is site knowledge, so it
    comes down the wire from the pack rather than living in JavaScript where
    a site change would mean shipping an extension release.
    """
    rows = client.get("/api/adapters").json()
    assert set(rows[0]["labels"]) >= {
        "brand",
        "marke",
        "model no",
        "model",
        "hours used",
    }
    #: Ignored labels come too: the client must be able to *see* a label in
    #: order to report it, and the server is what decides it means nothing.
    assert "colour" in rows[0]["labels"]


def test_a_label_no_rule_covers_is_reported_rather_than_silently_dropped(client):
    r = client.post(
        "/api/analyze",
        json={
            "url": "https://toolshop.invalid/item/dhp484",
            "fields": {"Model No": "DHP484", "Torque": "54 Nm"},
        },
    )
    assert r.json()["unmapped_labels"] == ["Torque"]


def test_an_ignored_label_never_answers_for_a_rule_it_merely_resembles(client):
    """ "Hours Until Service" contains "hours" and is not usage."""
    r = client.post(
        "/api/analyze",
        json={
            "url": "https://toolshop.invalid/item/dhp484",
            "fields": {"Model No": "DHP484", "Hours Until Service": "12"},
        },
    )
    assert "usage_hours" not in r.json()["context"]


def test_identity_is_read_from_the_title_when_the_page_has_no_label_for_it(client):
    """The values come from the pack's own identity rows, so this works
    without the engine ever being told what a brand is."""
    r = client.post(
        "/api/analyze",
        json={
            "url": "https://toolshop.invalid/item/dhp484",
            "title": "Makita DHP484 combi drill",
            "fields": {"Model No": "DHP484"},
        },
    )
    assert r.json()["identity"]["brand"] == "makita"


def test_a_page_that_resolves_nothing_says_so_instead_of_erroring(client):
    r = client.post(
        "/api/analyze",
        json={
            "url": "https://toolshop.invalid/item/unknown",
            "fields": {"Model No": "NOPE"},
        },
    )
    assert r.status_code == 200
    assert r.json()["coverage"] == "NOT_MATCHED"
    assert r.json()["claims"] == []


def test_the_answer_names_the_packs_that_produced_it(client):
    """Backlog B15's footer, re-pointed.

    The panel has always named the build that answered, so that a stale deploy
    was visible to anyone looking at it rather than silently serving pre-fix
    behaviour. With no server to be stale, the thing a reader now needs to
    identify is *whose knowledge* this is — and with several packs installed
    and no central authority, that is not a detail. It is the answer's byline.
    """
    r = client.post(
        "/api/analyze",
        json={
            "url": "https://toolshop.invalid/item/dhp484",
            "fields": {"Model No": "DHP484", "Hours Used": "900"},
        },
    )
    assert r.json()["packs"] == [{"pack_id": "tools", "version": "0.2.0"}]


def test_a_page_with_no_claims_names_no_packs_rather_than_all_of_them(client):
    r = client.post(
        "/api/analyze",
        json={"url": "https://toolshop.invalid/item/x", "fields": {"Model No": "NOPE"}},
    )
    assert r.json()["packs"] == []


def test_context_values_come_back_with_the_units_the_pack_declared(client):
    """So the panel can render "900 hours" without knowing what hours are.

    The alternative is a unit table in the extension, which is the same
    hardcoded-list bug in a different language: correct until a pack measures
    wear in charge cycles.
    """
    r = client.post(
        "/api/analyze",
        json={
            "url": "https://toolshop.invalid/item/dhp484",
            "fields": {"Model No": "DHP484", "Hours Used": "900"},
        },
    )
    assert r.json()["context_units"] == {"usage_hours": "hours"}


# ── claim health ─────────────────────────────────────────────────────────
#
# PACK now ships two sourced claims: "Cell imbalance trips protection" carries
# a refutation, "Bit shank corrodes in storage" carries only a supporting
# source. The refuted claim must rank first for that reason, not by accident
# of list order.


def test_the_liveness_probe_still_answers_after_the_health_router(client):
    """`/api/health` is the probe; `/api/health/weakest` is the new view."""
    assert client.get("/api/health").json()["ok"] is True


def test_the_weakest_endpoint_lists_claims_worst_first(client):
    body = client.get("/api/health/weakest").json()
    titles = [c["title"] for c in body["claims"]]
    assert titles == [
        "Cell imbalance trips protection",
        "Bit shank corrodes in storage",
    ]
    concerns = [tuple(c["concern"]) for c in body["claims"]]
    assert concerns == sorted(concerns)


def test_the_weakest_endpoint_reports_each_signal_separately(client):
    claim = client.get("/api/health/weakest").json()["claims"][0]
    for field in ("refuted_by", "independent_sources", "best_tier",
                  "best_trust", "oldest_retrieved_at", "newest_published_at"):
        assert field in claim


def test_the_weakest_endpoint_honours_the_limit(client):
    body = client.get("/api/health/weakest?limit=1").json()
    assert len(body["claims"]) <= 1


def test_the_weakest_endpoint_can_be_scoped_to_one_pack(client):
    body = client.get("/api/health/weakest?pack_id=tools").json()
    assert {c["pack_id"] for c in body["claims"]} <= {"tools"}


def test_the_subject_endpoint_returns_the_tree_with_its_evidence(client):
    subject = client.get("/api/subjects").json()[0]["subject_id"]
    body = client.get(f"/api/health/subject/{subject}").json()
    assert body["subject_id"] == subject
    assert body["claims"]
    assert "evidence" in body["claims"][0]
    assert "health" in body["claims"][0]


def test_an_unknown_subject_is_an_empty_tree_not_a_500(client):
    body = client.get("/api/health/subject/nope").json()
    assert body["claims"] == []


def test_the_health_view_never_writes(client):
    """Read-only by contract. If this view can mutate, it is not observability."""
    before = client.get("/api/health/weakest").json()
    client.get("/api/health/weakest")
    assert client.get("/api/health/weakest").json() == before


def test_the_mcp_tool_and_the_dashboard_agree_on_one_store(client, monkeypatch):
    """The dashboard and an agent must not be able to disagree.

    Both `subject_health` (mcp_server.py) and `/api/health/subject/{id}`
    (this router) are thin callers of `kriko.lookup.tree.tree_json` — this
    test is what makes that fact load-bearing rather than incidental: point
    both surfaces at the exact same store and their payloads must be
    byte-identical, not merely similar field-by-field.
    """
    monkeypatch.setattr(mcp_server, "STORE_PATH", client.store_path)
    subject_id = ids.subject_id("platform", {"brand": "makita", "platform": "LXT"})

    over_http = client.get(f"/api/health/subject/{subject_id}").json()
    over_mcp = mcp_server.subject_health(subject_id=subject_id)

    assert over_mcp == over_http
    assert over_http["claims"]  # not a vacuous comparison of two empty trees


def test_health_names_every_version_a_reader_might_be_asked_for(client):
    """"What am I running" has three answers, and they move on different clocks.

    The app binary, the store's schema, and each pack's own semver are
    deliberately independent — packs update weekly through the engine, the
    binary rarely and through Tauri. Collapsing them into one "version" is how
    a reader reports the wrong one.
    """
    body = client.get("/api/health").json()
    assert body["version"], "the app's own version is the first thing support asks for"
    assert body["schema_version"] == SCHEMA_VERSION
    assert body["packs"] == [{"pack_id": "tools", "version": "0.2.0"}]


def test_an_analysis_records_which_door_it_came_in_by(client):
    """The extension and the dashboard were the same row in history.

    Both POST /api/analyze, and `source` was hardcoded, so a reader could not
    tell an answer their browser produced from one they asked for here — which
    is the first thing you want to know when a result surprises you.
    """
    body = {"url": "https://toolshop.invalid/item/dhp484", "fields": {}}
    client.post("/api/analyze", json={**body, "origin": "extension"})
    client.post("/api/analyze", json=body)

    # Newest first, and the fixture's store carries earlier tests' rows, so
    # read only the two this test just wrote.
    items = client.get("/api/history").json()["items"][:2]
    assert [item["source"] for item in items] == ["analyze", "extension"]


def test_an_unknown_origin_is_refused_rather_than_recorded(client):
    """`source` is free text in the table, so the endpoint is the only gate.

    A closed vocabulary on purpose — this names which door a request came in
    by, and doors do not grow with pack coverage.
    """
    response = client.post(
        "/api/analyze",
        json={
            "url": "https://toolshop.invalid/item/dhp484",
            "fields": {},
            "origin": "whatever",
        },
    )
    assert response.status_code == 422
