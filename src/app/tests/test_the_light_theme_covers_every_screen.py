"""The white theme is whole, not a skin over half a page.

The app keeps one palette of names and swaps the values at paint time
(`theme::paint` / `theme::paint_a`). A screen that hardcodes a dark colour with
`rgb(...)` or `rgba(...)` would stay a dark island in the light theme, and the
defect would only show in a screenshot nobody takes. This is the guard that
makes "done" mean "covered": the only raw sRGB lives in the theme module
itself, where the mapping is, or in the two files that must not follow the
theme (the sky's own image and ink, and the contrast arithmetic).

The check reads Rust source with comments stripped, the way the other shell
tests do, so a colour named in a comment does not fail the gate.
"""

from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[3] / "kriko-gpui" / "src"

#: The files allowed to name raw sRGB.
#:   theme.rs      the palette itself, and the light mapping
#:   contrast.rs   WCAG arithmetic over raw channels
#:   sky_ink.rs    generated from the sky images, never theme-mapped
RAW_ALLOWED = {"theme.rs", "contrast.rs", "sky_ink.rs"}


def _code(path: Path) -> str:
    return "\n".join(
        re.sub(r"//.*$", "", line)
        for line in path.read_text(encoding="utf-8").splitlines()
    )


def test_no_screen_paints_a_raw_colour():
    offenders: list[str] = []
    for path in sorted(SRC.rglob("*.rs")):
        if path.name in RAW_ALLOWED:
            continue
        code = _code(path)
        for match in re.finditer(r"\b(rgb|rgba|hsla)\s*\(", code):
            offenders.append(f"{path.relative_to(SRC)}: {match.group(0)}")
    assert not offenders, (
        "a raw colour skips the light mapping; paint it through "
        "theme::paint/theme::paint_a/fixed: " + ", ".join(offenders)
    )


def test_the_theme_carries_a_light_palette_and_the_escape_hatch():
    theme = _code(SRC / "theme.rs")
    assert "pub fn set_light(" in theme
    assert "pub fn paint(" in theme
    assert "pub fn paint_a(" in theme
    assert "pub fn fixed(" in theme, "the sky and on-brand words need a fixed colour"
    assert "fn light_colour(" in theme
    assert "fn light_alpha(" in theme


def test_every_screen_reads_the_shared_card_head():
    """A card header with its own glyph is the pattern the pass promised; a
    screen that still draws a bare eyebrow has been skipped."""
    skipped: list[str] = []
    for path in sorted((SRC / "screens").glob("*.rs")):
        if path.name in {"mod.rs", "guidance.rs", "logs.rs"}:
            continue
        code = _code(path)
        if 'card()' in code and "card_head(" not in code and "eyebrow(" in code:
            skipped.append(path.name)
    assert not skipped, f"screens still heading cards with a bare eyebrow: {skipped}"
