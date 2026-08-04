"""kriko-hub web — browser dashboard over the ledger (B20, web edition).

    .venv/bin/python -m knowledge.hub.web          # http://127.0.0.1:8787

The DearPyGui app is deprecated: GL rendering on WSLg was slow and broken
(GLX missing, scaling issues, stalls that swallowed clicks). A browser is
always hardware-accelerated and native on the host. This is the same data
plane — `knowledge/hub/metrics.py` (test-pinned) — over a tiny FastAPI:

  GET  /                the dashboard page (inline HTML/JS, no build step)
  GET  /api/state       one snapshot: counts, spend, pending, parts,
                        documents, findings, recent runs
  GET  /api/part/{id}   part detail (claims, variants)
  GET  /api/doc/{id}    full document text
  POST /api/run         spawn `knowledge.ledger.run <argv>` (validated)
  GET  /api/log         streaming output buffer of the current run

Binds 127.0.0.1 only. Run buttons enforce the same --max-usd machinery as
the CLI; the browser polls state every second.
"""

import json
import os
import subprocess
import sys
import threading
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from knowledge.hub import metrics
from knowledge.ledger import db

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
LEDGER_PATH = db.LEDGER_PATH
DATA_DIR = REPO_ROOT / "backend" / "data"
EXPORT_DIR = REPO_ROOT / "knowledge" / "ledger_export"
REMEDIATION_LOG = REPO_ROOT / "logs" / "remediation.jsonl"
MAX_LOG_CHARS = 50000

ALLOWED_COMMANDS = {"acquire", "backfill", "extract", "resolve", "cluster",
                    "verdict", "export", "report", "remediate"}

app = FastAPI(title="kriko-hub", docs_url=None, redoc_url=None)

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
        findings = metrics.findings(DATA_DIR)
        runs = metrics.recent_runs(conn, 6)
        last = metrics.last_remediation(REMEDIATION_LOG)
    finally:
        conn.close()
    return {
        "counts": c, "spend": s, "pending": p, "parts": parts,
        "documents": docs, "findings": findings, "runs": runs,
        "last_remediation": last,
    }


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


# ── page ──────────────────────────────────────────────────────────────────────

