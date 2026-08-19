"""kriko-hub web — browser dashboard over the ledger (B20, web edition).

    .venv/bin/python -m knowledge.hub.web          # http://127.0.0.1:8787

The DearPyGui app is deprecated: GL rendering on WSLg was slow and broken
(GLX missing, scaling issues, stalls that swallowed clicks). A browser is
always hardware-accelerated and native on the host. This is the same data
plane — `knowledge/hub/metrics.py` (test-pinned) — over a tiny FastAPI:

  GET  /                the dashboard page (inline HTML/JS, no build step)
  GET  /api/state       snapshot: counts, spend, pending, catalog, parts,
                        documents, recent runs (no heavy report build)
  GET  /api/coverage    catalog coverage findings — cached 60s, built on
                        demand only (the report is ~1.5s; ?refresh=1 to force)
  GET  /api/part/{id}   part detail (claims, variants)
  GET  /api/doc/{id}    full document text
  POST /api/run         spawn `knowledge.ledger.run <argv>` (validated)
  GET  /api/log         streaming output buffer of the current run
  GET  /api/table/{t}   ledger table preview (50 rows + row count)
  POST /api/stop        kill the active run
  GET  /api/models      every catalogued car + its onboarding rollup
  GET  /api/model/{k}   one car's work list (same payload the agent gets)
  GET  /api/demand      onboarding queue from real traffic — the picker's makes
  GET  /api/generations/{make}/{model}   researched generation lineup
  GET  /api/harnesses   installed harnesses + the models each offers
  POST /api/agent-preview   the exact argv a run would execute (no spawn)
  POST /api/research-generations   phase 1: agent researches the lineup (B23)
  POST /api/onboard     phase 2: agent onboards {model}_{generation} (B23)
  GET  /api/activity    recent ledger writes — what the agent is doing now

  Phase 4:

  GET  /api/review          claims awaiting human review (status='review')
  POST /api/review/{id}     {action: approve|reject} → status verified/rejected
  GET  /api/coverage-matrix models × subsystem-group claim counts (heatmap)
  GET  /api/sources         every source_domain, tiered + counted
  GET  /api/runs            persisted run history (knowledge/hub/runs.jsonl)

Binds 127.0.0.1 only. Run buttons enforce the same --max-usd machinery as
the CLI; the browser polls state every second.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import yaml
from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from knowledge.agent import gates as agent_gates
from knowledge.catalog import doctor as catalog_doctor, generations as gencat, model_state
from knowledge.hub import metrics
from knowledge.ledger import db
from knowledge.ledger.verdict import AGENT_EXTRACTOR_VERSION
from knowledge.sources.tiers import resolve_tier
from knowledge.yamlutil import load_yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
LEDGER_PATH = db.LEDGER_PATH
DATA_DIR = REPO_ROOT / "backend" / "data"
GENERATIONS_DIR = gencat.GENERATIONS_DIR
EXPORT_DIR = REPO_ROOT / "knowledge" / "ledger_export"
REMEDIATION_LOG = REPO_ROOT / "logs" / "remediation.jsonl"
MAX_LOG_CHARS = 50000

ALLOWED_COMMANDS = {"acquire", "backfill", "extract", "resolve", "cluster",
                    "verdict", "export", "report", "remediate"}

MAX_ACTIVITY = 200

# Phase 4 stores. Both live next to this file; JSONL is append-only, which is
# the whole reason it was picked over sqlite — one open("a"), no schema.
RUNS_LOG = Path(__file__).resolve().parent / "runs.jsonl"
# Gate feedback, NOT a promotion queue. CLAUDE.md's automation principle bars a
# human from the data path: nothing written here reaches serving. It is a
# labelled-example log for tuning the deterministic gates.
CLAIM_SIGNAL_LOG = Path(__file__).resolve().parent / "claim_signals.jsonl"
AGENT_RUN_LOG = REPO_ROOT / "logs" / "agent_runs.jsonl"
_SIGNAL_LOCK = threading.Lock()  # serialises claim_signals.jsonl appends
_RUNS_LOCK = threading.Lock()     # serialises runs.jsonl appends

# Catalog-shaped identifiers only. make/model reach a subprocess argv, so
# anything with a path separator, a space, or a shell metacharacter is refused
# outright rather than escaped — there is no legitimate model key that needs one.
_SAFE_NAME = re.compile(r"[a-z0-9_]{1,40}")

AGENT_NAME = "kriko_research"

# The agent's task forms. The request names a task; it never supplies prose.
TASKS = {
    "generations": "find generations for {make} {model}",
    "onboard": "onboard {make} {model}",
}

# No car has more generations than this; the bound keeps a typo out of argv.
MAX_GENERATION = 20

# An LLM model id also reaches argv, so it gets the same treatment as make and
# model — a slightly wider charset because provider ids carry `/`, `.` and `-`.
_SAFE_MODEL = re.compile(r"[A-Za-z0-9_./:-]{1,80}")

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


def _split_key(key: str) -> tuple[str, str]:
    """'renault_megane_4' -> ('renault', 'megane_4'), validated."""
    make, _, model = key.partition("_")
    if not _SAFE_NAME.fullmatch(make) or not _SAFE_NAME.fullmatch(model or ""):
        raise HTTPException(400, f"malformed model key: {key!r}")
    return make, model

app = FastAPI(title="kriko-hub", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"),
          name="static")

_run_lock = threading.Lock()
RUN = {"proc": None, "cmd": "", "buf": "", "exit": None, "started": None}

# opencode/claude style their stdout with ANSI escapes (colour, cursor moves).
# In the browser pane those render as garbage or invisible blank lines, which
# reads as "no output". Strip them once, server-side.
_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07")


def _brief(obj, limit: int = 100) -> str:
    """Compact one-line hint of a tool's input/output, for the progress view."""
    try:
        s = json.dumps(obj, ensure_ascii=False) if obj is not None else ""
    except (TypeError, ValueError):
        s = str(obj)
    s = " ".join(s.split())
    return s[:limit] + ("…" if len(s) > limit else "")


