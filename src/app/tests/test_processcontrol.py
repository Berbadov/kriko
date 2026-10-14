import os
import subprocess
import sys
import textwrap
import time

import pytest

from app import processcontrol
from app.agentresources import slot


def test_custom_process_factory_keeps_mocked_popen_behavior():
    calls = []

    class Fake:
        pass

    def factory(command, **kwargs):
        calls.append((command, kwargs))
        return Fake()

    result = processcontrol.contained_popen(["fake"], factory=factory, cwd=".")
    assert isinstance(result, Fake)
    assert calls[0][1]["cwd"] == "."


def test_monkeypatched_subprocess_popen_is_treated_as_a_custom_factory(monkeypatch):
    calls = []
    fake = object()

    def factory(command, **kwargs):
        calls.append((command, kwargs))
        return fake

    monkeypatch.setattr(subprocess, "Popen", factory)
    assert processcontrol.contained_popen(
        ["fake"], factory=subprocess.Popen, cwd=".") is fake
    assert calls[0][1]["cwd"] == "."


def test_live_child_holds_shared_worker_permit(monkeypatch):
    monkeypatch.setenv("KRIKO_MAX_AGENT_CHILDREN", "1")
    child = processcontrol.contained_popen(
        [sys.executable, "-c", "import time; time.sleep(0.2)"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    with pytest.raises(TimeoutError):
        with slot("agent_child", timeout=0.03):
            pass
    with slot("agent_child", timeout=5):
        pass
    assert child.poll() == 0


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object descendant proof")
def test_job_contains_descendant_after_parent_exits(tmp_path):
    child_script = tmp_path / "child.py"
    parent_script = tmp_path / "parent.py"
    pid_file = tmp_path / "child.pid"
    child_script.write_text("import time; time.sleep(60)\n", encoding="utf-8")
    parent_script.write_text(textwrap.dedent(f"""
        import subprocess, sys, time
        child = subprocess.Popen([sys.executable, {str(child_script)!r}])
        open({str(pid_file)!r}, 'w').write(str(child.pid))
        time.sleep(0.15)
    """), encoding="utf-8")
    job = processcontrol.create_job_object()
    assert job is not None
    parent = processcontrol.contained_popen(
        [sys.executable, str(parent_script)], job=job,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    assert parent.wait(timeout=5) == 0
    child_pid = int(pid_file.read_text(encoding="utf-8"))
    time.sleep(0.1)
    processcontrol.kill_tree(parent, job)
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        try:
            os.kill(child_pid, 0)
        except OSError:
            break
        time.sleep(0.05)
    else:
        pytest.fail("descendant remained alive after its Job Object was stopped")


@pytest.mark.skipif(os.name != "nt", reason="Windows native launch failure")
def test_job_assignment_failure_kills_suspended_process(monkeypatch):
    started = []

    def fake_assign(_job, proc):
        started.append(proc)
        raise OSError("assignment refused")

    monkeypatch.setattr(processcontrol, "_assign_windows_job", fake_assign)
    with pytest.raises(OSError, match="assignment refused"):
        processcontrol.contained_popen(
            [sys.executable, "-c", "pass"], job=123,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    assert started and started[0].poll() is not None
