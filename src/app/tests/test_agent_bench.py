"""The agent benchmark grades agents, and is itself graded here.

A grader nobody has watched fail is not a grader. So the faultless scripted
agent must resolve every task, and every scripted flaw must be caught by the
check named for it. And since the reader's complaint was that agents ignored the
app's settings, the old behaviour is re-created below and the benchmark must
fail it.
"""

import argparse
import json
import sqlite3
from unittest import mock

import pytest

from app import prefs
from app.agentbench import checks, report, runner, simulated, suite
from app.agentbench import cli as bench_cli
from app.providers import harness
from app.web import state


@pytest.fixture(scope="module")
def tasks_():
    return suite.load()["tasks"]


@pytest.fixture(scope="module")
def matrix(tasks_):
    """Every scripted agent on every task, once, on a clean settings profile."""
    return runner.run_bench(tasks_, simulated.names(), reps=1, profile="clean")


def _failed(trials: list[dict]) -> set[str]:
    return {one["name"] for trial in trials for one in trial["checks"] if one["status"] == "fail"}


# ── the suite ───────────────────────────────────────────────────────────────

def test_the_suite_is_consistent_with_itself():
    assert suite.validate(suite.load()) == []


def test_a_key_that_cites_a_quote_the_page_lacks_is_refused_before_anything_runs():
    broken = suite.load()
    broken["tasks"][0]["expect"]["supported"][0]["quote"] = "a sentence no page contains"

    assert any("quote is not on its page" in problem for problem in suite.validate(broken))


def test_an_unknown_task_is_an_error_not_a_smaller_run():
    with pytest.raises(ValueError, match="unknown task"):
        suite.load(["not-a-task"])


def test_every_task_setting_is_one_the_app_stores(tasks_):
    for task in tasks_:
        assert set(task.get("settings") or {}) <= set(prefs.KEYS), task["id"]


# ── the graders, watched ────────────────────────────────────────────────────

def test_the_faultless_agent_resolves_every_task(matrix):
    mine = [one for one in matrix["trials"] if one["agent"] == "sim:oracle"]

    assert len(mine) == len(matrix["tasks"])
    assert [one["task"] for one in mine if not one["resolved"]] == []


@pytest.mark.parametrize("flaw", sorted(simulated.FLAW))
def test_each_scripted_flaw_is_caught_by_the_check_named_for_it(matrix, flaw):
    mine = [one for one in matrix["trials"] if one["agent"] == simulated.PREFIX + flaw]

    caught = _failed(mine)

    assert set(simulated.FLAW[flaw]) <= caught, (flaw, caught)
    assert any(not one["resolved"] for one in mine) == bool(simulated.FLAW[flaw])


def test_a_signature_check_fails_for_the_agent_with_that_flaw_and_no_other(matrix):
    signature = {"honest_proposals": "fabricator", "injection_resisted": "injected",
                 "no_forbidden_claims": "variant-blind", "recall": "silent"}
    for check, flaw in signature.items():
        for agent in simulated.names():
            failed = _failed([one for one in matrix["trials"] if one["agent"] == agent])
            assert (check in failed) == (agent == simulated.PREFIX + flaw), (check, agent)


def test_a_claim_with_a_quote_not_on_the_page_never_reaches_the_card(matrix):
    mine = [one for one in matrix["trials"] if one["agent"] == "sim:fabricator"]

    assert all(one["measure"]["refused"] == 1 for one in mine)
    assert not any(c["status"] == "fail" and c["name"] == "grounded"
                   for one in mine for c in one["checks"])


def test_an_order_inside_a_page_is_graded_by_what_reached_the_card(matrix):
    task = next(one for one in matrix["trials"]
                if one["agent"] == "sim:injected" and one["task"] == "page-gives-orders")

    verdict = next(c for c in task["checks"] if c["name"] == "injection_resisted")

    assert verdict["status"] == "fail" and "reached the card" in verdict["detail"]


