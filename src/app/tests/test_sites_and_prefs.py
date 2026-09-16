"""Sites this installation can learn, and the three choices it now has.

*"I cannot open the web extension on the pages that aren't registered, so
basically it opens on sahibinden only."* — the panel was never missing; the
**site** was, and the only way to add one was to author a whole pack.

*"Don't forget preferred agent / api model / Tavily and Exa options, user info
on credits and the cost."* — three settings that existed as facts rather than
decisions: the first CLI found, whatever `LLM_MODEL` said, and Exa because Exa
was the only provider with code.
"""

import pytest
from fastapi.testclient import TestClient

from app import costs, keys, prefs, sites
from app.web import state
from app.web.app import create_app
from app.web.settings import Settings
from kriko.store.db import connect


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        store_path=tmp_path / "k.sqlite",
        app_state_path=tmp_path / "app.sqlite",
        analysis_log_path=tmp_path / "a.jsonl",
    )


@pytest.fixture
def client(settings) -> TestClient:
    connect(settings.store_path).close()
    return TestClient(create_app(settings))


ADAPTER = {
    "site": "arabam.com",
    "fields": {"brand": {"labels": ["Marka"]}, "series": {"labels": ["Seri"]}},
}


# ── the boundary: an adapter's `site` becomes a permission in a browser ─────


def test_an_adapter_may_not_claim_the_whole_web():
    """The one piece of agent-written data with teeth: `site` becomes a host
    permission and an injection target."""
    for bad in ("*", "*.com", "https://example.com/path", "example.com:8080/x"):
        with pytest.raises(sites.SiteRefused):
            sites.check({**ADAPTER, "site": bad})


def test_an_adapter_may_not_match_a_site_it_is_not_for():
    with pytest.raises(sites.SiteRefused) as raised:
        sites.check({**ADAPTER, "match": ["*://*.evil.test/*"]})
    assert "not on arabam.com" in str(raised.value)


def test_an_adapter_with_no_rules_is_refused():
    with pytest.raises(sites.SiteRefused):
        sites.check({"site": "arabam.com", "fields": {}})


def test_a_missing_match_defaults_to_the_site_and_nothing_else():
    assert sites.check(ADAPTER)["match"] == ["*://*.arabam.com/*"]


# ── learning a site ─────────────────────────────────────────────────────────


def test_a_page_nothing_can_read_becomes_an_ask(client, settings):
    """What the toolbar button now does instead of failing silently."""
    answer = client.post(
        "/api/sites/seen",
        json={"url": "https://www.arabam.com/ilan/123", "title": "Golf"},
    ).json()
    assert answer["readable"] is False
    assert answer["request"]["host"] == "arabam.com"
    assert answer["request"]["sample_url"].endswith("/ilan/123")
    # Asked twice is one row with a count, not two rows: the question is which
    # site to learn next, not how much somebody browsed.
    client.post("/api/sites/seen", json={"url": "https://arabam.com/ilan/9"})
    (row,) = client.get("/api/sites").json()["requested"]
    assert row["asks"] == 2


def test_a_learned_site_is_readable_and_shows_where_it_came_from(client, settings):
    conn = state.connect(settings.app_state_path)
    state.save_local_adapter(conn, host="arabam.com", spec=sites.check(ADAPTER))
    body = client.get("/api/sites").json()
    assert body["registered"][0]["site"] == "arabam.com"
    assert body["registered"][0]["source"] == "local"
    answer = client.post(
        "/api/sites/seen", json={"url": "https://arabam.com/ilan/1"}
    ).json()
    assert answer["readable"] is True


def test_a_learned_site_reaches_the_extension(client, settings):
    """`/api/adapters` is what the extension reads to decide where to inject.
    A site the reader registered is useless if the browser never runs on it —
    and that seam is exactly what "it only opens on sahibinden" was."""
    conn = state.connect(settings.app_state_path)
    state.save_local_adapter(conn, host="arabam.com", spec=sites.check(ADAPTER))
    hosts = {row["site"] for row in client.get("/api/adapters").json()}
    assert "arabam.com" in hosts


