"""The local dashboard.

The app is built by a factory taking `Settings`, which is what makes these tests
possible at all: each builds an app pointed at its own temporary store. The old
hub computed its paths as import-time module constants, so its endpoints could
not be tested without monkeypatching the module and two tests could not run
against two stores. That coupling is what blocked backlog B28's router split.
"""

import json
import sqlite3
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
                store_path=store_path,
                analysis_log_path=tmp_path / "analyses.jsonl",
                # Not optional, and it was missing: the default is
                # `~/.kriko/app.sqlite`, so every test on this fixture used to
                # write its history, marks and sightings into the developer's
                # own. See src/app/tests/conftest.py — that is now a failure
                # rather than a comment.
                app_state_path=tmp_path / "app.sqlite",
            )
        )
    )
    # Exposed so tests that need to point another surface (e.g. the MCP
    # server) at this exact store can do so without rebuilding it.
    tc.store_path = store_path
    return tc


# ── the page itself ──────────────────────────────────────────────────────


def test_root_identifies_the_service(client):
    assert client.get("/").status_code == 200
    assert client.get("/").json()["desktop"] == "Tauri"
    assert client.get("/api/docs").status_code == 200


def test_health_reports_which_store_it_is_looking_at(client):
    body = client.get("/api/health").json()
    assert body["ok"] is True
    assert body["store"].endswith("store.sqlite")


def test_health_serves_the_work_answers_from_the_probe_snapshot(client):
    """`store_readable` and `jobs` come from the background probe, not inline.

    The shell's watchdog polls this endpoint while the app is busy, and a
    health check that waits on the store lock or the runner's lock reads as
    "stopped answering" to a process that is fine. The endpoint must answer
    from the last finished probe round, so these keys are always present and
    shaped the way the probe computes them.
    """
    body = client.get("/api/health").json()
    assert body["store_readable"] is True
    assert set(body["jobs"]) == {"running", "queued", "concurrency", "agent_slots"}


def test_health_answers_while_the_store_is_locked(tmp_path):
    """A locked store must not hold the health answer.

    Reproduces the wedged-watchdog report: another process holds the engine
    store (an orphaned sidecar, the MCP server) and the sync probe's SQLite
    read blocks on the 5 s busy timeout. With the answer served from the
    probe snapshot the endpoint still returns immediately, carrying the last
    finished round.
    """
    import time

    store_path = tmp_path / "locked.sqlite"
    conn = connect(store_path)
    conn.execute("BEGIN EXCLUSIVE")
    conn.execute("CREATE TABLE IF NOT EXISTS hold (x)")
    # An exclusive transaction held open blocks every other connection's
    # read past its busy timeout; commit nothing until the end.
    app = create_app(
        Settings(
            store_path=store_path,
            analysis_log_path=tmp_path / "analyses.jsonl",
            app_state_path=tmp_path / "app.sqlite",
        )
    )
    probe = app.state.health_probe
    try:
        with TestClient(app) as tc:
            started = time.monotonic()
            body = tc.get("/api/health").json()
            elapsed = time.monotonic() - started
        assert body["ok"] is True
        # The inline probe would block for the store's 5 s busy timeout; the
        # snapshot answer is immediate (the generous bound leaves room for a
        # slow CI machine, not for a SQLite wait).
        assert elapsed < 2.0, f"/api/health took {elapsed:.2f}s with the store locked"
        assert "store_readable" in body and "jobs" in body
    finally:
        conn.rollback()
        conn.close()
        probe.stop()


def test_the_probe_keeps_the_previous_answer_when_a_round_times_out(tmp_path):
    """A probe round that outlives its budget reports staleness, not a default."""
    import threading

    from app.web import app as web_app

    store_path = tmp_path / "store.sqlite"
    connect(store_path).close()

    class WedgedRunner:
        def concurrency(self):
            threading.Event().wait(30)  # never answers inside the budget
            return {"running": 0, "queued": 0, "concurrency": 0, "agent_slots": 0}

    probe = web_app.HealthProbe(store_path, WedgedRunner())
    try:
        first = probe.snapshot()
        assert first["store_readable"] is True
        # Force a refresh whose jobs probe wedges; the store half still
        # finishes, the jobs half keeps the previous value.
        store_readable, jobs = probe._refresh()
        assert store_readable is True
        assert jobs == first["jobs"], "a wedged probe must keep the last answer"
    finally:
        probe.stop()


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


