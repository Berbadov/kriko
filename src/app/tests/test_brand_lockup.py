"""The lockup is generated, and these are what make that true rather than said.

`packaging/render_lockup.py` draws the mark beside the word on one grid. The
SVGs it writes are committed, because a build that has to run a script before
it can show a logo is a build that will one day ship without one — but a
committed generated file is a file somebody edits by hand, so it is checked
back against its generator here.

The interesting assertion is the first: the lockup's mark is *read out of*
`logo-mark.svg` rather than copied into the generator. Copying it would be the
same two-drawings failure `test_brand_icon.py` exists for, one file further
along.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "packaging"))

import render_icon  # noqa: E402
import render_lockup  # noqa: E402


def test_the_committed_lockups_are_what_the_generator_writes():
    """Edit either SVG by hand and this fails, which is the point."""
    full, mono = render_lockup.render()
    assert render_lockup.LOCKUP.read_text(encoding="utf-8") == full
    assert render_lockup.MONO.read_text(encoding="utf-8") == mono


def test_the_lockup_wears_the_mark_rather_than_a_copy_of_it():
    """Change the mark, re-run, and the lockup changes with it.

    Proven by redrawing the mark in memory and checking the lockup's rects
    follow — not by reading the generator, which would only prove the code
    says what it says.
    """
    # Bytes, not text: `write_text` translates newlines to the platform's own
    # on Windows, so a text round-trip dirties the file there (LF becomes CRLF)
    # while passing silently on Linux. The restore must be byte-identical.
    source = render_lockup.MARK.read_bytes()
    try:
        render_lockup.MARK.write_bytes(
            source.replace(b'x="2" y="1" width="3" height="14"',
                           b'x="2" y="1" width="4" height="14"'),
        )
        moved, _ = render_lockup.render()
    finally:
        render_lockup.MARK.write_bytes(source)
    assert 'x="2" y="1" width="4" height="14"' in moved


def test_the_monochrome_twin_carries_no_colour_and_no_ground():
    """It is for grounds that are not ours — a README, a print, an invoice.

    A ground rect would paint a near-black box onto a white page, and a fixed
    ink would be invisible on half of them. `currentColor` is the only fill
    that is right in both places.
    """
    mono = render_lockup.MONO.read_text(encoding="utf-8")
    assert 'fill="currentColor"' in mono
    assert not re.search(r'fill="#', mono), "the mono lockup names a colour"
    assert f'width="{render_lockup.CAP + 2}" height="16"' not in mono


def test_the_word_sits_at_the_mark_s_own_cap_height_and_weight():
    """One grid, or the two halves read as a logo beside a font."""
    mark = render_lockup.MARK.read_text(encoding="utf-8")
    stem = [one for one in render_icon.RECT.findall(mark)
            if int(one[3]) == render_lockup.CAP]
    assert stem, f"the mark has no {render_lockup.CAP}-cell stem to match"
    assert int(stem[0][2]) == render_lockup.STROKE

    for letter, (_, blocks) in render_lockup.GLYPHS.items():
        tallest = max(y + h for _, y, _, h in blocks)
        assert tallest == render_lockup.CAP, (
            f"{letter} is {tallest} cells tall against a cap of "
            f"{render_lockup.CAP}"
        )
        assert min(w for _, _, w, _ in blocks) >= render_lockup.STROKE, (
            f"{letter} has a stroke thinner than the mark's"
        )


def test_the_gap_is_wider_than_the_tracking():
    """Otherwise the eye reads the mark as a sixth letter: "KKRIKO"."""
    assert render_lockup.GAP > render_lockup.TRACK