_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>kriko-hub</title>
<style>
:root{--bg:#16171c;--panel:#1c1e24;--panel2:#24262e;--line:#30333c;
--text:#e2e4ea;--dim:#8c919e;--accent:#ff8a3d;--ok:#6fce8e}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font:14px/1.45 system-ui,Segoe UI,sans-serif}
header{display:flex;align-items:center;gap:14px;padding:10px 16px;border-bottom:1px solid var(--line)}
header h1{font-size:15px;font-weight:600}
header .meta{color:var(--dim);font-size:12px}
nav{display:flex;gap:4px;padding:8px 12px 0;border-bottom:1px solid var(--line)}
nav button{background:none;border:none;color:var(--dim);font:inherit;padding:8px 14px;
cursor:pointer;border-bottom:2px solid transparent}
nav button.on{color:var(--text);border-bottom-color:var(--accent)}
main{padding:16px;max-width:1400px}
.page{display:none}.page.on{display:block}
h2{font-size:13px;color:var(--dim);text-transform:uppercase;letter-spacing:.06em;margin:14px 0 8px}
table{width:100%;border-collapse:collapse;margin-bottom:8px;background:var(--panel)}
th,td{padding:6px 10px;text-align:left;border-bottom:1px solid var(--line);
white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:420px}
th{color:var(--dim);font-weight:500;background:var(--panel2)}
tr:hover td{background:#2a2c34}
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:8px}
.kpi{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:12px}
.kpi b{font-size:20px;display:block}
.kpi span{color:var(--dim);font-size:12px}
button.run{background:var(--panel2);color:var(--text);border:1px solid var(--line);
border-radius:6px;padding:7px 12px;cursor:pointer;font:inherit}
button.run:hover{border-color:var(--accent)}
button.run:disabled{opacity:.4;cursor:default}
input[type=number]{background:var(--panel2);color:var(--text);border:1px solid var(--line);
border-radius:6px;padding:7px 10px;width:120px}
select{background:var(--panel2);color:var(--text);border:1px solid var(--line);
border-radius:6px;padding:7px 10px;max-width:100%;margin-bottom:8px}
pre{background:var(--panel);border:1px solid var(--line);border-radius:8px;
padding:12px;overflow:auto;max-height:46vh;font:12px/1.5 ui-monospace,monospace}
.tag{display:inline-block;border-radius:4px;padding:1px 7px;font-size:11px;background:var(--panel2)}
.muted{color:var(--dim)}
.err{color:#ff8080}
</style></head><body>
<header><h1>kriko-hub</h1><span class="meta" id="meta"></span></header>
<nav id="nav">
<button data-p="overview" class="on">Overview</button>
<button data-p="parts">Parts</button>
<button data-p="sources">Sources</button>
<button data-p="run">Run</button>
<button data-p="ledger">Ledger</button>
<button data-p="coverage">Coverage</button>
</nav>
<main>
<div class="page on" id="p-overview">
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
    <button class="run" id="b-import">import verdicts ($0)</button>
    <button class="run" id="b-pass">full $0 pass</button>
    <button class="run" id="b-remediate">remediate ($0)</button>
    <button class="run" id="b-export">export</button>
    <button class="run" id="b-stop">stop</button>
  </div>
  <h2>Output <span class="muted" id="run-state"></span></h2>
  <pre id="log"></pre>
</div>
<div class="page" id="p-ledger">
  <h2>Ledger browser (read-only)</h2>
  <select id="table-sel">
    <option>documents</option><option>evidence</option><option>clusters</option>
    <option>verdicts</option><option>resolutions</option>
    <option>evidence_flags</option><option>runs</option>
  </select>
  <pre id="table-preview"></pre>
</div>
<div class="page" id="p-coverage">
  <h2>Coverage findings</h2><table id="t-findings"></table>
</div>
</main>
<script>
const $=s=>document.querySelector(s), esc=s=>String(s??'').replace(/[&<>"]/g,
  c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const fmt=$=>'$'+Number($).toFixed(4);
let state=null, logState=null, selPart='', selDoc='', selTable='documents',
    running=false;
const TABS=['overview','parts','sources','run','ledger','coverage'];
function showTab(p){TABS.forEach(t=>{
  $('#p-'+t).classList.toggle('on',t===p);
  document.querySelector('#nav button[data-p="'+t+'"]').classList.toggle('on',t===p);});
}
document.querySelectorAll('#nav button').forEach(b=>
  b.onclick=()=>showTab(b.dataset.p));
function kpi(label,val,accent){return '<div class="kpi"><b style="color:'+
  (accent?accent:'')+'">'+esc(val)+'</b><span>'+esc(label)+'</span></div>';}
function rows(heads,data,extra){return '<table><tr>'+heads.map(h=>
  '<th>'+esc(h)+'</th>').join('')+'</tr>'+data.map(r=>'<tr>'+r.map(c=>
  '<td>'+c+'</td>').join('')+'</tr>').join('')+'</table>';}
function renderState(){
  const c=state.counts,s=state.spend,p=state.pending;
  $('#kpis').innerHTML=
    kpi('documents',c.documents)+kpi('evidence',c.evidence)+
    kpi('clusters',c.clusters)+kpi('verdicts',c.verdicts)+
    kpi('total spend',fmt(s.total_usd),'#ff8a3d')+
    kpi('import verdicts',s.verdicts_import+' ($0)','#6fce8e')+
    kpi('LLM verdicts',s.verdicts_llm)+
    kpi('cost to finish',fmt(p.extract_usd+p.verdict_usd),'#ff8a3d');
  $('#t-spend').innerHTML=rows(['stage','model','calls','tokens_in','tokens_out','usd'],
    s.rows.map(r=>[r.stage,r.model,r.calls,r.tokens_in,r.tokens_out,fmt(r.usd)]));
  $('#t-pending').innerHTML=rows(['pending extraction','pending verdicts','import-ready','LLM','extract $','verdict $'],
    [[p.extract_chunks+' chunks',p.verdict_pending+' clusters',p.import_ready,p.llm,
      fmt(p.extract_usd),fmt(p.verdict_usd)]]);
  $('#t-runs').innerHTML=rows(['started_at','stage','model','calls','usd'],
    state.runs.map(r=>[r.started_at.slice(0,19),r.stage,r.model||'-',r.calls,fmt(r.usd)]));
  const sel=$('#part-sel');
  const parts=state.parts.map(x=>x.part_id+' ('+x.claims+')');
  if(parts.join()!==sel.dataset.items){sel.dataset.items=parts.join();
    sel.innerHTML=parts.map(v=>'<option>'+esc(v)+'</option>').join('');}
  if(!sel.value) sel.selectedIndex=0;
  const cur=sel.value&&sel.value.split(' ')[0];
  if(cur!==selPart){selPart=cur; if(cur) loadPart(cur);}
  const dsel=$('#doc-sel');
  const dopt=state.documents.map(d=>'#'+d.id+' '+d.source_type+' '+d.url);
  if(dopt.join()!==dsel.dataset.items){dsel.dataset.items=dopt.join();
    dsel.innerHTML=dopt.map(v=>'<option>'+esc(v.slice(0,90))+'</option>').join('');}
  const dcur=dsel.value&&Number(dsel.value.split(' ')[0].slice(1));
  if(dcur&&dcur!==selDoc){selDoc=dcur; loadDoc(dcur);}
  $('#t-findings').innerHTML=rows(['kind','subject','part','message'],
    state.findings.map(f=>[f.kind,f.subject,f.part_id||'',f.message]));
  if(state.last_remediation)
    $('#meta').textContent='last remediation: '+state.last_remediation.ts+
      ' · '+fmt(state.last_remediation.usd);
  const tsel=$('#table-sel');
  if(tsel.value!==selTable){selTable=tsel.value||'documents'; loadTable(selTable);}
}
async function loadPart(id){const r=await fetch('/api/part/'+id);const d=await r.json();
  $('#part-detail').innerHTML='<div class="muted">'+esc(d.title||'')+
    ' · '+esc(d.part_type)+'</div><div class="muted">variants: '+
    esc((d.variants||[]).join(', '))+ '</div>'+rows(['title','severity','domain'],
    (d.claims||[]).map(c=>[c.title,c.severity,c.domain]));}
async function loadDoc(id){const r=await fetch('/api/doc/'+id);const d=await r.json();
  $('#doc-detail').innerHTML='<div class="muted">'+esc(d.url)+' ['+esc(d.source_type)+
    '] target='+esc(d.target_hint)+'</div><pre>'+esc(d.raw_text.slice(0,20000))+'</pre>';}
async function loadTable(t){const q=await fetch('/api/table/'+t);const d=await q.json();
  $('#table-preview').textContent=d.head+'\n'+d.body;}
async function poll(){try{state=await (await fetch('/api/state')).json();
  renderState();}catch(e){$('#meta').textContent='ledger unavailable';}
  try{logState=await (await fetch('/api/log')).json();
    $('#log').textContent=logState.buf;
    running=logState.running;
    $('#run-state').textContent=running?'running…':'exit '+(logState.exit??'-')+' · '+(logState.cmd||'');
    setRunButtons(!running);
    if(!running) loadTable(selTable);
  }catch(e){}}
function setRunButtons(en){['b-extract','b-import','b-pass','b-remediate',
  'b-export'].forEach(id=>$(id).disabled=!en);}
async function doRun(argv){const r=await fetch('/api/run',{method:'POST',
  headers:{'Content-Type':'application/json'},body:JSON.stringify({argv})});
  if(!r.ok) $('#run-state').textContent=(await r.json()).detail;}
$('#b-extract').onclick=()=>doRun(['extract','--max-usd',
  (Number($('#cap').value)||0).toFixed(2)]);
$('#b-import').onclick=()=>doRun(['verdict','--import-only']);
$('#b-pass').onclick=()=>doRun(['pass']);
$('#b-remediate').onclick=()=>doRun(['remediate']);
$('#b-export').onclick=()=>doRun(['export','--export-dir','""" + str(EXPORT_DIR) + """']);
$('#b-stop').onclick=async()=>{await fetch('/api/stop',{method:'POST'})};
$('#table-sel').addEventListener('change',e=>loadTable(e.target.value));
setInterval(poll,1000);poll();
</script></body></html>
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
        rows = conn.execute(f"SELECT * FROM {table} LIMIT 8").fetchall()
        if rows:
            cols = rows[0].keys()
            head = " | ".join(cols)
            body = "\n".join(" | ".join(str(r[c])[:40] for c in cols)
                             for r in rows)
        else:
            head, body = "", "(empty)"
    finally:
        conn.close()
    return {"head": head, "body": body}


@app.post("/api/stop")
def stop() -> dict:
    with _run_lock:
        proc = RUN["proc"]
    if proc and proc.poll() is None:
        proc.kill()
        proc.wait()
        return {"ok": True, "stopped": True}
    return {"ok": True, "stopped": False}


def main() -> None:
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8787, log_level="warning")


if __name__ == "__main__":
    main()
