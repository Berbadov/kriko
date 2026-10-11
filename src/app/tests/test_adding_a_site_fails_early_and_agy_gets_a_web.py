"""Add site: the two failures a reader hit on akakce.com, 2026-10-11.

    "Add site seems to be not working. I've got value error for akakce.com: the
    adapter was refused. Also Antigravity returns: ANTIGRAVITY CLI returned
    nothing. headless mode cannot approve tool permissions."

Reproduced from the job rows on the reader's machine, and they were two things:

* **Antigravity** was asked to "read that page", reached for `curl` and `dir`,
  was auto-denied the shell, and the run ended at the first denial with
  nothing read. The brief now tells it which tools it has.
* **The refusal** came after a run had spent the reader's quota: every pack on
  the machine was disabled, so the brief listed no identity keys, and the
  agent honestly wrote an adapter with an empty `identity`, which is refused.
  With no key to map into the answer is known before the agent runs.
"""

import pytest

from app.providers import harness as harness_mod
from app.web import tasks
from kriko.store.db import connect


def test_antigravity_is_told_to_use_its_web_tools_and_not_a_shell():
    agy = next(one for one in harness_mod.KNOWN if one.id == "antigravity-cli")
    assert "read_url_content" in agy.ask_note
    assert "shell" in agy.ask_note


def test_ask_appends_the_note_for_a_cli_that_has_one(monkeypatch):
    agy = next(one for one in harness_mod.KNOWN if one.id == "antigravity-cli")
    researcher = harness_mod.HarnessResearcher(agy, timeout=5)
    seen = []
    monkeypatch.setattr(researcher, "_run", lambda prompt, on_line=None: seen.append(prompt) or "ok")
    researcher.ask("Read the page")
    assert seen == ["Read the page" + agy.ask_note]


class _Progress:
    def set(self, *a, **k): pass
    def log(self, *a, **k): pass
    def check(self): pass
    def partial(self, *a, **k): pass
    replies = None


def test_adding_a_site_with_no_enabled_pack_says_so_before_any_agent_runs(tmp_path, monkeypatch):
    settings = type("S", (), {"store_path": tmp_path / "k.sqlite",
                              "app_state_path": tmp_path / "app.sqlite"})()
    connect(settings.store_path).close()
    monkeypatch.setattr(harness_mod, "available",
                        lambda: pytest.fail("the agent must not be looked for"))
    with pytest.raises(ValueError, match="no pack is installed"):
        tasks.site_register(settings, {"host": "akakce.com"}, _Progress())