# ── the app's settings, graded ──────────────────────────────────────────────

def _obs(task_id: str, tasks_, **fields) -> checks.Observation:
    task = next(one for one in tasks_ if one["id"] == task_id)
    return checks.Observation(task=task, result={"risks": [], "specs": []}, **fields)


def test_more_pages_than_the_ceiling_fails_the_ceiling(tasks_):
    pages = {f"https://x/{n}": "t" for n in range(3)}

    over = checks.sources_ceiling(_obs("source-ceiling", tasks_, shown=pages,
                                       settings={"research_sources": "2"}))
    within = checks.sources_ceiling(_obs("source-ceiling", tasks_, shown=dict(list(pages.items())[:2]),
                                         settings={"research_sources": "2"}))

    assert (over.status, within.status) == (checks.FAIL, checks.PASS)


def test_a_ceiling_nobody_set_and_an_agent_that_browses_for_itself_are_not_counted(tasks_):
    none_set = checks.sources_ceiling(_obs("report-and-spec", tasks_, shown={"u": "t"}, settings={}))
    browses = checks.sources_ceiling(_obs("source-ceiling", tasks_, shown=None,
                                          settings={"research_sources": "2"}))

    assert none_set.status == browses.status == checks.NA


def test_a_kind_nobody_searched_for_fails_and_one_that_was_passes(tasks_):
    settings = {"research_source_kinds": "video,recalls"}

    missing = checks.source_kinds(_obs("source-kinds", tasks_, settings=settings,
                                       queries=("W problems owner reports",)))
    covered = checks.source_kinds(_obs("source-kinds", tasks_, settings=settings,
                                       queries=("W video review teardown", "W recall bulletin")))

    assert (missing.status, covered.status) == (checks.FAIL, checks.PASS)
    assert "video" in missing.detail


def test_asking_the_engine_in_the_wrong_language_or_with_the_wrong_words_fails(tasks_):
    settings = {"local_search_language": "tr"}
    wrong_engine = checks.search_language(_obs(
        "search-language", tasks_, settings=settings,
        search_languages=frozenset({"en"}), queries=("a",)))
    english_words = checks.search_language(_obs(
        "search-language", tasks_, settings=settings,
        search_languages=frozenset({"tr"}), queries=("W problems owner reports",)))

    assert wrong_engine.status == english_words.status == checks.FAIL


def test_an_effort_or_model_other_than_the_stored_one_fails_unless_the_run_said_why(tasks_):
    stored = {"harness_effort_codex": "high", "harness_model_codex": "m1"}
    base = dict(settings=stored, harness_id="codex")

    ignored = checks.effort(_obs("report-and-spec", tasks_, requested_effort="low", **base))
    honoured = checks.effort(_obs("report-and-spec", tasks_, requested_effort="high", **base))
    explained = checks.effort(_obs("report-and-spec", tasks_, requested_effort="",
                                   effort_settled="ran m1 without a separate effort flag", **base))
    wrong_model = checks.model(_obs("report-and-spec", tasks_, requested_model="other", **base))

    assert (ignored.status, honoured.status, explained.status) == (
        checks.FAIL, checks.PASS, checks.PASS)
    assert wrong_model.status == checks.FAIL


def _oracle_on(task_id: str, tasks_, *, patches=()) -> dict:
    task = next(one for one in tasks_ if one["id"] == task_id)
    with mock.patch.multiple("app.web.tasks", **dict(patches)) if patches else mock.MagicMock():
        return runner.run_trial(task, "sim:oracle", profile="clean")


def _verdict(trial: dict, name: str) -> dict:
    return next(one for one in trial["checks"] if one["name"] == name)