def _fmt_opencode_event(line: str) -> str | None:
    """Render one `opencode run --format json` event as a readable progress
    line, so the browser shows each tool call and answer the moment it
    happens instead of a silent pane. Returns None for events with nothing
    worth showing (non-JSON lines are never fed here)."""
    try:
        ev = json.loads(line)
    except ValueError:
        return None
    etype, part = ev.get("type", ""), ev.get("part") or {}

    if etype == "text":
        return part.get("text") or None
    if etype == "step_start":
        return "· model working…"
    if etype == "step_finish":
        tok = (part.get("tokens") or {}).get("total")
        cost = part.get("cost")
        bits = [f"{tok} tok" for tok in (tok,) if tok is not None]
        try:
            bits.append(f"${float(cost):.4f}")
        except (TypeError, ValueError):
            pass
        return "✓ step done" + (" · " + " · ".join(bits) if bits else "")
    if etype in ("tool_use", "tool_use_permission"):
        tool = part.get("tool") or part.get("name") or "tool"
        state = part.get("state") or {}
        status = state.get("status") or etype.rsplit("_", 1)[-1]
        if status in ("error", "rejected"):
            return f"✗ {tool} failed — {_brief(state.get('error'), 140)}"
        if status == "running":
            return f"→ {tool} {_brief(state.get('input'))}".rstrip()
        out = state.get("output")
        # completed: hint at the result — parsed JSON gets compacted, text
        # output shows its first meaningful line
        hint = ""
        try:
            parsed = json.loads(out) if isinstance(out, str) else None
        except ValueError:
            parsed = None
        if isinstance(parsed, dict):
            hint = _brief(parsed, 80)
        elif out:
            hint = next((l.strip() for l in str(out).splitlines() if l.strip()), "")
        return f"✓ {tool}" + (f" — {hint[:80]}" if hint else "")
    return None


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


def _pump(proc: subprocess.Popen, json_events: bool = False) -> None:
    """Background reader: stdout -> RUN['buf']. Daemon thread, dies with the
    process; a completed process still drains to EOF.

    json_events: the stream is `opencode run --format json` output — render
    each event line through _fmt_opencode_event so the pane shows live tool
    activity instead of raw JSON."""
    try:
        for line in proc.stdout:  # type: ignore[union-attr]
            if json_events:
                rendered = _fmt_opencode_event(line)
                if rendered is None:
                    continue
                clean = rendered + "\n"
            else:
                clean = _ANSI_RE.sub("", line)
            with _run_lock:
                RUN["buf"] = (RUN["buf"] + clean)[-MAX_LOG_CHARS:]
    except Exception:
        pass
    with _run_lock:
        RUN["exit"] = proc.returncode if proc.poll() is not None else None
        rec = RUN.pop("record", None)
    if rec:
        # The run is only history once it has an exit code — the record is
        # held in RUN from spawn to EOF and lands in runs.jsonl here.
        t0 = rec.pop("_t0", None)
        rec["exit_code"] = proc.returncode
        rec["duration_s"] = round(time.time() - t0, 1) if t0 else None
        try:
            with _RUNS_LOCK:
                with open(RUNS_LOG, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except OSError:
            pass


def _spawn(cmd: list[str], meta: dict | None = None) -> str:
    env = _load_env()
    proc = subprocess.Popen(cmd, cwd=REPO_ROOT, env=env,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, bufsize=1)
    json_events = ("--format" in cmd
                   and cmd[cmd.index("--format") + 1:cmd.index("--format") + 2] == ["json"])
    meta = meta or {}
    with _run_lock:
        RUN["cmd"] = " ".join(str(c) for c in cmd)
        RUN["buf"] = ""
        RUN["exit"] = None
        RUN["started"] = time.time()
        RUN["proc"] = proc
        RUN["record"] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "argv": [str(c) for c in cmd],
            "task": meta.get("task"),
            "make": meta.get("make"),
            "model": meta.get("model"),
            "_t0": RUN["started"],
        }
    threading.Thread(target=_pump, args=(proc, json_events), daemon=True).start()
    return RUN["cmd"]


