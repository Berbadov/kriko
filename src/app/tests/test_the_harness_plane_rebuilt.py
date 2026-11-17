"""The rebuilt agent-harness plane: roster, clocks, accounts and teardown.

Each test here pins one finding of the 2026-11-17 profile:

* every roster row is reachable and names a protocol;
* a model call is never started with less time left than it can use;
* an account wall is found before the host read and remembered;
* a run with no page and no finding is not a success;
* the document budget caps fetched pages, and a job reuses them;
* a Windows temp folder that will not delete does not mask the run's error;
* a model id the CLI does not offer falls back to the CLI's default;
* a slow cold probe gets room and reads as unknown, never as "no models".
"""

import json
import os
import time
from pathlib import Path

import pytest

from app import chat, chatdata
from app.providers import harness as harness_mod
from app.providers.harness import HarnessResearcher
from app.web import tasks
from kriko.research.base import ResearchTask


def _row(ident: str):
    return next(one for one in harness_mod.KNOWN if one.id == ident)


# ── 1. the roster ────────────────────────────────────────────────────────────


def test_every_known_row_is_reachable_and_names_a_protocol(monkeypatch):
    """No row may sit in `KNOWN` where `chosen()` can never return it."""
    known_protocols = {
        "claude", "vibe", "agy", "codex", "copilot",
        "opencode", "hermes",
    }
    ids = [one.id for one in harness_mod.KNOWN]
    assert len(ids) == len(set(ids)), ids
    for one in harness_mod.KNOWN:
        assert one.protocol in known_protocols, one.id
        assert one.executable, one.id
        # Installed here, or known well enough to offer a way to install it.
        assert harness_mod.locate(one) or (
            one.download_url and one.install_hint and one.needs_account
        ), one.id


def test_the_rows_that_were_dropped_are_back():
    for ident, protocol in (("opencode", "opencode"), ("hermes", "hermes"),
                            ("codex", "codex"), ("github-copilot", "copilot")):
        one = _row(ident)
        assert one.protocol == protocol


def test_the_opencode_process_fallback_speaks_its_json_format():
    opencode = _row("opencode")
    assert "--format" in opencode.args and "json" in opencode.args


def test_the_default_harness_cannot_silently_be_a_different_cli():
    """A row that is installed is offered; none is filtered out of `KNOWN`."""
    assert {one.id for one in harness_mod.KNOWN} >= {
        "claude-code", "codex", "opencode", "hermes", "antigravity-cli",
        "mistral-vibe", "github-copilot",
    }


def test_retired_rows_keep_their_preference_keys():
    from app import prefs

    assert prefs.harness_model_key("gemini-cli") in prefs.KEYS
    assert prefs.harness_effort_key("gemini-cli") in prefs.KEYS


# ── 2. the turn clock is a phase gate ────────────────────────────────────────


class _Clock:
    def __init__(self, left: float):
        self.left = left
        self.lines: list[str] = []
        self.partials: list[dict] = []
        self.progress: list[float] = []

    def remaining(self) -> float:
        return self.left

    def set(self, progress, message=""):
        self.progress.append(progress)

    def log(self, line):
        self.lines.append(line)

    def partial(self, result):
        self.partials.append(result)

    def check(self):
        pass


def _context(tmp_path):
    from kriko.store.db import connect
    from app.web import state

    store = connect(tmp_path / "knowledge.sqlite")
    app_state = state.connect(tmp_path / "app.sqlite")
    return chatdata.Context(store=store, app=app_state)


def test_a_model_call_that_cannot_finish_is_not_started(tmp_path, monkeypatch):
    """The reader's 90-second turn ended inside a call started with 3 s left."""
    ctx = _context(tmp_path)
    clock = _Clock(100.0)
    asked: list[str] = []
    url = "https://forum.example/evo"
    rows = [{"url": url, "page_read": True, "title": "EVO thread",
             "page_excerpt": "The 850 EVO is the pick."}]

    from app import chatdata as data

    original = data.SOURCES["web_search"]

    def run(_ctx, **_kwargs):
        clock.left = 3.0  # what the host search and read left behind
        return {"rows": rows, "truncated": False, "note": "",
                "pages_attempted": 1}

    import dataclasses
    import functools

    @functools.wraps(original.run)
    def wrapped(ctx, **kwargs):
        return run(ctx, **kwargs)

    monkeypatch.setitem(data.SOURCES, "web_search",
                        dataclasses.replace(original, run=wrapped))

    def never(_prompt, _on_text):
        asked.append(_prompt)
        return "should not be written"

    out = chat.run_turn(
        "Which 500 GB SATA SSD should I buy?", ask=lambda _p: "unused",
        ask_stream=never, ctx=ctx, hooks=clock)

    assert asked == [], "a call started with three seconds left cannot finish"
    assert out["status"] == "out_of_time"
    assert url in out["sources"]
    assert any(one["id"] == "turn-out-of-time" for one in out["activity"])
    ctx.store.close()
    ctx.app.close()