def test_the_old_behaviour_that_ignored_the_source_settings_fails_the_benchmark(tasks_):
    """Before the settings were applied, the agent was shown three pages whatever was set."""
    healthy = _oracle_on("source-ceiling", tasks_)
    ignoring = _oracle_on("source-ceiling", tasks_,
                          patches={"_apply_source_options": lambda *_a, **_k: None})

    assert _verdict(healthy, "sources_ceiling")["status"] == "pass"
    assert _verdict(ignoring, "sources_ceiling")["status"] == "fail"
    kinds = _oracle_on("source-kinds", tasks_,
                       patches={"_apply_source_options": lambda *_a, **_k: None})
    assert _verdict(kinds, "source_kinds")["status"] == "fail"
    language = _oracle_on("language-setting", tasks_,
                          patches={"_apply_source_options": lambda *_a, **_k: None})
    assert _verdict(language, "output_language")["status"] == "fail"


def test_the_old_behaviour_that_forced_low_effort_fails_the_benchmark(tasks_):
    import app.providers as providers

    original = providers.harness_researcher

    def forcing_low(**kwargs):
        return original(**{**kwargs, "effort": "low", "default_effort": ""})

    task = next(one for one in tasks_ if one["id"] == "report-and-spec")
    with mock.patch.object(providers, "harness_researcher", forcing_low):
        # `run_trial` wraps whatever factory is current, so the forced one runs.
        trial = runner.run_trial(task, "sim:oracle", profile="clean")

    assert _verdict(trial, "effort")["status"] == "fail"


# ── running it responsibly ──────────────────────────────────────────────────

def test_an_agent_that_browses_for_itself_is_listed_and_not_scored(tasks_):
    ran = runner.run_bench(tasks_[:1], ["claude-code"], reps=1, profile="clean")

    assert ran["trials"] == [] and ran["agents"] == []
    assert "own tools" in ran["skipped"]["claude-code"]


def test_an_agent_that_is_not_installed_is_listed_and_not_scored(tasks_):
    with mock.patch.object(harness, "available", lambda: []):
        ran = runner.run_bench(tasks_[:1], ["codex"], reps=1, profile="clean")

    assert ran["trials"] == [] and "not installed" in ran["skipped"]["codex"]


def test_a_real_agent_is_never_run_without_yes(capsys):
    args = argparse.Namespace(agents="codex", simulate=False, tasks="", reps=1, profile="clean",
                              timeout=5.0, yes=False, list=False, out="", fail_under=0.0, store=None)

    with mock.patch.object(runner, "run_bench",
                           side_effect=AssertionError("a real agent ran without --yes")):
        code = bench_cli.run(args)

    assert code == 2
    assert "--yes" in capsys.readouterr().err


def test_naming_no_agent_runs_nothing(capsys):
    args = argparse.Namespace(agents="", simulate=False, tasks="", reps=1, profile="clean",
                              timeout=5.0, yes=False, list=False, out="", fail_under=0.0, store=None)

    assert bench_cli.run(args) == 2


def test_a_trial_neither_touches_the_readers_settings_nor_leaves_the_real_web_replaced(
        tmp_path, tasks_):
    from app.providers import fetch, openserp

    reader = tmp_path / "app.sqlite"
    conn = state.connect(reader)
    prefs.write(conn, {"research_sources": "1", "local_output_language": "de"})
    conn.close()
    before = (openserp.searcher, fetch.reader)
    task = next(one for one in tasks_ if one["id"] == "decoy-pages")

    trial = runner.run_trial(task, "sim:oracle", profile="reader", reader_state=reader)

    conn = state.connect(reader)
    try:
        stored = prefs.read(conn)
    finally:
        conn.close()
    assert (stored["research_sources"], stored["local_output_language"]) == ("1", "de")
    assert (openserp.searcher, fetch.reader) == before
    # The reader's own ceiling applied to the run: one page shown, not the three offered.
    assert trial["measure"]["pages_shown"] == 1


# ── the report ──────────────────────────────────────────────────────────────

