"""kriko-hub — DearPyGui dashboard for the ledger pipeline (B20).

    .venv/bin/python -m knowledge.hub.app

Single window, tab pages, fixed layout — deliberately no floating windows
and no docking (floating/docked windows broke on WSLg scaling: shapes
resized oddly, windows stacked over each other, clicks went nowhere).
One window fills the viewport; each page owns its fixed area; the tab bar
switches pages. Polled ~1s with fresh read-only ledger connections, so
anything the kriko_research agent (or a cron remediate pass) writes shows
up in real time.

  Overview   ledger counts, spend plot, cost-to-finish, recent runs
  Parts      part -> claims/variants drill-down
  Sources    documents -> raw text viewer
  Run        pending work + buttons (spawns `knowledge.ledger.run`)
  Ledger     generic read-only SQLite browser
  Coverage   coverage findings

Buttons run the CLI subprocesses (single source of truth for pipeline
logic) and stream their output into the log. Cost caps are enforced by the
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
MAX_LOG_CHARS = 30000
INIT_FILE = Path.home() / ".kriko-hub-layout.ini"  # kept unused; layout is fixed

# Colors — consistent dark palette with one accent.
_BG = (22, 23, 28, 255)
_BG_CHILD = (28, 30, 36, 255)
_BG_FRAME = (36, 39, 47, 255)
_BG_TABLE = (26, 28, 34, 255)
_TEXT = (226, 228, 234, 255)
_TEXT_DIM = (140, 145, 158, 255)
_ACCENT = (255, 138, 61, 255)
_BORDER = (48, 51, 60, 255)


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


def _apply_theme() -> None:
    with dpg.theme(tag="kriko_theme"):
        with dpg.theme_component(dpg.mvAll):
            for col, val in (
                (dpg.mvThemeCol_WindowBg, _BG),
                (dpg.mvThemeCol_ChildBg, _BG_CHILD),
                (dpg.mvThemeCol_PopupBg, _BG_CHILD),
                (dpg.mvThemeCol_FrameBg, _BG_FRAME),
                (dpg.mvThemeCol_FrameBgHovered, (44, 48, 58, 255)),
                (dpg.mvThemeCol_FrameBgActive, (52, 57, 69, 255)),
                (dpg.mvThemeCol_Text, _TEXT),
                (dpg.mvThemeCol_TextDisabled, _TEXT_DIM),
                (dpg.mvThemeCol_TextSelectedBg, (255, 138, 61, 70)),
                (dpg.mvThemeCol_Button, (46, 50, 60, 255)),
                (dpg.mvThemeCol_ButtonHovered, (62, 67, 80, 255)),
                (dpg.mvThemeCol_ButtonActive, (86, 92, 108, 255)),
                (dpg.mvThemeCol_Header, (48, 52, 63, 255)),
                (dpg.mvThemeCol_HeaderHovered, (62, 67, 80, 255)),
                (dpg.mvThemeCol_HeaderActive, (86, 92, 108, 255)),
                (dpg.mvThemeCol_CheckMark, _ACCENT),
                (dpg.mvThemeCol_SliderGrab, _ACCENT),
                (dpg.mvThemeCol_SliderGrabActive, (255, 160, 100, 255)),
                (dpg.mvThemeCol_Tab, _BG_FRAME),
                (dpg.mvThemeCol_TabHovered, (52, 57, 69, 255)),
                (dpg.mvThemeCol_TabActive, (46, 50, 60, 255)),
                (dpg.mvThemeCol_TableHeaderBg, _BG_TABLE),
                (dpg.mvThemeCol_TableRowBg, _BG_TABLE),
                (dpg.mvThemeCol_TableRowBgAlt, (31, 33, 40, 255)),
                (dpg.mvThemeCol_Border, _BORDER),
                (dpg.mvThemeCol_BorderShadow, (0, 0, 0, 0)),
                (dpg.mvThemeCol_ScrollbarBg, _BG),
                (dpg.mvThemeCol_ScrollbarGrab, (58, 63, 75, 255)),
            ):
                dpg.add_theme_color(col, val)
            for col, val in (
                (dpg.mvPlotCol_AxisBg, _BG_CHILD),
                (dpg.mvPlotCol_AxisBgHovered, _BG_CHILD),
                (dpg.mvPlotCol_AxisBgActive, _BG_CHILD),
                (dpg.mvPlotCol_AxisGrid, _BORDER),
                (dpg.mvPlotCol_AxisText, _TEXT_DIM),
                (dpg.mvPlotCol_AxisTick, _TEXT_DIM),
                (dpg.mvPlotCol_FrameBg, _BG_CHILD),
                (dpg.mvPlotCol_LegendBg, _BG_CHILD),
            ):
                dpg.add_theme_color(col, val, category=dpg.mvThemeCat_Plots)
            dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 5)
            dpg.add_theme_style(dpg.mvStyleVar_GrabRounding, 4)
            dpg.add_theme_style(dpg.mvStyleVar_WindowBorderSize, 0)
            dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 7, 5)
            dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 8, 6)
    dpg.bind_theme("kriko_theme")


def _font_scale(screen_h: int) -> float:
    """HiDPI: WSLg exposes a huge virtual X screen; without a scale the UI
    renders unreadably small. Override with KRIKO_HUB_FONT_SCALE."""
    env = os.environ.get("KRIKO_HUB_FONT_SCALE")
    if env:
        return float(env)
    return max(1.0, min(round(screen_h / 800, 1), 2.2))


def _screen_size() -> tuple[int, int]:
    """Logical screen size via tkinter (X/GLFW have no monitor API here)."""
    try:
        import tkinter
        root = tkinter.Tk()
        w, h = root.winfo_screenwidth(), root.winfo_screenheight()
        root.destroy()
        return int(w), int(h)
    except Exception:
        return 1700, 990


class Hub:
    def __init__(self) -> None:
        self.runs: list[dict] = []          # {proc, buf} for running subprocesses
        self.doc_selected: int | None = None
        self.doc_items: list[str] = []
        self.part_ids: list[str] = []
        self.ledger_tables = ["documents", "evidence", "clusters", "verdicts",
                              "resolutions", "evidence_flags", "runs"]
        self._spend_stages: list[str] | None = None

    # ── subprocess runner (Run page buttons) ─────────────────────────────────
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
        except Exception:  # ledger locked/absent — skip this tick
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
        stages = [r["stage"] for r in s["rows"]]
        usd = [r["usd"] for r in s["rows"]]
        if stages != self._spend_stages:  # rebuild only on change — no flicker
            self._spend_stages = stages
            if dpg.does_item_exist("plot_spend"):
                dpg.delete_item("plot_spend")
            if stages:
                x = list(range(len(stages)))
                plot = dpg.add_plot(label="Spend by stage (USD)",
                                    tag="plot_spend", height=220, width=-1,
                                    parent="page_overview")
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
        dpg.set_value("t_pend_total", f"COST TO FINISH ≈ ${p['extract_usd'] + p['verdict_usd']:.4f}")

    def _refresh_parts(self, conn) -> None:
        plist = metrics.parts(DATA_DIR)
        self.part_ids = [p["part_id"] for p in plist]
        dpg.configure_item("combo_part", items=self.part_ids)
        if self.part_ids and not dpg.get_value("combo_part"):
            dpg.set_value("combo_part", self.part_ids[0])
        cur = dpg.get_value("combo_part")
        if cur:
            self._show_part(cur)

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
        if app_data is None or app_data >= len(self.doc_items):
            return
        self.doc_selected = int(self.doc_items[app_data].split(" ", 1)[0][1:])

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

    # ── Run page buttons ─────────────────────────────────────────────────────
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

    # ── UI construction: one window, tab pages, fixed areas ──────────────────
    def build(self, vw: int, vh: int) -> None:
        tab_h = 26                          # tab bar strip
        page_h = vh - tab_h - 12            # usable page height (scrollable)
        with dpg.window(tag="main_win", label="kriko-hub", pos=(0, 0),
                        width=vw, height=vh, no_resize=True, no_move=True):
            with dpg.tab_bar(tag="tabs"):
                self._page_overview(tab_h, page_h)
                self._page_parts(tab_h, page_h)
                self._page_sources(tab_h, page_h)
                self._page_run(tab_h, page_h)
                self._page_ledger(tab_h, page_h)
                self._page_coverage(tab_h, page_h)

    def _page_overview(self, tab_h: int, page_h: int) -> None:
        with dpg.tab(label="Overview"):
            with dpg.child_window(tag="page_overview", height=page_h,
                                  autosize_x=True, border=False):
                with dpg.table(header_row=True, row_background=True,
                               borders_innerH=True, borders_innerV=True,
                               resizable=True):
                    for col in ("documents", "evidence", "clusters", "verdicts"):
                        dpg.add_table_column(label=col)
                    with dpg.table_row():
                        for tag in ("t_docs", "t_ev", "t_cl", "t_vr"):
                            dpg.add_text(tag=tag)
                dpg.add_text("Spend", bullet=True)
                dpg.add_text(tag="t_total")
                dpg.add_text(tag="t_split")
                dpg.add_text("Pending", bullet=True)
                dpg.add_text(tag="t_pend_extract")
                dpg.add_text(tag="t_pend_verdict")
                dpg.add_text(tag="t_pend_total", color=(230, 180, 60))
                dpg.add_text("Recent runs", bullet=True)
                with dpg.table(tag="t_runs", header_row=True,
                               row_background=True, borders_innerH=True,
                               borders_innerV=True, scrollY=True):
                    for col in ("at", "stage", "model", "calls", "usd"):
                        dpg.add_table_column(label=col)
                dpg.add_text(tag="t_last_rem")

    def _page_parts(self, tab_h: int, page_h: int) -> None:
        with dpg.tab(label="Parts"):
            with dpg.child_window(height=page_h, autosize_x=True, border=False):
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
                               borders_innerV=True, resizable=True,
                               scrollY=True):
                    for col in ("title", "severity", "domain"):
                        dpg.add_table_column(label=col)

    def _page_sources(self, tab_h: int, page_h: int) -> None:
        with dpg.tab(label="Sources"):
            with dpg.child_window(height=page_h, autosize_x=True, border=False):
                dpg.add_listbox(tag="list_docs", num_items=12,
                                callback=self._doc_picked, width=-1)
                dpg.add_text("Selected document", bullet=True)
                dpg.add_text(tag="t_doc_meta", wrap=0)
                with dpg.child_window(height=300, autosize_x=True, border=True):
                    dpg.add_text(tag="t_doc_text", wrap=100)

    def _page_run(self, tab_h: int, page_h: int) -> None:
        with dpg.tab(label="Run"):
            with dpg.child_window(height=page_h, autosize_x=True, border=False):
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
                with dpg.child_window(tag="log_win", height=page_h - 260,
                                      autosize_x=True, border=True):
                    dpg.add_text(tag="log_text", wrap=0)

    def _page_ledger(self, tab_h: int, page_h: int) -> None:
        with dpg.tab(label="Ledger"):
            with dpg.child_window(height=page_h, autosize_x=True, border=False):
                dpg.add_combo(tag="combo_table", label="table",
                              items=self.ledger_tables, width=-1)
                with dpg.child_window(height=page_h - 80, autosize_x=True,
                                      border=True):
                    dpg.add_text(tag="t_ledger_preview", wrap=0)

    def _page_coverage(self, tab_h: int, page_h: int) -> None:
        with dpg.tab(label="Coverage"):
            with dpg.child_window(height=page_h, autosize_x=True, border=False):
                dpg.add_text(tag="t_findings_count")
                with dpg.table(tag="t_findings", header_row=True,
                               row_background=True, borders_innerH=True,
                               borders_innerV=True, resizable=True,
                               scrollY=True):
                    for col in ("kind", "subject", "part", "message"):
                        dpg.add_table_column(label=col)

    # ── per-frame updates ────────────────────────────────────────────────────
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
                dpg.set_value("t_doc_text", (doc["raw_text"] or "")[:20000])
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
    sw, sh = _screen_size()
    # Cap the viewport to the screen and center it — everything inside is one
    # fixed window, so no floating-window state can ever go off-screen.
    vw = min(1700, max(sw - 60, 1000))
    vh = min(990, max(sh - 60, 700))
    hub = Hub()
    hub.build(vw, vh)
    _apply_theme()
    dpg.create_viewport(title="kriko-hub", width=vw, height=vh,
                        min_width=1000, min_height=700)
    dpg.setup_dearpygui()
    dpg.set_global_font_scale(_font_scale(sh))
    dpg.show_viewport()
    dpg.set_viewport_pos((max((sw - vw) // 2, 0), max((sh - vh) // 2, 0)))
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
