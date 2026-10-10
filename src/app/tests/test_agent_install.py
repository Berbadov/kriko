"""One click installs an agent the way its vendor says, and says if Kriko can now run it."""

import pytest
from fastapi.testclient import TestClient

from app import agentinstall
from app.providers import harness
from app.web.app import create_app
from app.web.settings import Settings


class _Progress:
    def __init__(self):
        self.lines, self.steps = [], []

    def log(self, line):
        self.lines.append(line)

    def set(self, value, message=""):
        self.steps.append((value, message))

    def check(self):
        pass


@pytest.fixture(autouse=True)
def _windows(monkeypatch):
    monkeypatch.setattr(agentinstall.os, "name", "nt")


def test_the_shipped_agents_have_a_windows_install_that_is_not_a_bash_pipe():
    for ident in ("claude-code", "antigravity-cli", "codex", "mistral-vibe"):
        script = agentinstall.command_for(ident)
        assert script and "| bash" not in script and "curl " not in script, ident
        assert agentinstall.can_install(ident)


def test_the_local_agent_installs_ollama_and_an_unknown_agent_has_no_install():
    assert agentinstall.command_for("local") == agentinstall.OLLAMA_SETUP_URL
    assert not agentinstall.can_install("no-such-agent")


def test_the_current_registered_install_wins_over_an_obsolete_path(monkeypatch):
    monkeypatch.setattr(agentinstall, "_registered_ollama_exe", lambda: "D:/local/Ollama/ollama.exe")
    monkeypatch.setattr(agentinstall.shutil, "which", lambda *a, **k: "C:/old/Ollama/ollama.exe")
    assert agentinstall._ollama_exe() == "D:/local/Ollama/ollama.exe"


def test_a_cli_install_runs_its_script_then_looks_for_the_cli(monkeypatch, tmp_path):
    ran = []
    monkeypatch.setattr(agentinstall, "_run", lambda script, progress: ran.append(script))
    monkeypatch.setattr(harness, "locate", lambda one: str(tmp_path / "claude.exe"))
    got = agentinstall.install(None, {"agent_id": "claude-code"}, _Progress())
    assert ran == [agentinstall.command_for("claude-code")]
    assert got["installed"] and got["path"].endswith("claude.exe")


def test_an_install_that_leaves_the_cli_unfindable_says_so(monkeypatch):
    monkeypatch.setattr(agentinstall, "_run", lambda script, progress: None)
    monkeypatch.setattr(harness, "locate", lambda one: "")
    with pytest.raises(RuntimeError, match="cannot find it"):
        agentinstall.install(None, {"agent_id": "codex"}, _Progress())


def test_the_local_setup_skips_what_is_already_there(monkeypatch):
    monkeypatch.setattr(agentinstall, "_verify_local", lambda *a: None)
    monkeypatch.setattr(agentinstall, "_starter", lambda progress: agentinstall.STARTER_MODEL)
    monkeypatch.setattr(agentinstall, "_answers", lambda base: True)
    monkeypatch.setattr(agentinstall.modelpull, "ollama_base", lambda path=None: "")
    monkeypatch.setattr(agentinstall.modelpull, "installed", lambda base: [{"name": agentinstall.STARTER_MODEL}])
    monkeypatch.setattr(agentinstall, "_run", lambda *a: pytest.fail("Ollama is already running"))
    monkeypatch.setattr(agentinstall.modelpull, "pull", lambda *a: pytest.fail("the model is already there"))
    got = agentinstall.install(None, {"agent_id": "local"}, _Progress())
    assert got == {"id": "local", "installed": True, "model": agentinstall.STARTER_MODEL}


