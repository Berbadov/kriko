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

import json

import pytest
from fastapi.testclient import TestClient

from app import agenda, agentconfig, agentskill
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


def test_the_skill_names_the_steps_and_the_tools_and_no_screen(settings):
    """B178: the skill used to require screen names ("Verify", "Sites") so the
    reader's Activity screen and the protocol matched. It is now agent-facing
    only: it names the five steps and the authoring tools an agent calls, and
    no screen (`test_the_skill_is_short_and_generic` asserts the absence)."""
    conn = connect(settings.store_path)
    conn.execute(
        "INSERT INTO packs (pack_id, name, version, schema_version, built_at,"
        " content_digest, enabled, installed_at)"
        " VALUES ('probe', 'Probe', '1', 1, '2026-09-01', 'd', 1, '2026-09-01')"
    )
    conn.commit()
    body = agentskill.render(conn) or ""
    conn.close()
    for tool, _given, _got in agentskill.STEPS:
        assert f"`{tool}`" in body, tool
    for tool in ("draft_pack", "write_draft_file", "build_draft", "amend_draft"):
        assert tool in body, tool
    assert "Verify" not in body and "Sites" not in body


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


# ── B157: "Update the skill" clears when pressed and stays clear ────────────
#
# *"Fix the Claude Code bug that keeps showing the \"update the skill\" button"*
# (2026-09-29). Startup rendered the skill without the "What to research next"
# block, the status check and the button rendered it with the block, and the
# block's counts move with every analysis. So the digest a file carried was
# never the digest the status compared it with, and the button came back after
# every restart and every check. The tests above passed because their store had
# an empty agenda: nothing to disagree about.


def _seed(settings):
    """A pack with two subjects and no claims: a non-empty agenda, by design."""
    conn = connect(settings.store_path)
    conn.execute(
        "INSERT INTO packs (pack_id, name, version, schema_version, built_at,"
        " content_digest, enabled, installed_at)"
        " VALUES ('probe', 'Probe', '1', 1, '2026-09-01', 'd', 1, '2026-09-01')"
    )
    conn.execute(
        "INSERT INTO pack_assets VALUES (?,?,?,?)",
        (
            "probe",
            "research/principle.md",
            "principle",
            "Keep what a buyer cannot cheaply learn.",
        ),
    )
    for subject_id, label in (("s-a", "Alpha unit"), ("s-b", "Beta unit")):
        conn.execute(
            "INSERT INTO subjects (subject_id, pack_id, kind, label)"
            " VALUES (?, 'probe', 'unit', ?)",
            (subject_id, label),
        )
    conn.commit()
    conn.close()


def _ask(settings, subject_id, times):
    """What an analysis leaves behind: the demand the agenda ranks by."""
    with open(settings.analysis_log_path, "a", encoding="utf-8") as f:
        for _ in range(times):
            f.write(
                json.dumps({"coverage": "MATCHED_NO_DATA", "subjects": [subject_id]})
                + "\n"
            )


def _claude_skill(client) -> dict:
    return next(
        one for one in client.get("/api/agent-targets").json()["targets"]
        if one["id"] == "claude-code"
    )["skill"]


def _skill_on_disk(target) -> str:
    return agentconfig.skill_path(target, agentskill.SKILL_NAME).read_text(
        encoding="utf-8"
    )


def test_the_skill_reads_current_after_startup_press_analysis_and_restart(
    settings, target
):
    _seed(settings)
    # The premise of the bug: a store whose agenda is not empty.
    conn = connect(settings.store_path)
    assert agenda.compute(conn, log_path=settings.analysis_log_path)["rows"]
    conn.close()
    agentconfig.write_skill(
        target, agentskill.SKILL_NAME, agentskill.stamped("# an older protocol")
    )

    with TestClient(create_app(settings)) as client:
        # 1. Startup refreshed the old copy. It must read current, not stale.
        assert _claude_skill(client)["stale"] is False

        # 2. The button. What it answers, and what the screen says next.
        pressed = client.post("/api/agent-targets/claude-code/skill")
        assert pressed.status_code == 200, pressed.text
        assert pressed.json()["status"]["stale"] is False
        assert _claude_skill(client)["stale"] is False

        # 3. A new analysis moves the agenda's counts and its order.
        _ask(settings, "s-b", 3)
        assert _claude_skill(client)["stale"] is False

        # 4. Research lands: a claim on a subject changes what the pack holds.
        conn = connect(settings.store_path)
        conn.execute(
            "INSERT INTO claims (claim_id, pack_id, subject_id, kind, domain,"
            " severity, created_at) VALUES ('c1', 'probe', 's-a', 'known_issue',"
            " 'd', 'high', '2026-09-02')"
        )
        conn.commit()
        conn.close()
        assert _claude_skill(client)["stale"] is False

    written = _skill_on_disk(target)

    # 5. Restarted, with everything above changed underneath the file.
    with TestClient(create_app(settings)) as client:
        assert _claude_skill(client)["stale"] is False
    # And nothing was rewritten on the way: a file that reads current is left
    # alone, which is what makes "press once" mean once.
    assert _skill_on_disk(target) == written


def test_an_updated_pack_is_still_stale_after_the_counts_stopped_counting(
    settings, target
):
    """The exclusion is the snapshot, not the protocol.

    A pack that updated is exactly what the button exists for; a digest that
    ignored it would fix the flicker by hiding the reason. Since B178 the skill
    carries a pack's identity and version and no longer its bar (that reaches
    the agent through `research_brief`), so the version is what moves it.
    """
    _seed(settings)
    with TestClient(create_app(settings)) as client:
        client.post("/api/agent-targets/claude-code/skill")
        assert _claude_skill(client)["stale"] is False

        conn = connect(settings.store_path)
        conn.execute("UPDATE packs SET version = '2' WHERE pack_id = 'probe'")
        conn.commit()
        conn.close()
        assert _claude_skill(client)["stale"] is True

        client.post("/api/agent-targets/claude-code/skill")
        assert _claude_skill(client)["stale"] is False


def test_the_digest_ignores_the_snapshot_and_nothing_else():
    stable = "# protocol\n\nthe loop\n"
    with_snapshot = (
        "# protocol\n\n"
        + agentskill.snapshot("## What to research next\n\n- Alpha, asked 4 times\n")
        + "\nthe loop\n"
    )
    other_snapshot = (
        "# protocol\n\n"
        + agentskill.snapshot("## What to research next\n\n- Beta, asked 9 times\n")
        + "\nthe loop\n"
    )
    assert agentskill.digest(with_snapshot) == agentskill.digest(other_snapshot)
    assert agentskill.digest(with_snapshot) == agentskill.digest(stable)
    assert agentskill.digest(stable) != agentskill.digest(stable + "a new step\n")
