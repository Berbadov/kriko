"""How to run vLLM on this machine, with the CUDA build its driver supports.

Kriko does not install vLLM. A vLLM server is minutes of download and gigabytes
of disk, and it runs in WSL 2 on Windows, outside anything this app controls.
This module reads the machine (`app.machine.read`) and writes the steps the
reader would run, with the one choice that is easy to get wrong already made:
the torch build. A driver reports the newest CUDA it can run. The build has to
be that version or older, and an NVIDIA Blackwell card needs 12.8 or newer.

Once a server answers on 127.0.0.1:8000, `providers.local_discovery` finds it
by its address, as it finds Ollama.
"""

from __future__ import annotations

import re

#: The builds vLLM publishes, newest first: driver CUDA needed, torch backend.
_BUILDS = ((13, 0, "cu130"), (12, 9, "cu129"), (12, 8, "cu128"))

#: The address `vllm serve` takes, and the one local discovery looks at.
HOST = "127.0.0.1"
PORT = 8000


def parse_cuda(text: str | None) -> tuple[int, int] | None:
    """`13.4` as `(13, 4)`. Anything that is not a version is `None`."""
    found = re.fullmatch(r"\s*(\d+)\.(\d+)\s*", text or "")
    return (int(found.group(1)), int(found.group(2))) if found else None


def header_version(smi_text: str) -> str | None:
    """The CUDA version in the header of a plain `nvidia-smi` run.

    Older drivers print `CUDA Version: 12.4`. Newer ones print
    `CUDA UMD Version: 13.4`. Both say the newest CUDA the driver can run.
    """
    found = re.search(r"CUDA\s+(?:UMD\s+)?Version:\s*(\d+\.\d+)", smi_text or "")
    return found.group(1) if found else None


def build_for(driver: tuple[int, int]) -> str | None:
    """The newest torch build that this driver can run, or `None` when it is too old."""
    for major, minor, tag in _BUILDS:
        if driver >= (major, minor):
            return tag
    return None


def _model_for(vram_mb: int | None) -> str:
    gb = (vram_mb or 0) / 1024
    if gb >= 24:
        return "Qwen/Qwen2.5-14B-Instruct"
    if gb >= 10:
        return "Qwen/Qwen2.5-7B-Instruct"
    return "Qwen/Qwen2.5-3B-Instruct"


def plan(machine: dict) -> dict:
    """What to run, in order, for this machine. `ready` is false when vLLM cannot run here."""
    gpu = machine.get("gpu") or {}
    vram = gpu.get("vram_total_mb")
    driver_text = (machine.get("cuda") or {}).get("driver")
    driver = parse_cuda(driver_text)
    system = machine.get("os") or ""

    def refuse(why: str) -> dict:
        return {"ready": False, "build": None, "driver_cuda": driver_text, "summary": why, "steps": [], "notes": []}

    if system == "Darwin":
        return refuse("vLLM needs an NVIDIA graphics card. This computer has none that it can use.")
    if not gpu.get("name") or driver is None:
        return refuse("Kriko cannot read an NVIDIA driver here. vLLM needs an NVIDIA graphics card and its driver.")
    build = build_for(driver)
    if build is None:
        return refuse(
            f"The driver supports CUDA {driver_text}. vLLM needs CUDA 12.8 or newer. Update the NVIDIA driver, then check again."
        )

    version = build[2:4] + "." + build[4:]
    summary = f"The driver supports CUDA {driver_text}. Use the CUDA {version} build."
    model = _model_for(vram)
    steps: list[dict] = []
    if system == "Windows":
        steps.append({
            "title": "Install WSL 2 with Ubuntu, once",
            "where": "PowerShell",
            "command": "wsl --install -d Ubuntu",
        })
    where = "Ubuntu" if system == "Windows" else "Terminal"
    steps += [
        {"title": "Install uv", "where": where, "command": "curl -LsSf https://astral.sh/uv/install.sh | sh"},
        {"title": "Make an environment", "where": where, "command": "uv venv --python 3.12 && source .venv/bin/activate"},
        {"title": f"Install vLLM for CUDA {version}", "where": where, "command": f"uv pip install vllm --torch-backend={build}"},
        {
            "title": "Start the server",
            "where": where,
            "command": f"vllm serve {model} --host {HOST} --port {PORT} --max-model-len 4096",
        },
    ]
    notes = ["Kriko finds the server by its address when it runs. Press Check again."]
    if system == "Windows":
        notes.insert(0, "vLLM does not run on Windows itself. WSL 2 shares the Windows NVIDIA driver, so do not install a driver in Ubuntu.")
    if vram is not None and vram < 8 * 1024:
        notes.append(f"This card has {vram / 1024:.0f} GB. Keep the model small, or add --gpu-memory-utilization 0.85.")
    return {"ready": True, "build": build, "driver_cuda": driver_text, "summary": summary, "model": model, "steps": steps, "notes": notes}
