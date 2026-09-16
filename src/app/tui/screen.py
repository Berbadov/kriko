"""One frame, as a pure function of state. No terminal in this file.

Everything that decides *what the operator sees* lives here and returns a list
of strings; `term.py` puts them on the glass. That split is the only reason any
of this is testable — `tests/test_tui.py` asserts on frames, not on a tty.

**The layout answers one question per band.** Top: which engine am I attached
to, and is the harness plane actually usable. Middle: the list for the current
tab. Bottom: the detail for the selected row, which for a job is its live log.
Last line: what just happened, or what went wrong.

Colour is applied *after* padding, never before. A frame is diffed by string
equality and truncated by width, and an SGR sequence counted as four visible
characters would corrupt both — so `pad` works on plain text and `style`
wraps the finished cell.
"""

from app.tui.term import ESC

BOLD = "1"
DIM = "2"
REVERSE = "7"
RED = "31"
GREEN = "32"
YELLOW = "33"
BLUE = "34"

#: The tabs, in the order the number keys select them.
TABS = ("planes", "agenda", "jobs", "ops")

#: State names the engine's job rows use, and how each should read.
JOB_COLOURS = {
    "succeeded": GREEN, "failed": RED, "cancelled": YELLOW,
    "running": BLUE, "queued": DIM, "interrupted": YELLOW,
}

#: `operations.state` uses a smaller vocabulary than `jobs.state`
#: (`running | ok | failed`) — same colours where the words overlap.
OP_COLOURS = {"ok": GREEN, "failed": RED, "running": BLUE}


def style(text: str, *codes: str) -> str:
    if not codes or not text:
        return text
    return f"{ESC}[{';'.join(codes)}m{text}{ESC}[0m"


def pad(text: str, width: int) -> str:
    """Exactly `width` visible characters, truncating with an ellipsis.

    `width` can arrive non-positive, and the arithmetic here used to go wrong
    in a way that looked like corruption rather than a bug: `text[:width - 1]`
    with a negative width slices *from the end*, so a 17-character title in a
    width of -16 rendered as its first character. Found running the frozen
    console under a pty that reported no window size, which clamps to 20
    columns — and a terminal that reports nothing is exactly the case nobody
    tests interactively.
    """
    if width <= 0:
        return ""
    text = text.replace("\t", " ")
    if len(text) > width:
        return text[: width - 1] + "…" if width > 1 else text[:width]
    return text + " " * (width - len(text))


def rule(width: int) -> str:
    return style("─" * width, DIM)


def _plane_rows(data: dict) -> list[dict]:
    """One display row per plane, plus a row per harness binary found.

    The harness rows are the point of this screen. "Agent operations do
    nothing" is, more often than not, `locate()` finding no CLI — and the only
    way to tell that from "the CLI ran and found nothing" is to see whether a
    path is printed here.
    """
    rows = []
    for plane in data.get("planes", []):
        ready = plane.get("ready")
        rows.append({
            "kind": "plane",
            "id": plane.get("id", ""),
            "ready": bool(ready),
            "cost": plane.get("cost_basis", ""),
            "what": plane.get("what", ""),
            "default": plane.get("id") == data.get("default"),
        })
        for harness in plane.get("harnesses", []):
            rows.append({
                "kind": "harness",
                "id": harness.get("id", ""),
                "ready": True,
                "cost": harness.get("label", ""),
                "what": harness.get("path") or harness.get("command", ""),
                "default": False,
            })
        for harness in plane.get("unusable", []):
            rows.append({
                "kind": "unusable",
                "id": harness.get("id", ""),
                "ready": False,
                "cost": harness.get("label", ""),
                "what": harness.get("why", ""),
                "default": False,
            })
        if plane.get("id") == "harness" and not plane.get("harnesses"):
            looked = ", ".join(plane.get("looked_for", [])) or "nothing"
            rows.append({
                "kind": "unusable",
                "id": "none found",
                "ready": False,
                "cost": "",
                "what": f"looked for: {looked}",
                # The row says *that* nothing was found; the detail band says
                # where it looked, which is the half an operator can act on.
                # It goes in the band because the band wraps and a row does
                # not — a truncated remedy is not a remedy.
                "detail": f"No coding-agent CLI found. Looked for {looked} on PATH, "
                          f"in $KRIKO_HARNESS_DIRS, and in the directories these "
                          f"CLIs install themselves into. If one is installed "
                          f"somewhere else, set KRIKO_HARNESS_DIRS to its folder "
                          f"and press r.",
                "default": False,
            })
    return rows


