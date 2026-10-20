"""A turn says what it spent and how full the model's window is, or that it cannot.

*"token count plus context window bars."* Each number is a measurement a plane
reported, the window comes from the model catalogue and never from a constant
per model, and where a plane reports nothing the answer is "not reported"
rather than a guess made from characters.
"""

import json

import pytest
from fastapi.testclient import TestClient

from app import chat, evidence, exactfind, modelcatalogue
from app.turnusage import TurnUsage, history_trim, usage_of, window_for
from app.web import state, tasks
from app.web.app import create_app
from app.web.jobs import Progress
from app.web.settings import Settings

# ── adding up the calls ──────────────────────────────────────────────────


def test_a_split_is_summed_and_the_biggest_prompt_is_the_context_used():
    meter = TurnUsage()
    meter.record({"usd": 0.01, "tokens_in": 300, "tokens_out": 20})
    meter.record({"usd": 0.02, "tokens_in": 5000, "tokens_out": 400})
    meter.record({"usd": 0.0, "tokens_in": 800, "tokens_out": 60})
    snapshot = meter.snapshot()
    assert (snapshot["tokens_in"], snapshot["tokens_out"], snapshot["tokens"]) == (6100, 480, 6580)
    assert snapshot["usage"]["peak_in"] == 5000
    assert [one["tokens_in"] for one in snapshot["usage"]["per_call"]] == [300, 5000, 800]


def test_one_call_without_a_split_withholds_the_split_but_keeps_what_is_known():
    meter = TurnUsage()
    meter.record({"usd": 0.01, "tokens_in": 300, "tokens_out": 20})
    meter.record({"usd": 0.01, "tokens": 900})  # a plane that reports a total only
    snapshot = meter.snapshot()
    assert snapshot["tokens_in"] is None and snapshot["tokens_out"] is None
    assert snapshot["tokens"] == 1220
    assert snapshot["usage"]["measured_tokens"] == 1220
    assert snapshot["usage"]["peak_in"] == 300, "a measured prompt is still a measurement"


def test_a_plane_that_reports_nothing_is_not_reported_not_zero():
    meter = TurnUsage()
    meter.record({"usd": None, "tokens": None})
    snapshot = meter.snapshot()
    assert snapshot["tokens"] is None and snapshot["tokens_in"] is None
    context = meter.context("claude-sonnet-5")
    assert context["state"] == "not_reported"
    assert context["used"] is None and context["fill"] is None
    assert TurnUsage().context("claude-sonnet-5")["state"] == "pending"


def test_a_boolean_is_not_a_token_count():
    meter = TurnUsage()
    meter.record({"tokens_in": True, "tokens_out": True, "tokens": True})
    assert meter.snapshot()["tokens"] is None


def test_the_bar_fills_from_the_measured_prompt_over_the_catalogue_window():
    meter = TurnUsage()
    meter.record({"tokens_in": 100_000, "tokens_out": 50})
    context = meter.context("claude-haiku-4-5")
    assert (context["window"], context["window_source"]) == (200_000, "catalogue")
    assert context["used"] == 100_000 and context["fill"] == 0.5 and context["state"] == "measured"


# ── where the window comes from ──────────────────────────────────────────


def test_a_window_is_the_catalogue_row_and_a_readers_edit_wins(tmp_path):
    shipped = modelcatalogue.load()["claude-haiku-4-5"]["context"]
    assert window_for("claude-haiku-4-5") == (shipped, "catalogue")
    (tmp_path / "models.toml").write_text(
        '[anthropic]\n"claude-haiku-4-5" = { context = 64000, usd_in = 1, usd_out = 5 }\n',
        encoding="utf-8")
    assert window_for("claude-haiku-4-5", home=tmp_path) == (64000, "catalogue")


def test_a_model_the_catalogue_does_not_know_has_no_window_unless_it_is_local():
    assert window_for("some-model-released-tomorrow") == (None, "")
    assert window_for("") == (None, "")
    assert window_for("some-model-released-tomorrow", local_window=8192) == (8192, "setting")
    # The catalogue still wins over a local setting when it has a row.
    assert window_for("claude-haiku-4-5", local_window=8192)[1] == "catalogue"


def test_the_interface_holds_no_window_of_its_own():
    """A per-model number in the screens would drift from `models.toml`."""
    from pathlib import Path

    ui = Path(__file__).resolve().parents[3] / "kriko-ui" / "src"
    shipped = {str(row["context"]) for row in modelcatalogue.load().values() if row.get("context")}
    for path in ui.rglob("*.ts*"):
        text = path.read_text(encoding="utf-8")
        assert not any(number in text for number in shipped), path


