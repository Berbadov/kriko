"""discover.py — YouTube source discovery TUI for Kriko.

Search YouTube for mechanic videos, preview transcripts in-terminal, and
approve or skip them. Approved videos are written to the curated YAML as
status=pending, ready to be processed by knowledge.process.

Usage:
    python -m knowledge.discover --make renault --model megane
    python -m knowledge.discover "megane 4 1.5 dCi arıza" --make renault --model megane

Keys:
    ↑↓      Navigate list
    Enter   Run selected suggestion OR fetch transcript for selected video
    A       Approve video → add to curated YAML as pending
    S       Skip (session only, no file write)
    T       View full transcript overlay
    P       Open suggested searches panel
    F5      Focus search input for new query
    Q       Quit
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT   = Path(__file__).parent.parent
CURATED_DIR = Path(__file__).parent / "sources" / "curated"
VARIANTS_DIR = REPO_ROOT / "backend" / "data" / "variants"


# ── Search template generator ─────────────────────────────────────────────────

def _generate_templates(make: str, model: str, gen: str) -> list[tuple[str, str]]:
    """Read variants YAML and produce suggested search queries by domain."""
    matches = sorted(VARIANTS_DIR.glob(f"{make}_{model}_{gen}.yaml"))
    rows: list[dict] = []
    gen_label_suffix = ""
    if matches:
        rows = yaml.safe_load(matches[0].read_text()) or []
        gen_label_suffix = rows[0].get("generation", gen) if rows else gen
    else:
        gen_label_suffix = gen

    make_t  = make.title()
    model_t = model.title()
    gen_label = f"{make_t} {model_t} {gen_label_suffix}".strip()

    templates: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(domain: str, query: str) -> None:
        if query not in seen:
            seen.add(query)
            templates.append((domain, query))

    # ── General / model-wide ──────────────────────────────────────────────────
    add("general",    f"{gen_label} arıza")
    add("general",    f"{gen_label} sorun")
    add("general",    f"{make_t} {model_t} common problems reliability")
    add("general",    f"{make_t} {model_t} used car problems forum owners")
    add("general",    f"{make_t} {model_t} buying guide used reliability issues")
    add("general",    f"{gen_label} kronik sorunları deneyimler")

    # ── Per engine code ───────────────────────────────────────────────────────
    engine_fuel: dict[str, str] = {}
    engine_cc:   dict[str, int] = {}
    for r in rows:
        ec = r.get("engine_code", "")
        if ec:
            engine_fuel[ec] = r.get("fuel", "")
            engine_cc[ec]   = r.get("displacement_cc", 0)

    for ec in sorted(engine_fuel):
        fuel = engine_fuel[ec]
        cc   = engine_cc[ec]
        litre = f"{cc / 1000:.1f}" if cc else ""

        add("engine", f"{ec} motor arıza")
        add("engine", f"{ec} engine problem reliability forum")
        add("engine", f"{make_t} {model_t} {ec} chronic and common problems")

        # ── Cooling/Thermostat (fuel-agnostic) ────────────────────────────────
        add("engine", f"{ec} water pump thermostat failure")
        add("engine", f"{ec} termostat arıza")

        if fuel == "diesel":
            add("engine",    f"{ec} EGR valve clogging {model_t}")
            add("engine",    f"{ec} EGR sorun")
            add("engine",    f"{ec} enjektör arıza")
            add("engine",    f"{litre} dCi {model_t} sorun")
            add("engine",    f"{litre} dCi timing belt replacement interval {model_t}")
            add("emissions", f"{ec} DPF clogging regeneration failure {model_t}")
            add("emissions", f"{ec} DPF sorun")
            add("emissions", f"{ec} AdBlue pump crystallization failure {model_t}")
            add("emissions", f"{ec} AdBlue sorun")
        elif fuel == "petrol":
            add("engine", f"{ec} timing chain tensioner failure {model_t}")
            add("engine", f"{ec} oil consumption turbo {model_t}")
            add("engine", f"{litre} TCe {model_t} arıza")
            add("engine", f"{litre} TCe {model_t} reliability problems known issues")
        elif fuel == "hybrid":
            add("engine", f"{ec} hybrid battery sorun")
            add("engine", f"{gen_label} hybrid arıza")

    # ── Transmission ──────────────────────────────────────────────────────────
    transmissions = sorted({r.get("transmission", "") for r in rows if r.get("transmission")})
    trans_codes = sorted({r.get("transmission_code", "") for r in rows if r.get("transmission_code")})

    for tr in transmissions:
        if tr == "automatic":
            add("gearbox", f"{gen_label} EDC sorun")
            add("gearbox", f"{gen_label} çift kavrama arıza")
            add("gearbox", f"{make_t} {model_t} automatic gearbox problem reliability")
            add("gearbox", f"{make_t} EDC dual clutch clutch pack wear problems")
            add("gearbox", f"{make_t} EDC mechatronics transmission repair")
        elif tr == "manual":
            add("gearbox", f"{gen_label} manuel vites sorun")

    for tc in trans_codes:
        if tc != "manual":
            tc_upper = tc.upper()
            add("gearbox", f"{gen_label} {tc_upper} sorun")
            add("gearbox", f"{make_t} {model_t} {tc_upper} gearbox problem reliability")
            add("gearbox", f"{make_t} {tc_upper} dual clutch clutch pack wear problems")
            add("gearbox", f"{make_t} {tc_upper} mechatronics transmission repair")
            add("gearbox", f"{make_t} {model_t} {tc_upper} chronic and common problems")

    # ── Electrical / electronics ──────────────────────────────────────────────
    add("cooling",    f"{make_t} {model_t} Cooling chronic problems")
    add("electrical", f"{make_t} {model_t} electronics chronic problems")
    add("electrical", f"{gen_label} elektrik arıza")
    add("electrical", f"{gen_label} electronic problem")

    # ── Body & suspension ─────────────────────────────────────────────────────
    add("suspension", f"{gen_label} süspansiyon sorun")
    add("suspension", f"{gen_label} salıncak rot rotil")
    add("suspension", f"{gen_label} front suspension wishbone ball joint failure")
    add("suspension", f"{gen_label} anti roll bar stabiliser link clunk")
    add("body",       f"{gen_label} pas sorun")

    # ── Climate / HVAC ────────────────────────────────────────────────────────
    add("hvac", f"{gen_label} klima sorun")
    add("hvac", f"{gen_label} AC condenser failure refrigerant leak")

    return templates


# ── YouTube search (yt-dlp, no API key) ──────────────────────────────────────

def _search_youtube(query: str, max_results: int = 20) -> list[dict]:
    try:
        import yt_dlp
    except ImportError:
        return []
    opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "playlist_items": f"1-{max_results}",
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f"ytsearch{max_results}:{query}", download=False)
            return [v for v in (info.get("entries") or []) if v and v.get("id")]
    except Exception:
        return []


def _load_known_ids() -> set[str]:
    ids: set[str] = set()
    if not CURATED_DIR.exists():
        return ids
    for path in CURATED_DIR.glob("*.yaml"):
        try:
            for e in (yaml.safe_load(path.read_text()) or []):
                if e.get("type") == "youtube" and e.get("video_id"):
                    ids.add(e["video_id"])
        except Exception:
            pass
    return ids


def _fmt_dur(sec: Any) -> str:
    if not sec:
        return "  --:--"
    s = int(sec)
    return f"{s // 60:3d}:{s % 60:02d}"


def _write_approved(video: dict, make: str, model: str, gen: str) -> None:
    CURATED_DIR.mkdir(parents=True, exist_ok=True)
    path = CURATED_DIR / f"{make}_{model}_{gen}.yaml"
    existing: list[dict] = []
    if path.exists():
        existing = yaml.safe_load(path.read_text()) or []
    existing.append({
        "type": "youtube",
        "video_id": video["id"],
        "site_or_channel": (video.get("channel") or video.get("uploader") or "YouTube")[:60],
        "tier": "C",
        "notes": (video.get("title") or "")[:80],
        "status": "pending",
        "added_at": str(date.today()),
        "processed_at": None,
    })
    path.write_text(yaml.dump(existing, allow_unicode=True, sort_keys=False))


# ── Textual TUI ───────────────────────────────────────────────────────────────

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import ScrollableContainer, Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Footer, Header, Input, Label, Static


class TranscriptScreen(ModalScreen[None]):
    """Full-screen scrollable transcript overlay."""

    BINDINGS = [Binding("escape", "dismiss", "Close")]

    def __init__(self, title: str, text: str) -> None:
        super().__init__()
        self._title = title
        self._text  = text

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-wrap"):
            yield Label(f" {self._title} ", id="modal-title")
            with ScrollableContainer(id="modal-scroll"):
                yield Static(self._text, id="modal-body")
            yield Label(" [Esc] Close ", id="modal-hint")

    DEFAULT_CSS = """
    TranscriptScreen { align: center middle; }
    #modal-wrap {
        width: 90%; height: 85%;
        background: $surface; border: double $primary; padding: 0 1;
    }
    #modal-title { text-style: bold; background: $primary; color: $text; padding: 0 1; }
    #modal-scroll { height: 1fr; }
    #modal-body   { padding: 1; }
    #modal-hint   { background: $surface; color: $text-muted; padding: 0 1; }
    """


class SuggestionsScreen(ModalScreen[str | None]):
    """Suggested search queries generated from the variants YAML."""

    BINDINGS = [Binding("escape", "dismiss", "Close")]

    def __init__(self, templates: list[tuple[str, str]]) -> None:
        super().__init__()
        self._templates = templates

    def compose(self) -> ComposeResult:
        with Vertical(id="sug-wrap"):
            yield Label(" Suggested Searches — Enter to run, Esc to close ", id="sug-title")
            yield DataTable(id="sug-table", cursor_type="row", zebra_stripes=True)
            yield Label(
                f" {len(self._templates)} queries across "
                f"{len({d for d, _ in self._templates})} domains ",
                id="sug-hint",
            )

    def on_mount(self) -> None:
        t = self.query_one("#sug-table", DataTable)
        t.add_column("Domain", key="domain", width=12)
        t.add_column("Query",  key="query",  width=60)
        for i, (domain, query) in enumerate(self._templates):
            t.add_row(domain, query, key=str(i))
        t.focus()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        idx = int(event.row_key.value)
        self.dismiss(self._templates[idx][1])

    DEFAULT_CSS = """
    SuggestionsScreen { align: center middle; }
    #sug-wrap {
        width: 82%; height: 82%;
        background: $surface; border: double $accent; padding: 0 1;
    }
    #sug-title { text-style: bold; background: $accent; color: $text; padding: 0 1; }
    #sug-table { height: 1fr; }
    #sug-hint  { background: $surface; color: $text-muted; padding: 0 1; }
    """


class DiscoverApp(App[None]):
    """Kriko · YouTube Source Discovery"""

    TITLE = "Kriko · Source Discovery"

    BINDINGS = [
        Binding("a",      "approve",          "Approve",      show=True),
        Binding("s",      "skip_video",       "Skip",         show=True),
        Binding("t",      "view_transcript",  "Transcript",   show=True),
        Binding("p",      "suggestions",      "Suggestions",  show=True),
        Binding("f5",     "new_search",       "New search",   show=True),
        Binding("q",      "quit",             "Quit",         show=True),
    ]

    DEFAULT_CSS = """
    #top-bar {
        height: 5; background: $surface; layout: horizontal; padding: 1 2;
    }
    #query-input { width: 4fr; }
    #make-input  { width: 1fr; margin-left: 1; }
    #model-input { width: 1fr; margin-left: 1; }
    #results     { height: 1fr; border: solid $primary; }
    #preview-panel {
        height: 7; border: solid $accent;
        overflow-y: scroll; padding: 0 1; background: $surface;
    }
    #status { height: 1; padding: 0 1; background: $surface; color: $text-muted; }
    """

    def __init__(self, query: str, make: str, model: str, gen: str) -> None:
        super().__init__()
        self._query0     = query
        self._make       = make
        self._model      = model
        self._gen        = gen
        self._videos: list[dict]        = []
        self._row_status: dict[int, str] = {}
        self._transcripts: dict[str, str] = {}
        self._known_ids: set[str]        = _load_known_ids()
        self._cur_row: int               = 0
        self._templates                  = _generate_templates(make, model, gen)

    # ── Compose ───────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="top-bar"):
            yield Input(self._query0, placeholder="Search query… (P for suggestions)", id="query-input")
            yield Input(self._make,   placeholder="make",  id="make-input")
            yield Input(self._model,  placeholder="model", id="model-input")
            yield Input(self._gen,    placeholder="gen (e.g. 4, e210, mk3)", id="gen-input")
        yield DataTable(id="results", cursor_type="row", zebra_stripes=True)
        yield Static("", id="preview-panel")
        yield Static("", id="status")
        yield Footer()

    def on_mount(self) -> None:
        t = self.query_one("#results", DataTable)
        t.add_column("#",        key="num",     width=4)
        t.add_column("St",       key="st",      width=3)
        t.add_column("Channel",  key="channel", width=22)
        t.add_column("Title",    key="title",   width=58)
        t.add_column("Duration", key="dur",     width=7)

        if self._query0:
            self._do_search(self._query0)
        else:
            # auto-open suggestions on first launch
            self.call_after_refresh(self.action_suggestions)

    # ── Search ────────────────────────────────────────────────────────────────

    def _do_search(self, query: str) -> None:
        self.query_one("#query-input", Input).value = query
        self._set_status(f"Searching: {query!r} …")
        self._search_worker(query)

    @work(thread=True, exclusive=True, group="search")
    def _search_worker(self, query: str) -> None:
        results = _search_youtube(query)
        self.call_from_thread(self._populate, results)

    def _populate(self, videos: list[dict]) -> None:
        self._videos = videos
        self._row_status = {}
        t = self.query_one("#results", DataTable)
        t.clear()
        for i, v in enumerate(videos):
            vid_id = v.get("id", "")
            st = "✗" if vid_id in self._known_ids else "·"
            self._row_status[i] = st
            t.add_row(
                str(i + 1), st,
                (v.get("channel") or v.get("uploader") or "")[:22],
                (v.get("title") or "")[:58],
                _fmt_dur(v.get("duration")),
                key=str(i),
            )
        n = len(videos)
        self._set_status(
            f"{n} result(s) — ↑↓ navigate · Enter transcript · A approve · S skip · P suggestions · Q quit"
        )

    # ── Transcript ────────────────────────────────────────────────────────────

    def on_key(self, event) -> None:
        if event.key == "enter":
            self._fetch_transcript_for_current()

    def _fetch_transcript_for_current(self) -> None:
        if not self._videos:
            return
        v      = self._videos[self._cur_row]
        vid_id = v.get("id", "")
        if vid_id in self._transcripts:
            self._show_preview(vid_id)
            return
        self._set_status(f"Fetching transcript: {v.get('title', '')[:55]}…")
        self._transcript_worker(vid_id)

    @work(thread=True, group="transcript")
    def _transcript_worker(self, video_id: str) -> None:
        from knowledge.sources.youtube import get_transcript
        text = get_transcript(video_id)
        self.call_from_thread(self._on_transcript, video_id, text)

    def _on_transcript(self, video_id: str, text: str | None) -> None:
        if text:
            self._transcripts[video_id] = text
            self._show_preview(video_id)
            self._set_status(f"Transcript loaded ({len(text):,} chars) — T for full view")
        else:
            self.query_one("#preview-panel", Static).update(
                "[dim]No transcript available for this video.[/dim]"
            )
            self._set_status("No transcript found.")

    def _show_preview(self, video_id: str) -> None:
        text    = self._transcripts.get(video_id, "")
        preview = text[:500] + (" …" if len(text) > 500 else "")
        self.query_one("#preview-panel", Static).update(preview)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        self._cur_row = int(event.row_key.value)
        v = self._videos[self._cur_row] if self._cur_row < len(self._videos) else {}
        vid_id = v.get("id", "")
        if vid_id in self._transcripts:
            self._show_preview(vid_id)
        else:
            self.query_one("#preview-panel", Static).update(
                f"[dim]{v.get('title','')}[/dim]\n[dim]Press Enter to fetch transcript.[/dim]"
            )

    # ── Actions ───────────────────────────────────────────────────────────────

    def action_approve(self) -> None:
        if not self._videos:
            return
        v      = self._videos[self._cur_row]
        vid_id = v.get("id", "")
        if vid_id in self._known_ids:
            self._set_status(f"Already in curated YAML: {vid_id}")
            return
        make  = self.query_one("#make-input",  Input).value.strip().lower()
        model = self.query_one("#model-input", Input).value.strip().lower()
        gen   = self.query_one("#gen-input",   Input).value.strip().lower()
        _write_approved(v, make, model, gen)
        self._known_ids.add(vid_id)
        self._update_status_cell(self._cur_row, "✓")
        self._set_status(
            f"✓ Added to {make}_{model}_{gen}.yaml — run: python -m knowledge.process {make} {model} {gen}"
        )

    def action_skip_video(self) -> None:
        self._update_status_cell(self._cur_row, "—")
        self._set_status("Skipped.")

    def action_view_transcript(self) -> None:
        if not self._videos:
            return
        v      = self._videos[self._cur_row]
        vid_id = v.get("id", "")
        text   = self._transcripts.get(vid_id)
        if not text:
            self._set_status("No transcript loaded — press Enter first.")
            return
        self.push_screen(TranscriptScreen(v.get("title", vid_id), text))

    def action_suggestions(self) -> None:
        if not self._templates:
            self._set_status("No variant data found — add variants YAML first.")
            return

        def on_select(query: str | None) -> None:
            if query:
                self._do_search(query)

        self.push_screen(SuggestionsScreen(self._templates), on_select)

    def action_new_search(self) -> None:
        self.query_one("#query-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "query-input" and event.value.strip():
            self._do_search(event.value.strip())

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _update_status_cell(self, row_idx: int, value: str) -> None:
        self._row_status[row_idx] = value
        try:
            self.query_one("#results", DataTable).update_cell(str(row_idx), "st", value)
        except Exception:
            pass

    def _set_status(self, msg: str) -> None:
        try:
            self.query_one("#status", Static).update(msg)
        except Exception:
            pass


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Kriko YouTube source discovery TUI.")
    parser.add_argument("query", nargs="?", default="", help="Initial search query")
    parser.add_argument("--make",  required=True, help="Car make, e.g. renault, toyota")
    parser.add_argument("--model", required=True, help="Car model, e.g. megane, corolla")
    parser.add_argument("--gen",   required=True, help="Generation key, e.g. 4, e210, mk3")
    args = parser.parse_args()
    DiscoverApp(query=args.query, make=args.make, model=args.model, gen=args.gen).run()


if __name__ == "__main__":
    main()
