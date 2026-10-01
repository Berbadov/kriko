"""The local machine plane, finished (B171) and first (B172).

The reader's words: "Local agent: finish the work it needs, then implement it"
and "Add our new local machine and make it the prioritised one". Every server
here is a loopback stub in a thread: a model server (`/v1/models`,
`/v1/chat/completions`), a self-hosted search (`/mega/search`) and Exa's hosted
MCP search. No model is downloaded, no real server is started and nothing
leaves 127.0.0.1.
"""

import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app import localplane, prefs
from app.providers import exa_mcp, local_discovery, local_inference
from app.providers.local_discovery import discover as real_discover
from app.providers.local_discovery import search_answers as real_search_answers
from app.web import state, tasks


class Stub:
    """One loopback server that plays every local service, scripted per test."""

    def __init__(self):
        self.models: list | None = []
        self.models_path = "/v1/models"
        self.chat: list = []          # (status, body-dict) popped per call
        self.chat_seen: list = []
        self.serp = {"results": []}
        self.mcp_text = ""
        self.mcp_agents: list = []
        self.delay = 0.0
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def _send(self, status, body, kind="application/json"):
                data = body if isinstance(body, bytes) else json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                path = self.path.split("?")[0]
                if path == stub.models_path and stub.models is not None:
                    return self._send(200, {"object": "list", "data": [
                        {"id": name} for name in stub.models]})
                if path == "/mega/search":
                    return self._send(200, stub.serp)
                if path == "/":
                    return self._send(200, b"up", "text/plain")
                self._send(404, {"error": "not found"})

            def do_POST(self):
                size = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(size) or b"{}")
                if self.path == "/v1/chat/completions":
                    stub.chat_seen.append(body)
                    time.sleep(stub.delay)
                    status, reply = stub.chat.pop(0) if stub.chat else (
                        200, {"choices": [{"message": {"content": "[]"}}]})
                    return self._send(status, reply)
                if self.path == "/mcp":
                    stub.mcp_agents.append(self.headers.get("User-Agent"))
                    method = body.get("method")
                    if method == "initialize":
                        payload = {"result": {"protocolVersion": "x"}}
                    else:
                        payload = {"result": {"content": [
                            {"type": "text", "text": stub.mcp_text}]}}
                    data = ("event: message\ndata: " + json.dumps(payload)
                            + "\n\n").encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("mcp-session-id", "s1")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                self._send(404, {})

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def completion(text: str, tokens=(3, 4)) -> tuple:
    return 200, {"choices": [{"message": {"content": text}}],
                 "usage": {"prompt_tokens": tokens[0],
                           "completion_tokens": tokens[1],
                           "total_tokens": sum(tokens)}}


@pytest.fixture
def stub():
    one = Stub()
    yield one
    one.close()


@pytest.fixture
def machine(monkeypatch):
    """The real discovery, undoing the suite-wide "nothing answers" guard."""
    monkeypatch.setattr(local_discovery, "discover", real_discover)
    monkeypatch.setattr(local_discovery, "search_answers", real_search_answers)


def dead_url() -> str:
    with socket.socket() as one:
        one.bind(("127.0.0.1", 0))
        return f"http://127.0.0.1:{one.getsockname()[1]}"


# ── discovery ──────────────────────────────────────────────────────────────


def test_a_server_reports_its_own_models(stub):
    stub.models = ["qwen3-4b", "llama3.2"]
    assert local_discovery.probe(stub.url) == {
        "url": stub.url, "up": True, "models": ["qwen3-4b", "llama3.2"]}


def test_an_address_with_v1_on_the_end_is_the_same_server(stub):
    stub.models = ["m"]
    assert local_discovery.probe(stub.url + "/v1/")["models"] == ["m"]


def test_models_are_found_at_the_root_path_too(stub):
    stub.models_path = "/models"
    stub.models = ["rooted"]
    assert local_discovery.probe(stub.url)["models"] == ["rooted"]


