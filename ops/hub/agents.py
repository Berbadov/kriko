"""Agent harness layer: which harnesses exist, which models they offer, and
the exact argv one agent run executes.

Extracted from web.py. This is the only place the hub builds an agent command,
so the preview endpoint and the run endpoints cannot drift apart. Nothing here
touches the shared RUN slot — spawning stays in web.py, because the run slot and
its lock are request-scoped state.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

from fastapi import HTTPException

from ops.hub.textfmt import _SAFE_MODEL, _SAFE_NAME

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

AGENT_NAME = "kriko_research"

# The agent's task forms. The request names a task; it never supplies prose.
TASKS = {
    "generations": "find generations for {make} {model}",
    "onboard": "onboard {make} {model}",
}

# No car has more generations than this; the bound keeps a typo out of argv.
MAX_GENERATION = 20

# Fixed argv templates. The request picks a harness by name; it never supplies
# a command. Adding a harness is a code change, deliberately.
HARNESSES = {
    # --format json: raw event stream (one JSON object per line) instead of the
    # ANSI-styled default, which only prints step headers and hides all the
    # tool activity while the agent works. _pump renders each event live.
    "opencode": lambda b, prompt, m: (
        [b, "run", "--agent", AGENT_NAME, "--format", "json"]
        + (["-m", m] if m else []) + [prompt]),
    "claude": lambda b, prompt, m: (
        [b, "-p", f"Use the {AGENT_NAME} agent to {prompt}"]
        + (["--model", m] if m else []) + ["--permission-mode", "acceptEdits"]),
}

# How to ask each harness which models it offers. opencode enumerates its own,
# so the picker never ships a model list that someone has to maintain. Claude
# Code has no equivalent command; its `--model` aliases are a small closed
# vocabulary (the field also accepts any full model id you type).
HARNESS_MODEL_CMD = {"opencode": ["models"]}
CLAUDE_MODEL_ALIASES = ["opus", "sonnet", "haiku", "fable"]

_MODELS_TTL_S = 600.0
_MODELS_CACHE: dict[str, tuple[float, list[str]]] = {}


def _load_env() -> dict:
    env = dict(os.environ)
    dotenv = REPO_ROOT / ".env"
    if dotenv.exists():
        for line in dotenv.read_text().splitlines():
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k and not k.startswith("#") and k not in env:
                env[k] = v
    return env


def _paid_providers(env: dict) -> set[str]:
    """Providers that bill per token, derived from the API keys in the env.

    The hub passes `.env` to the harness, so `opencode models` reports every
    provider those keys unlock — 400+ pay-per-token models alongside the ~26
    on the flat-rate plan. Picking one silently spends API credits, which is
    exactly what the agent path exists to avoid, so they are split out rather
    than listed together.

    Derived from the key names (`DEEPSEEK_API_KEY` -> `deepseek`), never a
    hardcoded provider list: a new key in `.env` is classified the moment it
    appears.
    """
    paid: set[str] = set()
    for key in env:
        if not key.endswith("_API_KEY"):
            continue
        stem = key[: -len("_API_KEY")].lower()
        paid.add(stem)                  # mistral_agent
        paid.add(stem.split("_")[0])    # mistral
    return paid


def _is_paid(model: str, paid: set[str]) -> bool:
    """Does this model id belong to a pay-per-token provider?"""
    return model.split("/", 1)[0].lower() in paid


def _harness_models(harness: str) -> list[str]:
    """Which models this harness offers, asked of the harness itself.

    Cached, because shelling out per poll would be absurd. A harness that
    cannot enumerate its models returns whatever closed vocabulary it
    documents — never a list this repo has to keep in sync with a vendor.
    """
    now = time.time()
    hit = _MODELS_CACHE.get(harness)
    if hit and now - hit[0] < _MODELS_TTL_S:
        return hit[1]

    models: list[str] = []
    binary = shutil.which(harness)
    if binary and harness in HARNESS_MODEL_CMD:
        try:
            out = subprocess.run([binary, *HARNESS_MODEL_CMD[harness]],
                                 capture_output=True, text=True, timeout=45,
                                 cwd=REPO_ROOT, env=_load_env())
            models = [ln.strip() for ln in out.stdout.splitlines() if ln.strip()]
        except (OSError, subprocess.SubprocessError):
            models = []
    elif binary and harness == "claude":
        models = list(CLAUDE_MODEL_ALIASES)

    _MODELS_CACHE[harness] = (now, models)
    return models


def _agent_command(task: str, make: str, model: str, harness: str,
                   generation=None, llm_model: str = "") -> list[str]:
    """Build the exact argv for one agent run — the single source of truth.

    Both the preview endpoint and the run endpoints call this, so what the UI
    shows is literally the command that executes; there is no second
    implementation to drift.

    This is the only place the hub builds a command other than
    `ops.ledger_run`, so every input that reaches argv is gated here:
    task names a fixed prompt template, make/model/llm_model must match their
    charsets, and the harness selects a fixed argv template rather than
    supplying a command. Nothing is interpolated into a shell.
    """
    if task not in TASKS:
        raise HTTPException(400, f"unknown task: {task!r} — one of {sorted(TASKS)}")
    if harness not in HARNESSES:
        raise HTTPException(
            400, f"unknown harness: {harness!r} — one of {sorted(HARNESSES)}")
    if llm_model and not _SAFE_MODEL.fullmatch(llm_model):
        raise HTTPException(400, f"malformed model id: {llm_model!r}")

    model = _with_generation(model, generation)
    if not _SAFE_NAME.fullmatch(make) or not _SAFE_NAME.fullmatch(model):
        raise HTTPException(400, "make/model must match [a-z0-9_] (1-40 chars)")

    binary = shutil.which(harness)
    if not binary:
        raise HTTPException(400, f"{harness} is not installed on this machine")
    return HARNESSES[harness](binary, TASKS[task].format(make=make, model=model),
                              llm_model)


def _with_generation(model: str, generation) -> str:
    """Append a validated generation as the model-key suffix (q2 + 1 -> q2_1)."""
    if generation in (None, ""):
        return model
    if isinstance(generation, bool) or not isinstance(generation, (int, str)):
        raise HTTPException(400, "generation must be a positive integer")
    try:
        n = int(generation)
    except (TypeError, ValueError):
        raise HTTPException(400, "generation must be a positive integer")
    if not 1 <= n <= MAX_GENERATION:
        raise HTTPException(
            400, f"generation must be between 1 and {MAX_GENERATION}")
    return f"{model}_{n}"