def _conn():
    return db.connect(LEDGER_PATH)


# ── API ───────────────────────────────────────────────────────────────────────


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return PAGE_PATH.read_text(encoding="utf-8")


@app.get("/api/state")
def state() -> dict:
    conn = _conn()
    try:
        c = metrics.ledger_counts(conn)
        s = metrics.spend(conn)
        p = metrics.pending(conn)
        parts = metrics.parts(DATA_DIR)
        docs = metrics.documents(conn, 50)
        runs = metrics.recent_runs(conn, 6)
        last = metrics.last_remediation(REMEDIATION_LOG)
    finally:
        conn.close()
    return {
        "counts": c, "spend": s, "pending": p, "parts": parts,
        "documents": docs, "runs": runs, "last_remediation": last,
        "catalog": metrics.catalog_counts(DATA_DIR, parts),
    }


# Coverage report build takes ~1.5s (full catalog parse); it is NOT part of the
# per-second state poll — fetched on demand by the Coverage tab and cached.
_COV_LOCK = threading.Lock()
_COV_TTL_S = 60.0
_COV = {"ts": 0.0, "findings": None}


@app.get("/api/coverage")
def coverage(refresh: int = 0) -> dict:
    import time
    now = time.time()
    with _COV_LOCK:
        if refresh or _COV["findings"] is None or now - _COV["ts"] > _COV_TTL_S:
            _COV["findings"] = metrics.findings(DATA_DIR)
            _COV["ts"] = now
        return {"findings": _COV["findings"], "ts": _COV["ts"]}


@app.get("/api/part/{part_id}")
def part(part_id: str) -> dict:
    detail = metrics.part_detail(DATA_DIR, part_id)
    if detail is None:
        raise HTTPException(404, f"no part {part_id}")
    return detail


@app.get("/api/doc/{doc_id}")
def doc(doc_id: int) -> dict:
    conn = _conn()
    try:
        d = metrics.document(conn, doc_id)
    finally:
        conn.close()
    if d is None:
        raise HTTPException(404, f"no document {doc_id}")
    return {"id": d["id"], "url": d["url"], "source_type": d["source_type"],
            "lang": d["lang"], "target_hint": d["target_hint"],
            "fetched_at": d["fetched_at"], "raw_text": d["raw_text"]}


@app.post("/api/run")
def run(payload: dict = Body(...)) -> dict:
    argv = payload.get("argv")
    if not isinstance(argv, list) or not argv or not all(
            isinstance(a, str) for a in argv):
        raise HTTPException(400, "argv must be a non-empty list of strings")
    if argv[0] == "pass":
        # The full $0 pass is a chained CLI sequence (no single stage exists).
        py = sys.executable
        chain = (f"{py} -m knowledge.ledger.run resolve && "
                 f"{py} -m knowledge.ledger.run cluster && "
                 f"{py} -m knowledge.ledger.run verdict --import-only && "
                 f"{py} -m knowledge.ledger.run export")
        cmd = ["bash", "-c", chain]
    else:
        if argv[0] not in ALLOWED_COMMANDS:
            raise HTTPException(400, f"command not allowed: {argv[0]}")
        if argv[0] == "export" and "--export-dir" not in argv:
            argv = argv + ["--export-dir", str(EXPORT_DIR)]
        cmd = [sys.executable, "-m", "knowledge.ledger.run", *argv]
    with _run_lock:
        old = RUN["proc"]
    if old and old.poll() is None:
        old.kill()
        old.wait()
    return {"ok": True, "cmd": _spawn(cmd, {"task": argv[0]})}


@app.get("/api/log")
def log() -> dict:
    with _run_lock:
        proc, buf, cmd, exit_code = RUN["proc"], RUN["buf"], RUN["cmd"], RUN["exit"]
        started = RUN["started"]
    running = proc is not None and proc.poll() is None
    elapsed = round(time.time() - started, 1) if (running and started) else None
    return {"cmd": cmd, "buf": buf, "running": running, "exit": exit_code,
            "elapsed": elapsed}


# ── Models: onboarding state + the agent driver (B23) ─────────────────────────


@app.get("/api/models")
def models() -> dict:
    """Every catalogued car with its onboarding rollup."""
    return {"models": model_state.list_models(DATA_DIR)}


@app.get("/api/model/{key}")
def model_detail(key: str) -> dict:
    """One car's full work list — the same payload the agent's onboard_model
    tool returns, so the browser and the agent never disagree."""
    make, model = _split_key(key)
    return model_state.model_state(make, model, DATA_DIR)


