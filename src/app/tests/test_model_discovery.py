"""The paid plane's LLM list: asked of the provider, never waited on by a page."""

import io
import json
import urllib.error

import pytest

from app import modeldiscovery


class _Reply(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _opener(payload, seen=None):
    def open_(request, timeout):
        if seen is not None:
            seen.append((request.full_url, dict(request.header_items())))
        return _Reply(json.dumps(payload).encode())
    return open_


@pytest.fixture
def keyed(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ak-test")
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)


def test_openai_shaped_lists_are_read_by_id(keyed):
    seen = []
    names = modeldiscovery.ask("openai", _opener({"data": [{"id": "gpt-x"}, {"id": "gpt-y"}, {"id": "gpt-x"}]}, seen))
    assert names == ["gpt-x", "gpt-y"]
    url, headers = seen[0]
    assert url.startswith("https://api.openai.com/v1/models")
    assert headers["Authorization"] == "Bearer sk-test"


def test_anthropic_is_asked_with_its_own_headers(keyed):
    seen = []
    assert modeldiscovery.ask("anthropic", _opener({"data": [{"id": "claude-x"}]}, seen)) == ["claude-x"]
    url, headers = seen[0]
    assert url.startswith("https://api.anthropic.com/v1/models")
    assert headers["X-api-key"] == "ak-test" and "Anthropic-version" in headers


def test_a_failure_is_a_smaller_list_never_an_error(keyed, monkeypatch):
    def refuse(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 404, "no", {}, None)
    assert modeldiscovery.ask("openai", refuse) == []
    assert modeldiscovery.ask("openai", _opener("not a dict")) == []
    monkeypatch.delenv("OPENAI_API_KEY")
    from pathlib import Path
    monkeypatch.setattr("app.keys.env_path", lambda home=None: Path(modeldiscovery.__file__ + ".none"))
    assert modeldiscovery.ask("openai", _opener({"data": [{"id": "x"}]})) == []


def test_a_page_read_never_waits_on_the_network(keyed, monkeypatch):
    """Nothing cached: `cached()` answers at once and refreshes behind."""
    started = []
    monkeypatch.setattr(modeldiscovery, "_refresh_in_background", lambda: started.append(1))
    assert modeldiscovery.cached() == {}
    assert started, "a stale cache did not start a refresh"
    modeldiscovery._CACHE["openai"] = (10**12, ["gpt-x"])
    started.clear()
    assert modeldiscovery.cached()["openai"] == ["gpt-x"]
