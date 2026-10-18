"""The vLLM steps pick the torch build the driver can run, and refuse when none fits."""

from __future__ import annotations

from app import machine, vllmplan


def _machine(cuda, *, os="Linux", gpu="NVIDIA GeForce RTX 5090", vram=32768):
    return {"gpu": {"name": gpu, "vram_total_mb": vram}, "cuda": {"driver": cuda}, "os": os}


def test_the_header_is_read_in_both_the_old_and_the_new_wording():
    assert vllmplan.header_version("| NVIDIA-SMI 550.54  Driver Version: 550.54   CUDA Version: 12.4 |") == "12.4"
    assert vllmplan.header_version("| NVIDIA-SMI 616.92   KMD Version: 616.92   CUDA UMD Version: 13.4 |") == "13.4"
    assert vllmplan.header_version("no card here") is None


def test_a_cuda_13_driver_gets_the_cuda_13_build():
    plan = vllmplan.plan(_machine("13.4"))
    assert plan["ready"] and plan["build"] == "cu130"
    install = [s["command"] for s in plan["steps"] if "install vllm" in s["command"]]
    assert install == ["uv pip install vllm --torch-backend=cu130"]


def test_an_older_driver_gets_an_older_build_and_a_too_old_one_is_refused():
    assert vllmplan.plan(_machine("12.9"))["build"] == "cu129"
    assert vllmplan.plan(_machine("12.8"))["build"] == "cu128"
    refused = vllmplan.plan(_machine("12.4"))
    assert not refused["ready"] and refused["steps"] == []
    assert "12.8" in refused["summary"]


def test_windows_runs_it_in_wsl_and_linux_does_not_need_it():
    windows = vllmplan.plan(_machine("13.4", os="Windows"))
    assert windows["steps"][0]["command"].startswith("wsl --install")
    assert {s["where"] for s in windows["steps"][1:]} == {"Ubuntu"}
    linux = vllmplan.plan(_machine("13.4"))
    assert not any("wsl" in s["command"] for s in linux["steps"])


def test_the_server_binds_the_address_discovery_looks_at():
    from app.providers import local_discovery

    serve = [s["command"] for s in vllmplan.plan(_machine("13.4"))["steps"] if "vllm serve" in s["command"]][0]
    assert f"--host {vllmplan.HOST} --port {vllmplan.PORT}" in serve
    assert ("vLLM", f"http://{vllmplan.HOST}:{vllmplan.PORT}") in local_discovery.CANDIDATES


def test_no_gpu_and_no_mac_are_refused_in_plain_words():
    assert not vllmplan.plan({"gpu": {"name": None}, "cuda": {"driver": None}, "os": "Windows"})["ready"]
    assert not vllmplan.plan(_machine("13.4", os="Darwin"))["ready"]


def test_a_small_card_gets_a_small_model_and_a_warning():
    plan = vllmplan.plan(_machine("13.4", gpu="RTX 3060 Laptop", vram=6144))
    assert plan["model"] == "Qwen/Qwen2.5-3B-Instruct"
    assert any("6 GB" in note for note in plan["notes"])


def test_the_machine_answer_carries_the_plan_and_the_driver(monkeypatch):
    monkeypatch.setattr(machine, "_smi", lambda *a, **k: {"name": "GPU", "vram_total_mb": 8192, "vram_used_mb": 0, "count": 1})
    monkeypatch.setattr(machine, "_cuda_driver", lambda *a, **k: "13.0")
    monkeypatch.setattr(machine, "runtimes", lambda: [])
    answer = machine.inspect()
    assert answer["cuda"] == {"driver": "13.0"}
    assert answer["vllm"]["build"] == "cu130"


def test_the_window_shows_the_steps_and_never_runs_them():
    from pathlib import Path

    ui = Path(__file__).resolve().parents[3] / "kriko-ui" / "src"
    card = (ui / "ui" / "panels" / "Local.tsx").read_text(encoding="utf-8")
    start = card.index("function VllmCard")
    body = card[start : card.index("/** The public list", start)]
    assert "navigator.clipboard" in body
    assert "post(" not in body and "fetch(" not in body
    hook = (ui / "engine" / "local.ts").read_text(encoding="utf-8")
    assert "/api/machine?fresh=true" in hook
    assert "vllm/install" not in hook