# ── what a plane says ────────────────────────────────────────────────────


def test_usage_is_read_from_the_researcher_as_the_plane_reported_it():
    class Api:
        spent, tokens_used, tokens_in, tokens_out = 0.02, 700, 600, 100

    assert usage_of(Api()) == {"usd": 0.02, "tokens": 700, "tokens_in": 600, "tokens_out": 100}


def test_a_harness_cli_that_counts_its_context_gives_a_split():
    class Cli:
        cost_usd = 0.3
        tokens_used = 9000
        telemetry = {"run": {"context": {"input_tokens": 100, "cache_creation_tokens": 400,
                                         "cache_read_tokens": 8000, "output_tokens": 500}}}

    got = usage_of(Cli())
    assert (got["tokens_in"], got["tokens_out"], got["tokens"]) == (8500, 500, 9000)


def test_a_harness_cli_that_counts_nothing_stays_unsplit():
    class Cli:
        cost_usd = None
        tokens_used = None
        telemetry = {"run": {"context": None}}

    got = usage_of(Cli())
    assert got["tokens_in"] is None and got["tokens_out"] is None


# ── the trimmed history ──────────────────────────────────────────────────


def say(role, text):
    return {"role": role, "text": text}


def test_a_short_chat_is_sent_whole():
    history = [say("reader", "a"), say("agent", "b")]
    assert history_trim(history) == {"messages": 2, "sent": 2, "trimmed": False,
                                     "dropped_replies": 0, "omitted_requests": 0}


def test_older_replies_are_dropped_after_the_last_eight_messages():
    history = [say("reader" if i % 2 == 0 else "agent", f"m{i}") for i in range(14)]
    trimmed = history_trim(history)
    assert trimmed["trimmed"] and trimmed["dropped_replies"] == 3  # of the six older, the agent's
    assert "omitted for the context limit" not in chat._history_text(history)


def test_it_agrees_with_what_chat_actually_omits():
    """`history_trim` repeats `chat._history_text`'s arithmetic, so the two are
    compared on the words the agent is told."""
    long = "x" * chat.HISTORY_CHARS
    history = [say("reader", long) for _ in range(40)]
    seen = history_trim(history)
    told = chat._history_text(history)
    assert seen["omitted_requests"] > 0
    assert f"{seen['omitted_requests']} older request(s) omitted for the context limit" in told
    fits = [say("reader", "short") for _ in range(40)]
    assert history_trim(fits)["omitted_requests"] == 0
    assert "omitted for the context limit" not in chat._history_text(fits)


# ── the chat job, end to end ─────────────────────────────────────────────


@pytest.fixture
def paths(tmp_path):
    return Settings(store_path=tmp_path / "knowledge.sqlite",
                    app_state_path=tmp_path / "app.sqlite",
                    analysis_log_path=tmp_path / "analysis.jsonl")


