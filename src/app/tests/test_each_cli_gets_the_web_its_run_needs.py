"""B154: each CLI gets the web access its run needs, and no more.

    oh god, claude code wasnt able to open any website as well as opencode,
    antigravity guy is slow but created a new pack and returned results very
    good but failed quick look … web search on cc and opencode might be an
    external block?

Three different answers, reproduced on the reader's machine on 0.10.13:

* **opencode** was not blocked by anyone. opencode 2.x asks, once, which
  provider its `websearch` tool should use; `opencode run` has nobody to ask,
  so every search came back "Web search cancelled".
* **Antigravity's quick look** died on Kriko's own arguments: the quick look
  asks for `--effort low`, the reader's model id already said `-medium`, and
  `agy` refuses the pair before it makes a single call.
* **Claude Code** was refused by one site's server (a 403 to its fetcher), and
  asked the same site again twice. That one is the site's call; what Kriko
  owns is telling the agent to move on.

None of these tests spawns a real CLI; a few spawn a Python stand-in that
reports what it was given.
"""

import json
import sys
from pathlib import Path

from app import disambiguate, packauthor, providers, quicklook, sites
from app.providers import harness as harness_mod
from app.providers.harness import HarnessResearcher
from kriko.research.agent import REFUSED_PAGE, AgentResearcher
from kriko.research.base import ResearchTask

#: `agy models` on the reader's machine, 2026-09-29, trimmed. The effort is
#: the tail of the id, and not every family has every level.
AGY_MODELS = [
    "gemini-3.8-flash-high", "gemini-3.8-flash-medium", "gemini-3.8-flash-low",
    "gemini-3.1-pro-high", "gemini-3.1-pro-low",
    "claude-sonnet-4-6", "gpt-oss-120b-medium",
]


def _one(ident: str):
    from app.tests.harness_fixtures import row
    return row(ident)


# ── opencode: the question nobody was there to answer ───────────────────────


def test_an_opencode_run_starts_with_its_search_provider_already_chosen():
    """The answer is a file in the run's own folder, and it goes with it.

    A project `opencode.json` is read from the folder `opencode run` starts
    in, so the reader's global config and opencode's own database — where
    the interactive answer would have been kept — are never written.
    """
    researcher = HarnessResearcher(_one("opencode"))
    with researcher._workspace():
        folder = Path(researcher._run_cwd)
        config = json.loads((folder / "opencode.json").read_text(encoding="utf-8"))
    # `exa` answers without a key of the reader's; `random` can land on one
    # that needs a key and return nothing, which is the same silence again.
    assert config == {"websearch": {"provider": "exa"}}
    assert not folder.exists()
    assert researcher._run_cwd is None


def test_every_run_is_told_its_folder_by_pwd_as_well_as_by_cwd():
    """Reproduced, not supposed: with the `opencode.json` in place, the run
    still said "Web search cancelled" when started from a shell whose `PWD`
    was another folder, and searched via Exa with `PWD` set to its own. A CLI
    that believes `PWD` over the real working directory reads whichever
    folder the reader's shell was in — so every run gets its own, for both
    kinds of workspace, and none survives the run."""
    for one in harness_mod.KNOWN:
        researcher = HarnessResearcher(one)
        with researcher._workspace():
            assert researcher._run_env["PWD"] == researcher._run_cwd, one.id
        assert researcher._run_env == {}, one.id


def test_only_opencode_is_handed_an_opencode_config():
    """A stray `opencode.json` is harmless to another CLI, and still not its
    business: the per-run folder of every other harness holds nothing but,
    where its row declares one and its build takes it, the page reader's
    config (B155; `test_the_page_reader.py` covers that file)."""
    for one in harness_mod.KNOWN:
        if one.id == "opencode" or one.sandbox_home:
            continue
        researcher = HarnessResearcher(one)
        with researcher._workspace():
            held = {p.name for p in Path(researcher._run_cwd).iterdir()}
        assert held <= {harness_mod.READER_CONFIG_FILE}, one.id