@app.get("/api/demand")
def demand(limit: int = 60) -> dict:
    """The onboarding queue: cars real buyers hit, grouped by make.

    Derived from logs/analyses.jsonl via backend.tools.demand — traffic-driven,
    never a hand-maintained list of makes (CLAUDE.md scalability rule). The
    picker offers what people actually search for, `not_onboarded` first.
    """
    from backend import config
    from backend.tools.demand import mine

    try:
        groups, _ = mine(Path(config.ANALYSES_LOG_PATH), limit=None)
    except Exception as exc:  # a missing/unreadable log must not kill the tab
        return {"makes": [], "error": str(exc)}

    order = {"not_onboarded": 0, "catalog_gap": 1, "missing_fields": 2}
    by_make: dict[str, list[dict]] = {}
    for grp in groups[:limit]:
        if grp.reason == "missing_fields":
            continue  # a scrape-quality signal, not a car anyone can onboard
        by_make.setdefault(grp.make, []).append({
            "model": grp.model, "slug": gencat.slugify(grp.model),
            "hits": grp.count, "reason": grp.reason,
            "years": sorted(grp.years)[:8],
        })

    makes = [{"make": mk, "slug": gencat.slugify(mk),
              "hits": sum(m["hits"] for m in models),
              "models": sorted(models, key=lambda m: (order.get(m["reason"], 9),
                                                      -m["hits"]))}
             for mk, models in by_make.items()]
    makes.sort(key=lambda m: -m["hits"])
    return {"makes": makes}


@app.get("/api/generations/{make}/{model}")
def generations_for(make: str, model: str) -> dict:
    """Researched generation lineup for one car, or researched:false."""
    if not _SAFE_NAME.fullmatch(make.lower()):
        raise HTTPException(400, f"malformed make: {make!r}")
    found = gencat.read_generations(make, model, GENERATIONS_DIR)
    if not found:
        return {"make": gencat.slugify(make), "model": gencat.slugify(model),
                "researched": False, "generations": []}
    return {**found, "researched": True}


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
    `knowledge.ledger.run`, so every input that reaches argv is gated here:
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


def _agent_spawn(cmd: list[str], meta: dict | None = None) -> str:
    """One run slot: stop whatever is running, then launch."""
    with _run_lock:
        old = RUN["proc"]
    if old and old.poll() is None:
        old.kill()
        old.wait()
    return _spawn(cmd, meta)


@app.get("/api/harnesses")
def harnesses() -> dict:
    """Installed harnesses and the models each offers, split by how they bill.

    `models` is the flat-rate plane — safe to run the agent on. `paid_models`
    are pay-per-token providers unlocked by API keys in `.env`; they are kept
    separate so a dropdown pick can't silently spend credits.
    """
    paid = _paid_providers(_load_env())
    out = []
    for name in sorted(HARNESSES):
        all_models = _harness_models(name)
        out.append({
            "name": name,
            "available": shutil.which(name) is not None,
            "models": [m for m in all_models if not _is_paid(m, paid)],
            "paid_models": [m for m in all_models if _is_paid(m, paid)],
        })
    return {"harnesses": out}


@app.post("/api/agent-preview")
def agent_preview(payload: dict = Body(...)) -> dict:
    """The exact command a run would execute — built, gated, but not spawned."""
    argv = _agent_command(
        str(payload.get("task", "")).strip(),
        str(payload.get("make", "")).strip().lower(),
        str(payload.get("model", "")).strip().lower(),
        str(payload.get("harness", "opencode")).strip(),
        payload.get("generation"),
        str(payload.get("llm_model", "")).strip(),
    )
    return {"argv": argv, "display": " ".join(argv)}


@app.post("/api/research-generations")
def research_generations(payload: dict = Body(...)) -> dict:
    """Phase 1: launch the agent to research which generations this car has.

    Also the step that resolves a scraped display name ("VW CC 1.4 TSI") to a
    real model slug — which is why it must run before anything can be picked.
    """
    make = str(payload.get("make", "")).strip().lower()
    model = gencat.slugify(payload.get("model", ""))
    argv = _agent_command("generations", make, model,
                          str(payload.get("harness", "opencode")).strip(),
                          llm_model=str(payload.get("llm_model", "")).strip())
    return {"ok": True, "cmd": _agent_spawn(argv, {"task": "generations",
                                                   "make": make, "model": model}),
            "make": make, "model": model}


