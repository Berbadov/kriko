"""B158: the model pickers list only models.

*"Model selection: run a script to fetch the model list first, then let the
user choose (models update daily)"* (the reader, 2026-09-29).

Three things were wrong with what the CLIs' own `models` commands became:

* `agy models` prints `Fetching available models...` on stderr, `_ask` merges
  stderr into stdout, and the Antigravity branch took the first word of every
  line, so `Fetching` was offered as a model beside the real ids.
* `opencode models` prints 426 lines on the reader's machine; `_ask` kept the
  last 400 (a bound made for `--help`), and the line filter refused every
  `provider/vendor/model` id, so the pick offered 13 of them.
* Vibe and Copilot list nothing, and the pick did not say so.

The two captures below are the CLIs' own output, taken on 2026-09-29.
"""

import sys

import pytest
from fastapi.testclient import TestClient

from app.providers import harness as harness_mod
from app.web.app import create_app
from app.web.settings import Settings
from kriko.store.db import connect

#: `agy models` as `_ask` receives it: the status line (stderr) first, then one
#: `id<TAB>display name` row per model.
AGY_MODELS = (
    "Fetching available models...\n"
    "gemini-3.8-flash-high\tGemini 3.8 Flash (High)\n"
    "gemini-3.8-flash-medium\tGemini 3.8 Flash (Medium)\n"
    "gemini-3.8-flash-low\tGemini 3.8 Flash (Low)\n"
    "gemini-3.7-flash-high\tGemini 3.7 Flash (High)\n"
    "gemini-3.7-flash-medium\tGemini 3.7 Flash (Medium)\n"
    "gemini-3.7-flash-low\tGemini 3.7 Flash (Low)\n"
    "gemini-3.6-flash-high\tGemini 3.6 Flash (High)\n"
    "gemini-3.6-flash-medium\tGemini 3.6 Flash (Medium)\n"
    "gemini-3.6-flash-low\tGemini 3.6 Flash (Low)\n"
    "gemini-3.1-pro-high\tGemini 3.1 Pro (High)\n"
    "gemini-3.1-pro-low\tGemini 3.1 Pro (Low)\n"
    "claude-sonnet-4-6\tClaude Sonnet 4.6 (Thinking)\n"
    "claude-opus-4-6-thinking\tClaude Opus 4.6 (Thinking)\n"
    "gpt-oss-120b-medium\tGPT-OSS 120B (Medium)\n"
)
AGY_IDS = [line.split("\t")[0] for line in AGY_MODELS.splitlines()[1:]]

#: A slice of `opencode models`: bare `provider/model` lines, and an aggregator
#: (`openrouter`) whose model names carry their own vendor and slash.
OPENCODE_MODELS = (
    "deepseek/deepseek-flash\n"
    "opencode-go/glm-5.2\n"
    "opencode/big-pickle\n"
    "openrouter/~anthropic/claude-fable-latest\n"
    "openrouter/anthropic/claude-opus-4.8\n"
    "openrouter/aion-labs/aion-rp-llama-3.1-8b\n"
)


def _row(one_id: str) -> harness_mod.Harness:
    return next(one for one in harness_mod.KNOWN if one.id == one_id)


def _answering(monkeypatch, text: str) -> None:
    """The CLI's `models` command says `text`; nothing else is stubbed."""
    monkeypatch.setattr(harness_mod, "_ask", lambda executable, *argv, **kw: text)


def test_agy_status_line_is_not_a_model(monkeypatch):
    """The reproduction: `Fetching` led the Antigravity list on the installed build."""
    _answering(monkeypatch, AGY_MODELS)
    names = harness_mod._from_models_command(_row("antigravity-cli"), "agy")
    assert "Fetching" not in names
    assert names == AGY_IDS


def test_a_line_that_is_not_a_row_of_the_listing_is_not_a_model(monkeypatch):
    """Rejected by the shape of a row, not by a list of words a CLI once printed."""
    noise = (
        "Fetching available models...\n"
        "Fetching\n"
        "Loading models, please wait\n"
        "Warning: your token expires in 2 days\n"
        "\n"
        "3 models available\n"
    )
    for one_id in ("antigravity-cli", "opencode"):
        _answering(monkeypatch, noise + "opencode/big-pickle\n")
        names = harness_mod._from_models_command(_row(one_id), "cli")
        assert names == ["opencode/big-pickle"], one_id
    _answering(monkeypatch, noise)
    assert harness_mod._from_models_command(_row("antigravity-cli"), "agy") == []