def test_the_local_setup_downloads_the_starter_model_when_ollama_has_none(monkeypatch):
    monkeypatch.setattr(agentinstall, "_verify_local", lambda *a: None)
    monkeypatch.setattr(agentinstall, "_starter", lambda progress: agentinstall.STARTER_MODEL)
    pulled = []
    monkeypatch.setattr(agentinstall, "_answers", lambda base: True)
    monkeypatch.setattr(agentinstall.modelpull, "ollama_base", lambda path=None: "http://127.0.0.1:11434")
    monkeypatch.setattr(agentinstall.modelpull, "installed", lambda base: [])
    monkeypatch.setattr(agentinstall.modelpull, "pull", lambda base, model, progress: pulled.append(model) or {})
    agentinstall.install(None, {"agent_id": "local"}, _Progress())
    assert pulled == [agentinstall.STARTER_MODEL]


def test_the_route_refuses_what_it_cannot_install(tmp_path):
    client = TestClient(create_app(Settings(
        store_path=tmp_path / "k.sqlite", packs_dir=tmp_path / "packs", analysis_log_path=tmp_path / "a.jsonl",
        dist_dir=tmp_path / "dist", app_state_path=tmp_path / "app.sqlite")))
    assert client.post("/api/agents/no-such-agent/install").status_code == 404


# ---- the install that stalled on a pipe ----
#
# The reader's words: "the install Ollama button does nothing and stalls with
# some loading logs". An installer that starts the app it installed leaves a
# grandchild holding the output pipe, and reading to end-of-file waits for
# that app to quit, which is never. A silent installer also never emits a line,
# so a Cancel checked only per line was never seen.

import os
import sys
import time

_LEAVES_A_GRANDCHILD = (
    "import subprocess, sys;"
    "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']);"
    "print('installed', flush=True)"
)


def test_a_finished_installer_is_not_waited_on_for_the_app_it_started():
    progress = _Progress()
    started = time.monotonic()
    agentinstall._stream([sys.executable, "-c", _LEAVES_A_GRANDCHILD], progress, grace=1.0)
    assert time.monotonic() - started < 15
    assert "installed" in progress.lines


@pytest.mark.skipif(sys.platform != "win32", reason="Authenticode is Windows's")
def test_a_signature_is_read_whatever_module_path_launched_the_app(monkeypatch):
    # PowerShell 7 leaves a module path that Windows PowerShell 5.1 cannot
    # load the security module from. Found by pressing the real button: the
    # check printed nothing and the installer was refused as unsigned.
    monkeypatch.setenv("PSModulePath", r"C:\no\such\modules")
    status, subject = agentinstall._signer_of(os.path.join(os.environ["SystemRoot"], "System32", "notepad.exe"))
    assert status == "Valid"
    assert "Microsoft" in subject


def test_a_failing_installer_says_what_it_said_last():
    with pytest.raises(RuntimeError, match="boom"):
        agentinstall._stream(
            [sys.executable, "-c", "import sys; print('boom'); sys.exit(3)"], _Progress())


def test_cancel_is_seen_while_the_installer_is_silent():
    class Stop(Exception):
        pass

    class Cancelling(_Progress):
        def __init__(self):
            super().__init__()
            self.calls = 0

        def check(self):
            self.calls += 1
            if self.calls > 3:
                raise Stop

    started = time.monotonic()
    with pytest.raises(Stop):
        agentinstall._stream([sys.executable, "-c", "import time; time.sleep(60)"], Cancelling())
    assert time.monotonic() - started < 15


def test_spinner_frames_are_not_log_lines():
    progress = _Progress()
    script = "[print(frame) for frame in ('-', chr(92), '|', '/')]; print('real line')"
    agentinstall._stream([sys.executable, "-c", script], progress)
    assert progress.lines == ["real line"]


# ---- the starter is sized to the machine, not one model for everyone ----
#
# The reader's words: the small agent "avoids doing hard work and gives few poor
# results". On the same real product 0.8B kept one finding and 4B of the same
# family kept three, in about the same time on a 6 GB GPU. Nothing here names a
# machine; each case is a machine's own report.


def _machine(gpu_mb=None, ram_mb=None):
    return {"gpu": {"name": "x", "vram_total_mb": gpu_mb}, "ram_total_mb": ram_mb}