def _onboard_block_reason(make: str, model: str, gen) -> str:
    """Why this onboarding target cannot be researched, if it cannot.

    Kriko's model keys carry a generation (`clio_5`), and the demand queue
    hands the picker scraped display slugs ("VW CC 1.4 TSI" ->
    `vw_cc_1_4_tsi`). Onboarding one of those with no generation produces the
    key `volkswagen_vw_cc_1_4_tsi`, which is not a car: the agent researches a
    model that does not exist, and the run looks broken for reasons nothing
    states. That exact case is refused here.

    Deliberately narrow. A generation-qualified target is a coherent key and
    stays allowed even before its lineup file exists (the CLI and the tests
    drive it that way), and a car already in the catalog is obviously fine —
    over-constraining the API would break working paths to fix a UI bug. The
    picker enforces the same rule client-side; this is the half no client can
    skip.
    """
    if gen not in (None, "", 0):
        return ""                                  # generation-qualified key
    if (DATA_DIR / "variants" / f"{make}_{model}.yaml").exists():
        return ""                                  # already a catalogued car
    lineup = gencat.read_generations(make, model, GENERATIONS_DIR)
    if lineup:
        known = ", ".join(str(g.get("generation")) for g in lineup["generations"])
        return f"pick a generation to onboard — researched: {known}"
    return (f"no generation given and no researched lineup for {make} {model} — "
            f"run 'find generations' first (model keys carry a generation, and "
            f"{model!r} may be a scraped display name, not a model)")


@app.post("/api/onboard")
def onboard(payload: dict = Body(...)) -> dict:
    """Phase 2: launch the research agent against one model generation."""
    make = str(payload.get("make", "")).strip().lower()
    model = str(payload.get("model", "")).strip().lower()
    gen = payload.get("generation")
    blocked = _onboard_block_reason(make, model, gen)
    if blocked:
        raise HTTPException(400, blocked)
    argv = _agent_command("onboard", make, model,
                          str(payload.get("harness", "opencode")).strip(),
                          gen, str(payload.get("llm_model", "")).strip())
    return {"ok": True, "cmd": _agent_spawn(argv, {"task": "onboard",
                                                   "make": make, "model": model}),
            "model_key": f"{make}_{_with_generation(model, gen)}"}


@app.get("/api/activity")
def activity(limit: int = 40) -> dict:
    """Recent ledger writes, newest first — what the agent is actually doing.

    Read off the ledger rather than the harness's stdout: every agent action
    goes through an MCP write tool, so the ledger is the authoritative record
    and this works identically whichever harness is driving.
    """
    n = max(1, min(int(limit), MAX_ACTIVITY))
    conn = _conn()
    try:
        docs = [{"kind": "document", "id": r["id"], "at": r["fetched_at"],
                 "label": r["url"], "detail": r["source_type"],
                 "target": r["target_hint"] or ""}
                for r in conn.execute(
                    "SELECT id, url, source_type, target_hint, fetched_at"
                    " FROM documents ORDER BY id DESC LIMIT ?", (n,))]
        evs = [{"kind": "evidence", "id": r["id"], "at": r["extracted_at"],
                "label": r["title"], "detail": r["domain"],
                "target": r["component_hint"] or "",
                "severity": r["severity"],
                "by_agent": r["extractor_version"] == AGENT_EXTRACTOR_VERSION,
                "grounded": bool(r["quote_grounded"])}
               for r in conn.execute(
                   "SELECT id, title, domain, severity, component_hint,"
                   " quote_grounded, extractor_version, extracted_at"
                   " FROM evidence ORDER BY id DESC LIMIT ?", (n,))]
    finally:
        conn.close()
    events = sorted(docs + evs, key=lambda e: e["at"] or "", reverse=True)
    return {"events": events[:n]}


# ── Phase 4: review queue, coverage heatmap, sources, run history ─────────────

# The seven display groups the ~20 subsystems in components.yaml collapse
# into (engine/timing -> engine). Kept as the fallback ordering; the live set
# is derived from components.yaml so a new subsystem appears automatically.
_DISPLAY_GROUPS = ("engine", "transmission", "emissions", "brakes",
                   "suspension", "electrical", "body")
_COMPONENTS_YAML = REPO_ROOT / "knowledge" / "catalog" / "components.yaml"

# Loose claim domains fold into their parent group; 'general' has no group of
# its own and falls through to the part file's directory.
_DOMAIN_GROUPS = {
    "engine": "engine", "cooling": "engine", "fuel system": "engine",
    "transmission": "transmission", "emissions": "emissions",
    "brakes": "brakes", "suspension": "suspension",
    "electrical": "electrical", "body": "body",
}

_COMPONENTS_CACHE: dict = {}