def test_a_reachable_server_with_no_model_is_up_with_an_empty_list(stub):
    stub.models = []
    assert local_discovery.probe(stub.url) == {
        "url": stub.url, "up": True, "models": []}


def test_a_server_that_answers_no_list_is_up_with_no_models(stub):
    stub.models = None  # 404 on both paths
    row = local_discovery.probe(stub.url)
    assert row["up"] is True and row["models"] == []


def test_nothing_listening_is_down():
    assert local_discovery.probe(dead_url())["up"] is False


def test_the_configured_address_is_probed_first_and_the_defaults_follow(machine, stub):
    stub.models = ["m"]
    rows = local_discovery.discover(stub.url)
    assert rows[0]["url"] == stub.url and rows[0]["name"] == "configured"
    assert {row["name"] for row in rows[1:]} == {n for n, _ in local_discovery.CANDIDATES}


# ── readiness ──────────────────────────────────────────────────────────────


def test_ready_with_the_servers_own_model_list(machine, stub):
    stub.models = ["nomic-embed-text", "qwen3-4b"]
    plan = localplane.resolve(url=stub.url, search_url=dead_url())
    assert plan["ready"] is True
    assert plan["models"] == ["nomic-embed-text", "qwen3-4b"]
    # An embedding model cannot answer a prompt, so it is not the default.
    assert plan["model"] == "qwen3-4b"
    assert plan["url"] == stub.url
    assert plan["search_kind"] == "exa"
    assert "Exa's free hosted search" in plan["line"]
    assert plan["model"] in plan["line"]


def test_a_server_up_with_no_model_says_so_and_what_to_do(machine, stub):
    stub.models = []
    plan = localplane.resolve(url=stub.url)
    assert plan["ready"] is False
    assert "no model is downloaded" in plan["reason"]
    assert "Download one" in plan["reason"]
    assert plan["line"] == plan["reason"]


def test_a_down_server_says_the_address_to_fix(machine):
    down = dead_url()
    plan = localplane.resolve(url=down)
    assert plan["ready"] is False
    assert down in plan["reason"]


def test_no_server_anywhere_names_the_places_it_looked(machine, monkeypatch):
    monkeypatch.setattr(local_discovery, "CANDIDATES", (("Nothing", dead_url()),))
    plan = localplane.resolve()
    assert plan["ready"] is False
    assert "Nothing" in plan["reason"] and "Start" in plan["reason"]


def test_a_chosen_model_the_server_lacks_is_not_used_and_the_list_is_shown(machine, stub):
    stub.models = ["a", "b"]
    plan = localplane.resolve(url=stub.url, model="gpt-4o-mini")
    assert plan["ready"] is False
    assert "gpt-4o-mini" in plan["reason"] and "a, b" in plan["reason"]


def test_a_chosen_model_the_server_has_is_used(machine, stub):
    stub.models = ["a", "b"]
    assert localplane.resolve(url=stub.url, model="b")["model"] == "b"


def test_openserp_is_used_when_it_answers(machine, stub):
    stub.models = ["m"]
    plan = localplane.resolve(url=stub.url, search_url=stub.url)
    assert plan["search_kind"] == "openserp"
    assert "on this machine" in plan["line"]


def test_the_settings_are_read_from_the_app_database(machine, stub, tmp_path):
    stub.models = ["a", "b"]
    path = tmp_path / "app.sqlite"
    conn = state.connect(path)
    prefs.write(conn, {prefs.LOCAL_URL: stub.url, prefs.LOCAL_MODEL: "b",
                       prefs.LOCAL_TIMEOUT: "900"})
    conn.close()
    plan = localplane.resolve(path)
    assert (plan["url"], plan["model"], plan["timeout"]) == (stub.url, "b", 900.0)


# ── the wire ───────────────────────────────────────────────────────────────