def test_a_limit_outside_its_bound_is_refused_or_clamped(client):
    """D12: every one of these limits reaches the SQL behind it, and a negative
    limit is SQLite's "no limit" — so an unclamped caller could ask for a whole
    catalog. The ask endpoints carry the bound on the model; the list views
    clamp in the handler."""
    assert client.post("/api/lookup", json={"limit": -1}).status_code == 422
    assert client.post("/api/lookup", json={"limit": 5000}).status_code == 422
    assert client.post(
        "/api/analyze", json={"url": "https://a.test/x", "limit": -1}
    ).status_code == 422
    assert client.get(
        "/api/packs/tools/gaps", params={"limit": -1}
    ).json() == client.get("/api/packs/tools/gaps", params={"limit": 1}).json()
    assert client.get(
        "/api/health/weakest", params={"limit": -1}
    ).json()["claims"] == []


# ── browsing ─────────────────────────────────────────────────────────────


def test_subject_detail_shows_attributes_relations_and_claims(client):
    subjects = client.get("/api/subjects?q=DHP484").json()
    detail = client.get(f"/api/subjects/{subjects[0]['subject_id']}").json()
    assert detail["label"] == "Makita DHP484"
    assert {a["key"] for a in detail["attributes"]} == {"brand", "model"}
    assert detail["relations"][0]["object_label"] == "LXT 18V"


def test_an_unknown_subject_is_a_404(client):
    assert client.get("/api/subjects/nope").status_code == 404


def test_a_percent_in_the_search_box_matches_literally_not_every_subject(client):
    # `%` and `_` are LIKE wildcards. Typed into Search they are two ordinary
    # characters a reader might paste from a model number — "%" must not read
    # as "match anything" and return the whole catalog (knowledge-18).
    assert client.get("/api/subjects?q=%25").json() == []
    assert client.get("/api/subjects?q=_").json() == []
    # The escape must not break matching what is actually there.
    assert client.get("/api/subjects?q=DHP484").json()


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


def test_compare_is_only_offered_once_there_are_two_saved_checks(client):
    """extension-16: the panel's Compare button used to be built unconditionally,
    opening onto Compare's own "needs two saved checks" empty state on the very
    first analysis. `compare_ready` lets the extension withhold the button
    instead of the app being the one to say no."""
    body = {
        "url": "https://toolshop.invalid/item/dhp484",
        "title": "Makita DHP484 combi drill",
        "fields": {"Model No": "DHP484"},
    }
    first = client.post("/api/analyze", json=body).json()
    assert first["compare_ready"] is False
    second = client.post("/api/analyze", json=body).json()
    assert second["compare_ready"] is True