class Counting:
    """A local model that counts like the real socket: cumulatively."""

    model = "test-local"

    def __init__(self, split=True):
        self.split = split
        self.tokens_used = 0
        self.tokens_in = 0 if split else None
        self.tokens_out = 0 if split else None
        self.usage_complete = True

    def __call__(self, prompt):
        small = "Produce conversation metadata" in prompt
        tin, tout = (50, 10) if small else (700 + len(prompt) // 100, 90)
        self.tokens_used += tin + tout
        if self.split:
            self.tokens_in += tin
            self.tokens_out += tout
        return '{"title":"Charging","followups":[]}' if small else "Charging stores energy in a battery."


def ask(paths, monkeypatch, model, text="Explain charging", history=()):
    monkeypatch.setattr(tasks, "_use_local_ask", lambda *a: True)
    monkeypatch.setattr(tasks, "_local_structured_completer", lambda *a: model)
    conn = state.connect(paths.app_state_path)
    try:
        thread = state.create_chat_thread(conn)
        for role, said in history:
            state.add_chat_message(conn, thread["thread_id"], role=role, text=said)
        reader = state.add_chat_message(conn, thread["thread_id"], role="reader", text=text)
        job = state.create_job(conn, "chat_ask", {})
        result = tasks.chat_ask(paths, {"thread_id": thread["thread_id"],
                                        "message_id": reader["message_id"], "text": text,
                                        "backend": "local"}, Progress(job, conn))
        return result, thread["thread_id"], state.partial_of(conn, job)
    finally:
        conn.close()


def test_a_local_turn_reports_its_split_and_how_full_the_window_is(paths, monkeypatch):
    result, _thread, _partial = ask(paths, monkeypatch, Counting())
    assert result["tokens_in"] is not None and result["tokens_out"] is not None
    assert result["tokens"] == result["tokens_in"] + result["tokens_out"]
    context = result["context"]
    assert context["state"] == "measured" and context["used"] == result["usage"]["peak_in"]
    # The window is what the local model was asked to hold, labelled as a setting.
    assert (context["window"], context["window_source"]) == (4096, "setting")
    assert context["fill"] == pytest.approx(context["used"] / 4096, abs=1e-3)
    assert context["history"]["trimmed"] is False


def test_a_plane_that_counts_only_a_total_says_not_reported(paths, monkeypatch):
    result, _thread, _partial = ask(paths, monkeypatch, Counting(split=False))
    assert result["tokens_in"] is None and result["tokens"] > 0
    assert result["context"]["state"] == "not_reported" and result["context"]["fill"] is None


def test_a_long_chat_says_its_history_was_trimmed(paths, monkeypatch):
    earlier = [("reader" if i % 2 == 0 else "agent", f"message {i}") for i in range(14)]
    result, _thread, _partial = ask(paths, monkeypatch, Counting(), history=earlier)
    assert result["context"]["history"]["trimmed"] is True


def test_a_reopened_chat_carries_each_turns_usage_without_a_second_copy(paths, monkeypatch):
    result, thread_id, _partial = ask(paths, monkeypatch, Counting())
    conn = state.connect(paths.app_state_path)
    try:
        # The answer message points at the job whose result holds the numbers.
        state.add_chat_message(conn, thread_id, role="agent", text="later")
        columns = {row[1] for row in conn.execute("PRAGMA table_info(chat_messages)")}
    finally:
        conn.close()
    assert not any("usage" in column or "token" in column for column in columns)
    items = TestClient(create_app(paths)).get(f"/api/chat/threads/{thread_id}/messages").json()["items"]
    answered = next(one for one in items if one["role"] == "agent" and one.get("usage"))
    assert answered["usage"]["tokens_in"] == result["tokens_in"]
    assert answered["usage"]["context"]["window"] == 4096
    assert set(answered["usage"]) <= {"spent_usd", "tokens", "tokens_in", "tokens_out", "usage", "context"}


def test_a_job_that_is_polled_carries_the_usage_while_it_runs(paths, monkeypatch):
    seen = []
    original = Progress.partial

    def spy(self, snapshot):
        seen.append(snapshot)
        return original(self, snapshot)

    monkeypatch.setattr(Progress, "partial", spy)
    ask(paths, monkeypatch, Counting())
    with_usage = [one for one in seen if "context" in one]
    assert with_usage, "the bars are drawn from the snapshots the screen already polls"
    assert with_usage[-1]["context"]["state"] == "measured"


# ── the kind of site behind a page, for the right-hand column ────────────


def test_each_page_read_carries_the_kind_of_site_the_engine_classifies(paths, monkeypatch):
    retailer = next(domain for domain, tier in exactfind.registry()["by_domain"].items()
                    if tier == "retailer")
    url = f"https://www.{retailer}/product/1"

    class Reader:
        model = "test-local"
        tokens_used = tokens_in = tokens_out = 0
        usage_complete = True

        def __call__(self, prompt):
            return "The page lists a CADR of 300."

    monkeypatch.setattr(tasks, "_chat_web_accessors",
                        lambda *a: (lambda query, limit: [{"title": "Shop", "url": url, "site": retailer}],
                                    lambda address: "CADR 300 m3/h"))
    result, thread_id, _partial = ask(paths, monkeypatch, Reader(),
                                      text="Find a quiet air purifier for a small bedroom")
    read = next(row for row in result["activity"] if row.get("kind") == "read")
    assert read["trust"]["tier"] == "retailer" and read["trust"]["domain"] == retailer
    stored = TestClient(create_app(paths)).get(f"/api/chat/threads/{thread_id}/messages").json()["items"]
    again = next(row for one in stored for row in one["activity"] if row.get("kind") == "read")
    assert again["trust"] == read["trust"], "a saved chat reopens with the same tier"


def test_tiering_changes_nothing_but_adds_trust_to_reads():
    rows = [{"id": "a", "kind": "search", "query": "q"},
            {"id": "b", "kind": "read", "url": "https://forum.example.org/t/1", "state": "done"},
            {"id": "c", "kind": "read", "url": "", "state": "failed"}]
    out = evidence.tier_pages(rows)
    assert out[0] == rows[0] and out[2] == rows[2]
    assert out[1]["trust"]["tier"] and {k: v for k, v in out[1].items() if k != "trust"} == rows[1]
    assert json.dumps(out)  # plain data