def test_the_socket_posts_to_v1_with_the_real_model_name_and_a_schema(stub):
    stub.chat = [completion("[]")]
    socket_ = local_inference.OpenAICompatSocket(
        stub.url, "qwen3-4b", response_json_schema=local_inference.FINDINGS_SCHEMA)
    assert socket_("prompt") == "[]"
    body = stub.chat_seen[0]
    assert body["model"] == "qwen3-4b"
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["schema"]["type"] == "array"
    assert (socket_.tokens_in, socket_.tokens_out, socket_.tokens_used) == (3, 4, 7)


def test_a_server_that_refuses_the_schema_is_asked_again_plainly(stub):
    stub.chat = [(400, {"error": {"message": "no response_format"}}),
                 completion("[]")]
    socket_ = local_inference.OpenAICompatSocket(
        stub.url, "m", response_json_schema=local_inference.FINDINGS_SCHEMA)
    assert socket_("p") == "[]"
    assert "response_format" in stub.chat_seen[0]
    assert "response_format" not in stub.chat_seen[1]


def test_a_missing_model_names_the_address_and_the_model(stub):
    stub.chat = [(404, {"error": {"message": "model 'local' not found"}})]
    with pytest.raises(local_inference.LocalInferenceError) as said:
        local_inference.OpenAICompatSocket(stub.url, "local")("p")
    text = str(said.value)
    assert stub.url in text and "'local'" in text and "no model named" in text


def test_a_server_that_is_down_is_reported_as_down():
    down = dead_url()
    with pytest.raises(local_inference.LocalInferenceError) as said:
        local_inference.OpenAICompatSocket(down, "m")("p")
    assert down in str(said.value) and "server down" in str(said.value)


def test_a_slow_server_is_reported_with_the_timeout(stub):
    stub.delay = 1.0
    with pytest.raises(local_inference.LocalInferenceError) as said:
        local_inference.OpenAICompatSocket(stub.url, "m", timeout=0.2)("p")
    assert "0.2 s" in str(said.value) and "timeout" in str(said.value)


def test_an_empty_completion_is_a_failure_not_silence(stub):
    stub.chat = [completion("   ")]
    with pytest.raises(local_inference.LocalInferenceError) as said:
        local_inference.OpenAICompatSocket(stub.url, "m")("p")
    assert "empty reply" in str(said.value)


# ── the plane says what failed ─────────────────────────────────────────────


def _task():
    from kriko.research.base import ResearchTask

    return ResearchTask(
        subject_id="s1", subject_label="Widget MK2", subject_kind="widget",
        pack_id="p1", queries=["{label} problems"], search_names=("Widget MK2",))


def _document(text="The pump fails early on this model."):
    from kriko.research.base import Document

    return Document(url="https://a.test/x", text=text, title="t",
                    published_at="", site_or_channel="a.test")


def test_a_failed_completion_reaches_the_job_log_with_the_reason():
    from kriko.research.local import LocalPlane

    def broken(prompt):
        raise local_inference.LocalInferenceError(
            "http://127.0.0.1:11434 has no model named 'local'")

    plane = LocalPlane(search=None, fetch=None, complete=broken)
    lines = []
    plane.on_action = lines.append
    assert plane.extract(_task(), _document()) == []
    assert any("127.0.0.1:11434" in line and "no model named" in line
               for line in lines)
    assert "no model named" in plane.note


def test_a_second_failure_in_a_row_stops_the_run_with_the_reason():
    from kriko.research.local import LocalPlane

    def broken(prompt):
        raise local_inference.LocalInferenceError("server down")

    plane = LocalPlane(search=None, fetch=None, complete=broken)
    plane.extract(_task(), _document())
    with pytest.raises(local_inference.LocalInferenceError):
        plane.extract(_task(), _document())


def test_a_good_reply_resets_the_count():
    from kriko.research.local import LocalPlane

    replies = iter(["fail", "[]", "fail", "[]"])

    def flaky(prompt):
        one = next(replies)
        if one == "fail":
            raise RuntimeError("blip")
        return one

    plane = LocalPlane(search=None, fetch=None, complete=flaky)
    for _ in range(4):
        plane.extract(_task(), _document())


