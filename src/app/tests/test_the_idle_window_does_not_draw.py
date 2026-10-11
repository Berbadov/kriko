"""A window with nothing happening draws nothing (#184).

GPUI's `AnimationElement` asks for the next frame until its animation is done,
and a `.repeat()` animation is never done. Every frame lays out and paints the
whole window, so one looping element anywhere on screen costs a CPU core for as
long as it is there. Installed 1.4.0, idle, window open behind another one:
10.38 CPU-seconds in 10 s. Three loops ran with no work at all: a 14 s
"breath" over the page head, the needs-you tag in the titlebar, and the
waiting marks inside the *closed* Live dock, all up for as long as a question
waits.

Three rules keep it from coming back, one test each:

* **Motion is decided once per frame, from the window.** `render` sets
  `motion` from the reader's setting *and* `window.is_window_active()`, so a
  window behind others, minimized or in the tray never loops. GPUI redraws on
  every activation change, so the loops come back on focus. A screen that
  reads `reduce_motion` itself would bypass that, so none may.
* **Only work indicators loop.** A spinner, a breathing ripple, a live meter's
  head, a progress sheen and an agent mark's phase are drawn while a job runs
  and gone when it ends. Anything else that loops is drawn while nothing
  happens; adding one means adding it here and saying why.
* **Waiting rests.** The needs-you tag blinks, and a waiting agent's mark
  breathes, a few rounds when they appear, then stay lit. A question can wait
  for days, and it is not work. The closed Live dock, still laid out at zero
  width for its slide, does not move at all.

These read the source with comments stripped, like the other shell tests
(`tools/gate.sh gpui` compiles it where there is a registry).
"""

from __future__ import annotations

import re
from pathlib import Path

CRATE = Path(__file__).resolve().parents[3] / "kriko-gpui"
SRC = CRATE / "src"

#: The functions allowed to hold a `.repeat()`: each draws only while work is
#: running, and is passed `motion`, so it is still when the window is not in
#: front. A new entry needs the same two properties.
WORK_INDICATORS = {
    ("theme.rs", "progress_bar"),
    ("theme.rs", "led_ripple"),
    ("theme.rs", "meter_live"),
    ("theme.rs", "spinner"),
    ("marks.rs", "mark_dots"),
}


def _code(path: Path) -> str:
    """The file with `//` comments stripped: a comment is not behaviour."""
    return "\n".join(
        re.sub(r"//.*$", "", line)
        for line in path.read_text(encoding="utf-8").splitlines()
    )


def _sources() -> list[Path]:
    return sorted(SRC.rglob("*.rs"))


def _block(source: str, opener: str) -> str:
    """The brace-balanced block starting at the first `{` after `opener`."""
    start = source.index("{", source.index(opener))
    depth = 0
    for i in range(start, len(source)):
        depth += {"{": 1, "}": -1}.get(source[i], 0)
        if depth == 0:
            return source[start : i + 1]
    raise AssertionError(f"unbalanced block after {opener!r}")


def test_render_decides_motion_from_the_setting_and_the_window():
    render = _block(_code(SRC / "app.rs"), "impl Render for Kriko")
    assert re.search(
        r"self\.motion\s*=\s*!self\.reduce_motion\s*&&\s*window\.is_window_active\(\)\s*;",
        render,
    ), "render must set `self.motion = !self.reduce_motion && window.is_window_active();`"
    # decided before anything draws, the boot screen included
    first_return = render.index("return")
    assert render.index("self.motion") < first_return


def test_no_screen_decides_motion_on_its_own():
    # the one decision in `render`, and Settings flipping the setting itself
    allowed = ("self.motion = !self.reduce_motion", "let on = !this.reduce_motion;")
    offenders = [
        f"{path.relative_to(SRC)}: {line.strip()}"
        for path in _sources()
        for line in _code(path).splitlines()
        if re.search(r"!\s*(?:self|app|this)\.reduce_motion\b", line)
        and not any(a in line for a in allowed)
    ]
    assert not offenders, (
        "read `app.motion`, which is also off while the window is not in front: "
        + ", ".join(offenders)
    )


def _functions_with_a_loop() -> set[tuple[str, str]]:
    found = set()
    for path in _sources():
        current = None
        for line in _code(path).splitlines():
            top = re.match(r"(?:pub(?:\([^)]*\))? )?fn (\w+)", line)
            if top:
                current = top.group(1)
            if ".repeat()" in line:
                found.add((path.name, current or "<module>"))
    return found


def test_only_work_indicators_loop():
    unexpected = _functions_with_a_loop() - WORK_INDICATORS
    assert not unexpected, (
        "a `.repeat()` animation redraws the whole window every frame for as "
        f"long as it is on screen; these loop outside a work indicator: {sorted(unexpected)}"
    )


def test_the_needs_you_blink_rests():
    theme = _code(SRC / "theme.rs")
    blink = theme[theme.index("LedAnim::Blink {") :]
    blink = blink[: blink.index(".into_any_element()")]
    assert ".repeat()" not in blink
    assert "BLINKS" in blink


def test_a_closed_dock_is_still():
    """Closed, the dock is laid out at zero width for its slide; its waiting
    marks looped there unseen, which was the last idle loop found."""
    dock = _block(_code(SRC / "dock.rs"), "pub fn dock(")
    assert re.search(r"let motion = app\.motion && app\.dock_open;", dock)


def test_a_waiting_mark_rests():
    dots = _block(_code(SRC / "marks.rs"), "fn mark_dots(")
    waiting = dots[dots.index("phase == Phase::Waiting") :]
    waiting = waiting[: waiting.index("} else if animated")]
    assert ".repeat()" not in waiting
    assert "WAIT_BREATHS" in waiting


def test_the_page_head_does_not_breathe():
    veil = _block(_code(SRC / "theme.rs"), "fn sky_veil")
    assert "with_animation" not in veil
