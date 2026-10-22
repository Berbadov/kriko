"""The light theme is whole, and an idle window does not draw.

Two rules the old native window kept, now held for the web interface in
`kriko-ui/`. Both break invisibly: a colour defined for the dark palette only
leaves a dark island in the light theme, and an animation that keeps running in
a window nobody is looking at costs battery for nothing. Neither shows in a
test the compiler runs.

* **Every colour token is defined for both palettes.** The dark palette is the
  default in `:root`. The light one is written twice: for `data-theme="light"`
  and for the system's light setting. A token that only the default defines
  stays dark under both.
* **No screen reaches for a raw colour that the theme cannot change** beyond a
  short list of places that must not follow it (white on a fill, a mask, text
  over the hero sky).
* **Reduce motion stops CSS motion, and a window that is not in front stops
  the rest.**
"""

from __future__ import annotations

import re
from pathlib import Path

UI = Path(__file__).resolve().parents[3] / "kriko-ui" / "src"
TOKENS = (UI / "styles" / "tokens.css").read_text(encoding="utf-8")

#: A token that names a colour. Sizes, times and fonts do not change with the theme.
COLOUR = re.compile(r"^--(ground|raise|panel|panel-2|edge|edge-strong|ink|ink-2|ink-3|accent|accent-hi|accent-soft|ok|warn|risk|glass|glass-edge)$")


def _declared(block: str) -> set[str]:
    return set(re.findall(r"(--[\w-]+)\s*:", block))


def _block(opener: str) -> str:
    """The brace-balanced block that starts at `opener`, nested ones included."""
    start = TOKENS.index("{", TOKENS.index(opener))
    depth = 0
    for i in range(start, len(TOKENS)):
        depth += {"{": 1, "}": -1}.get(TOKENS[i], 0)
        if depth == 0:
            return TOKENS[start : i + 1]
    raise AssertionError(f"unbalanced braces after {opener!r}")


def _colours(names: set[str]) -> set[str]:
    return {n for n in names if COLOUR.match(n)}


def test_the_default_palette_names_every_colour():
    default = _colours(_declared(_block(":root {")))
    assert len(default) >= 15, f"only {sorted(default)} are named in the default palette"


def test_the_explicit_light_theme_redefines_every_colour_the_default_names():
    default = _colours(_declared(_block(":root {")))
    light = _colours(_declared(_block(":root[data-theme='light']")))
    assert default - light == set(), (
        f"{sorted(default - light)} are dark in the light theme: the screens that "
        "use them stay dark islands"
    )


def test_the_system_light_setting_redefines_the_same_colours():
    explicit = _colours(_declared(_block(":root[data-theme='light']")))
    system = _colours(_declared(_block("@media (prefers-color-scheme: light)")))
    assert explicit - system == set(), (
        f"{sorted(explicit - system)} follow the explicit light theme and not the "
        "system's: a reader on a light system sees a different app"
    )


def test_a_raw_colour_outside_the_theme_is_one_of_the_few_that_must_not_follow_it():
    """Counted, so a new one is a decision someone made and not an accident."""
    allowed_per_file = {
        "styles/tokens.css": None,  # the palette itself
        "ui/DitherSky.tsx": None,  # the sky's own colours, which no theme changes
        "ui/AgentMark.tsx": 9,  # each agent's own brand tone, which no theme changes
        "styles/shell.css": 3,  # the switch knob and its shadow, the drawer scrim
        "styles/chat.css": 6,  # a mask, and white text and its shadow over the hero sky
        "styles/compare.css": 1,  # white on a critical fill
        "styles/activity.css": 1,  # ink on the green check
        "ui/TopBar.tsx": 1,  # the logo's own white, swapped for the text colour
        "ui/Starting.tsx": 1,  # the same logo white, swapped the same way
    }
    pattern = re.compile(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(")
    seen: dict[str, int] = {}
    for path in sorted(UI.rglob("*")):
        if path.suffix not in {".css", ".tsx", ".ts"}:
            continue
        relative = path.relative_to(UI).as_posix()
        count = len(pattern.findall(path.read_text(encoding="utf-8")))
        if count:
            seen[relative] = count
    for relative, count in seen.items():
        assert relative in allowed_per_file, (
            f"{relative} names {count} raw colour(s): use a token from tokens.css, "
            "or add the place to this list if it must not follow the theme"
        )
        limit = allowed_per_file[relative]
        assert limit is None or count <= limit, (
            f"{relative} names {count} raw colours and {limit} are allowed: "
            "a new one is a dark island in the light theme"
        )


def test_reduce_motion_stops_css_motion():
    base = (UI / "styles" / "base.css").read_text(encoding="utf-8")
    block = base[base.index(":root[data-motion='off']") :]
    assert "animation-duration: 0.001ms !important" in block
    assert "transition-duration: 0.001ms !important" in block


def test_a_window_that_is_not_in_front_stops_moving():
    prefs = (UI / "prefs.tsx").read_text(encoding="utf-8")
    front = prefs[prefs.index("function useInFront") : prefs.index("export function PrefsProvider")]
    for event in ("'focus'", "'blur'", "'visibilitychange'"):
        assert event in front, f"the window's front state ignores {event}"
    assert "document.hasFocus()" in front and "visibilityState === 'visible'" in front
    body = prefs[prefs.index("export function PrefsProvider") :]
    assert "useInFront()" in body, "the front state is computed and never used"
    assert "dataset.motion" in body, "the motion setting never reaches the page"
