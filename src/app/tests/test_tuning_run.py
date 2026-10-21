"""The command: the plan before the press, the ledger, the report, the comparison."""

import json

import pytest

from app.tests import tuning_fakes as fakes
from app.tuning import agents as agent_mod
from app.tuning import cli, compare, run
from app.tuning.grade import Grader
from app.web import state

ROSTER = [fakes.ANSWERER, fakes.GRADER]
SECRET = "sk-live-9f8e7d6c5b4a39281706f5e4d3c2b1a0"


@pytest.fixture
def app_state(tmp_path):
    path = tmp_path / "app.sqlite"
    state.connect(path).close()
    return path


class Rehearsal(cli.Dependencies):
    """The CLI's edges, replaced: no agent is ever opened unless a test lets it."""

    def __init__(self, answerer, grader_agent, roster=ROSTER):
        super().__init__(roster=lambda _path: roster, fetch=fakes.fetch)
        self.fake_answerer, self.grader_agent = answerer, grader_agent
        self.opened: list[str] = []
        self.answerer = lambda *_: self.fake_answerer
        self.open_grader = self._open

    def _open(self, ref, settings, **_):
        self.opened.append(ref.id)
        return self.grader_agent


def _pick(app_state, agent="codex", search="searchprov-x"):
    conn = state.connect(app_state)
    try:
        from app import prefs

        prefs.write(conn, {prefs.HARNESS: agent, prefs.SEARCH: search,
                           prefs.harness_model_key(agent): "model-a"})
    finally:
        conn.close()


def _argv(app_state, tmp_path, *extra):
    return ["run", "--state", str(app_state), "--out", str(tmp_path / "out"), "--limit", "2", *extra]


# ── the press ───────────────────────────────────────────────────────────────

def test_without_yes_the_plan_and_its_cost_are_shown_and_nothing_runs(app_state, tmp_path, capsys):
    _pick(app_state)
    answerer = fakes.FakeAnswerer(default=RuntimeError("must not be asked"))
    deps = Rehearsal(answerer, fakes.FakeGraderAgent())
    code = cli.main(_argv(app_state, tmp_path), deps)
    shown = capsys.readouterr()
    assert code == 2
    assert answerer.asked == [] and deps.opened == []
    assert "2 attempt(s)" in shown.out and "Codex" in shown.out and "Claude Code" in shown.out
    assert "at most" in shown.out and "searchprov-x" in shown.out
    assert "add --yes" in shown.err
    assert not (tmp_path / "out").exists()


def test_with_no_second_agent_the_command_stops_instead_of_self_grading(app_state, tmp_path, capsys):
    _pick(app_state)
    deps = Rehearsal(fakes.FakeAnswerer(), fakes.FakeGraderAgent(), roster=[fakes.ANSWERER])
    code = cli.main(_argv(app_state, tmp_path, "--yes"), deps)
    assert code == 2 and deps.opened == []
    assert "never lets an agent grade itself" in capsys.readouterr().err


def test_a_pick_that_is_not_installed_is_an_error_not_a_substitution(app_state, tmp_path, capsys):
    _pick(app_state, agent="ghost")
    code = cli.main(_argv(app_state, tmp_path, "--yes"), Rehearsal(fakes.FakeAnswerer(), fakes.FakeGraderAgent()))
    assert code == 2 and "'ghost' is not available" in capsys.readouterr().err


def test_the_preference_is_read_from_settings_and_an_override_wins(app_state):
    _pick(app_state, agent="codex", search="tavily")
    found = agent_mod.read_preference(app_state, ROSTER)
    assert (found.agent.id, found.search_provider) == ("codex", "tavily")
    found = agent_mod.read_preference(app_state, ROSTER, agent="claude-code", search="exa")
    assert (found.agent.id, found.search_provider) == ("claude-code", "exa")
    conn = state.connect(app_state)
    try:
        conn.execute("DELETE FROM settings")
        conn.commit()
    finally:
        conn.close()
    found = agent_mod.read_preference(app_state, ROSTER)
    assert found.agent.id == "codex" and found.search_provider == agent_mod.DEFAULT_SEARCH


# ── the run ─────────────────────────────────────────────────────────────────

def _run_it(app_state, tmp_path, answerer, grader_agent, *extra):
    _pick(app_state)
    deps = Rehearsal(answerer, grader_agent)
    code = cli.main(_argv(app_state, tmp_path, "--yes", "--label", "before", *extra), deps)
    folder = next((tmp_path / "out").glob("tuning-*"))
    return code, run.load(folder), folder, deps