def _component_registry() -> tuple[list[str], dict[str, str]]:
    """(display groups, component_id -> group) from components.yaml.

    The registry is the contract: a subsystem's first path segment is its
    display group, so the heatmap follows components.yaml instead of a list
    someone has to keep in sync here.
    """
    if "reg" not in _COMPONENTS_CACHE:
        groups: list[str] = []
        by_id: dict[str, str] = {}
        try:
            with open(_COMPONENTS_YAML, encoding="utf-8") as fh:
                comps = (yaml.safe_load(fh) or {}).get("components") or []
            for c in comps:
                group = str(c.get("subsystem") or "").split("/", 1)[0]
                if group and group not in groups:
                    groups.append(group)
                if c.get("id"):
                    by_id[c["id"]] = group
        except (OSError, yaml.YAMLError):
            groups = []
        ordered = [g for g in _DISPLAY_GROUPS if g in groups] + \
                  [g for g in groups if g not in _DISPLAY_GROUPS]
        _COMPONENTS_CACHE["reg"] = (ordered or list(_DISPLAY_GROUPS), by_id)
    return _COMPONENTS_CACHE["reg"]


def _claim_group(claim: dict, part_type: str) -> str | None:
    """Which display group a claim counts under, or None if unplaceable.

    component_id (components.yaml ref) wins when present; today's catalog
    YAMLs carry only `domain`, so that is the operative path.
    """
    _, by_id = _component_registry()
    cid = claim.get("component_id")
    if cid in by_id:
        return by_id[cid]
    g = _DOMAIN_GROUPS.get(str(claim.get("domain") or "").strip().lower())
    if g:
        return g
    return part_type if part_type in _DISPLAY_GROUPS else None


def _catalog_claims(data_dir: Path | None = None) -> list[dict]:
    """Flat read-only view of every claim in backend/data/parts/**."""
    data_dir = data_dir or DATA_DIR
    out: list[dict] = []
    for path in sorted((data_dir / "parts").rglob("*.yaml")):
        data = load_yaml(path)
        pid = data.get("part_id")
        if not pid:
            continue
        part_type = path.parent.name
        for c in data.get("claims") or []:
            if not isinstance(c, dict) or not c.get("id"):
                continue
            out.append({
                "claim_id": c["id"],
                "title": c.get("title") or "",
                "title_tr": c.get("title_tr") or "",
                "severity": c.get("severity"),
                "domain": c.get("domain"),
                "rationale": c.get("rationale") or "",
                "inspection_advice": c.get("inspection_advice") or "",
                "group": _claim_group(c, part_type),
                "part_id": pid,
                "part_type": part_type,
                "status": c.get("status"),
                "confidence": c.get("confidence"),
                "sources": [
                    {"domain": s.get("source_domain") or "",
                     "url": s.get("source_url") or "",
                     "quote": s.get("quote") or ""}
                    for s in (c.get("sources") or [])
                    if isinstance(s, dict)],
            })
    return out


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _model_part_ids(model_key: str, data_dir: Path) -> set[str]:
    """Part ids one car references, via its fitment (variants as fallback)."""
    rows: list[dict] = []
    for sub in ("fitment", "variants"):
        path = data_dir / sub / f"{model_key}.yaml"
        if path.exists():
            try:
                loaded = yaml.safe_load(path.read_text()) or []
            except yaml.YAMLError:
                loaded = []
            if isinstance(loaded, list):
                rows = [r for r in loaded if isinstance(r, dict)]
            if rows:
                break
    return {p["part_id"] for p in model_state.part_work_list(rows, data_dir)}


@app.get("/api/review")
def review_queue(status: str = "review", severity: str | None = None,
                 group: str | None = None, part_id: str | None = None,
                 model_key: str | None = None, limit: int = 250) -> dict:
    """Claims the pipeline has not settled, each with the DETERMINISTIC gate's
    verdict on it — what the machine thinks and exactly why.

    This is an inspector, not a promotion queue. CLAUDE.md's automation
    principle bars a human from the data path (`G5`: "a manual step that
    'someone should review' is a bug, not a process"), so nothing here writes
    to the catalog. The value of a browser over this data is seeing *which
    rule* fires on a claim and whether that rule is right — feedback that
    tunes the gate, which then runs unattended on every car.

    Filters compose: ?group=engine&model_key=renault_clio_5 is exactly what a
    heatmap cell click asks for.
    """
    n = max(1, min(int(limit), MAX_ACTIVITY))
    wanted = None if status == "all" else status
    part_ids = _model_part_ids(model_key, DATA_DIR) if model_key else None

    claims = [c for c in _catalog_claims()
              if (wanted is None or c["status"] == wanted)
              and (not severity or c["severity"] == severity)
              and (not group or c["group"] == group)
              and (not part_id or c["part_id"] == part_id)
              and (part_ids is None or c["part_id"] in part_ids)]
    sev_rank = {"high": 0, "medium": 1, "low": 2}
    claims.sort(key=lambda c: (sev_rank.get(str(c["severity"]), 3), c["claim_id"]))
    shown = [dict(c, gate=_gate_verdict(c)) for c in claims[:n]]
    return {"claims": shown, "total": len(claims),
            "would_drop": sum(1 for c in shown if not c["gate"]["ok"]),
            "recent": _recent_signals(10)}