# ── the hosted search fallback ─────────────────────────────────────────────

EXA_TEXT = (
    "Title: First page\nURL: https://one.test/a\nPublished: 2020\nHighlights:\n"
    "words\n\nTitle: Second page\nURL: https://two.test/b\nAuthor: N/A\n")


def test_exa_search_parses_entries_and_names_itself_honestly(stub, monkeypatch):
    monkeypatch.setattr(exa_mcp, "ENDPOINT", stub.url + "/mcp")
    stub.mcp_text = EXA_TEXT
    search = exa_mcp.searcher()
    assert search("widget problems", 5) == [
        {"url": "https://one.test/a", "title": "First page", "site": "one.test"},
        {"url": "https://two.test/b", "title": "Second page", "site": "two.test"},
    ]
    assert stub.mcp_agents and all(
        agent.startswith("kriko/") for agent in stub.mcp_agents)


def test_exa_search_honours_the_limit(stub, monkeypatch):
    monkeypatch.setattr(exa_mcp, "ENDPOINT", stub.url + "/mcp")
    stub.mcp_text = EXA_TEXT
    assert len(exa_mcp.searcher()("q", 1)) == 1


def test_exa_search_failure_is_a_named_search_error():
    from kriko.research.politeness import LocalSearchError

    with pytest.raises(LocalSearchError):
        exa_mcp.searcher(dead_url() + "/mcp")("q", 3)


# ── first plane (B172) ─────────────────────────────────────────────────────


@pytest.fixture
def ready(monkeypatch, stub):
    """A machine with a model server and search, found the way the real
    discovery finds them: through the configured address."""
    stub.models = ["qwen3-4b"]
    monkeypatch.setattr(local_discovery, "discover", real_discover)
    monkeypatch.setattr(local_discovery, "search_answers", real_search_answers)
    return stub


def _path(tmp_path, **values):
    path = tmp_path / "app.sqlite"
    conn = state.connect(path)
    prefs.write(conn, values)
    conn.close()
    return path


def test_with_the_local_plane_ready_an_unnamed_run_uses_it_and_says_why(ready, tmp_path):
    path = _path(tmp_path, **{prefs.LOCAL_URL: ready.url})
    plane, why = tasks.default_plane(path)
    assert plane == "local" == tasks.default_backend(path)
    assert "first when it is ready" in why and "qwen3-4b" in why


def test_an_agent_the_reader_picked_keeps_the_run(ready, tmp_path):
    path = _path(tmp_path, **{prefs.LOCAL_URL: ready.url,
                              prefs.HARNESS: "claude-code"})
    plane, why = tasks.default_plane(path)
    assert plane != "local"
    assert "picked in Settings" in why


def test_not_ready_falls_back_and_says_why(machine, tmp_path):
    path = _path(tmp_path, **{prefs.LOCAL_URL: dead_url()})
    plane, why = tasks.default_plane(path)
    assert plane in {"harness", "agent"}
    assert "the local plane is not ready" in why


def test_a_run_log_names_the_plane_and_the_reason(ready, tmp_path, monkeypatch):
    path = _path(tmp_path, **{prefs.LOCAL_URL: ready.url})
    settings = type("S", (), {"store_path": tmp_path / "k.sqlite",
                              "app_state_path": path})()

    class Plane:
        name = "local"
        cost_basis = "self_hosted"

        def brief(self, task):
            return "brief"

        def gather(self, task):
            return []

    monkeypatch.setattr(tasks, "plan_task", lambda *a, **k: _task())
    monkeypatch.setattr(tasks, "_subject_pack", lambda conn, subject_id: "p1")
    monkeypatch.setattr(tasks, "_researcher", lambda params: Plane())
    progress = _Progress()

    tasks.research(settings, {"subject_id": "s1"}, progress)

    assert any(line.startswith("plane: local. The local plane is first when it is ready")
               for line in progress.lines)

    progress = _Progress()
    tasks.research(settings, {"subject_id": "s1", "backend": "local"}, progress)
    assert "plane: local. Named for this run." in progress.lines


