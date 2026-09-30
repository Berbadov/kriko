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


def test_the_detail_shows_the_rules_a_local_adapter_reads(client, settings):
    """B181: the screen shows, per site, what is read and what was missed."""
    conn = state.connect(settings.app_state_path)
    state.save_local_adapter(conn, host="arabam.com", spec=sites.check(ADAPTER))
    body = client.get("/api/sites/arabam.com/detail").json()
    assert body["editable"] is True
    keys = {rule["key"] for rule in body["rules"]}
    assert "brand" in keys and "series" in keys
    assert body["match"] == ["*://*.arabam.com/*"]
    assert body["spec"]["site"] == "arabam.com"


def test_a_packs_detail_is_read_only(client, settings, tmp_path):
    """B181: a shipped adapter is shown, not offered for editing."""
    store = connect(settings.store_path)
    store.execute(
        "INSERT INTO packs (pack_id, name, version, schema_version, built_at,"
        " content_digest, enabled, installed_at)"
        " VALUES ('probe', 'Probe', '1', 1, '2026-09-01', 'd', 1, '2026-09-01')"
    )
    store.execute(
        "INSERT INTO pack_assets (pack_id, name, kind, content)"
        " VALUES ('probe', 'adapters/arabam.json', 'adapter', ?)",
        ('{"id": "pack.arabam", "site": "arabam.com",'
         ' "match": ["*arabam.com/*"], "fields": {}}',),
    )
    store.commit()
    body = client.get("/api/sites/arabam.com/detail").json()
    assert body["editable"] is False
    assert body["spec"] is None
    assert body["pack_id"] == "probe"


def test_amending_a_learned_site_checks_and_stores(client, settings):
    """B181: the mapping can be changed, and only a valid one is kept."""
    conn = state.connect(settings.app_state_path)
    state.save_local_adapter(conn, host="arabam.com", spec=sites.check(ADAPTER))
    amended = {
        **ADAPTER,
        "fields": {"brand": {"labels": ["Marka"]}, "series": {"labels": ["Seri"]},
                   "year": {"labels": ["Yıl"]}},
    }
    answer = client.put("/api/sites/arabam.com", json={"spec": amended})
    assert answer.status_code == 200
    stored = client.get("/api/sites/arabam.com/detail").json()
    assert "year" in {rule["key"] for rule in stored["rules"]}


def test_amending_a_packs_site_is_refused(client, settings):
    store = connect(settings.store_path)
    store.execute(
        "INSERT INTO packs (pack_id, name, version, schema_version, built_at,"
        " content_digest, enabled, installed_at)"
        " VALUES ('probe', 'Probe', '1', 1, '2026-09-01', 'd', 1, '2026-09-01')"
    )
    store.execute(
        "INSERT INTO pack_assets (pack_id, name, kind, content)"
        " VALUES ('probe', 'adapters/arabam.json', 'adapter', ?)",
        ('{"id": "pack.arabam", "site": "arabam.com",'
         ' "match": ["*arabam.com/*"], "fields": {}}',),
    )
    store.commit()
    answer = client.put("/api/sites/arabam.com", json={"spec": ADAPTER})
    assert answer.status_code == 422


def test_an_amendment_with_no_rules_is_refused(client, settings):
    conn = state.connect(settings.app_state_path)
    state.save_local_adapter(conn, host="arabam.com", spec=sites.check(ADAPTER))
    answer = client.put("/api/sites/arabam.com",
                        json={"spec": {"site": "arabam.com", "fields": {}}})
    assert answer.status_code == 422
    stored = client.get("/api/sites/arabam.com/detail").json()
    assert "year" not in {rule["key"] for rule in stored["rules"]}


# ── the three choices ───────────────────────────────────────────────────────


def test_nothing_chosen_behaves_exactly_as_before(client):
    """Every key empty, including the per-stage ones.

    Asserted as a whole rather than key by key, because the property is that
    an installation which never opens this screen behaves *exactly* as it did —
    and a per-stage model quietly defaulting to something would break that in
    the one way nobody would notice.
    """
    body = client.get("/api/prefs").json()
    # Against `prefs.KEYS` rather than a list written out here. The per-harness
    # keys are derived from the roster now — they were a hand-written tuple
    # that had gone stale and silently dropped Mistral Vibe's model on write —
    # so a literal copy in this file would be the same bug one layer out, and
    # would fail the day a harness is added rather than the day one breaks.
    assert body["chosen"] == dict.fromkeys(prefs.KEYS, "")


