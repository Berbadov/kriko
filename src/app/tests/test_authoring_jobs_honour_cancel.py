"""`pack_author`, `pack_amend` and `site_register` never called
`progress.check()`, so a reader's Cancel press on any of them was a no-op:
the handler ran to completion, wrote its draft or adapter, and reported
SUCCEEDED regardless. `jobs.py`'s cooperative-cancel contract only holds for
a handler that actually checks, and these three did not.

`harness.py` gives the agent's subprocess no way to be interrupted from here
(out of this plane's files), so the run itself still finishes — but nothing
written to app.sqlite or the draft store needs to happen once a cancel has
already been asked for, and that much is checkable and fixed here.
"""

from app.tests.test_an_agent_authors_a_whole_pack import PACK, _fake_cli, _reply


class _CancelsAfterAsk:
    def __init__(self):
        self.lines: list[str] = []
        self._asked = False

    def log(self, line):
        self.lines.append(line)

    def set(self, fraction, message=""):
        if message:
            self.lines.append(message)

    @property
    def cancelled(self):
        return self._asked

    def check(self):
        from app.web.jobs import Cancelled

        if self._asked:
            raise Cancelled()

    def note_ask_happened(self):
        self._asked = True


def test_pack_author_writes_no_draft_once_cancelled_after_the_ask(
    tmp_path, monkeypatch
):
    import pytest

    from app.providers import harness as harness_mod
    from app.web import jobs, tasks

    fake = _fake_cli(tmp_path, _reply(PACK))
    monkeypatch.setattr(harness_mod, "available", lambda: [fake])
    real_ask = harness_mod.HarnessResearcher.ask
    progress = _CancelsAfterAsk()

    def ask_then_flag_cancel(self, prompt):
        result = real_ask(self, prompt)
        progress.note_ask_happened()
        return result

    monkeypatch.setattr(harness_mod.HarnessResearcher, "ask", ask_then_flag_cancel)
    monkeypatch.setattr(
        "app.providers.harness_researcher",
        lambda **kw: harness_mod.HarnessResearcher(fake, timeout=60))

    settings = type("S", (), {"store_path": tmp_path / "k.sqlite",
                                  "app_state_path": tmp_path / "app.sqlite"})()
    with pytest.raises(jobs.Cancelled):
        tasks.pack_author(settings, {"category": "cordless drills"}, progress)

    from app import packdraft
    assert not packdraft.drafts_root(settings.store_path).exists()


def test_pack_amend_leaves_the_draft_unchanged_once_cancelled_after_the_ask(
    tmp_path, monkeypatch
):
    import json

    import pytest

    from app import packauthor
    from app.providers import harness as harness_mod
    from app.web import jobs, tasks

    store_path = tmp_path / "k.sqlite"
    drafted = packauthor.author(store_path, _reply(PACK), category="drills")
    before = packauthor.draft_state(store_path, drafted["slug"])

    addition = {
        "subjects": [
            {"kind": "product", "label": "Hilti SF6H",
             "identity": {"brand": "hilti", "series": "SF6H"}},
        ],
    }
    fake = _fake_cli(tmp_path, _reply(addition))
    monkeypatch.setattr(harness_mod, "available", lambda: [fake])
    real_ask = harness_mod.HarnessResearcher.ask
    progress = _CancelsAfterAsk()

    def ask_then_flag_cancel(self, prompt):
        result = real_ask(self, prompt)
        progress.note_ask_happened()
        return result

    monkeypatch.setattr(harness_mod.HarnessResearcher, "ask", ask_then_flag_cancel)
    monkeypatch.setattr(
        "app.providers.harness_researcher",
        lambda **kw: harness_mod.HarnessResearcher(fake, timeout=60))

    settings = type("S", (), {"store_path": store_path,
                                  "app_state_path": tmp_path / "app.sqlite"})()
    with pytest.raises(jobs.Cancelled):
        tasks.pack_amend(
            settings, {"slug": drafted["slug"], "note": "the missing one"}, progress)

    after = packauthor.draft_state(store_path, drafted["slug"])
    assert after["subjects"] == before["subjects"]


def test_site_register_saves_no_adapter_once_cancelled_after_the_ask(
    tmp_path, monkeypatch
):
    import json

    import pytest

    from app.providers import harness as harness_mod
    from app.web import jobs, state, tasks
    from kriko.store.db import connect

    spec = {
        "pack_id": "cars",
        "fields": {"title": {"selector": "h1"}},
    }
    fake = _fake_cli(
        tmp_path,
        "```json\n" + json.dumps(spec) + "\n```",
    )
    monkeypatch.setattr(harness_mod, "available", lambda: [fake])
    real_ask = harness_mod.HarnessResearcher.ask
    progress = _CancelsAfterAsk()

    def ask_then_flag_cancel(self, prompt):
        result = real_ask(self, prompt)
        progress.note_ask_happened()
        return result

    monkeypatch.setattr(harness_mod.HarnessResearcher, "ask", ask_then_flag_cancel)
    monkeypatch.setattr(
        "app.providers.harness_researcher",
        lambda **kw: harness_mod.HarnessResearcher(fake, timeout=60))

    settings = type("S", (), {"store_path": tmp_path / "k.sqlite",
                                  "app_state_path": tmp_path / "app.sqlite"})()
    connect(settings.store_path).close()
    with pytest.raises(jobs.Cancelled):
        tasks.site_register(
            settings, {"host": "example.test"}, progress)

    conn = state.connect(settings.app_state_path)
    assert state.local_adapters(conn, enabled_only=False) == []
