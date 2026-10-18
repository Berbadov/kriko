"""The first-start tour points at things that exist, and does not trap the reader.

Every step that names a target must find a `data-tour` mark in the source, the
tour is kept off under automation, the choice to skip is remembered without a
crash when storage is blocked, and Settings can start it again.
"""

from __future__ import annotations

import re
from pathlib import Path

UI = Path(__file__).resolve().parents[3] / "kriko-ui" / "src"
TOUR = (UI / "tour" / "Tour.tsx").read_text(encoding="utf-8")
SOURCES = "\n".join(
    path.read_text(encoding="utf-8")
    for path in UI.rglob("*.tsx")
    if path.name != "Tour.tsx"
)


def test_every_target_is_marked_somewhere():
    targets = re.findall(r"target: '([a-z-]+)'", TOUR)
    assert targets, "no step names a target, so this test checks nothing"
    for target in targets:
        mark = re.escape(target)
        # Marked as `data-tour="x"`, or built from a template like `nav-${item.id}`.
        literal = re.search(rf'data-tour="{mark}"', SOURCES)
        built = target.startswith("nav-") and "data-tour={`nav-${item.id}`}" in SOURCES
        assert literal or built, f"nothing is marked data-tour={target}"


def test_the_tour_stays_off_under_automation():
    assert "navigator.webdriver" in TOUR


def test_skipping_is_remembered_and_blocked_storage_is_not_fatal():
    assert re.search(r"try \{\s*localStorage\.setItem\(KEY", TOUR)
    assert re.search(r"try \{\s*return localStorage\.getItem\(KEY", TOUR)


def test_the_tour_can_be_left_with_the_keyboard():
    assert "'Escape'" in TOUR and "close()" in TOUR


def test_settings_can_start_it_again():
    settings = (UI / "ui" / "panels" / "Settings.tsx").read_text(encoding="utf-8")
    assert "onClick={startTour}" in settings


def test_the_card_words_are_short():
    # Plain, short sentences: STYLE.md allows at most 20 words in one.
    for sentence in re.findall(r"text: '([^']+)'", TOUR):
        for part in re.split(r"(?<=[.?!]) ", sentence):
            assert len(part.split()) <= 20, part


def test_the_tour_shows_the_agent_pick_and_the_source_kinds():
    targets = re.findall(r"target: '([a-z-]+)'", TOUR)
    assert "agent-pick" in targets and "source-kinds" in targets
    # The source kinds live in a panel, so that step opens the panel first, and
    # every step without a panel closes it again.
    assert re.search(r"target: 'source-kinds', panel: 'settings'", TOUR)
    assert "showDrawer(step.panel ?? null)" in TOUR
    assert "showDrawer(null)" in TOUR  # leaving the tour closes the panel too