# ── 3. account preflight, cached ─────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _fresh_account_cache():
    harness_mod._ACCOUNT_VERDICTS.clear()
    # Every other test starts from a healthy account, so a run test never
    # shells out to the reader's real CLI for a sign-in check.
    for one in harness_mod.KNOWN:
        harness_mod._ACCOUNT_VERDICTS[one.id] = (time.monotonic(), "ok", "")
    yield
    harness_mod._ACCOUNT_VERDICTS.clear()


def test_a_signed_out_account_is_found_before_anything_is_spent(monkeypatch):
    harness_mod._ACCOUNT_VERDICTS.clear()
    claude = _row("claude-code")
    monkeypatch.setattr(harness_mod, "locate", lambda _one: "C:/fake/claude")
    probes: list[tuple] = []

    def ask(executable, *argv, **_kwargs):
        probes.append((executable, argv))
        return json.dumps({"loggedIn": False})

    monkeypatch.setattr(harness_mod, "_ask", ask)
    with pytest.raises(RuntimeError) as raised:
        harness_mod.require_account(claude)
    assert "not signed in" in str(raised.value).lower()
    assert probes, "the CLI's own auth status was asked"

    # Cached for the cooldown: a second call inside the window spends nothing.
    with pytest.raises(RuntimeError):
        harness_mod.require_account(claude)
    assert len(probes) == 1


def test_the_five_hour_limit_is_recognised_as_an_account_wall():
    """The profile saw this exact sentence and Kriko tried the run again."""
    assert harness_mod.account_failure(
        "You've hit your 5-hour limit \u00b7 resets 1:10pm (Europe/Istanbul)")


def test_a_quota_wall_is_remembered_and_never_replayed(monkeypatch):
    harness_mod._ACCOUNT_VERDICTS.clear()
    vibe = _row("mistral-vibe")
    harness_mod.remember_account_failure(vibe, "402 Vibe budget exhausted")
    monkeypatch.setattr(harness_mod, "locate", lambda _one: "C:/fake/vibe")
    calls: list = []
    monkeypatch.setattr(harness_mod, "_ask", lambda *a, **k: calls.append(a) or "")
    with pytest.raises(RuntimeError) as raised:
        harness_mod.require_account(vibe)
    assert "exhausted" in str(raised.value)
    assert calls == [], "a remembered wall is not re-probed"


# ── 4. no evidence is not success ────────────────────────────────────────────


class _Reader:
    def __init__(self, pages=()):
        self.search_coverage = {"pages_read": len(pages), "queries_searched": 1}
        self.page_titles = {}
        self.telemetry = {"stages": []}
        self.search_provider = "test"
        self.sources = {}
        for url, text in pages:
            self.sources[url] = text


def test_a_run_with_no_page_and_no_finding_says_so(monkeypatch):
    monkeypatch.setattr(harness_mod, "HOST_READ_HARNESSES", frozenset())
    researcher = HarnessResearcher(_row("claude-code"))
    monkeypatch.setattr(researcher, "_run", lambda _prompt: '{"findings": []}')
    documents = researcher.gather(ResearchTask(
        subject_id="widget", subject_label="Widget", subject_kind="product",
        pack_id="products", queries=("Widget problems",), max_documents=2,
    ))
    assert documents == []
    assert researcher.coverage["status"] == "no_supported_findings"
    assert tasks._no_evidence_run(researcher)
    assert "no_supported_findings" in tasks._no_evidence_run(researcher)


# ── 5. host-read cost ────────────────────────────────────────────────────────


def test_fetched_pages_never_exceed_the_document_budget(monkeypatch):
    researcher = HarnessResearcher(_row("codex"))
    researcher.max_documents = 2
    seen: list[dict] = []

    def read(_queries, **kwargs):
        seen.append(kwargs)
        return _Reader([("https://a.example", "a page")]), [
            ("https://a.example", "a page")], None

    monkeypatch.setattr(researcher, "_read_web_pages", read)
    monkeypatch.setattr(researcher, "_run", lambda _prompt: "answered")
    researcher.ask_quick("Widget")
    assert seen[-1]["max_pages"] == 2


def test_pages_read_earlier_in_the_job_are_reused(monkeypatch):
    researcher = HarnessResearcher(_row("codex"))
    researcher.max_documents = 2
    reads: list = []

    def read(queries, **kwargs):
        reads.append(tuple(queries))
        return _Reader([("https://a.example", "a page")]), [
            ("https://a.example", "a page")], None

    monkeypatch.setattr(researcher, "_read_web_pages", read)
    monkeypatch.setattr(researcher, "_run", lambda _prompt: "answered")
    researcher.ask_quick("Widget")
    researcher.ask_quick("Widget")
    assert len(reads) == 1, "the second phase paid for the same pages again"


# ── 6. Windows teardown and the reaper ───────────────────────────────────────


def test_a_folder_that_will_not_delete_does_not_mask_the_runs_error(monkeypatch):
    monkeypatch.setattr(
        harness_mod.shutil, "rmtree",
        lambda *_a, **_k: (_ for _ in ()).throw(PermissionError("held open")))

    with harness_mod.run_directory("kriko-research-") as folder:
        (folder / "held.txt").write_text("still held", encoding="utf-8")
    # Reaching here is the assertion: no PermissionError escaped.