def rows_for(tab: str, data: dict) -> list[dict]:
    """The selectable rows of a tab. The list pane and every key that moves a
    cursor read this, so a tab cannot disagree with its own cursor."""
    if tab == "planes":
        return _plane_rows(data.get("planes") or {})
    if tab == "agenda":
        return list((data.get("agenda") or {}).get("rows", []))
    if tab == "jobs":
        return list((data.get("jobs") or {}).get("items", []))
    if tab == "ops":
        return list((data.get("ops") or {}).get("items", []))
    return []


def _line_planes(row: dict, width: int) -> str:
    mark = "●" if row["ready"] else "○"
    colour = GREEN if row["ready"] else (DIM if row["kind"] == "plane" else YELLOW)
    left = f"{mark} {row['id']:<14} {row['cost']:<22}"
    text = pad(f"{left} {row['what']}", width)
    if row["kind"] == "plane":
        return style(text, BOLD) if row["default"] else text
    return style(text, colour)


def _line_agenda(row: dict, width: int) -> str:
    label = row.get("label") or row.get("identity") or row.get("subject_id") or "—"
    asked = row.get("asked", 0)
    text = f"{row.get('kind', ''):<16} {asked:>4} asked  {label}"
    return pad(text, width)


def _line_jobs(row: dict, width: int) -> str:
    state = row.get("state", "")
    progress = row.get("progress") or 0
    bar = f"{int(progress * 100):>3}%" if state == "running" else "    "
    text = pad(
        f"{state:<11} {bar} {row.get('kind', ''):<13} {row.get('message', '')}", width
    )
    return style(text, JOB_COLOURS.get(state, "")) if state in JOB_COLOURS else text


def _line_ops(row: dict, width: int) -> str:
    state = row.get("state", "")
    cost = ""
    if row.get("usd"):
        cost = f"${row['usd']:.2f}"
    elif row.get("tokens"):
        cost = f"{row['tokens']}tok"
    text = pad(
        f"{state:<8} {row.get('door', ''):<5} {row.get('kind', ''):<10} "
        f"{cost:<8} {row.get('name', '')}",
        width,
    )
    return style(text, OP_COLOURS.get(state, "")) if state in OP_COLOURS else text


LINES = {"planes": _line_planes, "agenda": _line_agenda, "jobs": _line_jobs,
         "ops": _line_ops}


def detail_for(tab: str, row: dict | None, data: dict) -> list[str]:
    """What the bottom band says about the selected row."""
    if row is None:
        return ["nothing selected"]
    if tab == "planes":
        return [row.get("detail") or row.get("what", "")]
    if tab == "agenda":
        lines = [row.get("why", "")]
        subject = row.get("subject_id") or ""
        if subject:
            lines.append(f"subject: {subject}   pack: {row.get('pack_id', '')}")
        if not subject:
            lines.append(
                "no subject id — this row is a message to the catalog, not a task "
                "an agent can be given"
            )
        return lines
    if tab == "jobs":
        log = (data.get("log") or {}).get(row.get("job_id", "")) or row.get("log") or ""
        lines = [line for line in log.splitlines() if line]
        return lines or [row.get("message", "") or "no output yet"]
    if tab == "ops":
        lines = [f"subject: {row.get('subject_id') or '—'}   "
                 f"pack: {row.get('pack_id') or '—'}   "
                 f"started: {row.get('started_at', '')}"]
        if row.get("error"):
            lines.append(f"error: {row['error']}")
        elif row.get("response_json"):
            lines.append(row["response_json"])
        return lines
    return []


def wrap(text: str, width: int) -> list[str]:
    words, lines, current = text.split(), [], ""
    for word in words:
        if current and len(current) + 1 + len(word) > width:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)
    return lines or [""]