def test_a_six_gb_gpu_gets_the_4b_not_the_0_8b():
    assert agentinstall.starter_model(_machine(gpu_mb=6144, ram_mb=15606)) == "qwen3.5:4b"


def test_the_model_never_outgrows_the_gpu_it_would_run_on():
    # 9B is 6.6 GB on disk: it does not fit 8 GB beside the screen and the cache
    assert agentinstall.starter_model(_machine(gpu_mb=8192, ram_mb=32768)) == "qwen3.5:4b"
    assert agentinstall.starter_model(_machine(gpu_mb=12288, ram_mb=32768)) == "qwen3.5:9b"


def test_without_a_gpu_the_share_of_ram_decides():
    assert agentinstall.starter_model(_machine(ram_mb=16384)) == "qwen3.5:4b"
    assert agentinstall.starter_model(_machine(ram_mb=8192)) == "qwen3.5:2b"
    assert agentinstall.starter_model(_machine(ram_mb=4096)) == "qwen3.5:0.8b"


def test_a_gpu_too_small_to_help_falls_back_to_ram():
    assert agentinstall.starter_model(_machine(gpu_mb=2048, ram_mb=16384)) == "qwen3.5:4b"


def test_nothing_reported_is_the_smallest_not_a_guess():
    assert agentinstall.starter_model({}) == f"{agentinstall.STARTER_FAMILY}:0.8b"


def test_no_starter_is_larger_than_the_cap_however_big_the_machine():
    assert agentinstall.starter_model(_machine(gpu_mb=98304, ram_mb=262144),
                                      (0.8, 4.0, 9.0, 27.0, 122.0)) == "qwen3.5:9b"


def test_the_library_page_names_the_sizes_when_it_can(monkeypatch):
    monkeypatch.setattr(agentinstall.modelpull, "library", lambda: [
        {"name": "other", "sizes": ["1b"], "about": ""},
        {"name": "qwen3.5", "sizes": ["0.8b", "2b", "e2b", "4b", "35b"], "about": ""}])
    assert agentinstall._library_sizes() == (0.8, 2.0, 4.0, 35.0)


def test_an_unreadable_library_falls_back_to_the_known_sizes(monkeypatch):
    def down():
        raise RuntimeError("offline")

    monkeypatch.setattr(agentinstall.modelpull, "library", down)
    assert agentinstall._library_sizes() == agentinstall.STARTER_SIZES


# ---- an Ollama that answers but cannot run anything ----
#
# Found on the reader's own machine: `Programs\Ollama\lib` held only a CUDA
# folder, the model runner (`llama-server.exe`) was missing, `/api/version`
# answered and every generate failed with a 500. An installer that stalled had
# left half an install, and "installed" was true of it.

import http.server
import json as _json
import threading


class _Ollama(http.server.BaseHTTPRequestHandler):
    body = {"error": "error starting llama-server: llama-server binary not found (checked: C:/x)"}
    status = 500

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        raw = _json.dumps(type(self).body).encode()
        self.send_response(type(self).status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *a):
        pass


@pytest.fixture
def ollama_stub():
    handler = type("H", (_Ollama,), {})
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield handler, f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def test_a_missing_model_runner_is_an_incomplete_install(ollama_stub):
    _, base = ollama_stub
    with pytest.raises(agentinstall._BrokenRuntime, match="llama-server"):
        agentinstall._verify_local(base, "m", _Progress())


def test_running_out_of_memory_is_not_blamed_on_the_install(ollama_stub):
    handler, base = ollama_stub
    handler.body = {"error": "model requires more system memory than is available"}
    with pytest.raises(RuntimeError, match="more system memory") as error:
        agentinstall._verify_local(base, "m", _Progress())
    assert not isinstance(error.value, agentinstall._BrokenRuntime)


