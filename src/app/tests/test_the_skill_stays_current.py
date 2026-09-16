"""The protocol an agent reads has to follow the code and the packs.

*"I believe you did not make any changes to skill text?"* — a fair reading of
the reader's own machine, and the bug behind it. The skill is **generated** from
the installed packs and from this app's code, and it was written exactly once:
when Connect was pressed. So an overhauled protocol, a tool that did not exist
last month, and a pack that updated yesterday all reached the app and none of
them reached the agent.

A digest makes staleness visible, `/api/agent-targets` reports it, and startup
refreshes the copies that are already wired — because a protocol that needs the
reader to remember to press a button is a protocol that drifts.
"""

import pytest
from fastapi.testclient import TestClient

from app import agentconfig, agentskill
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
def target(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(agentconfig, "_home", lambda: home)
    return agentconfig.by_id("claude-code")


def test_a_skill_carries_its_own_digest():
    body = agentskill.stamped("# a protocol")
    assert agentskill.STAMP in body
    assert agentskill.digest_of_file(body) == agentskill.digest(body)


def test_the_digest_survives_being_written_and_read_back(target, tmp_path):
    """The check has to be *equal* for an unchanged file, or every copy reports
    itself stale forever — which is the same as having no check."""
    body = agentskill.stamped("# a protocol")
    agentconfig.write_skill(target, agentskill.SKILL_NAME, body)
    status = agentconfig.skill_status(target, agentskill.SKILL_NAME, body)
    assert status["present"] is True and status["stale"] is False


def test_a_changed_protocol_is_stale_on_disk(target):
    agentconfig.write_skill(
        target, agentskill.SKILL_NAME, agentskill.stamped("# the old protocol")
    )
    status = agentconfig.skill_status(
        target, agentskill.SKILL_NAME, agentskill.stamped("# the new protocol")
    )
    assert status["stale"] is True


def test_nothing_on_disk_is_missing_rather_than_stale(target):
    """A harness the reader never connected gets nothing until they press
    Connect: writing into the config directory of a CLI they never wired would
    be installing something they did not ask for."""
    status = agentconfig.skill_status(
        target, agentskill.SKILL_NAME, agentskill.stamped("# a protocol")
    )
    assert status["present"] is False and status["stale"] is False
    assert agentconfig.refresh_skills(
        agentskill.SKILL_NAME, agentskill.stamped("# a protocol")
    ) == []


def test_a_wired_harness_is_refreshed(target):
    agentconfig.write_skill(
        target, agentskill.SKILL_NAME, agentskill.stamped("# the old protocol")
    )
    fresh = agentskill.stamped("# the new protocol")
    written = agentconfig.refresh_skills(agentskill.SKILL_NAME, fresh)
    assert [one["target"] for one in written] == ["claude-code"]
    assert "the new protocol" in agentconfig.skill_path(
        target, agentskill.SKILL_NAME
    ).read_text(encoding="utf-8")


def test_a_read_only_home_is_never_why_the_app_fails_to_start(target, monkeypatch):
    agentconfig.write_skill(
        target, agentskill.SKILL_NAME, agentskill.stamped("# the old protocol")
    )

    def refuse(*args, **kwargs):
        raise OSError("read-only file system")

    monkeypatch.setattr(agentconfig, "write_skill", refuse)
    assert agentconfig.refresh_skills(
        agentskill.SKILL_NAME, agentskill.stamped("# the new one")
    ) == []


def test_the_screen_can_say_the_skill_is_old(settings, target):
    agentconfig.write_skill(
        target, agentskill.SKILL_NAME, agentskill.stamped("# a protocol from June")
    )
    connect(settings.store_path).close()
    # As a context manager, so the lifespan actually runs: the refresh happens
    # at startup, and a client that never starts the app is testing the screen
    # without the mechanism behind it.
    with TestClient(create_app(settings)) as client:
        row = next(
            one for one in client.get("/api/agent-targets").json()["targets"]
            if one["id"] == "claude-code"
        )
    # Startup refreshed it: what the screen reports afterwards is current,
    # which is the point — the reader is not asked to notice anything.
    assert row["skill"]["present"] is True
    assert row["skill"]["stale"] is False


def test_one_harness_can_be_refreshed_on_its_own(settings, target):
    agentconfig.write_skill(
        target, agentskill.SKILL_NAME, agentskill.stamped("# older")
    )
    conn = connect(settings.store_path)
    conn.execute(
        "INSERT INTO packs (pack_id, name, version, schema_version, built_at,"
        " content_digest, enabled, installed_at)"
        " VALUES ('probe', 'Probe', '1', 1, '2026-09-01', 'd', 1, '2026-09-01')"
    )
    conn.commit()
    conn.close()
    client = TestClient(create_app(settings))
    answer = client.post("/api/agent-targets/claude-code/skill")
    assert answer.status_code == 200, answer.text
    assert answer.json()["status"]["stale"] is False


def test_the_skill_names_the_operations_the_app_shows_back(settings):
    """What an agent does appears on the reader's Activity screen under these
    names. A protocol that called them something else would make the two
    unrelatable."""
    conn = connect(settings.store_path)
    conn.execute(
        "INSERT INTO packs (pack_id, name, version, schema_version, built_at,"
        " content_digest, enabled, installed_at)"
        " VALUES ('probe', 'Probe', '1', 1, '2026-09-01', 'd', 1, '2026-09-01')"
    )
    conn.commit()
    body = agentskill.render(conn) or ""
    conn.close()
    for word in ("research", "agenda", "author", "recheck", "lookup"):
        assert word in body, word
    assert "amend_draft" in body
    # And the two operations an agent does not call but has to know exist.
    assert "Verify" in body and "Sites" in body


def test_the_skill_refuses_to_be_a_checklist(settings):
    """A gold set exists to score benchmarks. A finding submitted because it
    appears there, rather than because it was read on a page, is a fabrication
    with a quote attached."""
    conn = connect(settings.store_path)
    conn.execute(
        "INSERT INTO packs (pack_id, name, version, schema_version, built_at,"
        " content_digest, enabled, installed_at)"
        " VALUES ('probe', 'Probe', '1', 1, '2026-09-01', 'd', 1, '2026-09-01')"
    )
    conn.commit()
    body = agentskill.render(conn) or ""
    conn.close()
    assert "gold.yaml" in body
    assert "not a checklist to copy from" in body