# ── Antigravity: one effort, said once ──────────────────────────────────────


def _agy(monkeypatch, models=AGY_MODELS):
    monkeypatch.setattr(harness_mod, "efforts_for", lambda one: ["low", "medium", "high"])
    monkeypatch.setattr(harness_mod, "models_for", lambda one, **_: list(models))
    return _one("antigravity-cli")


def test_an_effort_moves_into_the_model_id_the_cli_lists(monkeypatch):
    """The quick look's `low` on the reader's `-medium` pick: the pair agy
    refused. The run gets the `-low` sibling and no `--effort` beside it."""
    agy = _agy(monkeypatch)
    assert harness_mod.settle_effort(agy, "gemini-3.8-flash-medium", "low") == (
        "gemini-3.8-flash-low", "")


def test_a_level_the_family_does_not_have_keeps_the_readers_model(monkeypatch):
    """`gemini-3.1-pro` lists `-high` and `-low` and no `-medium`. A made-up id
    would fail the same way the pair did, so the reader's pick stands and the
    flag that contradicts it goes."""
    agy = _agy(monkeypatch)
    assert harness_mod.settle_effort(agy, "gemini-3.1-pro-high", "medium") == (
        "gemini-3.1-pro-high", "")


def test_a_model_that_carries_no_level_keeps_its_flag(monkeypatch):
    """Nothing to reconcile: `claude-sonnet-4-6` ends in a version, not a
    level, and no model at all means the CLI's default takes the flag."""
    agy = _agy(monkeypatch)
    assert harness_mod.settle_effort(agy, "claude-sonnet-4-6", "low") == (
        "claude-sonnet-4-6", "low")
    assert harness_mod.settle_effort(agy, "", "low") == ("", "low")


def test_a_cli_without_levels_in_its_ids_is_left_alone(monkeypatch):
    """The rule reads each CLI's own lists, so a CLI with no effort dial — or
    one whose ids happen to end in a word — passes through untouched."""
    monkeypatch.setattr(harness_mod, "efforts_for", lambda one: [])
    opencode = _one("opencode")
    assert harness_mod.settle_effort(opencode, "opencode/some-model-high", "low") == (
        "opencode/some-model-high", "low")


def test_a_tail_that_only_looks_like_a_level_keeps_its_flag(monkeypatch):
    """Review's case: a dial that one day offers `max`, and a model named
    `…-codex-max` with no `-low`/`-high` sibling. The name is a coincidence,
    so the effort stays a flag instead of being silently dropped."""
    agy = _agy(monkeypatch, models=["gpt-5.1-codex-max", "gpt-5.1-codex"])
    monkeypatch.setattr(harness_mod, "efforts_for", lambda one: ["low", "high", "max"])
    assert harness_mod.settle_effort(agy, "gpt-5.1-codex-max", "low") == (
        "gpt-5.1-codex-max", "low")


def test_an_unknown_list_drops_the_flag_rather_than_risk_the_refusal(monkeypatch):
    """A cold model cache says nothing either way. The refusal fails the run;
    the reader's own level only makes it slower — so the flag goes."""
    agy = _agy(monkeypatch, models=[])
    assert harness_mod.settle_effort(agy, "gemini-3.8-flash-medium", "low") == (
        "gemini-3.8-flash-medium", "")


def _door(monkeypatch, agy, **pick):
    monkeypatch.setattr(harness_mod, "chosen", lambda preferred="": agy)
    monkeypatch.setattr(harness_mod, "locate", lambda one: f"/usr/bin/{one.executable}")
    monkeypatch.setattr(harness_mod, "declared", lambda _: frozenset(
        {"--output-format", "--disable-slash-commands", "--model", "--effort", "-p"}))
    return providers.harness_researcher(preferred="antigravity-cli", **pick)


def test_the_quick_look_on_a_suffixed_pick_builds_a_vector_agy_accepts(monkeypatch):
    """End to end through the door the quick look uses, down to the argv."""
    agy = _agy(monkeypatch)
    researcher = _door(monkeypatch, agy, model="gemini-3.8-flash-medium", effort="low")
    vector = harness_mod.command_for(
        agy, model=researcher.requested_model, effort=researcher.requested_effort)
    assert vector[vector.index("--model") + 1] == "gemini-3.8-flash-low"
    assert "--effort" not in vector