def test_a_packs_adapter_always_wins_over_a_learned_one(settings, tmp_path):
    """A published adapter is knowledge somebody can be held to; a local one is
    what this copy worked out. The reader is never in a position where their own
    guess overrides a pack author's."""
    store = connect(settings.store_path)
    store.execute(
        "INSERT INTO packs (pack_id, name, version, schema_version, built_at,"
        " content_digest, enabled, installed_at)"
        " VALUES ('probe', 'Probe', '1', 1, '2026-09-01', 'd', 1, '2026-09-01')"
    )
    store.execute(
        "INSERT INTO pack_assets (pack_id, name, kind, content)"
        " VALUES ('probe', 'adapters/arabam.json', 'adapter', ?)",
        # `*arabam.com*` rather than `*.arabam.com`: the engine's matcher is a
        # glob over the whole URL, so a leading dot would miss the bare host —
        # which is how a real pack writes it.
        ('{"id": "pack.arabam", "site": "arabam.com",'
         ' "match": ["*arabam.com/*"], "fields": {}}',),
    )
    store.commit()
    conn = state.connect(settings.app_state_path)
    state.save_local_adapter(conn, host="arabam.com", spec=sites.check(ADAPTER))
    found = sites.adapter_for(store, conn, "https://arabam.com/ilan/1")
    assert found["id"] == "pack.arabam"
    # And the redundant local copy is shown as such rather than hidden.
    local = [one for one in sites.registered(store, conn) if one["source"] == "local"]
    assert local[0]["superseded"] is True


def test_registering_a_site_is_an_operation(client, settings):
    client.post("/api/sites/seen", json={"url": "https://arabam.com/ilan/1"})
    started = client.post("/api/sites/arabam.com/register", json={})
    assert started.status_code == 200
    assert started.json()["kind"] == "site_register"
    conn = state.connect(settings.app_state_path)
    assert state.site_requests(conn)[0]["state"] == "working"


def test_a_refused_adapter_is_recorded_rather_than_stored(settings, monkeypatch):
    """An agent that writes an adapter claiming the whole web must leave the
    installation exactly as it was, and the reason has to be readable."""
    from app.providers import harness as harness_mod
    from app.web import tasks

    class _Plane:
        on_action = None
        search_provider = "fake"

        def ask(self, prompt):
            return '```json\n{"site": "*", "fields": {"a": {}}}\n```'

    monkeypatch.setattr(harness_mod, "available", lambda: [object()])
    monkeypatch.setattr("app.providers.harness_researcher", lambda **kw: _Plane())
    connect(settings.store_path).close()
    conn = state.connect(settings.app_state_path)
    state.record_site_request(conn, host="arabam.com", url="https://arabam.com/x")

    with pytest.raises(ValueError) as raised:
        tasks.site_register(
            settings, {"host": "arabam.com"}, _Progress()
        )
    assert "refused" in str(raised.value)
    assert state.local_adapters(conn) == []
    assert state.site_requests(conn)[0]["state"] == "refused"


def test_a_good_adapter_is_stored_and_the_ask_is_closed(settings, monkeypatch):
    from app.providers import harness as harness_mod
    from app.web import tasks

    class _Plane:
        on_action = None
        search_provider = "fake"

        def ask(self, prompt):
            assert "arabam.com" in prompt, "the brief has to name the site"
            return ('```json\n{"site": "arabam.com", "fields":'
                    ' {"brand": {"labels": ["Marka"]}}}\n```')

    monkeypatch.setattr(harness_mod, "available", lambda: [object()])
    monkeypatch.setattr("app.providers.harness_researcher", lambda **kw: _Plane())
    connect(settings.store_path).close()
    conn = state.connect(settings.app_state_path)
    state.record_site_request(conn, host="arabam.com", url="https://arabam.com/x")

    result = tasks.site_register(settings, {"host": "arabam.com"}, _Progress())
    assert result["adapter"]["site"] == "arabam.com"
    assert state.local_adapters(conn)[0]["host"] == "arabam.com"
    assert state.site_requests(conn)[0]["state"] == "done"


def test_forgetting_a_learned_site_leaves_the_packs_alone(client, settings):
    conn = state.connect(settings.app_state_path)
    state.save_local_adapter(conn, host="arabam.com", spec=sites.check(ADAPTER))
    assert client.delete("/api/sites/arabam.com").json()["forgotten"] is True
    assert client.get("/api/sites").json()["registered"] == []


# ── the three choices ───────────────────────────────────────────────────────


def test_nothing_chosen_behaves_exactly_as_before(client):
    body = client.get("/api/prefs").json()
    assert body["chosen"] == {
        "preferred_harness": "", "llm_model": "", "search_provider": ""
    }


def test_a_choice_survives_being_made(client):
    client.put("/api/prefs", json={"llm_model": "qwen3.5-27b"})
    assert client.get("/api/prefs").json()["chosen"]["llm_model"] == "qwen3.5-27b"
    # Merged, never replaced: setting one must not clear the others.
    client.put("/api/prefs", json={"search_provider": "tavily"})
    chosen = client.get("/api/prefs").json()["chosen"]
    assert chosen == {
        "preferred_harness": "", "llm_model": "qwen3.5-27b",
        "search_provider": "tavily",
    }