def test_the_planes_card_lists_local_first_while_ready(ready, tmp_path):
    from fastapi.testclient import TestClient

    from app.web.app import create_app
    from app.web.settings import Settings

    path = _path(tmp_path, **{prefs.LOCAL_URL: ready.url})
    client = TestClient(create_app(Settings(
        store_path=tmp_path / "k.sqlite", app_state_path=path,
        analysis_log_path=tmp_path / "a.jsonl")))
    body = client.get("/api/research-planes").json()
    assert body["planes"][0]["id"] == "local" and body["default"] == "local"
    row = body["planes"][0]
    assert row["ready"] is True and row["models"] == ["qwen3-4b"]
    assert client.get("/api/local-plane").json()["model"] == "qwen3-4b"
    door = client.get("/api/extension/research-plane").json()
    assert (door["backend"], door["cost_basis"], door["budget_usd"]) == (
        "local", "self_hosted", 0.0)
    assert "first when it is ready" in door["why"]


def test_the_empty_run_sentence_exists_for_the_local_plane():
    assert "local" in tasks.EMPTY_RUN
    assert {"agent", "harness", "api", "local"} <= set(tasks.EMPTY_RUN)


# ── a quick look with no CLI and no key (B171 done-when) ───────────────────


PAGE = ("Owners report the timing chain stretches early on the 1.5 dCi. "
        "Several garages replaced it before 90000 miles.")


class _Progress:
    job_id = "j"

    def __init__(self):
        self.lines = []

    def log(self, line):
        self.lines.append(line)

    def set(self, *args, **kwargs):
        pass

    def check(self):
        pass

    def replies(self):
        return []

    def partial(self, *args, **kwargs):
        pass


def test_a_quick_look_runs_on_the_local_model_with_grounded_quotes(
        ready, tmp_path, monkeypatch):
    from app.providers import fetch

    monkeypatch.setattr(exa_mcp, "ENDPOINT", ready.url + "/mcp")
    ready.mcp_text = "Title: Forum\nURL: https://forum.test/t/1\n"
    monkeypatch.setattr(fetch, "reader", lambda *a, **k: (
        lambda url: PAGE if url == "https://forum.test/t/1" else ""))
    risks = {"assumed": "the 1.5 dCi", "category": "", "pack": "", "risks": [
        {"title": "Timing chain stretches early", "url": "https://forum.test/t/1",
         "quote": "the timing chain stretches early on the 1.5 dCi",
         "why": "Owners report it.", "check": "Ask for the chain invoice.",
         "severity": "high"},
        {"title": "Invented fault", "url": "https://forum.test/t/1",
         "quote": "this sentence is on no page", "why": "x", "check": "y",
         "severity": "low"},
    ]}
    ready.chat = [completion('["renault 1.5 dci timing chain"]'),
                  completion(json.dumps(risks))]
    path = _path(tmp_path, **{prefs.LOCAL_URL: ready.url})
    settings = type("S", (), {"store_path": tmp_path / "k.sqlite",
                              "app_state_path": path})()
    progress = _Progress()

    result = tasks.quick_look(
        settings, {"product": "Renault Clio 1.5 dCi", "backend": "local"}, progress)

    assert [one["title"] for one in result["risks"]] == ["Timing chain stretches early"]
    assert result["risks"][0]["sources"][0]["grounded"] is True
    assert result["dropped"] == 1
    assert result["cost_basis"] == "self_hosted" and result["model"] == "qwen3-4b"
    assert any("local plane: Ready" in line for line in progress.lines)
    assert ready.chat_seen[0]["model"] == "qwen3-4b"
    assert "Pages you fetched" in ready.chat_seen[1]["messages"][0]["content"]


