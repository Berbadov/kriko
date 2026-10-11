"""A follow-up is answered from the web, briefly, and the reply is written as it goes."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient

from app import followup, quicklook
from app.providers import local_agent
from app.providers.local_inference import OpenAICompatSocket
from app.web import state, tasks
from app.web.app import create_app
from app.web.settings import Settings


@pytest.fixture
def settings(tmp_path):
    return Settings(store_path=tmp_path / "knowledge.sqlite",
                    app_state_path=tmp_path / "app.sqlite",
                    analysis_log_path=tmp_path / "analysis.jsonl")


class Progress:
    """The job's channel, recording what the answer wrote into the row."""

    def __init__(self):
        self.partials: list[dict] = []
        self.lines: list[str] = []

    def set(self, *args):
        pass

    def log(self, line):
        self.lines.append(line)

    def check(self):
        pass

    def partial(self, result):
        self.partials.append(dict(result))


# ── the brief, the Sources line and the write throttle ──────────────────────

def test_the_brief_asks_a_question_first_and_for_a_short_sourced_answer():
    brief = followup.web_brief("Is it quiet?", product="Acme X 300", context="Recorded: hum.")
    assert brief.startswith("Product: Acme X 300\nThe reader asks a follow-up question: Is it quiet?")
    assert "Recorded: hum." in brief
    assert f"under {followup.MAX_WORDS} words" in brief
    assert "Do not invent risks" in brief
    assert "'Sources:'" in brief


def test_the_sources_line_comes_off_the_answer_and_names_its_pages():
    assert followup.split("It is quiet.\nSources: https://a.test/x https://b.test/y.") == (
        "It is quiet.", ["https://a.test/x", "https://b.test/y"])
    assert followup.split("No page answered this.") == ("No page answered this.", [])
    # An answer that is only a Sources line keeps its text rather than a blank card.
    assert followup.split("Sources: https://a.test/x") == (
        "Sources: https://a.test/x", ["https://a.test/x"])


def test_the_pages_behind_an_answer_are_the_pages_read_then_the_ones_named():
    class Researcher:
        sources = {"https://www.a.test/1": "text", "https://b.test/2": "text"}

    found = followup.sources_of(Researcher(), [
        "https://b.test/2", "https://c.test/3", "ftp://not-a-page", "https://c.test/3"])
    assert found == [
        {"url": "https://www.a.test/1", "domain": "a.test"},
        {"url": "https://b.test/2", "domain": "b.test"},
        {"url": "https://c.test/3", "domain": "c.test"},
    ]
    assert followup.sources_of(object(), ["https://d.test/4"]) == [
        {"url": "https://d.test/4", "domain": "d.test"}]


def test_a_reply_is_written_as_it_grows_and_not_on_every_piece():
    now = [0.0]
    writes: list[dict] = []
    reply = followup.Reply(writes.append, base={"agent": {"id": "local"}}, clock=lambda: now[0])
    reply.add("Hel")
    reply.add("lo")
    reply.add("")
    assert writes == [{"agent": {"id": "local"}, "answer": "Hel"}]
    now[0] = 1.0
    reply.add(" there.\nSources: https://a.test/x")
    assert writes[-1] == {"agent": {"id": "local"}, "answer": "Hello there."}


def test_the_quick_look_brief_carries_its_product_and_findings_as_a_starting_point():
    brief = quicklook.follow_up(
        "Is it quiet?", "Acme X 300", "the 300 model",
        [{"title": "Hum", "severity": "low", "body": "Hums at night.",
          "sources": [{"domain": "a.test", "url": "https://a.test/1", "quote": "It hums."}]}],
        [])
    assert brief.startswith("Product: Acme X 300\nThe reader asks a follow-up question: Is it quiet?")
    assert "a starting point, not the limit" in brief
    assert "- Hum (low): Hums at night." in brief
    assert "The quick look took the product as: the 300 model" in brief


# ── the local socket writes the reply as it arrives ─────────────────────────