def test_the_startup_reaper_removes_only_old_run_folders(tmp_path):
    old = tmp_path / "kriko-agent-old"
    new = tmp_path / "kriko-agent-new"
    research = tmp_path / "kriko-research-old"
    unrelated = tmp_path / "someone-elses-folder"
    for path in (old, new, research, unrelated):
        path.mkdir()
    ancient = time.time() - 2 * 86400
    for path in (old, research, unrelated):
        os.utime(path, (ancient, ancient))

    removed = harness_mod.reap_stale_run_dirs(root=tmp_path, older_than=86400)

    assert removed == 2
    assert not old.exists() and not research.exists()
    assert new.exists() and unrelated.exists()


# ── 7. model ids are validated at run start ──────────────────────────────────


def test_a_model_the_cli_does_not_list_falls_back_to_its_default(monkeypatch):
    opencode = _row("opencode")
    monkeypatch.setattr(harness_mod, "models_for",
                        lambda _one, **_kwargs: ["opencode/big-pickle"])
    chosen, note = harness_mod.validated_model(opencode, "opencode/muse-spark")
    assert chosen == ""
    assert "not a model" in note

    chosen, note = harness_mod.validated_model(opencode, "opencode/big-pickle")
    assert chosen == "opencode/big-pickle" and note == ""


def test_an_unasked_list_is_not_a_verdict_against_the_readers_choice(monkeypatch):
    opencode = _row("opencode")
    monkeypatch.setattr(harness_mod, "models_for", lambda _one, **_kwargs: [])
    chosen, note = harness_mod.validated_model(opencode, "opencode/anything")
    assert chosen == "opencode/anything" and note == ""


def test_the_run_start_falls_back_and_says_why(monkeypatch):
    from app import providers

    opencode = _row("opencode")
    monkeypatch.setattr(providers, "resolve_agent",
                        lambda *_a, **_k: (opencode, ""))
    monkeypatch.setattr(harness_mod, "settle_effort",
                        lambda _one, model, effort: (model, effort))
    monkeypatch.setattr(
        harness_mod, "validated_model",
        lambda _one, _model: ("", "that model is not offered; using the default"))
    researcher = providers.harness_researcher(preferred="opencode", api=False)
    assert researcher.requested_model == ""
    assert "using the default" in researcher.effort_settled


# ── 8. slow probes ───────────────────────────────────────────────────────────


def test_slow_cold_probes_get_room_and_stay_rows(monkeypatch):
    assert harness_mod.probe_seconds("hermes") > harness_mod.HELP_TIMEOUT_SECONDS
    assert harness_mod.probe_seconds("agy") > harness_mod.HELP_TIMEOUT_SECONDS
    assert harness_mod.probe_seconds("claude") == harness_mod.HELP_TIMEOUT_SECONDS

    hermes = _row("hermes")
    with harness_mod._MODELS_LOCK:
        harness_mod._MODELS_UNKNOWN[hermes.id] = time.monotonic()
    try:
        note = harness_mod.models_note(hermes, [])
        assert "could not be read" in note
        assert "listed no models" not in note
    finally:
        harness_mod._MODELS_UNKNOWN.pop(hermes.id, None)


# ── the resident wires ───────────────────────────────────────────────────────


def test_opencode_resident_speaks_acp_with_a_job_dir_policy(monkeypatch, tmp_path):
    monkeypatch.setattr(harness_mod, "locate", lambda _one: "C:/tools/opencode.exe")
    from app.providers import resident

    monkeypatch.setattr(resident, "owned_folder",
                        lambda *_a, **_k: tmp_path / "owned")
    researcher = HarnessResearcher(_row("opencode"))
    profile = researcher._resident_profile()
    assert profile.wire == "acp"
    assert profile.argv[-1] == "acp"
    config = json.loads((tmp_path / "owned" / "work" / "opencode.jsonc")
                        .read_text(encoding="utf-8"))
    assert config["permission"]["bash"] == "deny"
    assert config["permission"]["edit"] == "deny"


def test_hermes_resident_narrows_acp_to_the_web_toolset(monkeypatch, tmp_path):
    monkeypatch.setattr(harness_mod, "locate", lambda _one: "C:/tools/hermes.exe")
    from app.providers import resident

    monkeypatch.setattr(resident, "owned_folder",
                        lambda *_a, **_k: tmp_path / "owned")
    researcher = HarnessResearcher(_row("hermes"))
    profile = researcher._resident_profile()
    assert profile.wire == "acp"
    assert profile.argv[-1] == "acp"
    policy = Path(profile.env["HERMES_MANAGED_DIR"])
    config = (policy / "config.yaml").read_text(encoding="utf-8")
    assert "acp:" in config and "web" in config
    assert "hermes-acp" not in config
    assert profile.env["HERMES_IGNORE_RULES"] == "1"
    # The reader's own home is not replaced: Hermes would rebuild a second
    # runtime before it ever answered `initialize`.
    assert "HERMES_HOME" not in profile.env
