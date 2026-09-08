"""The frontend's size, as a decision rather than an oversight.

The 1.0.0 audit's F16 read: 197 KB of JavaScript and 36 KB of CSS, one chunk,
no code splitting — *fine for a local app*, and noted only so that it is a
decision somebody made rather than a number nobody looked at. This file is
what turns it into the former.

**Why there is no code splitting, and why that is right here.** Splitting
trades one download for several. That trade pays on a website, where the second
chunk arrives over the network and most visitors never reach the screen it
holds. This bundle is read off the local disk by a window the shell only shows
*after* `/api/health` answers, and every reader has every route: the rail
offers all of them, and the Console can reach any of them by name. A lazy route
here would buy nothing and add a loading state to a screen that currently has
none.

So the size is not something to optimise — it is something to *watch*. The
failure mode this guards is not a slow app, it is the quiet arrival of a
dependency nobody weighed: a date library, an icon set, a charting package,
each one reasonable on its own and none of them visible in a diff. A budget
makes that arrival an argument someone has to make out loud.

Deliberately generous, and deliberately not a ratchet. A ratchet that tightens
on every build turns an unrelated commit red and teaches people to raise the
number without reading it; this leaves room to work and only speaks up when
something has changed by a lot. Raising it is fine — raising it *knowingly* is
the whole point.
"""

import re
from pathlib import Path

import pytest

#: Headroom over today's figures (197 KB JS, 36 KB CSS), which is about a
#: third. Enough that ordinary feature work never touches it; small enough
#: that one accidental library does.
BUDGET = {".js": 280_000, ".css": 60_000}

#: The whole payload, gzipped or not, including the index and any asset Vite
#: emitted beside the two bundles. What the window actually has to read.
TOTAL_BUDGET = 420_000

STATIC = Path(__file__).resolve().parents[1] / "web" / "static"


def _assets() -> list[Path]:
    return sorted(p for p in (STATIC / "assets").iterdir() if p.is_file())


def test_the_committed_bundle_is_there_to_measure():
    """A missing directory would satisfy every budget below it."""
    assert STATIC.is_dir(), f"no committed build output at {STATIC}"
    assert (STATIC / "index.html").is_file()
    assert _assets(), "no assets in the committed build"


@pytest.mark.parametrize("suffix", sorted(BUDGET))
def test_each_kind_of_asset_stays_inside_its_budget(suffix: str):
    files = [p for p in _assets() if p.suffix == suffix]
    assert files, f"the build emitted no {suffix} at all"
    total = sum(p.stat().st_size for p in files)
    assert total <= BUDGET[suffix], (
        f"{suffix} is {total:,} bytes against a budget of {BUDGET[suffix]:,}. "
        "If the growth is something you meant, raise BUDGET and say what "
        "arrived in the commit message — this test exists to make that a "
        "sentence someone writes, not a number that drifts."
    )


def test_the_whole_payload_stays_inside_its_budget():
    total = sum(p.stat().st_size for p in STATIC.rglob("*") if p.is_file())
    assert total <= TOTAL_BUDGET, (
        f"the committed build is {total:,} bytes against {TOTAL_BUDGET:,}. "
        "Per-kind budgets pass and this does not, so something arrived that is "
        "neither JS nor CSS — a font, an image, a source map."
    )


def test_no_source_maps_ship():
    """A `.map` is the size of the source it maps, and it ships the source.

    Never intentional in a release build, and easy to turn on by accident in
    a `vite.config` edit — a per-kind budget would not see it, because the
    per-kind budgets do not name `.map`.
    """
    assert [p.name for p in _assets() if p.suffix == ".map"] == []


def test_the_page_asks_for_the_files_that_are_there():
    """The split decision, stated as a check.

    One JS chunk and one CSS file is the *choice* documented above, so a
    second chunk appearing is worth a conversation rather than a silent pass.
    This also catches an `index.html` left pointing at a bundle that has been
    rebuilt under a new hash — the stale-bundle failure, from the other end.
    """
    index = (STATIC / "index.html").read_text(encoding="utf-8")
    referenced = set(re.findall(r"assets/([\w.-]+\.(?:js|css))", index))
    present = {p.name for p in _assets() if p.suffix in BUDGET}
    assert referenced == present, (
        f"index.html asks for {sorted(referenced)} and the build holds "
        f"{sorted(present)}. Either the bundle is stale or a second chunk "
        "arrived — see this file's docstring on why there is one."
    )