def test_a_site_no_installed_pack_can_read_says_so_not_an_empty_answer(client):
    """Silence would look identical to "this product has no known issues" — and
    a site nothing reads is an expected, frequent answer (check-21), not a
    server error, so it comes back 200 with a reason rather than a 404."""
    r = client.post(
        "/api/analyze", json={"url": "https://elsewhere.invalid/item/1", "fields": {}}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["readable"] is False
    assert body["reason"] == "no_adapter"


def test_a_bare_url_with_no_scraped_fields_says_the_page_was_not_read(client):
    """A pasted URL alone (check-1): the adapter matches the site, but there is
    no scraped DOM to map, so `mapped.identity` is empty. Running the lookup
    anyway would ask "what is known about no product in particular" and come
    back `no_match` — indistinguishable from "no pack covers this category"."""
    r = client.post(
        "/api/analyze",
        json={"url": "https://toolshop.invalid/item/dhp484", "fields": {}},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["readable"] is False
    assert body["reason"] == "page_not_read"


def test_the_adapters_endpoint_tells_the_client_where_it_is_worth_scraping(client):
    rows = client.get("/api/adapters").json()
    assert [a["id"] for a in rows] == ["toolshop"]
    assert rows[0]["match"] == ["*toolshop.invalid/item/*"]


def test_the_adapters_endpoint_hands_the_client_its_declared_panel(client):
    """The rules for the reader's own page ride with the adapter.

    The extension renders two blocks from the page itself rather than from the
    engine's answer — a damage silhouette and an equipment list on a listing
    site — and until this shipped, the words, the selectors, the titles and
    the alert thresholds for them were JavaScript in `extension/`. That is the
    same failure `_MAKE_MAP` was: a manual edit per site, per market, per
    category, in the one language none of the repo's AST gates can read.

    A pack that declares none gets an empty block rather than a missing key,
    so the client has one kind of absent to handle.
    """
    rows = client.get("/api/adapters").json()
    assert all("local_panel" in row for row in rows)
    assert rows[0]["local_panel"] == {}


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


def test_a_failure_to_record_a_label_never_costs_the_reader_the_answer(client, monkeypatch):
    """The instrument must not break the experiment.

    Every caller of `record_unmapped` is on the path of a reader waiting for
    an answer about a car they are standing next to. A coverage signal is
    worth less than that, always.
    """
    from app.web import state as state_module

    def explode(*args, **kwargs):
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(state_module, "record_unmapped", explode)
    r = client.post(
        "/api/analyze",
        json={
            "url": "https://toolshop.invalid/item/dhp484",
            "fields": {"Model No": "DHP484", "Torque": "54 Nm"},
        },
    )
    assert r.status_code == 200
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
    binary rarely and through the desktop shell. Collapsing them into one "version" is how
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
    # A field is required (check-1): an adapter matched but nothing scraped
    # is now reported as "page not read" rather than run through the lookup,
    # so this needs at least one field to reach the door-tracking it tests.
    body = {
        "url": "https://toolshop.invalid/item/dhp484",
        "fields": {"Model No": "DHP484"},
    }
    client.post("/api/analyze", json={**body, "origin": "extension"})
    client.post("/api/analyze", json=body)

    # Newest first, and the fixture's store carries earlier tests' rows, so
    # read only the two this test just wrote.
    items = client.get("/api/history").json()["items"][:2]
    assert [item["source"] for item in items] == ["analyze", "extension"]


def test_an_analysis_labels_history_by_the_matched_subject_not_the_url(client):
    """check-15: the history row and Result heading used to be the raw,
    150-character listing address. Once the adapter resolved a product, the
    row should say what was found, not where it was pasted from."""
    client.post(
        "/api/analyze",
        json={
            "url": "https://toolshop.invalid/item/dhp484",
            "fields": {"Model No": "DHP484"},
        },
    )
    label = client.get("/api/history").json()["items"][0]["label"]
    assert label == "Makita DHP484"


def test_a_lookup_is_labelled_by_the_matched_subject_when_exact(client):
    """check-14: identity values joined in alphabetical key order read as
    value soup ("brand makita model DHP484"); the subject's own label reads
    as a product name."""
    client.post(
        "/api/lookup",
        json={"kind": "product", "identity": {"brand": "makita", "model": "DHP484"}},
    )
    label = client.get("/api/history").json()["items"][0]["label"]
    assert label == "Makita DHP484"


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


# ── the research protocol, as a skill ───────────────────────────────────


def test_the_skill_says_what_this_installation_considers_worth_keeping(client):
    """The protocol is assembled from the packs, not written in the binary.

    The same agent researching a car and a power tool must be told two
    different things about what counts, and neither sentence may live in
    `app/` — otherwise the protocol stops versioning with the knowledge.
    """
    body = client.get("/api/agent-skill").json()["body"]
    assert "Tools" in body
    # B178: the bar is the pack's and reaches the agent per subject, through
    # `research_brief`; the skill stays the same size whatever a pack says.
    assert "Only the expensive." not in body
    brief = _brief(client, ids.subject_id("product", {"brand": "makita", "model": "DHP484"}))
    assert "Only the expensive." in brief


def _brief(client, subject_id: str) -> str:
    from kriko.research import plan_task
    from kriko.research.agent import AgentResearcher

    conn = connect(client.app.state.settings.store_path)
    try:
        return AgentResearcher().brief(plan_task(conn, subject_id, "tools"))
    finally:
        conn.close()


def test_the_skill_names_the_loop_in_order(client):
    payload = client.get("/api/agent-skill").json()
    # The agenda leads: `coverage_gaps` is alphabetical, so an agent that
    # starts there researches subjects beginning with A while the product
    # someone actually looked up waits. See app/agenda.py.
    assert [s["tool"] for s in payload["steps"]][0] == "research_agenda"
    assert [s["tool"] for s in payload["steps"]][-1] == "submit_findings"
    # The quote rule is the one thing an agent must not learn by trial and
    # error: `submit_findings` rejects a paraphrase, and an agent that finds
    # that out from an error has already thrown the document away.
    assert "quote" in payload["body"]


def test_the_frontmatter_description_is_one_line(client):
    """A harness matches a skill by reading this line. A wrapped description
    is not a description — it is a parse error the reader never sees."""
    body = client.get("/api/agent-skill").json()["body"]
    found = re.search(r"^description: (.+)$", body, re.M)
    assert found is not None, "the skill body has no description line"
    description = found.group(1)
    assert "\n" not in description
    assert len(description) > 40


def test_the_brief_states_the_pack_keys_and_words_rather_than_letting_an_agent_guess(client):
    """An agent that has to guess an identity key invents a plausible one.

    B178 moved these from the skill, where they made its length depend on the
    packs, to the brief, which is per subject. The identity is read off the
    rows and the domain words off the pack's vocabulary, so a second category
    gets its own set with no edit here.
    """
    brief = _brief(client, ids.subject_id("product", {"brand": "makita", "model": "DHP484"}))
    assert "brand=makita" in brief and "model=DHP484" in brief
    # The domain vocabulary is the other invented-value risk: a claim filed
    # under a domain the pack never declared is unfindable.
    assert "`domain` — one of: " in brief and "mech" in brief


def test_the_skill_counts_what_is_held_and_what_is_missing(client):
    """The gap count is what turns a protocol document into a task list."""
    body = client.get("/api/agent-skill").json()["body"]
    assert "4 subjects, 2 claims, 2 with none." in body


def test_the_skill_carries_no_worked_example_from_any_category(client):
    """B178: it names no product. The subject to start on comes from
    `research_agenda`, which is live, and not from an example that goes stale."""
    body = client.get("/api/agent-skill").json()["body"]
    assert "research_brief(subject_id=" not in body
    assert "has nothing known about it" not in body


def test_the_skill_teaches_the_refusals_before_they_happen(client):
    """Every refusal `accept_findings` can return is named in the document.

    An agent that learns "quotes must be verbatim" from a rejection has
    already closed the tab it read the sentence in.
    """
    body = client.get("/api/agent-skill").json()["body"]
    for phrase in ("document_text", "verbatim", "`severity`", "`domain`"):
        assert phrase in body


def test_the_skill_generator_types_no_category_words(client):
    """The whole point: `app/` may describe a pack, never know one.

    A `_MAX_WORDS`-style constant is fine; "engine_code" is not. This walks
    the module's own source rather than its output, because the output is
    *supposed* to be full of the fixture pack's words.
    """
    from pathlib import Path

    from app import agentskill

    source = Path(agentskill.__file__).read_text(encoding="utf-8")
    for word in ("engine_code", "make", "mileage", "brand", "voltage", "cam belt"):
        assert f'"{word}"' not in source
        assert f"'{word}'" not in source


def test_a_store_with_no_packs_gets_the_authoring_skill(tmp_path):
    """Nothing to research is not nothing to do (B96).

    This test used to assert the opposite — no packs, no skill — on the
    reasoning that a store with no knowledge has no research protocol. True,
    and it left an agent connected to a fresh install with no instructions at
    all, which is what the reader hit: "no agents guideline for brand new
    packages". The job on an empty installation is to author the first pack,
    so that is what the skill says, and it says nothing about a research loop
    it has no principle to hold anything to.
    """
    app_ = create_app(
        Settings(
            store_path=tmp_path / "empty.sqlite",
            app_state_path=tmp_path / "app.sqlite",
            analysis_log_path=tmp_path / "a.jsonl",
        )
    )
    with TestClient(app_) as empty:
        body = empty.get("/api/agent-skill").json()["body"]
    assert "draft_pack" in body
    assert "This installation has no packs" in body
    # And not the research loop: an agenda over nothing is a prompt spent on
    # instructions the agent cannot follow.
    assert "## The five steps" not in body


def test_connecting_installs_the_skill_next_to_the_config(client, tmp_path, monkeypatch):
    from app import agentconfig

    monkeypatch.setattr(agentconfig, "_home", lambda: tmp_path / "home")
    written = client.post("/api/agent-targets/claude-code/connect").json()["skill"]

    assert written.endswith("SKILL.md")
    assert "## The five steps" in (tmp_path / "home" / ".claude/skills"
                                     / "kriko-research" / "SKILL.md").read_text(encoding="utf-8")


def test_a_harness_with_nowhere_to_put_a_skill_still_connects(client, tmp_path, monkeypatch):
    from app import agentconfig

    monkeypatch.setattr(agentconfig, "_home", lambda: tmp_path / "home")
    row = client.post("/api/agent-targets/cursor/connect").json()

    assert row["state"] == "connected"
    assert row["skill"] is None