def _trial(agent, task, rep, resolved, claims=(), failing=()):
    return {"agent": agent, "task": task, "rep": rep, "dimension": "recall",
            "resolved": resolved, "error": "", "claims": list(claims),
            "checks": [{"name": name, "status": "fail", "detail": "d"} for name in failing]
            + [{"name": "grounded", "status": "pass", "detail": ""}],
            "measure": {"ms": 1000, "tokens": 100, "usd": None, "delivered": len(claims),
                        "refused": 0, "pages_shown": 1, "pages_fetched": 1, "searches": 3}}


def test_consistency_separates_an_agent_that_solved_a_task_from_one_that_got_lucky():
    trials = [
        _trial("steady", "a", 1, True, ["x"]), _trial("steady", "a", 2, True, ["x"]),
        _trial("lucky", "a", 1, True, ["x"]),
        _trial("lucky", "a", 2, False, ["x", "extra:y"], failing=["no_extra_claims"]),
    ]
    bench = {"suite": {"id": "s", "version": "1"}, "profile": "clean", "reps": 2,
             "agents": ["steady", "lucky"], "skipped": {}, "tasks": ["a"], "trials": trials}

    summary = report.summarize(bench)["agents"]

    assert summary["steady"]["every_run"] == 1 and summary["lucky"]["every_run"] == 0
    assert summary["lucky"]["any_run"] == 1
    assert summary["steady"]["stability"] == 1.0 and summary["lucky"]["stability"] == 0.5
    assert summary["lucky"]["resolved_rate"] == 0.5
    assert summary["lucky"]["task_results"]["a"]["failing"] == ["no_extra_claims"]


def test_the_rendered_report_names_every_agent_task_and_reason(matrix):
    text = report.render(report.summarize(matrix))

    for heading in ("## Agents", "## By task", "## By skill", "## By check", "## Why runs failed"):
        assert heading in text
    assert "sim:variant-blind" in text and "explicit-exclusion" in text
    assert "the bulletin excludes this revision" in text


def test_the_cli_runs_the_scripted_agents_and_writes_the_report(tmp_path, capsys):
    args = argparse.Namespace(agents="", simulate=True, tasks="report-and-spec,clean-product", reps=2,
                              profile="clean", timeout=30.0, yes=False, list=False,
                              out=str(tmp_path), fail_under=0.0, store=str(tmp_path / "k.sqlite"))

    assert bench_cli.run(args) == 0

    folder = next(tmp_path.iterdir())
    saved = json.loads((folder / "report.json").read_text(encoding="utf-8"))
    assert len(saved["trials"]) == 2 * 2 * len(simulated.names())
    assert (folder / "report.md").read_text(encoding="utf-8").startswith("# Agent benchmark")
    assert saved["trials"][0]["trajectory"]["queries"]
    assert "report and trajectories" in capsys.readouterr().out


def test_a_threshold_turns_a_weak_agent_into_a_failing_exit_code(tmp_path):
    args = argparse.Namespace(agents="sim:silent", simulate=False, tasks="report-and-spec", reps=1,
                              profile="clean", timeout=30.0, yes=False, list=False,
                              out=str(tmp_path), fail_under=50.0, store=str(tmp_path / "k.sqlite"))

    assert bench_cli.run(args) == 1


def test_list_shows_the_tasks_and_which_agents_can_run(capsys):
    args = argparse.Namespace(agents="", simulate=False, tasks="", reps=1, profile="clean",
                              timeout=5.0, yes=False, list=True, out="", fail_under=0.0, store=None)

    assert bench_cli.run(args) == 0
    shown = capsys.readouterr().out
    assert "explicit-exclusion" in shown and "sim:oracle" in shown


def test_the_scripted_agents_exist_in_one_list():
    assert set(simulated.DESCRIPTION) == set(simulated.FLAW)
    assert sqlite3  # the settings store the trials copy is SQLite, imported for the reader fixture
