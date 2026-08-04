"""kriko-hub — DearPyGui desktop dashboard for the ledger pipeline (B20).

    .venv/bin/python -m knowledge.hub.app

Six clickable windows over the live ledger DB, polled ~1s with fresh
read-only connections, so anything the kriko_research agent (or a cron
remediate pass) writes shows up in real time:

  Overview     spend plot, cost-to-finish, live log tails
  Model & Make parts -> claims/variants/findings drill-down
  Sources      documents with badges -> raw text viewer
  Extraction   pending work + run buttons (spawns `knowledge.ledger.run`)
  Ledger       generic read-only SQLite browser
  Scaffold     coverage findings + the $0 command set

Buttons run the CLI subprocesses (single source of truth for pipeline logic)
and stream their output into the log window. Cost caps are enforced by the
same --max-usd machinery the CLI uses.
"""

from __future__ import annotations

import os
import select
import subprocess
import sys
import time
from pathlib import Path

from dearpygui import dearpygui as dpg

from knowledge.hub import metrics
from knowledge.ledger import db

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
LEDGER_PATH = db.LEDGER_PATH
DATA_DIR = REPO_ROOT / "backend" / "data"
EXPORT_DIR = REPO_ROOT / "knowledge" / "ledger_export"
REMEDIATION_LOG = REPO_ROOT / "logs" / "remediation.jsonl"
ANALYSES_LOG = REPO_ROOT / "logs" / "analyses.jsonl"
MAX_LOG_CHARS = 30000


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


