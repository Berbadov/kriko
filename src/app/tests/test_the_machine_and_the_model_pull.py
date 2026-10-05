"""The machine the app runs on, and a model downloaded through Ollama.

No network and no real program: `nvidia-smi` is a fake subprocess, Ollama is a
fake server on a loopback port. What is pinned is the honest part: a number
the machine did not give is `null`, never a guess; the download's progress and
failure are Ollama's own; cancel stops it; and a runtime that cannot be driven
over HTTP is refused in words, not given a button.
"""

import json
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient

from app import machine, modelpull
from app.web import state
from app.web.app import create_app
from app.web.jobs import Cancelled
from app.web.settings import Settings


# ---- the machine ----

class Done:
    def __init__(self, out="", code=0):
        self.stdout, self.returncode = out, code


def test_the_gpu_is_what_nvidia_smi_says(monkeypatch):
    monkeypatch.setattr(machine.shutil, "which", lambda name: "smi")
    seen = {}

    def run(cmd, **kw):
        seen["cmd"] = cmd
        return Done("NVIDIA RTX 4090, 24564, 1203\n")

    gpu = machine._smi(run)
    assert gpu == {"name": "NVIDIA RTX 4090", "vram_total_mb": 24564,
                   "vram_used_mb": 1203, "count": 1}
    assert "--query-gpu=name,memory.total,memory.used" in seen["cmd"]


def test_no_gpu_tool_is_null_not_zero(monkeypatch):
    monkeypatch.setattr(machine.shutil, "which", lambda name: None)
    gpu = machine._smi()
    assert gpu["name"] is None and gpu["vram_total_mb"] is None

    monkeypatch.setattr(machine.shutil, "which", lambda name: "smi")
    assert machine._smi(lambda *a, **k: Done("", 9))["vram_total_mb"] is None

    def boom(*a, **k):
        raise subprocess.TimeoutExpired("smi", 5)

    assert machine._smi(boom)["name"] is None
    odd = machine._smi(lambda *a, **k: Done("Some GPU, [N/A], [N/A]\n"))
    assert odd["name"] == "Some GPU" and odd["vram_total_mb"] is None


def test_the_answer_is_cached_for_a_minute(monkeypatch):
    machine.forget()
    calls = []
    monkeypatch.setattr(machine, "inspect", lambda: calls.append(1) or {"n": len(calls)})
    clock = [100.0]
    assert machine.read(now=lambda: clock[0]) == {"n": 1}
    clock[0] += 59
    assert machine.read(now=lambda: clock[0]) == {"n": 1}
    clock[0] += 2
    assert machine.read(now=lambda: clock[0]) == {"n": 2}
    assert machine.read(fresh=True, now=lambda: clock[0]) == {"n": 3}
    machine.forget()