def test_a_run_records_who_answered_and_who_graded_and_keeps_the_graders_reasoning(app_state, tmp_path):
    code, doc, folder, deps = _run_it(app_state, tmp_path, fakes.FakeAnswerer(), fakes.FakeGraderAgent())
    assert code == 0 and deps.opened == ["claude-code"]
    assert doc["answered_by"]["agent"]["id"] == "codex" and doc["graded_by"]["id"] == "claude-code"
    row = doc["rows"][0]
    assert row["answered_by"]["id"] == "codex" and row["answered_by"]["search_provider"] == "searchprov-x"
    assert row["graded_by"]["id"] == "claude-code" and row["graded_by"]["id"] != row["answered_by"]["id"]
    assert row["grading"]["summary"] and row["grading"]["facts"]
    assert doc["summary"]["attempts"] == 2


def test_the_ledger_carries_no_secret_from_a_question_an_answer_or_the_environment(
        app_state, tmp_path, monkeypatch):
    monkeypatch.setenv("SOME_SERVICE_API_KEY", "env-secret-value-12345678")
    leaky = fakes.good_answer(
        text=f"Stainless steel, 8 bar [{fakes.URL}] (my key is {SECRET}, mail me@example.org, "
             "env-secret-value-12345678)", log=[f"GET https://x.example/?api_key={SECRET}&q=1"])
    _, _, folder, _ = _run_it(app_state, tmp_path, fakes.FakeAnswerer(default=leaky), fakes.FakeGraderAgent())
    written = "\n".join(path.read_text(encoding="utf-8") for path in folder.rglob("*.json"))
    html = "\n".join(path.read_text(encoding="utf-8") for path in folder.rglob("*.html"))
    for secret in (SECRET, "env-secret-value-12345678", "me@example.org"):
        assert secret not in written and secret not in html


def test_the_report_is_plain_sortable_html_with_the_reasoning_expandable(app_state, tmp_path):
    answerer = fakes.FakeAnswerer(default=fakes.good_answer(text="<script>alert(1)</script> " + fakes.URL))
    _, _, folder, _ = _run_it(app_state, tmp_path, answerer, fakes.FakeGraderAgent())
    index = (folder / "report" / "index.html").read_text(encoding="utf-8")
    assert "<script" not in index and "&lt;script&gt;" in index           # nothing to execute
    assert "<details><summary>Grader's reasoning</summary>" in index
    assert "Answered by" in index and "Graded by" in index and "never the agent" in index
    assert "sorted-facts-asc.html" in index and "sorted-facts-desc.html" in index
    low_to_high = (folder / "report" / "sorted-seconds-asc.html").read_text(encoding="utf-8")
    assert "low → high" in low_to_high


def test_every_failed_attempt_is_classified_and_the_classes_are_counted_in_the_report(app_state, tmp_path):
    bad = {"identity": {"matches": False, "reason": "wrong variant"},
           "requirements_ignored": ["answer in Turkish"]}
    _, doc, folder, _ = _run_it(app_state, tmp_path, fakes.FakeAnswerer(), fakes.FakeGraderAgent(overrides=bad))
    assert doc["summary"]["failure_classes"] == {"wrong_identity": 2, "ignored_requirement": 2}
    assert doc["summary"]["commonest_failure"] == "ignored_requirement"      # a tie goes to the vocabulary's order
    index = (folder / "report" / "index.html").read_text(encoding="utf-8")
    assert "wrong_identity" in index and "(commonest)" in index


def test_a_case_that_breaks_the_answerer_is_a_row_and_the_run_goes_on(app_state, tmp_path):
    answerer = fakes.FakeAnswerer(answers={"shoe-easy-eva": RuntimeError("the agent crashed")})
    code, doc, _, _ = _run_it(app_state, tmp_path, answerer, fakes.FakeGraderAgent())
    assert code == 0
    broken = next(row for row in doc["rows"] if row["case"] == "shoe-easy-eva")
    assert broken["status"] == "error" and "the agent crashed" in broken["answer"]["error"]
    assert len(doc["rows"]) == 2 and "runtime_error" in broken["failures"]


def test_an_ungraded_attempt_is_not_counted_as_a_pass(app_state, tmp_path):
    _, doc, _, _ = _run_it(app_state, tmp_path, fakes.FakeAnswerer(), fakes.FakeGraderAgent(raw="no json"))
    assert doc["summary"]["ungraded"] == 2 and doc["summary"]["accepted"] == 0
    assert doc["summary"]["pass_rate"] is None


def test_the_benchmark_corpus_is_the_default_and_a_case_file_is_added_to_it(app_state, tmp_path):
    file = tmp_path / "mine.json"
    file.write_text(json.dumps({"cases": [fakes.CHAT]}), encoding="utf-8")
    _pick(app_state)
    deps = Rehearsal(fakes.FakeAnswerer(), fakes.FakeGraderAgent(overrides={"facts": []}))
    cli.main(["run", "--state", str(app_state), "--out", str(tmp_path / "out"), "--cases", str(file),
              "--yes"], deps)
    assert deps.fake_answerer.asked == ["chat-abc-1"]                    # --cases alone: just those
    deps = Rehearsal(fakes.FakeAnswerer(), fakes.FakeGraderAgent(overrides={"facts": []}))
    cli.main(["run", "--state", str(app_state), "--out", str(tmp_path / "out2"), "--cases", str(file),
              "--bench", "--limit", "20", "--yes"], deps)
    assert "chat-abc-1" in deps.fake_answerer.asked and "shoe-easy-eva" in deps.fake_answerer.asked