class FakeEngine:
    """A local engine that streams, answers whole, or refuses a field, as a test asks."""

    def __init__(self):
        self.requests: list[tuple[str, dict]] = []
        self.refuse_reasoning = False

    def serve(self):
        engine = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, status, body: bytes, kind: str):
                self.send_response(status)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                engine.requests.append((self.path, body))
                if engine.refuse_reasoning and "reasoning_effort" in body:
                    refusal = json.dumps({"error": {"message": "unknown field"}}).encode()
                    return self._send(400, refusal, "application/json")
                if self.path == "/api/chat":
                    lines = [{"message": {"content": "Hi"}, "done": False},
                             {"message": {"content": " there"}, "done": False},
                             {"done": True, "done_reason": "stop",
                              "prompt_eval_count": 4, "eval_count": 2}]
                    return self._send(200, "".join(json.dumps(one) + "\n" for one in lines).encode(),
                                      "application/x-ndjson")
                if not body.get("stream"):
                    whole = {"choices": [{"message": {"content": "Whole reply."},
                                          "finish_reason": "stop"}],
                             "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}}
                    return self._send(200, json.dumps(whole).encode(), "application/json")
                events = [{"choices": [{"delta": {"content": "Hel"}, "finish_reason": None}]},
                          {"choices": [{"delta": {"content": "lo"}, "finish_reason": None}]},
                          {"choices": [{"delta": {}, "finish_reason": "stop"}]},
                          {"choices": [], "usage": {"prompt_tokens": 3, "completion_tokens": 2,
                                                    "total_tokens": 5}}]
                text = "".join(f"data: {json.dumps(one)}\n\n" for one in events) + "data: [DONE]\n\n"
                return self._send(200, text.encode(), "text/event-stream")

        return Handler


@pytest.fixture
def engine():
    fake = FakeEngine()
    server = ThreadingHTTPServer(("127.0.0.1", 0), fake.serve())
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield fake, f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def test_the_openai_stream_hands_each_piece_over_and_returns_the_whole_reply(engine):
    fake, url = engine
    pieces: list[str] = []
    socket = OpenAICompatSocket(url, "tiny", timeout=5)
    assert socket.stream("Question?", pieces.append) == "Hello"
    assert pieces == ["Hel", "lo"]
    assert socket.tokens_out == 2 and socket.last_finish_reason == "stop"
    assert socket.last_usage_complete is True
    _, body = fake.requests[-1]
    assert body["stream"] is True and body["stream_options"] == {"include_usage": True}


def test_a_native_stream_is_read_when_runtime_options_must_reach_the_server(engine):
    fake, url = engine
    pieces: list[str] = []
    socket = OpenAICompatSocket(url, "tiny", timeout=5, runtime_options={"num_ctx": 4096})
    assert socket.stream("Question?", pieces.append) == "Hi there"
    assert pieces == ["Hi", " there"]
    assert socket.tokens_in == 4 and socket.tokens_out == 2
    path, body = fake.requests[-1]
    assert path == "/api/chat" and body["options"]["num_ctx"] == 4096


def test_an_optional_field_the_server_refuses_is_dropped_and_the_reply_still_streams(engine):
    fake, url = engine
    fake.refuse_reasoning = True
    pieces: list[str] = []
    socket = OpenAICompatSocket(url, "tiny", timeout=5)
    assert socket.stream("Question?", pieces.append) == "Hello"
    assert "reasoning_effort" not in fake.requests[-1][1]
    assert pieces == ["Hel", "lo"]


def test_a_schema_bound_reply_is_whole_and_is_handed_over_once(engine):
    fake, url = engine
    pieces: list[str] = []
    socket = OpenAICompatSocket(url, "tiny", timeout=5, response_json_schema={"type": "object"})
    assert socket.stream("Question?", pieces.append) == "Whole reply."
    assert pieces == ["Whole reply."]
    assert fake.requests[-1][1]["stream"] is False


def test_an_empty_reply_is_named_by_why_it_is_empty():
    socket = OpenAICompatSocket("http://127.0.0.1:1", "tiny")
    assert socket._empty("length").code == "truncated"
    assert socket._empty("stop").code == "empty_reply"


def test_a_socket_that_cannot_stream_still_hands_its_reply_over_once():
    asker = local_agent.LocalAsker(
        plan=lambda prompt: "", complete=lambda prompt: "Whole.", search=None, fetch=None,
        model="m", search_provider="openserp")
    pieces: list[str] = []
    assert asker._complete.stream("Question?", pieces.append) == "Whole."
    assert pieces == ["Whole."]


# ── the two follow-ups, end to end on a local plane ─────────────────────────

def test_a_quick_look_follow_up_searches_the_web_and_writes_a_short_answer(settings, monkeypatch):
    conn = state.connect(settings.app_state_path)
    quick = state.create_job(conn, "quick_look", {"product": "Acme X 300"})
    state.finish_job(conn, quick, state.SUCCEEDED, result={
        "assumed": "the 300 model",
        "risks": [{"title": "Hum", "body": "Hums at night.", "severity": "low",
                   "sources": [{"domain": "a.test", "url": "https://a.test/1",
                                "quote": "It hums."}]}],
        "specs": []})
    conn.close()

    class Researcher:
        sources = {"https://b.test/review": "Reviews say it is quiet."}

        def ask(self, prompt):
            self.prompt = prompt
            for piece in ["It is ", "quiet.", "\nSources: https://b.test/review"]:
                self.on_text(piece)
            return "It is quiet.\nSources: https://b.test/review"

    researcher = Researcher()
    monkeypatch.setattr(tasks, "_use_local_ask", lambda *a: True)
    monkeypatch.setattr(tasks, "_local_asker", lambda *a: researcher)
    progress = Progress()
    result = tasks.quick_ask(settings, {"quick_job_id": quick, "q": "Is it quiet?",
                                        "max_tokens": 600}, progress)
    assert result["answer"] == "It is quiet."
    assert result["sources"] == [{"url": "https://b.test/review", "domain": "b.test"}]
    assert result["product"] == "Acme X 300" and result["q"] == "Is it quiet?"
    for text in ("Acme X 300", "Is it quiet?", "- Hum (low): Hums at night.", "Do not invent risks"):
        assert text in researcher.prompt
    assert progress.partials, "the reply must be written while it is being given"
    assert all(result["answer"].startswith(one["answer"]) for one in progress.partials)


@pytest.fixture
def check(settings):
    conn = state.connect(settings.app_state_path)
    lookup_id = state.record_lookup(conn, source="extension", label="Example product",
                                    request={}, response={"claims": [{
                                        "title": "Seal wear", "body": "Leaks after heavy use.",
                                        "severity": "medium", "advice": "Ask for service records.",
                                        "sources": [{"url": "https://example.test/source",
                                                     "quote": "The seal can leak."}],
                                    }], "context": {"hours": 100},
                                        "context_units": {"hours": "h"}})
    conn.close()
    return lookup_id


def test_a_listing_follow_up_keeps_its_agent_while_it_streams_and_names_its_sources(
        settings, check, monkeypatch):
    class Researcher:
        model = "small-local-model"

        def ask(self, prompt):
            self.prompt = prompt
            self.on_text("Ask for a service record.")
            return "Ask for a service record.\nSources: https://example.test/source"

    researcher = Researcher()
    monkeypatch.setattr(tasks, "_use_local_ask", lambda *a: True)
    monkeypatch.setattr(tasks, "_local_asker", lambda *a: researcher)
    progress = Progress()
    result = tasks.lookup_ask(settings, {"lookup_id": check,
                                        "question": "What should I check?"}, progress)
    assert result["answer"] == "Ask for a service record."
    assert result["sources"] == [{"url": "https://example.test/source", "domain": "example.test"}]
    assert result["agent"] == {"id": "local", "label": "Local model", "model": "small-local-model"}
    assert "Seal wear" in researcher.prompt and "Do not invent risks" in researcher.prompt
    assert progress.partials and all("agent" in one for one in progress.partials)
    assert progress.partials[-1]["answer"] == "Ask for a service record."


def test_the_panel_reads_a_follow_up_while_it_is_being_written(settings):
    conn = state.connect(settings.app_state_path)
    quick = state.create_job(conn, "quick_look", {"product": "Acme"})
    state.finish_job(conn, quick, state.SUCCEEDED, result={"risks": [], "specs": []})
    asking = state.create_job(conn, "quick_ask", {"quick_job_id": quick, "q": "Is it quiet?"})
    state.start_job(conn, asking)
    state.save_partial(conn, asking, {"answer": "It is qui"})
    conn.close()
    asks = TestClient(create_app(settings)).get(
        f"/api/extension/quick-look/{quick}/asks").json()["asks"]
    assert asks == [{"job_id": asking, "q": "Is it quiet?", "answer": "It is qui",
                     "sources": [], "state": "running", "done": False, "message": ""}]