def header(state, width: int) -> list[str]:
    # The address goes before the name does. `engine_label` is a URL and can
    # easily be wider than a narrow terminal on its own, and a header that
    # spends every column on "http://127.0.0.1:40201 (own engine)" has told the
    # reader nothing about what they are looking at.
    where = state.engine_label
    if len(where) + len("kriko · agent ops") + 1 > width:
        where = ""
    # The tab bar is the one row with no padding to absorb an overflow — three
    # named tabs are 30 columns and will not fit an 80-column terminal's
    # narrower cousins. Names first, numbers alone when they do not fit, and
    # `pad` on the whole thing as the floor.
    labels = [f" {index} {name} " for index, name in enumerate(TABS, start=1)]
    if sum(len(label) for label in labels) > width:
        labels = [f" {index} " for index in range(1, len(TABS) + 1)]
    tabs, used = [], 0
    for label, name in zip(labels, TABS):
        if used + len(label) > width:
            break
        used += len(label)
        tabs.append(style(label, REVERSE if name == state.tab else DIM))
    bar = "".join(tabs) + " " * (width - used)
    title = pad("kriko · agent ops", max(0, width - len(where)))
    return [
        style(title, BOLD) + style(where, DIM),
        bar,
        rule(width),
    ]


def footer(state, width: int) -> list[str]:
    keys = {
        "planes": "r refresh · s shell · q quit",
        "agenda": "enter research · a run whole agenda · r refresh · s shell · q quit",
        "jobs": "enter follow · c cancel · R retry · r refresh · s shell · q quit",
        "ops": "r refresh · s shell · q quit",
    }[state.tab]
    message = state.error or state.status
    colour = RED if state.error else DIM
    return [rule(width), style(pad(keys, width), DIM), style(pad(message, width), colour)]


def render(state, width: int, height: int) -> list[str]:
    """The whole frame. Never longer than `height`, never wider than `width`."""
    top = header(state, width)
    bottom = footer(state, width)
    rows = rows_for(state.tab, state.data)
    selected = state.cursor.get(state.tab, 0)
    if rows:
        selected = max(0, min(selected, len(rows) - 1))

    detail_height = max(3, min(10, (height - len(top) - len(bottom)) // 3))
    list_height = height - len(top) - len(bottom) - detail_height - 1
    list_height = max(1, list_height)

    # Scroll so the cursor is always on screen, without moving when it does not
    # have to — a list that re-centres on every keypress is unreadable.
    first = max(0, min(state.scroll.get(state.tab, 0), max(0, len(rows) - list_height)))
    if selected < first:
        first = selected
    elif selected >= first + list_height:
        first = selected - list_height + 1
    state.scroll[state.tab] = first

    body = []
    line_of = LINES[state.tab]
    window = rows[first : first + list_height]
    for index, row in enumerate(window):
        text = line_of(row, width - 2)
        prefix = style("▸ ", BLUE) if first + index == selected else "  "
        body.append(prefix + (style(text, REVERSE) if first + index == selected else text))
    if not rows:
        body.append(style(pad("  " + _empty(state), width), DIM))
    while len(body) < list_height:
        body.append("")

    detail = detail_for(state.tab, rows[selected] if rows else None, state.data)
    wrapped: list[str] = []
    for line in detail:
        wrapped.extend(wrap(line, width - 2) if len(line) > width - 2 else [line])
    # The tail, not the head: a job's log is interesting at the end.
    wrapped = wrapped[-detail_height:]
    detail_band = [rule(width)] + [pad("  " + line, width) for line in wrapped]
    while len(detail_band) < detail_height + 1:
        detail_band.append("")

    return (top + body + detail_band + bottom)[:height]


def _empty(state) -> str:
    return {
        "planes": "no planes reported — is the engine answering?",
        "agenda": "nothing to research: either no packs are installed, or "
                  "nothing has been asked for yet",
        "jobs": "no jobs yet — start one from the agenda tab",
        "ops": "no operations recorded yet — nothing has touched the "
               "knowledge through any door",
    }[state.tab]