def _gate_verdict(claim: dict) -> dict:
    """What the agent write gate would say about this claim today.

    Same function the MCP server runs before writing evidence, so the browser
    and the write path cannot disagree about what counts as low value.
    """
    src = (claim.get("sources") or [{}])[0]
    res = agent_gates.check_evidence(
        claim.get("title") or "", claim.get("rationale") or "",
        claim.get("inspection_advice") or "", claim.get("part_id"),
        src.get("url") or "")
    return {"ok": res.ok, **res.as_dict()}


def _recent_signals(n: int) -> list[dict]:
    """Tail of the gate-feedback log, newest first."""
    try:
        lines = CLAIM_SIGNAL_LOG.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for ln in reversed(lines):
        try:
            out.append(json.loads(ln))
        except ValueError:
            continue
        if len(out) >= n:
            break
    return out


# Claim ids are catalog-shaped identifiers; anything with a path separator or
# shell metacharacter is refused outright rather than escaped.
_SAFE_CLAIM_ID = re.compile(r"[A-Za-z0-9_.-]{1,120}")


@app.post("/api/review/{claim_id}")
def review_signal(claim_id: str, payload: dict = Body(...)) -> dict:
    """Record agreement or disagreement with the gate's verdict on one claim.

    Deliberately inert on the catalog. The previous version of this endpoint
    rewrote `status: review` to `verified` in the part YAML — a human decision
    inside the data path, which is the one thing G5 forbids, and which does not
    scale past the first thousand claims anyway. What survives is the useful
    half: a labelled example. Signals accumulate in claim_signals.jsonl, and a
    rule that keeps collecting disagreement is a rule to fix — in
    `knowledge/agent/gates.py`, where the fix then applies to every car.
    """
    action = str(payload.get("action") or "")
    if action not in ("agree", "disagree"):
        raise HTTPException(400, "action must be 'agree' or 'disagree'")
    if not _SAFE_CLAIM_ID.fullmatch(claim_id):
        raise HTTPException(400, f"malformed claim id: {claim_id!r}")

    claim = next((c for c in _catalog_claims() if c["claim_id"] == claim_id), None)
    if claim is None:
        raise HTTPException(404, f"no claim {claim_id}")

    verdict = _gate_verdict(claim)
    record = {"ts": _now_iso(), "claim_id": claim_id, "action": action,
              "part_id": claim["part_id"], "title": claim["title"],
              "gate_ok": verdict["ok"], "rejections": verdict["rejections"],
              "note": str(payload.get("note") or "")[:500]}
    try:
        with _SIGNAL_LOCK:
            with open(CLAIM_SIGNAL_LOG, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as exc:
        raise HTTPException(500, f"could not record signal: {exc}") from exc

    return {"ok": True, "recorded": True, "applied_to_catalog": False,
            "claim_id": claim_id, "action": action, "gate": verdict,
            "message": "recorded as gate feedback — the catalog is only ever "
                       "written by the pipeline"}


# ── Catalog doctor: identity damage, visible and fixable from the browser ────


@app.get("/api/doctor")
def doctor_report() -> dict:
    """Identity damage across every car: bad codes, trim-shaped ids, duplicate
    powertrains, orphan fitment rows. `fixable` findings are what a $0
    deterministic repair pass would resolve; the rest need research."""
    findings = catalog_doctor.diagnose(DATA_DIR)
    return {"findings": [{"kind": f.kind, "model_key": f.model_key,
                          "subject": f.subject, "message": f.message,
                          "fixable": f.fixable} for f in findings],
            "fixable": sum(1 for f in findings if f.fixable),
            "needs_research": sum(1 for f in findings if not f.fixable)}


@app.post("/api/doctor/repair")
def doctor_repair() -> dict:
    """Run the deterministic repair ($0, no LLM): merge duplicate powertrains,
    canonicalize codes, rename trim-shaped ids, prune orphan fitment rows."""
    res = catalog_doctor.repair(DATA_DIR)
    remaining = [f for f in catalog_doctor.diagnose(DATA_DIR) if not f.fixable]
    return {"ok": True, "rewritten": res.rewritten, "renames": res.renames,
            "actions": [f.message for f in res.findings],
            "needs_research": [f.message for f in remaining]}


@app.get("/api/agent-runs")
def agent_runs(limit: int = 25) -> dict:
    """What agent onboarding passes actually achieved (logs/agent_runs.jsonl,
    written by the MCP `finish_model` tool) — harness-independent, and it
    outlives the session the run happened in, unlike the output pane."""
    n = max(1, min(int(limit), 200))
    try:
        lines = AGENT_RUN_LOG.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    out = []
    for ln in reversed(lines):
        try:
            out.append(json.loads(ln))
        except ValueError:
            continue
        if len(out) >= n:
            break
    return {"runs": out}


@app.get("/api/coverage-matrix")
def coverage_matrix() -> dict:
    """Models × subsystem display groups: how many claims cover each cell.

    Model -> part ids follows the catalog's own join (fitment codes ->
    part files, the same axes model_state.part_work_list reads), and each
    claim lands in a group via components.yaml / its domain. Rejected claims
    don't count — they're not coverage.
    """
    groups, _ = _component_registry()
    by_part: dict[str, list[dict]] = {}
    for c in _catalog_claims():
        by_part.setdefault(c["part_id"], []).append(c)

    models = []
    for vpath in sorted((DATA_DIR / "variants").glob("*.yaml")):
        part_ids = _model_part_ids(vpath.stem, DATA_DIR)
        cells = {g: 0 for g in groups}
        total = 0
        for pid in part_ids:
            for c in by_part.get(pid, ()):
                if c["status"] == "rejected" or not c["group"]:
                    continue
                if c["group"] in cells:
                    cells[c["group"]] += 1
                    total += 1
        models.append({"model_key": vpath.stem, "cells": cells, "total": total})

    return {"groups": groups, "models": models,
            "max": max((m["total"] for m in models), default=0)}


@app.get("/api/sources")
def sources() -> dict:
    """Every source_domain in the catalog with its tier, trust and weight.

    Tier resolution is knowledge/sources/tiers.py — the same single
    enforcement point verdicts use, so the browser never disagrees with the
    confidence math.
    """
    counts: dict[str, int] = {}
    for c in _catalog_claims():
        for s in c["sources"]:
            domain = (s["domain"] or "").strip().lower()
            if domain:
                counts[domain] = counts.get(domain, 0) + 1
    out = []
    for domain, n in counts.items():
        tier, trust = resolve_tier(domain)
        out.append({"domain": domain, "tier": tier, "trust": trust,
                    "contribution_count": n})
    out.sort(key=lambda s: (-s["contribution_count"], s["domain"]))
    return {"sources": out}


@app.get("/api/runs")
def run_history(limit: int = 50) -> dict:
    """Last N persisted runs (newest first) from knowledge/hub/runs.jsonl."""
    n = max(1, min(int(limit), 200))
    try:
        lines = RUNS_LOG.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    out = []
    for ln in reversed(lines):
        try:
            rec = json.loads(ln)
        except ValueError:
            continue
        rec.pop("_t0", None)
        out.append(rec)
        if len(out) >= n:
            break
    return {"runs": out}


# ── page ──────────────────────────────────────────────────────────────────────

# The page is a real .html file (knowledge/hub/static/index.html), not a Python
# string. It used to be one, and a stray escape silently broke the whole
# dashboard once already (commit 49aa90c, "dead page — JS breakage from string
# escaping"). Read per request: the hub is a local dev tool, and an edit should
# show up on refresh without a restart.
PAGE_PATH = Path(__file__).resolve().parent / "static" / "index.html"


# ── ledger preview (generic read-only table browser) ─────────────────────────

_TABLES = ("documents", "evidence", "clusters", "verdicts",
           "resolutions", "evidence_flags", "runs")


@app.get("/api/table/{table}")
def table(table: str) -> dict:
    if table not in _TABLES:
        from fastapi import HTTPException
        raise HTTPException(404, f"no table {table}")
    conn = _conn()
    try:
        count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        rows = conn.execute(f"SELECT * FROM {table} LIMIT 50").fetchall()
        if rows:
            cols = rows[0].keys()
            head = " | ".join(cols)
            body = "\n".join(" | ".join(str(r[c])[:40] for c in cols)
                             for r in rows)
        else:
            head, body = "", "(empty)"
    finally:
        conn.close()
    return {"head": head, "body": body, "count": count}


@app.post("/api/stop")
def stop() -> dict:
    with _run_lock:
        proc = RUN["proc"]
    if proc and proc.poll() is None:
        proc.kill()
        proc.wait()
        return {"ok": True, "stopped": True}
    return {"ok": True, "stopped": False}


def _open_browser(url: str) -> None:
    """Open the dashboard in the Windows host browser when running under WSL.
    A WSLg browser window is the fallback — that GUI stack is software-
    rendered (llvmpipe), i.e. exactly the slow path the web edition exists
    to avoid."""
    if os.environ.get("WSL_DISTRO_NAME"):
        try:
            subprocess.Popen(["wslview", url],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except FileNotFoundError:
            try:
                subprocess.Popen(["/mnt/c/Windows/System32/cmd.exe",
                                  "/c", "start", "", url],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return
            except FileNotFoundError:
                pass
    import webbrowser
    webbrowser.open(url)


def main() -> None:
    import time
    import uvicorn
    url = "http://127.0.0.1:8787"
    print(f"kriko-hub web: {url}  (Ctrl+C to stop)")
    # Give uvicorn a beat to bind, then open the host browser; harmless if
    # no browser opens.
    _open_browser(url)
    time.sleep(0.5)
    uvicorn.run(app, host="127.0.0.1", port=8787, log_level="warning")


if __name__ == "__main__":
    main()
