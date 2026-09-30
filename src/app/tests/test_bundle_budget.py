"""The frontend's size, as a decision rather than an oversight.

The 1.0.0 audit's F16 read: 197 KB of JavaScript and 36 KB of CSS, one chunk,
no code splitting — *fine for a local app*, and noted only so that it is a
decision somebody made rather than a number nobody looked at. This file is
what turns it into the former.

**Why the routes are not split, and why one leaf is.** Splitting trades one
download for several. That trade pays on a website, where the second chunk
arrives over the network and most visitors never reach the screen it holds.
This bundle is read off the local disk by a window the shell only shows *after*
`/api/health` answers, and every reader has every route: the rail offers all of
them, and the Console can reach any of them by name. A lazy route here buys
nothing and adds a loading state to a screen that currently has none. That
reasoning was tested on 2026-09-16 by splitting every route and then putting
them back, which cost a first paint 126 KB smaller and thirteen new loading
states nobody had asked for.

The same reasoning points the other way exactly once. `@xterm/xterm` is 335 KB
-- more than half of everything shipped -- for a panel behind a keystroke that
most readers never press, and it is not a screen the rail lists or the Console
reaches. "Most readers never open it" is the website case arriving inside a
local app, so the terminal is deferred to first open and everything else is
eager. `DEFERRED` below names it, because a second entry appearing there is the
argument this file exists to force: the next one has to make the same case out
loud.

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
#:
#: Raised .js from 280,000 to 720,000 on 2026-09-11 for the embedded terminal,
#: which brought in `@xterm/xterm` and `@xterm/addon-fit` — a terminal emulator
#: and its DOM renderer — and pushed the built bundle to 551,840 bytes. **Given
#: back on 2026-09-16** when that panel was removed (§2.9): a budget raised for
#: one library and left raised after it goes is not a budget, it is a ratchet
#: that only turns one way. Back to 280,000, which today's 251 KB sits inside.
#:
#: Raised .js from 280,000 to 282,000 on 2026-09-19: no new dependency, just
#: controls — the benchmark scope grid as buttons instead of text fields, the
#: per-harness LLM dropdowns, the provider self-test buttons, and the Sites
#: activation rows. 280,406 bytes of ordinary feature work, not a library
#: arriving unweighed.
#: Raised .js from 282,000 to 290,000 on 2026-09-20. Again no dependency —
#: four controls and one compatibility fold, all of them things that were
#: previously text the reader had to type or a defect they could not see:
#: `Pick.svelte` (a real `<select>` with an escape hatch, replacing five
#: `<input list=…>` datalists), `Scale.svelte` (the depth dial, on three
#: screens that had no depth control at all), the per-harness effort dropdown,
#: and the Bench regroup. 286,429 bytes.
#: Raised .js from 290,000 to 300,000 on 2026-09-22. No dependency again, and
#: the two things that arrived are both answers to one report — "they look all
#: separate, and detected harnesses aren't including the all". First, the glyph
#: table left `shell/NavIcon.svelte` for `lib/Icon.svelte` and grew eleven
#: entries (agent, llm, effort, search, cost, fetch, agenda, plug, skill,
#: schedule, ok, warn, download), which is inline path data rather than an icon
#: font precisely so that it costs bytes here and no request at runtime.
#: Second, `Agents.prefs.svelte`: the per-agent card that replaced an
#: undivided run of eight `.field` divs. 293,105 bytes.
#: Raised .js from 300,000 to 325,000 on 2026-09-27. No dependency
#: (`ui/package.json` untouched since the last raise): B145's ship-readiness
#: round — busy guards, error states and empty states on every screen, deep
#: links past the first page, the CLI door, the bench regroup — across 75
#: files of `ui/src`. It shipped over budget in 0.10.3 (317,327 bytes) because
#: that installer was built by hand without the gate; this records it rather
#: than trimming working controls to fit a number. 317,467 bytes.
#: Raised .js from 333,000 to 334,000 on 2026-09-30: B158, no dependency. A
#: pick whose CLI lists no models now says so (`Pick.svelte`'s `note`, passed
#: by four screens) and Bench names such a CLI beside the chips. 333,380 bytes.
#: Raised .js from 334,000 to 338,000 on 2026-09-30: B171, no dependency. The
#: Settings "Local machine" section (`LocalMachine.svelte`: server address, a
#: model list the server reports, search address, timeout, the readiness
#: line). 336,017 bytes.
BUDGET = {".js": 338_000, ".css": 60_000}

#: Chunks deliberately kept out of the first paint, by the stem Vite names them
#: with. Empty since the terminal left, and that is the honest state — the
#: alternative was leaving a name here that matches nothing, which reads as a
#: rule being enforced when nothing is.
DEFERRED: tuple[str, ...] = ()

#: What a reader waits on before the window can render — the entry chunk and
#: its CSS, with every deferred leaf above excluded. 253 KB of JS and 42 KB of
#: CSS today, against 574 KB before the terminal was deferred.
#:
#: Raised from 388,000 to 392,000 on 2026-09-29: #57's local research plane
#: gave `Planes.svelte` its own card and readiness probe, with no new
#: dependency. 332,077 bytes of JS and 56,361 of CSS, 388,438 in all; this
#: records it rather than trimming the card to fit a number.
#:
#: Raised from 392,000 to 396,000 on 2026-09-30 for the same B171 section:
#: 336,017 bytes of JS and 56,982 of CSS, 392,999 in all.
FIRST_PAINT_BUDGET = 396_000

#: The whole payload, gzipped or not, including the index and any asset Vite
#: emitted beside the two bundles. What the window actually has to read.
#:
#: Raised from 420,000 on 2026-09-10, and the reason is that it was firing for
#: the wrong thing. B92–B98 added six components (planes, usage, the schedule)
#: and the JS reached 229 KB — comfortably inside its own 280 KB budget, and
#: over a total that had been set when the JS was 197 KB. So the total was
#: red while the number it was watching was fine.
#:
#: It is now derived from the per-kind budgets plus the fixed weight of what
#: is *not* built: the committed `fonts/*.woff2` and the two marks. That keeps
#: it doing the one job its message claims — catching an asset that is
#: "neither JS nor CSS — a font, an image, a source map" — instead of
#: double-counting growth the per-kind budgets already police.
#:
#: Re-measured on 2026-09-29 (B159/B161), and left at 165,000. The seven
#: files of five families (Plex Sans, Plex Mono 400, Sora, Silkscreen,
#: JetBrains Mono, 161,043 bytes) became ten files of one (Plex Mono at 400,
#: 500 and 600 upright and 400 and 600 italic, latin and latin-ext, 150,112
#: bytes), which the app needs so that bold and italic are real faces and not
#: the browser's imitation. With `mark.svg` and the new `mark-large.svg` the
#: unbuilt weight is 157,375 bytes, so the figure did not have to move.
UNBUILT_ASSETS = 165_000
TOTAL_BUDGET = sum(BUDGET.values()) + UNBUILT_ASSETS

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

    One entry chunk plus the named deferred leaves is the *choice* documented
    above, so an unnamed chunk appearing is worth a conversation rather than a
    silent pass. This also catches an `index.html` left pointing at a bundle
    that has been rebuilt under a new hash — the stale-bundle failure, from
    the other end.
    """
    index = (STATIC / "index.html").read_text(encoding="utf-8")
    referenced = set(re.findall(r"assets/([\w.-]+\.(?:js|css))", index))
    present = {p.name for p in _assets() if p.suffix in BUDGET}
    deferred = {
        name
        for name in present
        if any(name.startswith(one + "-") for one in DEFERRED)
    }
    assert referenced == present - deferred, (
        f"index.html asks for {sorted(referenced)} and the build holds "
        f"{sorted(present)}, of which {sorted(deferred)} are deferred on "
        "purpose. Either the bundle is stale or a chunk arrived that nobody "
        "named — see this file's docstring, and add it to DEFERRED only with "
        "the argument for why it is not in the first paint."
    )


def test_the_first_paint_carries_only_what_it_needs():
    """What the window reads before it can show anything.

    The per-kind budgets police the whole build; this one polices the part a
    reader waits on. Without it, deferring the terminal would have looked
    identical to never having shipped it — the same total, and no record that
    the expensive half now arrives only if it is asked for.
    """
    index = (STATIC / "index.html").read_text(encoding="utf-8")
    referenced = set(re.findall(r"assets/([\w.-]+\.(?:js|css))", index))
    eager = sum(
        p.stat().st_size for p in _assets() if p.name in referenced
    )
    assert eager <= FIRST_PAINT_BUDGET, (
        f"the first paint is {eager:,} bytes against {FIRST_PAINT_BUDGET:,}. "
        "Something large became eager, or a deferred leaf was pulled back "
        "into the entry chunk by a stray static import."
    )