class Hub:
    def __init__(self) -> None:
        self.runs: list[dict] = []          # {proc, buf} for running subprocesses
        self.doc_selected: int | None = None
        self.doc_items: list[str] = []
        self.part_ids: list[str] = []
        self.ledger_tables = ["documents", "evidence", "clusters", "verdicts",
                              "resolutions", "evidence_flags", "runs"]

    # ── subprocess runner (buttons) ──────────────────────────────────────────
    def spawn(self, argv: list[str]) -> None:
        env = _load_env()
        cmd = [sys.executable, "-m", "knowledge.ledger.run", *argv]
        try:
            proc = subprocess.Popen(cmd, cwd=REPO_ROOT, env=env,
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True,
                                    bufsize=1)
        except OSError as exc:
            self._log(f"spawn failed: {exc}")
            return
        self.runs.append({"proc": proc, "buf": ""})
        self._log("$ " + " ".join(str(c) for c in cmd))

    def poll(self) -> None:
        alive = []
        for r in self.runs:
            proc = r["proc"]
            while proc.stdout is not None:
                rlist, _, _ = select.select([proc.stdout], [], [], 0)
                if not rlist:
                    break
                line = proc.stdout.readline()
                if not line:
                    break
                r["buf"] += line
                if len(r["buf"]) > MAX_LOG_CHARS:
                    r["buf"] = r["buf"][-MAX_LOG_CHARS:]
                self._log(line.rstrip())
            if proc.poll() is None:
                alive.append(r)
            else:
                tail = proc.stdout.read() if proc.stdout else ""
                if tail:
                    r["buf"] += tail
                    self._log(tail.rstrip())
                self._log(f"exit {proc.returncode}")
        self.runs = alive

    def _log(self, line: str) -> None:
        cur = dpg.get_value("log_text") or ""
        dpg.set_value("log_text", (cur + "\n" + line)[-MAX_LOG_CHARS:])

    # ── refresh ──────────────────────────────────────────────────────────────
    def refresh(self) -> None:
        try:
            conn = db.connect(LEDGER_PATH)
        except Exception:  # ledger temporarily locked/absent — skip this tick
            return
        try:
            self._refresh_counts(conn)
            self._refresh_spend(conn)
            self._refresh_pending(conn)
            self._refresh_parts(conn)
            self._refresh_documents(conn)
            self._refresh_findings(conn)
            self._refresh_runs(conn)
        finally:
            conn.close()

    def _refresh_counts(self, conn) -> None:
        c = metrics.ledger_counts(conn)
        dpg.set_value("t_docs", f"{c['documents']:,}")
        dpg.set_value("t_ev", f"{c['evidence']:,}")
        dpg.set_value("t_cl", f"{c['clusters']:,}")
        dpg.set_value("t_vr", f"{c['verdicts']:,}")

    def _refresh_spend(self, conn) -> None:
        s = metrics.spend(conn)
        dpg.set_value("t_total", f"${s['total_usd']:.4f}")
        dpg.set_value("t_split",
                      f"{s['verdicts_import']} import ($0) + {s['verdicts_llm']} LLM")
        if dpg.does_item_exist("plot_spend"):
            dpg.delete_item("plot_spend", children_only=True)
            dpg.delete_item("plot_spend")
        stages = [r["stage"] for r in s["rows"]]
        usd = [r["usd"] for r in s["rows"]]
        if stages:
            x = list(range(len(stages)))
            plot = dpg.add_plot(label="Spend by stage (USD)", tag="plot_spend",
                                height=220, width=-1, parent="grp_overview")
            xaxis = dpg.add_plot_axis(dpg.mvXAxis, label="stage", parent=plot)
            yaxis = dpg.add_plot_axis(dpg.mvYAxis, label="USD", parent=plot)
            dpg.add_bar_series(x, usd, label="usd", weight=1, parent=yaxis)
            dpg.set_axis_ticks(xaxis, [[s, i] for i, s in enumerate(stages)])

    def _refresh_pending(self, conn) -> None:
        p = metrics.pending(conn)
        dpg.set_value("t_pend_extract",
                      f"{p['extract_chunks']} chunk call(s) ≈ ${p['extract_usd']:.4f}")
        dpg.set_value("t_pend_verdict",
                      f"{p['verdict_pending']} cluster(s) "
                      f"({p['import_ready']} import-ready $0, {p['llm']} LLM) "
                      f"≈ ${p['verdict_usd']:.4f}")
        finish = p["extract_usd"] + p["verdict_usd"]
        dpg.set_value("t_pend_total", f"COST TO FINISH ≈ ${finish:.4f}")

    def _refresh_parts(self, conn) -> None:
        plist = metrics.parts(DATA_DIR)
        self.part_ids = [p["part_id"] for p in plist]
        dpg.configure_item("combo_part", items=self.part_ids)
        if not self.part_ids:
            return
        if self.part_ids and not dpg.get_value("combo_part"):
            dpg.set_value("combo_part", self.part_ids[0])
        self._show_part(dpg.get_value("combo_part"))

    def _show_part(self, part_id: str) -> None:
        detail = metrics.part_detail(DATA_DIR, part_id) or {}
        dpg.set_value("t_part_title", f"{detail.get('title', '')} "
                                      f"({detail.get('part_type', '')})")
        dpg.set_value("t_part_variants", ", ".join(detail.get("variants", [])))
        dpg.delete_item("t_part_claims", children_only=True)
        for c in detail.get("claims", []):
            with dpg.table_row(parent="t_part_claims"):
                dpg.add_text(c.get("title") or "")
                dpg.add_text(c.get("severity") or "")
                dpg.add_text(c.get("domain") or "")

    def _refresh_documents(self, conn) -> None:
        rows = metrics.documents(conn, 200)
        self.doc_items = [f"#{r['id']} {r['source_type']:<8} {r['url'][:70]}"
                          for r in rows]
        dpg.configure_item("list_docs", items=self.doc_items)

    def _doc_picked(self, sender, app_data, user_data) -> None:
        idx = app_data
        if idx is None or idx >= len(self.doc_items):
            return
        item = self.doc_items[idx]
        doc_id = int(item.split(" ", 1)[0][1:])
        self.doc_selected = doc_id

    def _refresh_findings(self, conn) -> None:
        flist = metrics.findings(DATA_DIR)
        dpg.set_value("t_findings_count", f"{len(flist)} finding(s)")
        dpg.delete_item("t_findings", children_only=True)
        for f in flist[:100]:
            with dpg.table_row(parent="t_findings"):
                dpg.add_text(f["kind"])
                dpg.add_text(f["subject"])
                dpg.add_text(f["part_id"] or "")
                dpg.add_text(f["message"])

    def _refresh_runs(self, conn) -> None:
        s = metrics.spend(conn)
        rows = metrics.recent_runs(conn, 6)
        dpg.delete_item("t_runs", children_only=True)
        for r in rows:
            with dpg.table_row(parent="t_runs"):
                dpg.add_text(r["started_at"][:19])
                dpg.add_text(r["stage"])
                dpg.add_text(r["model"] or "")
                dpg.add_text(f"{r['calls']}")
                dpg.add_text(f"${r['usd']:.4f}")
        last = metrics.last_remediation(REMEDIATION_LOG)
        if last:
            dpg.set_value("t_last_rem",
                          f"last remediation: {len(last.get('parts') or [])} part(s), "
                          f"+{last.get('ingested', 0)} docs, +{last.get('verdicts', 0)} "
                          f"verdicts, ${last.get('usd', 0.0):.4f}")

    # ── buttons ──────────────────────────────────────────────────────────────
    def _btn_extract(self) -> None:
        cap = max(float(dpg.get_value("inp_cap") or 0.0), 0.0)
        self.spawn(["extract", "--max-usd", f"{cap:.2f}"])

    def _btn_import(self) -> None:
        self.spawn(["verdict", "--import-only"])

    def _btn_pass(self) -> None:
        py = sys.executable
        chain = (f"{py} -m knowledge.ledger.run resolve && "
                 f"{py} -m knowledge.ledger.run cluster && "
                 f"{py} -m knowledge.ledger.run verdict --import-only && "
                 f"{py} -m knowledge.ledger.run export")
        env = _load_env()
        try:
            proc = subprocess.Popen(["bash", "-c", chain], cwd=REPO_ROOT,
                                    env=env, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True,
                                    bufsize=1)
        except OSError as exc:
            self._log(f"spawn failed: {exc}")
            return
        self.runs.append({"proc": proc, "buf": ""})
        self._log("$ " + chain)

    def _btn_remediate(self) -> None:
        self.spawn(["remediate"])

    def _btn_export(self) -> None:
        self.spawn(["export", "--export-dir", str(EXPORT_DIR)])

    # ── window builders ──────────────────────────────────────────────────────
    def build(self) -> None:
        with dpg.window(tag="win_overview", label="Overview", pos=(0, 0),
                        width=560, height=400):
            with dpg.group(tag="grp_overview"):
                dpg.add_text("Ledger", bullet=True)
                with dpg.table(header_row=True, row_background=True,
                               borders_innerH=True, borders_innerV=True):
                    for col in ("documents", "evidence", "clusters", "verdicts"):
                        dpg.add_table_column(label=col)
                    with dpg.table_row():
                        for tag in ("t_docs", "t_ev", "t_cl", "t_vr"):
                            dpg.add_text(tag=tag)
                dpg.add_text("Spend", bullet=True)
                dpg.add_text(tag="t_total")
                dpg.add_text(tag="t_split")
                dpg.add_spacer(height=4)
                dpg.add_text("Pending", bullet=True)
                dpg.add_text(tag="t_pend_extract")
                dpg.add_text(tag="t_pend_verdict")
                dpg.add_text(tag="t_pend_total", color=(230, 180, 60))
                dpg.add_text("Recent runs", bullet=True)
                with dpg.table(tag="t_runs", header_row=True,
                               row_background=True, borders_innerH=True,
                               borders_innerV=True):
                    for col in ("at", "stage", "model", "calls", "usd"):
                        dpg.add_table_column(label=col)
                dpg.add_text(tag="t_last_rem")

        with dpg.window(tag="win_parts", label="Model & Make", pos=(0, 400),
                        width=560, height=360):
            dpg.add_combo(tag="combo_part", label="part",
                          callback=lambda s, a, u: self._show_part(a),
                          width=-1)
            dpg.add_text(tag="t_part_title")
            with dpg.group(horizontal=True):
                dpg.add_text("Variants: ")
                dpg.add_text(tag="t_part_variants", wrap=0)
            dpg.add_text("Claims", bullet=True)
            with dpg.table(tag="t_part_claims", header_row=True,
                           row_background=True, borders_innerH=True,
                           borders_innerV=True, resizable=True):
                for col in ("title", "severity", "domain"):
                    dpg.add_table_column(label=col)

        with dpg.window(tag="win_sources", label="Sources", pos=(560, 0),
                        width=560, height=760):
            dpg.add_listbox(tag="list_docs", num_items=16,
                            callback=self._doc_picked, width=-1)
            dpg.add_text("Selected document", bullet=True)
            dpg.add_text(tag="t_doc_meta", wrap=0)
            with dpg.child_window(tag="doc_view", height=300, autosize_x=True,
                                  border=True):
                dpg.add_text(tag="t_doc_text", wrap=100)

        with dpg.window(tag="win_extract", label="Extraction / Runs",
                        pos=(1120, 0), width=560, height=760):
            dpg.add_text("Pending work", bullet=True)
            dpg.add_text(tag="t_pend_extract2")
            dpg.add_text(tag="t_pend_verdict2")
            dpg.add_text("Run controls (costs enforced by --max-usd)",
                         bullet=True)
            dpg.add_input_float(tag="inp_cap", label="extract max-usd",
                                default_value=0.05, step=0.01, width=-1)
            with dpg.group(horizontal=True):
                dpg.add_button(label="extract (capped)",
                               callback=lambda: self._btn_extract())
                dpg.add_button(label="import verdicts ($0)",
                               callback=lambda: self._btn_import())
                dpg.add_button(label="full $0 pass",
                               callback=lambda: self._btn_pass())
            with dpg.group(horizontal=True):
                dpg.add_button(label="remediate ($0)",
                               callback=lambda: self._btn_remediate())
                dpg.add_button(label="export",
                               callback=lambda: self._btn_export())
            dpg.add_text("Output", bullet=True)
            with dpg.child_window(tag="log_win", height=340, autosize_x=True,
                                  border=True):
                dpg.add_text(tag="log_text", wrap=0)

        with dpg.window(tag="win_ledger", label="Ledger browser",
                        pos=(0, 760), width=1120, height=200):
            dpg.add_combo(tag="combo_table", label="table",
                          items=self.ledger_tables, width=-1)
            dpg.add_text(tag="t_ledger_preview", wrap=0)

        with dpg.window(tag="win_scaffold", label="Scaffold / Coverage",
                        pos=(560, 760), width=1120, height=200):
            dpg.add_text(tag="t_findings_count")
            with dpg.table(tag="t_findings", header_row=True,
                           row_background=True, borders_innerH=True,
                           borders_innerV=True, resizable=True,
                           scrollY=True):
                for col in ("kind", "subject", "part", "message"):
                    dpg.add_table_column(label=col)

    def tick(self) -> None:
        self.poll()
        if self.doc_selected is not None:
            try:
                conn = db.connect(LEDGER_PATH)
                doc = metrics.document(conn, self.doc_selected)
                conn.close()
            except Exception:
                doc = None
            if doc:
                dpg.set_value("t_doc_meta",
                              f"{doc['url']}  [{doc['source_type']}, "
                              f"{doc['lang'] or '?'}] target={doc['target_hint']}")
                dpg.set_value("t_doc_text",
                              (doc["raw_text"] or "")[:20000])
        table = dpg.get_value("combo_table")
        if table:
            try:
                conn = db.connect(LEDGER_PATH)
                rows = conn.execute(f"SELECT * FROM {table} LIMIT 8").fetchall()
                conn.close()
            except Exception:
                rows = []
            if rows:
                cols = rows[0].keys()
                head = " | ".join(cols)
                body = "\n".join(" | ".join(str(r[c])[:40] for c in cols)
                                 for r in rows)
                dpg.set_value("t_ledger_preview", head + "\n" + body)


def main() -> None:
    dpg.create_context()
    hub = Hub()
    hub.build()
    dpg.create_viewport(title="kriko-hub", width=1700, height=990,
                        resizable=True, min_width=1200, min_height=800)
    dpg.setup_dearpygui()
    dpg.show_viewport()
    hub.refresh()
    last = 0.0
    while dpg.is_dearpygui_running():
        now = time.monotonic()
        if now - last >= 1.0:
            hub.refresh()
            hub.tick()
            last = now
        dpg.render_dearpygui_frame()
    dpg.destroy_context()


if __name__ == "__main__":
    main()