def test_searchbench_dispatches_tune_to_the_same_command(app_state, tmp_path, capsys, monkeypatch):
    from app.searchbench.__main__ import main as searchbench_main

    _pick(app_state)
    monkeypatch.setattr(cli, "Dependencies", lambda: Rehearsal(fakes.FakeAnswerer(), fakes.FakeGraderAgent()))
    code = searchbench_main(["tune", "run", "--state", str(app_state), "--out", str(tmp_path / "o"),
                             "--limit", "1"])
    assert code == 2 and "Nothing was run" in capsys.readouterr().err


# ── before and after ────────────────────────────────────────────────────────

def _ledger(tmp_path, name, verdicts, *, grader=fakes.GRADER, sha="aaaa", cases=None, answerer=None):
    """A real ledger written by the real run, with scripted verdicts per case."""
    cases = cases or [{**fakes.CASE, "id": f"case-{i}", "question": f"Question number {i} about the widget?"}
                      for i in range(len(verdicts))]
    script = {case["question"]: (fakes.verdict() if ok else fakes.verdict(
        identity={"matches": False, "reason": "no"})) for case, ok in zip(cases, verdicts)}
    agent = fakes.FakeGraderAgent(script, ref=grader)
    document = run.run_tuning(
        cases, answerer or fakes.FakeAnswerer(), Grader(agent), fetch=fakes.fetch, folder=tmp_path / name,
        label=name, preference={"agent": fakes.ANSWERER.public(), "search_provider": "searchprov-x"},
        engine={"version": "1.0", "git_sha": sha, "dirty": False})
    return document


def test_paired_differences_and_an_interval_over_the_same_cases(tmp_path):
    before = _ledger(tmp_path, "before", [True, True, False, False, False, True, False, False], sha="aaaa")
    after = _ledger(tmp_path, "after", [True, True, True, True, False, True, True, False], sha="bbbb")
    result = compare.compare(before, after)
    assert result["paired"] == 8 and result["same_case_set"] is True
    assert result["improved"] == ["case-2", "case-3", "case-6"] and result["regressed"] == []
    assert result["pass_rate"]["delta"] == pytest.approx(3 / 8)
    low, high = result["pass_rate"]["ci95"]
    assert low > 0 and high <= 1                       # every change was an improvement
    assert result["sign_test_p"] == pytest.approx(0.25)
    assert result["notes"] == []
    assert "interval excludes zero" in result["verdict"]


def test_a_difference_the_interval_cannot_tell_from_zero_says_so(tmp_path):
    before = _ledger(tmp_path, "before", [True, False, True, False])
    after = _ledger(tmp_path, "after", [False, True, True, False], sha="bbbb")
    result = compare.compare(before, after)
    assert result["pass_rate"]["delta"] == 0
    assert "not distinguishable" in result["verdict"]


def test_a_change_of_grader_or_answerer_or_case_set_is_flagged_at_the_top(tmp_path):
    before = _ledger(tmp_path, "before", [True, False, True, False])
    other_grader = agent_mod.AgentRef("antigravity-cli", "Antigravity", "harness", "model-c")
    after = _ledger(tmp_path, "after", [True, True, True, False], grader=other_grader, sha="bbbb")
    result = compare.compare(before, after)
    assert any("different grader" in note for note in result["notes"])
    smaller = _ledger(tmp_path, "smaller", [True, True], sha="cccc")
    assert any("did not ask the same questions" in note for note in compare.compare(before, smaller)["notes"])
    assert compare.compare(before, smaller)["paired"] == 2


def test_two_runs_of_the_same_engine_commit_say_nothing_changed(tmp_path):
    before = _ledger(tmp_path, "before", [True, False, True, False], sha="same")
    after = _ledger(tmp_path, "after", [True, False, True, False], sha="same")
    assert any("same engine commit" in note for note in compare.compare(before, after)["notes"])


def test_the_comparison_report_and_command_are_written_without_calling_an_agent(tmp_path, capsys):
    _ledger(tmp_path, "before", [True, False, False, True])
    _ledger(tmp_path, "after", [True, True, False, True], sha="bbbb")
    code = cli.main(["compare", str(tmp_path / "before"), str(tmp_path / "after")])
    page = (tmp_path / "after" / "report" / "compare.html").read_text(encoding="utf-8")
    assert code == 0 and "Before and after" in page and "improved" in page
    assert "95% interval" in page and "paired by case and repetition" in page
    assert "pass rate" in capsys.readouterr().out