def test_a_runtime_is_installed_when_it_is_on_path(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(machine.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(
        machine.shutil, "which", lambda name: "/bin/ollama" if name == "ollama" else None)
    rows = {row["id"]: row for row in machine.runtimes()}
    assert rows["ollama"]["installed"] and rows["ollama"]["path"] == "/bin/ollama"
    assert rows["ollama"]["can_pull"] is True
    assert not rows["lmstudio"]["installed"] and rows["lmstudio"]["path"] is None
    assert rows["lmstudio"]["can_pull"] is False

    # not on PATH, but where the installer leaves it
    where = tmp_path / "Programs" / "Ollama"
    where.mkdir(parents=True)
    (where / "ollama.exe").write_bytes(b"x")
    monkeypatch.setattr(machine.shutil, "which", lambda name: None)
    rows = {row["id"]: row for row in machine.runtimes()}
    assert rows["ollama"]["installed"]


@pytest.fixture
def settings(tmp_path):
    return Settings(
        store_path=tmp_path / "knowledge.sqlite",
        app_state_path=tmp_path / "app.sqlite",
        analysis_log_path=tmp_path / "analyses.jsonl",
        packs_dir=tmp_path / "packs",
    )


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as client:
        yield client


def test_the_machine_endpoint_answers_the_shape(client, monkeypatch):
    monkeypatch.setattr(machine, "inspect", lambda: {
        "gpu": {"name": None, "vram_total_mb": None, "vram_used_mb": None},
        "gpu_count": 0, "ram_total_mb": 16000,
        "cpu": {"name": "x", "cores": 8}, "os": "Windows", "runtimes": []})
    machine.forget()
    body = client.get("/api/machine").json()
    assert body["gpu"]["vram_total_mb"] is None and body["ram_total_mb"] == 16000
    machine.forget()


def test_the_real_machine_reports_ram_and_cores():
    # whatever this computer is, memory and cores are knowable
    assert (machine._ram_total_mb() or 0) > 0
    assert (machine.inspect()["cpu"]["cores"] or 0) > 0


# ---- the pull ----

class FakeOllama(BaseHTTPRequestHandler):
    script: list = []
    status = 200
    seen: list = []

    def do_POST(self):
        length = int(self.headers.get("content-length") or 0)
        type(self).seen.append((self.path, json.loads(self.rfile.read(length))))
        self.send_response(type(self).status)
        self.send_header("content-type", "application/x-ndjson")
        self.end_headers()
        try:
            for line in type(self).script:
                self.wfile.write((json.dumps(line) + "\n").encode())
                self.wfile.flush()
                time.sleep(0.005)
        except OSError:
            pass  # the reader hung up: that is how a cancel arrives

    def log_message(self, *a):
        pass


@pytest.fixture
def ollama():
    FakeOllama.script, FakeOllama.status, FakeOllama.seen = [], 200, []
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeOllama)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


class Recorder:
    def __init__(self, cancel_after=None):
        self.sets, self.logs, self.checks = [], [], 0
        self.cancel_after = cancel_after

    def set(self, value, message=""):
        self.sets.append((value, message))

    def log(self, line):
        self.logs.append(line)

    def check(self):
        self.checks += 1
        if self.cancel_after is not None and self.checks > self.cancel_after:
            raise Cancelled()


def test_the_pull_streams_ollamas_progress(ollama, monkeypatch):
    monkeypatch.setattr(modelpull, "REPORT_EVERY", 0.0)
    FakeOllama.script = [
        {"status": "pulling manifest"},
        {"status": "pulling aaa", "digest": "aaa", "total": 1000, "completed": 250},
        {"status": "pulling aaa", "digest": "aaa", "total": 1000, "completed": 1000},
        {"status": "pulling bbb", "digest": "bbb", "total": 1000, "completed": 500},
        {"status": "success"},
    ]
    progress = Recorder()
    result = modelpull.pull(ollama, "tiny:1b", progress)
    assert FakeOllama.seen == [("/api/pull", {"model": "tiny:1b", "stream": True})]
    fractions = [v for v, _ in progress.sets]
    assert fractions == sorted(fractions)          # the bar only moves forward
    assert 0.0 < max(fractions[:-1]) < 1.0         # and is a share, not a layer
    assert fractions[-1] == 1.0
    assert result["model"] == "tiny:1b" and result["bytes"] == 2000
    assert "pulling manifest" in progress.logs


def test_a_refusal_is_ollamas_own_words(ollama):
    FakeOllama.script = [
        {"status": "pulling manifest"},
        {"error": "pull model manifest: file does not exist"},
    ]
    with pytest.raises(RuntimeError, match="pull model manifest: file does not exist"):
        modelpull.pull(ollama, "nope", Recorder())


def test_a_stream_that_just_ends_is_not_success(ollama):
    FakeOllama.script = [{"status": "pulling manifest"}]
    with pytest.raises(RuntimeError, match="closed the download"):
        modelpull.pull(ollama, "x", Recorder())


def test_a_http_error_carries_ollamas_error(ollama):
    FakeOllama.status, FakeOllama.script = 400, [{"error": "invalid model name"}]
    with pytest.raises(RuntimeError, match="invalid model name"):
        modelpull.pull(ollama, "x", Recorder())


def test_nothing_listening_is_said(monkeypatch):
    with pytest.raises(RuntimeError, match="did not answer"):
        modelpull.pull("http://127.0.0.1:9", "x", Recorder())


def test_cancel_stops_the_download(ollama):
    FakeOllama.script = [
        {"status": "pulling a", "digest": "a", "total": 100, "completed": i}
        for i in range(1, 99)
    ]
    with pytest.raises(Cancelled):
        modelpull.pull(ollama, "x", Recorder(cancel_after=3))


# ---- the door ----

def test_only_ollama_can_be_pulled_through(client):
    refused = client.post("/api/local-models/pull", json={"runtime": "lmstudio", "model": "m"})
    assert refused.status_code == 400
    assert "LM Studio" in refused.json()["detail"]
    bad = client.post("/api/local-models/pull", json={"runtime": "ollama", "model": "a b; rm"})
    assert bad.status_code == 422


def test_a_pull_is_a_job_that_fails_with_the_runtimes_words(client, settings, monkeypatch, ollama):
    from app.web import tasks

    monkeypatch.setattr(modelpull, "ollama_base", lambda path=None: ollama)
    FakeOllama.script = [{"error": "model not found"}]
    started = client.post("/api/local-models/pull", json={"runtime": "ollama", "model": "tiny:1b"})
    assert started.status_code == 200 and started.json()["kind"] == "model_pull"
    assert "model_pull" in tasks.HANDLERS
    conn = state.connect(settings.app_state_path)
    deadline = time.time() + 10
    row = None
    while time.time() < deadline:
        row = state.get_job(conn, started.json()["job_id"])
        if row and row["done"]:
            break
        time.sleep(0.02)
    assert row and row["done"]
    assert "model not found" in json.dumps(row)


def test_without_ollama_running_the_job_says_so(settings, monkeypatch):
    from app.web import tasks

    monkeypatch.setattr(modelpull, "ollama_base", lambda path=None: "")
    with pytest.raises(RuntimeError, match="Ollama is not running"):
        tasks.model_pull(settings, {"model": "x"}, Recorder())


# ---- what Ollama holds ----

def test_installed_models_carry_ollamas_own_sizes():
    body = {"models": [
        {"name": "a:1b", "size": 1234,
         "details": {"parameter_size": "1.2B", "quantization_level": "Q4_K_M", "family": "x"}},
        {"name": "bare"},
        {"nothing": True},
    ]}

    class Reply:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps(body).encode()

    seen = []
    rows = modelpull.installed("http://h:1/", opener=lambda url, timeout: seen.append(url) or Reply())
    assert seen == ["http://h:1/api/tags"]
    assert rows[0] == {"name": "a:1b", "size_bytes": 1234, "params": "1.2B",
                       "quant": "Q4_K_M", "family": "x"}
    assert rows[1]["size_bytes"] is None and rows[1]["params"] is None
    assert len(rows) == 2


def test_nothing_up_holds_no_models(client, monkeypatch):
    monkeypatch.setattr(modelpull, "ollama_base", lambda path=None: "")
    assert client.get("/api/local-models").json() == {
        "runtime": None, "url": None, "models": []}
    assert modelpull.installed("http://127.0.0.1:9") == []