def test_a_run_not_on_the_readers_literal_pick_says_so_in_its_log(monkeypatch):
    """A quick look on `-low` where the reader chose `-medium`, or on `-high`
    with no flag, is quietly faster or slower unless the log says why."""
    agy = _agy(monkeypatch)
    moved = _door(monkeypatch, agy, model="gemini-3.8-flash-medium", effort="low")
    assert "gemini-3.8-flash-low" in moved.effort_settled
    kept = _door(monkeypatch, agy, model="gemini-3.1-pro-high", effort="medium")
    assert "gemini-3.1-pro-high" in kept.effort_settled
    assert "own level" in kept.effort_settled
    plain = _door(monkeypatch, agy, model="claude-sonnet-4-6", effort="low")
    assert plain.effort_settled == ""


def _echo(tmp_path: Path) -> harness_mod.Harness:
    """A real child that answers with what it was given, and nothing else."""
    script = tmp_path / "echo.py"
    script.write_text(
        "import json, os, sys\n"
        "print(json.dumps({'type': 'result', 'result': json.dumps({"
        "'prompt': sys.argv[-1], 'pwd': os.environ.get('PWD'), 'cwd': os.getcwd()})}))\n",
        encoding="utf-8")
    return harness_mod.Harness("fake", "Fake CLI", sys.executable, (str(script),),
                               structured=True)


def test_the_log_line_reaches_the_run_before_the_cli_starts(tmp_path):
    researcher = HarnessResearcher(_echo(tmp_path), timeout=30)
    researcher.effort_settled = "Running gemini-3.8-flash-low: …"
    said: list[str] = []
    researcher.on_action = said.append
    researcher.ask("brief")
    assert said[0] == researcher.effort_settled


def test_the_child_itself_sees_its_own_folder_as_pwd(tmp_path, monkeypatch):
    """Not the dict, the process: a `PWD` handed down from a shell elsewhere,
    and what the spawned child actually reads."""
    monkeypatch.setenv("PWD", str(tmp_path))
    got = json.loads(HarnessResearcher(_echo(tmp_path), timeout=30).ask("brief"))
    assert Path(got["pwd"]).resolve() == Path(got["cwd"]).resolve()
    assert Path(got["pwd"]).resolve() != tmp_path.resolve()


# ── Claude Code: a refused page is an answer, not a retry ────────────────────


def test_the_briefs_that_place_it_themselves_say_it_where_it_reads():
    """One wording, placed in context in the briefs that open pages most:
    research (also what an MCP agent is handed), quick look, pack author."""
    task = ResearchTask(subject_id="s", subject_label="A thing", subject_kind="product",
                        pack_id="things")
    assert "403" in REFUSED_PAGE and "another source" in REFUSED_PAGE
    assert REFUSED_PAGE in AgentResearcher().brief(task)
    assert REFUSED_PAGE in quicklook.brief("A thing")
    assert REFUSED_PAGE in packauthor.brief("things")


def test_every_brief_a_cli_is_handed_says_it_once(tmp_path):
    """Review found three briefs without it — amend, disambiguate, site
    register. The door they all pass is where it is guaranteed, so a brief
    written later is covered without anyone remembering to."""
    one = _echo(tmp_path)
    briefs = [
        packauthor.amend_brief({"name": "things"}),
        disambiguate.brief("A thing"),
        sites.BRIEF.format(site="shop.example", url="https://shop.example/p/1", keys="model"),
        quicklook.brief("A thing"),
        "a brief nobody has written yet",
    ]
    for brief in briefs:
        got = json.loads(HarnessResearcher(one, timeout=30).ask(brief))["prompt"]
        assert got.count(REFUSED_PAGE) == 1, brief[:40]
        assert got.startswith(brief.rstrip()), brief[:40]
