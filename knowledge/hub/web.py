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
  POST /api/research-generations   phase 1: agent researches the lineup (B23)
  POST /api/onboard     phase 2: agent onboards {model}_{generation} (B23)
  GET  /api/activity    recent ledger writes — what the agent is doing now

Binds 127.0.0.1 only. Run buttons enforce the same --max-usd machinery as
the CLI; the browser polls state every second.
"""

import os
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from knowledge.catalog import generations as gencat, model_state
from knowledge.hub import metrics
from knowledge.ledger import db
from knowledge.ledger.verdict import AGENT_EXTRACTOR_VERSION

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

# Catalog-shaped identifiers only. make/model reach a subprocess argv, so
# anything with a path separator, a space, or a shell metacharacter is refused
# outright rather than escaped — there is no legitimate model key that needs one.
_SAFE_NAME = re.compile(r"[a-z0-9_]{1,40}")

AGENT_NAME = "kriko_research"
ONBOARD_PROMPT = "onboard {make} {model}"
GENERATIONS_PROMPT = "find generations for {make} {model}"

# No car has more generations than this; the bound keeps a typo out of argv.
MAX_GENERATION = 20

# Fixed argv templates. The request picks a harness by name; it never supplies
# a command. Adding a harness is a code change, deliberately.
HARNESSES = {
    "opencode": lambda b, prompt: [b, "run", "--agent", AGENT_NAME, prompt],
    "claude": lambda b, prompt: [
        b, "-p", f"Use the {AGENT_NAME} agent to {prompt}",
        "--permission-mode", "acceptEdits"],
}


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
RUN = {"proc": None, "cmd": "", "buf": "", "exit": None}


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


def _pump(proc: subprocess.Popen) -> None:
    """Background reader: stdout -> RUN['buf']. Daemon thread, dies with the
    process; a completed process still drains to EOF."""
    try:
        for line in proc.stdout:  # type: ignore[union-attr]
            with _run_lock:
                RUN["buf"] = (RUN["buf"] + line)[-MAX_LOG_CHARS:]
    except Exception:
        pass
    with _run_lock:
        RUN["exit"] = proc.returncode if proc.poll() is not None else None


def _spawn(cmd: list[str]) -> str:
    env = _load_env()
    proc = subprocess.Popen(cmd, cwd=REPO_ROOT, env=env,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, bufsize=1)
    with _run_lock:
        RUN["cmd"] = " ".join(str(c) for c in cmd)
        RUN["buf"] = ""
        RUN["exit"] = None
        RUN["proc"] = proc
    threading.Thread(target=_pump, args=(proc,), daemon=True).start()
    return RUN["cmd"]


def _conn():
    return db.connect(LEDGER_PATH)


# ── API ───────────────────────────────────────────────────────────────────────


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return _PAGE


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
    return {"ok": True, "cmd": _spawn(cmd)}


@app.get("/api/log")
def log() -> dict:
    with _run_lock:
        proc, buf, cmd, exit_code = RUN["proc"], RUN["buf"], RUN["cmd"], RUN["exit"]
    running = proc is not None and proc.poll() is None
    return {"cmd": cmd, "buf": buf, "running": running, "exit": exit_code}


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


def _agent_run(make: str, model: str, harness: str, prompt: str) -> str:
    """Shared gate + spawn for both agent phases.

    The only place the hub executes something other than `knowledge.ledger.run`,
    so both inputs are locked: make/model are catalog-shaped identifiers passed
    as argv (never interpolated into a shell), and the harness selects a fixed
    argv template rather than supplying a command.
    """
    if not _SAFE_NAME.fullmatch(make) or not _SAFE_NAME.fullmatch(model):
        raise HTTPException(400, "make/model must match [a-z0-9_] (1-40 chars)")
    if harness not in HARNESSES:
        raise HTTPException(
            400, f"unknown harness: {harness!r} — one of {sorted(HARNESSES)}")
    binary = shutil.which(harness)
    if not binary:
        raise HTTPException(400, f"{harness} is not installed on this machine")

    cmd = HARNESSES[harness](binary, prompt)
    with _run_lock:
        old = RUN["proc"]
    if old and old.poll() is None:
        old.kill()
        old.wait()
    return _spawn(cmd)


@app.post("/api/research-generations")
def research_generations(payload: dict = Body(...)) -> dict:
    """Phase 1: launch the agent to research which generations this car has.

    Also the step that resolves a scraped display name ("VW CC 1.4 TSI") to a
    real model slug — which is why it must run before anything can be picked.
    """
    make = str(payload.get("make", "")).strip().lower()
    model = gencat.slugify(payload.get("model", ""))
    harness = str(payload.get("harness", "opencode")).strip()
    cmd = _agent_run(make, model, harness,
                     GENERATIONS_PROMPT.format(make=make, model=model))
    return {"ok": True, "cmd": cmd, "make": make, "model": model}


@app.post("/api/onboard")
def onboard(payload: dict = Body(...)) -> dict:
    """Phase 2: launch the research agent against one model generation."""
    make = str(payload.get("make", "")).strip().lower()
    model = str(payload.get("model", "")).strip().lower()
    harness = str(payload.get("harness", "opencode")).strip()

    gen = payload.get("generation")
    if gen not in (None, ""):
        if isinstance(gen, bool) or not isinstance(gen, (int, str)):
            raise HTTPException(400, "generation must be a positive integer")
        try:
            gen_n = int(gen)
        except (TypeError, ValueError):
            raise HTTPException(400, "generation must be a positive integer")
        if not 1 <= gen_n <= MAX_GENERATION:
            raise HTTPException(
                400, f"generation must be between 1 and {MAX_GENERATION}")
        model = f"{model}_{gen_n}"

    cmd = _agent_run(make, model, harness,
                     ONBOARD_PROMPT.format(make=make, model=model))
    return {"ok": True, "cmd": cmd, "model_key": f"{make}_{model}"}


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


# ── page ──────────────────────────────────────────────────────────────────────

_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>kriko-hub</title>
<link rel="stylesheet" href="/static/style.css">
</head><body>
<header><h1>kriko-hub</h1><span class="meta" id="meta"></span></header>
<nav id="nav">
<button data-p="models" class="on">Models</button>
<button data-p="overview">Overview</button>
<button data-p="parts">Parts</button>
<button data-p="sources">Sources</button>
<button data-p="run">Run</button>
<button data-p="ledger">Ledger</button>
<button data-p="coverage">Coverage</button>
</nav>
<main>
<div class="page on" id="p-models">
  <h2>Onboard a model
    <span class="muted" id="onboard-state"></span></h2>
  <div class="onboard">
    <div class="step">
      <label>1 · Make <span class="muted">demand-ranked</span></label>
      <div class="choices" id="pick-make"></div>
    </div>
    <div class="step" id="step-model" hidden>
      <label>2 · Model</label>
      <div class="choices" id="pick-model"></div>
    </div>
    <div class="step" id="step-gen" hidden>
      <label>3 · Generation</label>
      <div class="choices" id="pick-gen"></div>
    </div>
    <div class="step" id="step-go" hidden>
      <label>4 · Run</label>
      <div class="choices">
        <select id="ob-harness">
          <option value="opencode">opencode</option>
          <option value="claude">claude code</option>
        </select>
        <button class="run go" id="b-onboard">Onboard →</button>
        <button class="run" id="b-onboard-stop">stop</button>
      </div>
    </div>
  </div>

  <div class="split">
    <div>
      <h2>Catalog</h2>
      <table id="t-models"></table>
    </div>
    <div>
      <h2>Live activity <span class="muted" id="act-meta"></span></h2>
      <div id="activity"></div>
    </div>
  </div>

  <h2 id="md-title">Model detail</h2>
  <div id="model-detail"><p class="muted">Pick a model to see its work list.</p></div>

  <h2>Agent output <span class="muted" id="ob-run-state"></span></h2>
  <pre id="ob-log"></pre>
</div>
<div class="page" id="p-overview">
  <h2>Ledger</h2>
  <div class="kpis" id="kpis"></div>
  <h2>Spend</h2><table id="t-spend"></table>
  <h2>Pending — cost to finish</h2><table id="t-pending"></table>
  <h2>Recent runs</h2><table id="t-runs"></table>
</div>
<div class="page" id="p-parts">
  <h2>Model &amp; Make</h2>
  <select id="part-sel"></select>
  <div id="part-detail"></div>
</div>
<div class="page" id="p-sources">
  <h2>Documents</h2>
  <select id="doc-sel"></select>
  <div id="doc-detail"></div>
</div>
<div class="page" id="p-run">
  <h2>Run controls — costs enforced by --max-usd</h2>
  <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:10px">
    <button class="run" id="b-extract">extract (capped)</button>
    <input type="number" id="cap" value="0.05" min="0" step="0.01">
    <button class="run" id="b-verdict">verdict (capped)</button>
    <button class="run" id="b-resolve">resolve ($0)</button>
    <button class="run" id="b-cluster">cluster ($0)</button>
    <button class="run" id="b-import">import verdicts ($0)</button>
    <button class="run" id="b-remediate">remediate ($0)</button>
    <button class="run" id="b-export">export</button>
    <button class="run" id="b-stop">stop</button>
  </div>
  <h2>Output <span class="muted" id="run-state"></span></h2>
  <pre id="log"></pre>
</div>
<div class="page" id="p-ledger">
  <h2>Ledger browser (read-only) <span class="muted" id="table-meta"></span></h2>
  <select id="table-sel">
    <option>documents</option><option>evidence</option><option>clusters</option>
    <option>verdicts</option><option>resolutions</option>
    <option>evidence_flags</option><option>runs</option>
  </select>
  <pre id="table-preview"></pre>
</div>
<div class="page" id="p-coverage">
  <h2>Coverage findings <button class="run" id="b-cov">refresh</button>
    <span class="muted" id="cov-meta"></span></h2>
  <table id="t-findings"></table>
</div>
</main>
<script src="/static/hub.js"></script>
</body></html>
"""


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