def test_opencode_models_with_a_vendor_inside_the_name_are_kept(monkeypatch):
    """`openrouter/anthropic/claude-opus-4.8` is one id, and `--model` takes it whole."""
    _answering(monkeypatch, OPENCODE_MODELS)
    assert harness_mod._from_models_command(_row("opencode"), "opencode") == [
        line for line in OPENCODE_MODELS.splitlines()
    ]


def test_a_long_listing_is_read_to_its_last_line():
    """`_ask` kept 400 lines, a bound made for `--help`; a CLI listing more lost its head."""
    program = "print('\\n'.join(f'vendor/model-{n}' for n in range(600)))"
    out = harness_mod._ask(sys.executable, "-c", program, keep_lines=10_000)
    assert len(out.splitlines()) == 600
    assert out.splitlines()[0] == "vendor/model-0"


def test_models_come_from_the_whole_output_of_the_models_command(monkeypatch):
    """`models_for` asks for the whole listing, not the `--help` bound."""
    seen = {}

    def ask(executable, *argv, **kw):
        seen.update(kw)
        return OPENCODE_MODELS

    monkeypatch.setattr(harness_mod, "_ask", ask)
    harness_mod._from_models_command(_row("opencode"), "opencode")
    assert seen.get("keep_lines", 0) > 400


# ── a CLI that lists no models says so ───────────────────────────────────────


def test_a_cli_with_no_listing_command_says_it_lists_no_models():
    vibe = _row("mistral-vibe")
    assert harness_mod.models_note(vibe, []) == "This CLI does not list its models"


def test_a_cli_that_listed_models_has_no_note(monkeypatch):
    assert harness_mod.models_note(_row("opencode"), ["opencode/big-pickle"]) == ""


def test_a_cli_asked_and_answering_nothing_says_so(monkeypatch):
    opencode = _row("opencode")
    monkeypatch.setattr(harness_mod, "locate", lambda one: "/usr/bin/opencode")
    monkeypatch.setattr(harness_mod, "_MODELS", {})
    assert harness_mod.models_note(opencode, []) == "", "not asked yet is not 'lists none'"
    _answering(monkeypatch, "Fetching available models...\n")
    assert harness_mod.models_for(opencode) == []
    assert harness_mod.models_note(opencode, []) == "This CLI listed no models"


def _settings(tmp_path) -> Settings:
    return Settings(
        store_path=tmp_path / "k.sqlite",
        app_state_path=tmp_path / "app.sqlite",
        analysis_log_path=tmp_path / "a.jsonl",
    )


@pytest.fixture
def two_clis(monkeypatch):
    """Antigravity (lists) and Vibe (lists nothing), the rest of the world stubbed."""
    agy, vibe = _row("antigravity-cli"), _row("mistral-vibe")
    monkeypatch.setattr(harness_mod, "available", lambda: [agy, vibe])
    monkeypatch.setattr(harness_mod, "locate", lambda one: f"/usr/bin/{one.executable}")
    monkeypatch.setattr(harness_mod, "efforts_for", lambda one: [])
    monkeypatch.setattr(harness_mod, "_MODELS", {})
    _answering(monkeypatch, AGY_MODELS)


def _by_id(rows):
    return {one["id"]: one for one in rows}


def test_the_agents_screen_row_carries_the_note(tmp_path, two_clis):
    connect(tmp_path / "k.sqlite").close()
    client = TestClient(create_app(_settings(tmp_path)))
    rows = _by_id(client.get("/api/prefs").json()["harnesses"])
    assert rows["antigravity-cli"]["llms"] == AGY_IDS
    assert rows["antigravity-cli"]["llms_note"] == ""
    assert rows["mistral-vibe"]["llms"] == []
    assert rows["mistral-vibe"]["llms_note"] == "This CLI does not list its models"


def test_the_run_screen_row_carries_the_same_note(tmp_path, two_clis):
    connect(tmp_path / "k.sqlite").close()
    client = TestClient(create_app(_settings(tmp_path)))
    planes = client.get("/api/research-planes").json()["planes"]
    rows = _by_id(next(p for p in planes if p["id"] == "harness")["harnesses"])
    assert rows["antigravity-cli"]["llms"] == AGY_IDS
    assert rows["antigravity-cli"]["llms_note"] == ""
    assert rows["mistral-vibe"]["llms_note"] == "This CLI does not list its models"
