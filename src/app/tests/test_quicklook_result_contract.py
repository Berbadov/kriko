"""A blank Quick Look is still useful when it has bounded, saved evidence."""

import json

import pytest

from app.web import state, tasks
from app.web.settings import Settings


class _Progress:
    def __init__(self, job_id):
        self.job_id = job_id
        self.messages = []

    def set(self, _progress, message):
        self.messages.append(message)

    def log(self, _line):
        pass

    def check(self):
        pass


def test_quicklook_refuses_a_provider_factory_fallback_for_a_named_agent(
        tmp_path, monkeypatch):
    from types import SimpleNamespace
    from app import providers

    settings = Settings(
        store_path=tmp_path / "knowledge.sqlite",
        app_state_path=tmp_path / "app.sqlite",
        analysis_log_path=tmp_path / "analysis.jsonl",
    )
    fallback = SimpleNamespace(harness=SimpleNamespace(id="other-cli"))
    monkeypatch.setattr(tasks, "_use_local_ask", lambda *_a, **_k: False)
    monkeypatch.setattr(providers, "harness_researcher", lambda **_kwargs: fallback)
    with pytest.raises(ValueError, match="selected research agent.*no other agent"):
        tasks.quick_look(settings, {
            "product": "Acme headset", "backend": "harness", "harness": "chosen-cli",
        }, _Progress("quick-job"))


def test_malformed_answer_is_not_reported_as_no_findings_or_sent_for_classification(
        tmp_path, monkeypatch):
    from types import SimpleNamespace
    from app import categorizer

    settings = Settings(store_path=tmp_path / "knowledge.sqlite",
                        app_state_path=tmp_path / "app.sqlite",
                        analysis_log_path=tmp_path / "analysis.jsonl")
    conn = state.connect(settings.app_state_path)
    job_id = state.create_job(conn, "quick_look", {"product": "TCL 55V6C"})
    conn.close()
    researcher = SimpleNamespace(
        ask_quick=lambda *_a, **_k: 'Here is a prose answer without the required findings.',
        sources={"https://manufacturer.example/product": "A retrieved product page."},
        coverage={"search_results": 12, "pages_read": 1}, metrics=[],
        cost_basis="per_token", spent=0.01, model="test", harness=SimpleNamespace(id="kriko-agent"),
    )
    monkeypatch.setattr(tasks, "_use_local_ask", lambda *_a, **_k: True)
    monkeypatch.setattr(tasks, "_local_asker", lambda *_a, **_k: researcher)
    monkeypatch.setattr(categorizer, "installed_catalogs", lambda *_a: [])
    def refuse_classification(*_a, **_k):
        pytest.fail("An unreadable research answer must not spend another classification call")
    monkeypatch.setattr(tasks, "_classify_catalog", refuse_classification)
    result = tasks.quick_look(settings, {"product": "TCL 55V6C"}, _Progress(job_id))
    assert result["diagnostic"]["code"] == "unreadable_answer"
    assert result["coverage"]["search_results"] == 12
    assert result["categorization"]["method"] == "unreadable_answer"

@pytest.mark.parametrize(
    ("coverage", "diagnostic_code"),
    [
        ({"status": "answer_completed", "pages_read": 2,
          "pages_relevant": 1, "pages_extracted": 0, "answer_passes": 1},
         "no_issues_found"),
        ({"status": "partial", "pages_read": 2, "pages_relevant": 1,
          "pages_extracted": 0, "answer_passes": 1, "pages_timed_out": 1},
         "partial"),
    ],
)
def test_quicklook_persists_listing_facts_and_selected_sources_even_without_risks(
        tmp_path, monkeypatch, coverage, diagnostic_code):
    settings = Settings(
        store_path=tmp_path / "knowledge.sqlite",
        app_state_path=tmp_path / "app.sqlite",
        analysis_log_path=tmp_path / "analysis.jsonl",
    )
    conn = state.connect(settings.app_state_path)
    job_id = state.create_job(conn, "quick_look", {"product": "Acme 5W-30 oil"})
    conn.close()

    class Researcher:
        sources = {"https://oil.example/spec": "SAE 5W-30 full synthetic oil."}
        relevant_sources = sources
        model = "selected-cli"
        harness = type("Harness", (), {"id": "codex"})()
        identity = {"product": "Acme 5W-30 oil"}
        telemetry = {}
        runtime = {"requested_device": "cpu", "actual_device": "gpu"}
        verification = {}
        metrics = []
        cost_basis = "subscription"

        def ask_quick(self, product, **_kwargs):
            assert product == "Acme 5W-30 oil"
            self.coverage = dict(coverage)
            return json.dumps({
                "assumed": "SAE 5W-30 full synthetic oil",
                "category": "engine oil",
                "risks": [],
                "specs": [{"name": "Viscosity", "value": "SAE 5W-30",
                           "url": "https://oil.example/spec",
                           "quote": "SAE 5W-30 full synthetic oil."}],
            })

    researcher = Researcher()
    monkeypatch.setattr(tasks, "_use_local_ask", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(tasks, "_local_asker", lambda *_args, **_kwargs: researcher)
    from app import categorizer
    monkeypatch.setattr(categorizer, "installed_catalogs", lambda _path: [])
    monkeypatch.setattr(categorizer, "choice_block", lambda _profiles: "")
    monkeypatch.setattr(categorizer, "deterministic", lambda *_args: {
        "status": "uncertain", "pack_id": "", "message": "No catalog."})

    page = {
        "facts": {"vehicle": "2018 Honda Civic", "engine": "1.5L turbo",
                  "approval": "API SP"},
        "description": "Full synthetic SAE 5W-30 engine oil.",
    }
    progress = _Progress(job_id)
    result = tasks.quick_look(settings, {
        "product": "Acme 5W-30 oil", "page": page,
        "page_url": "https://shop.example/item",
    }, progress)

    assert result["risks"] == []
    assert result["diagnostic"]["code"] == diagnostic_code
    assert result["listing"] == {
        "url": "https://shop.example/item", "facts": page["facts"],
        "description": page["description"],
    }
    assert result["product"] == "Acme 5W-30 oil"
    assert result["specs"][0]["quote"] == "SAE 5W-30 full synthetic oil."
    assert result["evidence_pages"] == [{
        "url": "https://oil.example/spec", "domain": "oil.example",
        "excerpt": "SAE 5W-30 full synthetic oil.",
    }]
    assert result["runtime"] == {"requested_device": "cpu", "actual_device": "gpu"}
    assert progress.messages
    if diagnostic_code == "no_issues_found":
        assert "1 relevant page(s) checked" in result["diagnostic"]["message"]
        assert "1 completed check(s)" in result["diagnostic"]["message"]
    else:
        assert "insufficient evidence" in result["diagnostic"]["message"]