def test_a_choice_survives_being_made(client):
    client.put("/api/prefs", json={"llm_model": "qwen3.5-27b"})
    assert client.get("/api/prefs").json()["chosen"]["llm_model"] == "qwen3.5-27b"
    # Merged, never replaced: setting one must not clear the others.
    client.put("/api/prefs", json={"search_provider": "tavily"})
    chosen = client.get("/api/prefs").json()["chosen"]
    assert chosen == dict.fromkeys(prefs.KEYS, "") | {
        "llm_model": "qwen3.5-27b", "search_provider": "tavily",
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


def test_paid_research_uses_extract_preference(settings, monkeypatch):
    from app import providers

    conn = state.connect(settings.app_state_path)
    prefs.write(conn, {prefs.MODEL: "global", prefs.role_key("extract"): "extractor"})
    conn.close()
    monkeypatch.setattr(providers, "_searcher", lambda *args: (lambda q, n: [], "exa"))
    monkeypatch.setattr(providers, "completer_for", lambda name: lambda prompt: "[]")
    researcher = providers.api_researcher(app_state_path=settings.app_state_path)
    assert researcher.model == "extractor"
    assert providers.api_researcher(
        app_state_path=settings.app_state_path, model="per-run"
    ).model == "per-run"


def test_a_chosen_provider_with_no_key_refuses_paid_fallback(
    settings, monkeypatch
):
    from app import providers

    monkeypatch.setattr(keys, "search_providers", lambda: ["exa"])
    monkeypatch.setattr(providers.exa, "searcher", lambda: "exa-search")
    conn = state.connect(settings.app_state_path)
    prefs.write(conn, {prefs.SEARCH: "tavily"})
    with pytest.raises(providers.MissingKey, match="tavily"):
        providers._searcher(settings.app_state_path)
    assert providers._searcher(settings.app_state_path, "exa")[1] == "exa"


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

    def replies(self) -> list[str]:
        # Nothing was said to this run. Present because the real `Progress`
        # has it and a handler wires it to the researcher unconditionally.
        return []


# ── choosing a model, with what you need to choose it ───────────────────
#
# "Let me choose the model." It was a free-text box: a choice offered with
# none of the information needed to make it, and no way to tell a model you
# cannot use from one that does not exist.

def test_a_model_is_offered_with_what_it_costs_and_how_much_it_reads(client):
    offered = client.get("/api/prefs").json()["models"]["offered"]
    assert offered, "a free-text box is not a choice"
    row = next(one for one in offered if one["id"] == "claude-opus-5")
    assert row["usd_in"] and row["usd_out"] and row["context"]
    assert row["speed"]


def test_a_model_with_no_key_says_why_rather_than_vanishing(client):
    """"Why can I not pick that one" has an answer, and hiding the row withholds it."""
    offered = client.get("/api/prefs").json()["models"]["offered"]
    unusable = [one for one in offered if one["unusable"]]
    assert unusable, "no keys are set in this fixture, so everything is unusable"
    assert all("key" in one["unusable"] for one in unusable)


def test_usable_models_are_listed_before_ones_that_cannot_run(client):
    offered = client.get("/api/prefs").json()["models"]["offered"]
    blocked = [bool(one["unusable"]) for one in offered]
    assert blocked == sorted(blocked), "unusable options must not lead the list"


def test_the_reader_is_told_where_to_edit_the_prices(client):
    """Editable config is only editable if you can find it."""
    assert client.get("/api/prefs").json()["models"]["catalogue"].endswith(
        "models.toml")


def test_each_usable_harness_can_take_its_own_model(client):
    """Sonnet for claude, a provider/model id for opencode, a model id for
    agy — three namespaces, so three keys and no shared fallback. Round-trips
    through the same prefs door as every other choice."""
    client.put("/api/prefs", json={"harness_model_claude_code": "sonnet"})
    chosen = client.get("/api/prefs").json()["chosen"]
    assert chosen["harness_model_claude_code"] == "sonnet"
    assert chosen["harness_model_opencode"] == ""
    assert chosen["harness_model_antigravity_cli"] == ""
    harnesses = client.get("/api/prefs").json()["harnesses"]
    for one in harnesses:
        assert "llm" in one and "llms" in one and "llm_hint" in one
        assert "llm_selectable" in one


def test_each_stage_of_a_run_can_take_its_own_model(client):
    roles = client.get("/api/prefs").json()["roles"]
    assert [one["id"] for one in roles] == [
        "plan", "extract", "synthesise", "validate"]
    assert all(one["note"] for one in roles), (
        "a client writing its own description of a stage is one that drifts")


def test_a_stage_with_no_choice_falls_back_to_the_default(client):
    from app import prefs
    from app.web import state

    client.put("/api/prefs", json={"llm_model": "gpt-4o-mini"})
    conn = state.connect(client.app.state.settings.app_state_path)
    try:
        assert prefs.for_role(conn, "extract") == "gpt-4o-mini"
        client.put("/api/prefs", json={"llm_model_extract": "claude-haiku-4-5"})
        assert prefs.for_role(conn, "extract") == "claude-haiku-4-5"
        # And only that stage moved.
        assert prefs.for_role(conn, "synthesise") == ""
        assert prefs.for_role(conn, "extract", "per-run") == "per-run"
    finally:
        conn.close()
