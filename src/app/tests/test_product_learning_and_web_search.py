import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import matching, prefs, sites
from app.providers import openserp
from app.web import state
from app.web.app import create_app
from app.web.settings import Settings
from kriko.adapters import adapt
from kriko.research.politeness import LocalSearchError


def test_declared_label_priority_wins_over_dom_order_and_promotional_title():
    spec = {"identity": {"model": {"labels": ["Seri", "Model"]}}}
    read = adapt(spec, {"Model": "1.4 Enjoy", "Seri": "Astra"},
                 title="ÖZAK-BOYASIZ 2017 MODEL OPEL ASTRA 105.000 KM KIRMIZI")
    assert read.identity == {"model": "Astra"}


def test_a_zero_score_storage_device_is_not_presented_as_the_nearest_car():
    resolution = SimpleNamespace(method="no_match", considered=[
        SimpleNamespace(score=0.0, label="Kingston A400 480GB", per_key=[]),
    ])
    step = matching.next_step(resolution, "NOT_MATCHED")
    assert "Kingston" not in step["say"]
    assert "research" in step["say"]


def test_a_title_fallback_cannot_hide_an_invented_learning_label():
    spec = {"identity": {"brand": {"labels": ["Invented"], "from": "title",
                                    "vocabulary": "brand"}}}
    sample = {"facts": {"Marka": "Opel"}, "title": "Opel Astra"}
    with pytest.raises(sites.SiteRefused, match="absent from the browser snapshot"):
        sites.validate_sample(spec, sample, {"brand": {"Opel"}})


def test_a_numeric_rule_that_discards_the_sample_identity_is_refused():
    spec = {"identity": {"capacity": {"labels": ["Capacity"], "parse": "int_range",
                                      "min": 1, "max": 10}}}
    with pytest.raises(sites.SiteRefused, match="cannot read its labelled value"):
        sites.validate_sample(spec, {"facts": {"Capacity": "480 GB"}}, {"capacity": {"480"}})


def test_the_snapshot_preserves_unknown_values_and_context_without_guessing():
    spec = {"identity": {"brand": {"labels": ["Marka"]}},
            "context": {"power": {"labels": ["Motor Gücü"]}}}
    read = sites.validate_sample(spec, {"facts": {"Marka": "New maker", "Motor Gücü": "100 hp"}},
                                 {"brand": {"Opel"}})
    assert read["identity"] == {"brand": "New maker"}
    assert read["context"] == {"power": "100 hp"}


@pytest.fixture
def web_client(tmp_path):
    settings = Settings(store_path=tmp_path / "store.sqlite",
                        app_state_path=tmp_path / "app.sqlite",
                        analysis_log_path=tmp_path / "analyses.jsonl")
    return TestClient(create_app(settings)), settings


def test_extension_web_search_uses_local_search_settings_without_needing_a_model(web_client, monkeypatch):
    client, settings = web_client
    conn = state.connect(settings.app_state_path)
    try:
        prefs.write(conn, {prefs.LOCAL_SEARCH_URL: "http://127.0.0.1:7999",
                           prefs.LOCAL_SEARCH_LANGUAGE: "tr"})
    finally:
        conn.close()
    calls = []

    def searcher(base_url, **kwargs):
        calls.append((base_url, kwargs))
        return lambda q, limit: [{"url": "https://example.com/astra", "title": q}]

    monkeypatch.setattr(openserp, "searcher", searcher)
    response = client.get("/api/extension/web-search", params={"q": "Opel Astra"})
    assert response.status_code == 200
    assert response.json()["items"][0]["title"] == "Opel Astra"
    assert calls[0][0] == "http://127.0.0.1:7999"
    assert calls[0][1]["language"] == "tr"
    assert calls[0][1]["engine"] == openserp.LOCAL_ENGINES


def test_extension_search_failure_is_distinct_from_no_results(web_client, monkeypatch):
    client, _ = web_client

    def fail(*args):
        raise LocalSearchError("connection refused")

    monkeypatch.setattr(openserp, "searcher", lambda *a, **kw: fail)
    response = client.get("/api/extension/web-search", params={"q": "Opel Astra"})
    assert response.status_code == 503
    assert "Local machine" in response.json()["detail"]


def test_fast_search_keeps_google_destinations_and_snippets(monkeypatch):
    class Reply:
        def read(self):
            return json.dumps({"results": [{"url": "https://www.google.com/goto?url=opaque",
                "title": "Astra specs", "snippet": "100 hp"}]}).encode()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(openserp.urllib.request, "urlopen", lambda *a, **kw: Reply())
    search = openserp.searcher(engine="google", mode="any",
                               resolve=lambda address, check=None: "https://example.com/astra")
    hits = search("Opel Astra")
    assert hits == [{"url": "https://example.com/astra", "title": "Astra specs",
                     "site": "example.com", "snippet": "100 hp"}]
