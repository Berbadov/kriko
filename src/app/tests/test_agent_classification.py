"""Usual agents classify saved products without a Jev-specific key."""

import json
from types import SimpleNamespace

import pytest

from app import categorizer
from app.web import tasks

PRODUCT = "Acme Gaming Mouse"
PROFILE = {
    "pack_id": "gaming.mice", "name": "Gaming mice", "version": "2.0.0",
    "content_digest": "revision-2", "enabled": True,
    "definition": {"kinds": [{"id": "mouse", "label": "mouse"}],
                   "identity_keys": [], "attributes": [], "examples": []},
    "terms": ["Gaming mice", "mouse"],
}
DECISION = {
    "decision": "assigned", "pack_id": "gaming.mice", "confidence": "high",
    "basis": [{"saved_text": PRODUCT, "catalog_text": "Gaming mice"}],
}


def test_default_agent_classifies_abstentions_with_audited_evidence(monkeypatch):
    monkeypatch.setattr(categorizer, "classify_with_jev", lambda *_a, **_k: pytest.fail("Jev is optional"))
    prompts = []

    def ask(prompt):
        prompts.append(prompt)
        return json.dumps(DECISION)

    result = categorizer.classify_configured(PRODUCT, {}, [PROFILE], ask=ask)
    assert result["method"] == "agent" and result["status"] == "assigned"
    assert result["audit"]["catalog"]["content_digest"] == "revision-2"
    assert len(prompts) == 1
    assert "Do not use the web" in prompts[0]
    assert "gaming.mice" in prompts[0]


def test_deterministic_match_does_not_start_an_agent():
    profile = {**PROFILE, "name": "Gaming Mouse"}
    result = categorizer.classify_configured(
        PRODUCT, {"category": "Gaming Mouse"}, [profile],
        ask=lambda _: pytest.fail("No model is needed for a clear match"))
    assert result["method"] == "deterministic"
    assert result["status"] == "assigned"


def test_mcp_agent_can_receive_a_task_then_submit_its_own_decision(monkeypatch, tmp_path):
    from app import mcp_server, prefs

    monkeypatch.setattr(categorizer, "installed_catalogs", lambda _: [PROFILE])
    monkeypatch.setattr(mcp_server, "_app_state_path", lambda: tmp_path / "app.sqlite")
    monkeypatch.setattr(mcp_server, "_store_path", lambda: tmp_path / "knowledge.sqlite")
    monkeypatch.setattr(prefs, "classification_provider", lambda _: "agent")
    monkeypatch.setattr(categorizer, "classify_with_jev", lambda *_a, **_k: pytest.fail("No TypeSafe key is required"))
    request = mcp_server.classify_product(PRODUCT, {})
    assert request["needs_agent_decision"] is True
    assert PRODUCT in request["agent_request"]["prompt"]
    assert request["agent_request"]["schema"] == categorizer.OUTPUT_SCHEMA
    result = mcp_server.classify_product(PRODUCT, {}, decision=DECISION)
    assert result["method"] == "agent" and result["status"] == "assigned"


@pytest.mark.parametrize("decision", [
    {**DECISION, "pack_id": "uninstalled.catalog"},
    {**DECISION, "basis": [{"saved_text": "invented quote", "catalog_text": "Gaming mice"}]},
])
def test_supplied_agent_decisions_still_need_installed_catalog_and_real_quotes(decision):
    result = categorizer.classify_configured(PRODUCT, {}, [PROFILE], decision=decision)
    assert result["status"] == "uncertain" and not result["pack_id"]


def _hooks():
    return SimpleNamespace(check=lambda: None, log=lambda _: None)


def test_task_uses_the_selected_coding_or_api_agent_without_tools(monkeypatch):
    from app import providers

    selected = []
    calls = []

    class Agent:
        cost_basis = "per_token"

        def ask(self, prompt, **options):
            calls.append((prompt, options, self.budget_usd))
            return json.dumps(DECISION)

    monkeypatch.setattr(tasks, "_classification_provider", lambda _: "agent")
    monkeypatch.setattr(tasks, "_use_local_ask", lambda *_: False)
    monkeypatch.setattr(providers, "harness_researcher", lambda **options: selected.append(options) or Agent())
    result = tasks._classify_catalog(SimpleNamespace(app_state_path="unused"),
                                     {"harness": "openai-api", "model": "my-model"},
                                     _hooks(), PRODUCT, {}, [PROFILE])
    assert result["status"] == "assigned"
    assert selected[0]["preferred"] == "openai-api"
    assert selected[0]["model"] == "my-model"
    assert calls[0][1] == {"allow_tools": False}
    assert calls[0][2] == tasks.CATEGORIZATION_BUDGET_USD


def test_task_uses_the_selected_local_model_with_the_classification_schema(monkeypatch):
    calls = []

    class Completer:
        def prompt_chars_allowed(self):
            return 20_000

        def json(self, prompt, schema):
            calls.append((prompt, schema))
            return json.dumps(DECISION)

    monkeypatch.setattr(tasks, "_classification_provider", lambda _: "agent")
    monkeypatch.setattr(tasks, "_use_local_ask", lambda *_: True)
    monkeypatch.setattr(tasks, "_local_structured_completer", lambda *_: Completer())
    result = tasks._classify_catalog(None, {}, _hooks(), PRODUCT, {}, [PROFILE])
    assert result["status"] == "assigned"
    assert calls[0][1] == categorizer.OUTPUT_SCHEMA


def test_unavailable_agent_leaves_the_check_uncategorized(monkeypatch):
    monkeypatch.setattr(tasks, "_classification_provider", lambda _: "agent")
    monkeypatch.setattr(tasks, "_use_local_ask", lambda *_: True)
    monkeypatch.setattr(tasks, "_local_structured_completer", lambda *_: (_ for _ in ()).throw(RuntimeError("offline")))
    result = tasks._classify_catalog(None, {}, _hooks(), PRODUCT, {}, [PROFILE])
    assert result["status"] == "uncertain" and not result["pack_id"]
    assert "choose a catalog manually" in result["message"]