def test_an_incomplete_install_is_reinstalled_once_and_verified_again(monkeypatch):
    calls = []
    monkeypatch.setattr(agentinstall, "_starter", lambda progress: "m")
    monkeypatch.setattr(agentinstall, "_answers", lambda base: True)
    monkeypatch.setattr(agentinstall.modelpull, "ollama_base", lambda path=None: "http://127.0.0.1:1")
    monkeypatch.setattr(agentinstall.modelpull, "installed", lambda base: [{"name": "m"}])
    monkeypatch.setattr(agentinstall, "_stop_ollama", lambda: calls.append("stop"))
    monkeypatch.setattr(agentinstall, "_install_ollama", lambda progress: calls.append("install"))
    monkeypatch.setattr(agentinstall, "_start_and_wait", lambda base, progress: calls.append("start"))

    def verify(base, model, progress):
        calls.append("verify")
        if calls.count("verify") == 1:
            raise agentinstall._BrokenRuntime("llama-server binary not found")

    monkeypatch.setattr(agentinstall, "_verify_local", verify)
    got = agentinstall.install(None, {"agent_id": "local"}, _Progress())
    assert calls == ["verify", "stop", "install", "start", "verify"]
    assert got["model"] == "m"


def test_a_second_failure_after_the_reinstall_is_reported_not_looped(monkeypatch):
    monkeypatch.setattr(agentinstall, "_starter", lambda progress: "m")
    monkeypatch.setattr(agentinstall, "_answers", lambda base: True)
    monkeypatch.setattr(agentinstall.modelpull, "ollama_base", lambda path=None: "http://127.0.0.1:1")
    monkeypatch.setattr(agentinstall.modelpull, "installed", lambda base: [{"name": "m"}])
    monkeypatch.setattr(agentinstall, "_stop_ollama", lambda: None)
    monkeypatch.setattr(agentinstall, "_install_ollama", lambda progress: None)
    monkeypatch.setattr(agentinstall, "_start_and_wait", lambda base, progress: None)

    def verify(base, model, progress):
        raise agentinstall._BrokenRuntime("llama-server binary not found")

    monkeypatch.setattr(agentinstall, "_verify_local", verify)
    with pytest.raises(agentinstall._BrokenRuntime):
        agentinstall.install(None, {"agent_id": "local"}, _Progress())


# ---- "Ready" on an install that can never answer ----
#
# The reader's own machine: Ollama listed `qwen3.5:0.8b`, the plane said Ready,
# the guided setup was hidden because a model was listed, and every run failed
# with HTTP 500 and a path. Once a call has said the runner is missing, the
# plane is not ready and says which button repairs it.

from app import localplane
from app.providers import local_inference


class _BrokenOllama(http.server.BaseHTTPRequestHandler):
    def _send(self, status, body):
        raw = _json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path.startswith("/v1/models"):
            self._send(200, {"data": [{"id": "m"}]})
        elif self.path.startswith("/api/version"):
            self._send(200, {"version": "0.40.2"})
        else:
            self._send(404, {})

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self._send(500, {"error": {"message": "error starting llama-server: llama-server binary not found"}})

    def log_message(self, *a):
        pass


def test_the_plane_stops_saying_ready_once_a_call_finds_the_runner_missing(monkeypatch):
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _BrokenOllama)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"
    from app.providers import local_discovery
    monkeypatch.setattr(local_discovery, "discover", lambda configured="", timeout=1.0: [
        {"name": "Ollama", **local_discovery.probe(base)}])
    local_inference.forget_incomplete()
    try:
        assert localplane.resolve(url=base, with_search=False)["ready"] is True
        socket = local_inference.OpenAICompatSocket(base, "m", max_tokens=8)
        with pytest.raises(local_inference.LocalInferenceError) as error:
            socket.complete("hi")
        assert error.value.code == "runtime_incomplete"
        assert "Set up Ollama" in str(error.value)
        plane = localplane.resolve(url=base, with_search=False)
        assert plane["ready"] is False and plane["runtime_incomplete"] is True
        assert "Set up Ollama" in plane["reason"] and plane["line"] == plane["reason"]
        local_inference.forget_incomplete(base)
        assert localplane.resolve(url=base, with_search=False)["ready"] is True
    finally:
        local_inference.forget_incomplete()
        server.shutdown()