def test_with_no_agent_and_a_ready_model_the_quick_look_picks_local_by_itself(
        ready, tmp_path, monkeypatch):
    path = _path(tmp_path, **{prefs.LOCAL_URL: ready.url})
    settings = type("S", (), {"store_path": tmp_path / "k.sqlite",
                              "app_state_path": path})()
    monkeypatch.setattr("app.providers.agent_ready", lambda *a, **k: False)
    assert tasks._use_local_ask(settings, {"harness": ""}) is True


def test_a_quick_look_with_nothing_to_search_fails_loudly(ready, tmp_path, monkeypatch):
    from app.providers import fetch

    monkeypatch.setattr(exa_mcp, "ENDPOINT", ready.url + "/mcp")
    ready.mcp_text = ""
    monkeypatch.setattr(fetch, "reader", lambda *a, **k: (lambda url: ""))
    ready.chat = [completion('["q"]')]
    path = _path(tmp_path, **{prefs.LOCAL_URL: ready.url})
    settings = type("S", (), {"store_path": tmp_path / "k.sqlite",
                              "app_state_path": path})()
    with pytest.raises(local_inference.LocalInferenceError) as said:
        tasks.quick_look(settings, {"product": "X", "backend": "local"}, _Progress())
    assert "no page could be read" in str(said.value)


def test_naming_the_local_plane_while_it_is_not_ready_fails_with_the_reason(
        machine, tmp_path):
    path = _path(tmp_path, **{prefs.LOCAL_URL: dead_url()})
    with pytest.raises(tasks.LocalNotReady) as said:
        tasks._researcher({"backend": "local", "app_state_path": path})
    assert "Nothing answers" in str(said.value)


def test_a_research_run_on_the_local_plane_builds_the_plane_from_the_server(
        ready, tmp_path, monkeypatch):
    monkeypatch.setattr(exa_mcp, "ENDPOINT", ready.url + "/mcp")
    path = _path(tmp_path, **{prefs.LOCAL_URL: ready.url})
    plane = tasks._researcher({"backend": "local", "app_state_path": path,
                               "model": "gpt-4o-mini"})
    assert plane.name == "local"
    assert plane.model == "qwen3-4b"          # the server's, not the Run screen's
    assert plane.search_provider == "exa-mcp"
    assert plane._complete.base_url == ready.url


# —— the second search door ————————————————————————————————

PARALLEL_TEXT = json.dumps({
    "results": [
        {"url": "https://one.test/a", "title": "First page",
         "excerpts": ["words"]},
        {"url": "https://two.test/b", "title": "Second page",
         "excerpts": ["more"]},
    ]})


def test_parallel_search_parses_entries(stub, monkeypatch):
    monkeypatch.setattr(exa_mcp, "PARALLEL_ENDPOINT", stub.url + "/mcp")
    stub.mcp_text = PARALLEL_TEXT
    assert exa_mcp.parallel_searcher()("q", 5) == [
        {"url": "https://one.test/a", "title": "First page", "site": "one.test"},
        {"url": "https://two.test/b", "title": "Second page", "site": "two.test"},
    ]


def test_the_fallback_search_rotates_to_parallel_on_a_refusal(stub, monkeypatch):
    monkeypatch.setattr(exa_mcp, "ENDPOINT", dead_url() + "/mcp")
    monkeypatch.setattr(exa_mcp, "PARALLEL_ENDPOINT", stub.url + "/mcp")
    stub.mcp_text = PARALLEL_TEXT
    assert exa_mcp.search_with_fallback()("q", 2) == [
        {"url": "https://one.test/a", "title": "First page", "site": "one.test"},
        {"url": "https://two.test/b", "title": "Second page", "site": "two.test"},
    ]


def test_the_fallback_search_stays_with_exa_while_exa_answers(stub, monkeypatch):
    monkeypatch.setattr(exa_mcp, "ENDPOINT", stub.url + "/mcp")
    monkeypatch.setattr(exa_mcp, "PARALLEL_ENDPOINT", dead_url() + "/mcp")
    stub.mcp_text = EXA_TEXT
    assert exa_mcp.search_with_fallback()("q", 1) == [
        {"url": "https://one.test/a", "title": "First page", "site": "one.test"}]