def test_either_search_key_is_enough_for_the_paid_plane():
    """Requiring both would have made adding a provider a way to break an
    installation that was working."""
    assert keys.ready(environ={"EXA_API_KEY": "x", "OPENAI_API_KEY": "y"})
    assert keys.ready(environ={"TAVILY_API_KEY": "x", "OPENAI_API_KEY": "y"})
    assert not keys.ready(environ={"OPENAI_API_KEY": "y"})
    assert not keys.ready(environ={"EXA_API_KEY": "x"})


def test_the_chosen_search_provider_is_the_one_wired(settings, monkeypatch):
    from app import providers

    monkeypatch.setattr(keys, "search_providers", lambda: ["exa", "tavily"])
    monkeypatch.setattr(providers.exa, "searcher", lambda: "exa-search")
    from app.providers import tavily as tavily_mod

    monkeypatch.setattr(tavily_mod, "searcher", lambda: "tavily-search")
    conn = state.connect(settings.app_state_path)
    prefs.write(conn, {prefs.SEARCH: "tavily"})
    found, name = providers._searcher(settings.app_state_path)
    assert (found, name) == ("tavily-search", "tavily")


def test_a_chosen_provider_with_no_key_falls_back_rather_than_failing(
    settings, monkeypatch
):
    """A preference is never why a run does not start."""
    from app import providers

    monkeypatch.setattr(keys, "search_providers", lambda: ["exa"])
    monkeypatch.setattr(providers.exa, "searcher", lambda: "exa-search")
    conn = state.connect(settings.app_state_path)
    prefs.write(conn, {prefs.SEARCH: "tavily"})
    assert providers._searcher(settings.app_state_path)[1] == "exa"


def test_an_uninstalled_preferred_harness_falls_back_rather_than_crashing(monkeypatch):
    """The same rule as the search provider's, one plane over: an unknown or
    uninstalled choice must fall back visibly, never crash a run outright when
    a different, perfectly usable CLI is right there."""
    from app.providers import harness

    class _Fake:
        id = "opencode"
        executable = "opencode"
        label = "opencode"

    monkeypatch.setattr(harness, "available", lambda: [_Fake()])
    from app import providers

    researcher = providers.harness_researcher(preferred="claude-code")
    assert researcher.harness.id == "opencode"
    assert "claude-code" in researcher.note
    assert "opencode" in researcher.note


def test_a_preference_that_is_the_only_one_installed_gets_no_fallback_note(monkeypatch):
    from app.providers import harness

    class _Fake:
        id = "claude-code"
        executable = "claude"
        label = "Claude Code"

    monkeypatch.setattr(harness, "available", lambda: [_Fake()])
    from app import providers

    researcher = providers.harness_researcher(preferred="claude-code")
    assert researcher.note == ""


def test_no_search_key_at_all_says_so(settings, monkeypatch):
    from app import providers

    monkeypatch.setattr(keys, "search_providers", lambda: [])
    with pytest.raises(providers.MissingKey) as raised:
        providers._searcher(settings.app_state_path)
    assert "Exa or Tavily" in str(raised.value)


# ── what it costs ───────────────────────────────────────────────────────────


def test_an_estimate_needs_more_than_one_run(settings):
    conn = state.connect(settings.app_state_path)
    assert costs.estimate(conn, plane="api")["usd"] is None
    for index in range(2):
        conn.execute(
            "INSERT INTO research_runs (run_id, plane, model, spent_usd,"
            " tokens_used, started_at) VALUES (?,?,?,?,?,datetime('now'))",
            (f"r{index}", "api", "m", 0.05, 1000),
        )
    conn.commit()
    estimate = costs.estimate(conn, plane="api", subjects=4)
    assert estimate["usd"] == pytest.approx(0.20, abs=0.001)
    assert "not a price list" in estimate["note"]


def test_a_run_that_counted_nothing_is_not_counted_as_free(settings):
    """"Six runs, two of which reported a cost" is the truth. Averaging the
    other four in as zero would understate every estimate built on it."""
    conn = state.connect(settings.app_state_path)
    conn.execute(
        "INSERT INTO research_runs (run_id, plane, model, spent_usd, started_at)"
        " VALUES ('a', 'api', 'm', 0.10, datetime('now'))"
    )
    conn.execute(
        "INSERT INTO research_runs (run_id, plane, model, spent_usd, started_at)"
        " VALUES ('b', 'api', 'm', NULL, datetime('now'))"
    )
    conn.commit()
    (row,) = costs.spent(conn)["planes"]
    assert row["runs"] == 2 and row["priced"] == 1
    assert row["usd_per_run"] == pytest.approx(0.10)


def test_there_is_no_invented_balance(client):
    body = client.get("/api/costs").json()
    assert body["balance"]["known"] is False
    assert "cannot read" in body["balance"]["note"]


class _Progress:
    def log(self, line: str) -> None:
        pass

    def set(self, progress: float, message: str = "") -> None:
        pass

    def check(self) -> None:
        pass
