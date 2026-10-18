"""The Catalogs and Sites panels never remove or roll back on the first press.

A discarded draft is the only copy of what an agent wrote. A forgotten site
is one that an agent had to read a page to learn. A step back changes what
Kriko says about a product. Each of the three asks first, and only the second
press reaches the engine. The panels also never write on their own: the engine
is asked to read a site, or to install a draft, only from a button.
"""

from __future__ import annotations

import re
from pathlib import Path

UI = Path(__file__).resolve().parents[3] / "kriko-ui" / "src"
CATALOGS = (UI / "ui" / "panels" / "Catalogs.tsx").read_text(encoding="utf-8")
SITES = (UI / "ui" / "panels" / "Sites.tsx").read_text(encoding="utf-8")
CATALOG_HOOK = (UI / "engine" / "catalogs.ts").read_text(encoding="utf-8")
SITE_HOOK = (UI / "engine" / "sites.ts").read_text(encoding="utf-8")


def _only_call_follows_the_question(source: str, call: str, question: str) -> None:
    assert source.count(call) == 1, f"{call} must be wired to one button"
    asked = source.index(question)
    assert asked < source.index(call), f"{call} is wired before {question!r}"


def test_a_step_back_asks_first():
    _only_call_follows_the_question(CATALOGS, "onClick={onBack}", "Go back?")
    assert CATALOGS.count("void stepBack(") == 1


def test_a_draft_is_discarded_only_after_the_question():
    _only_call_follows_the_question(CATALOGS, "onClick={onDiscard}", "Discard?")


def test_a_site_is_forgotten_only_after_the_question():
    _only_call_follows_the_question(SITES, "onClick={onForget}", "Forget?")


def test_no_effect_writes_to_the_engine():
    for name, source in (("catalogs", CATALOG_HOOK), ("sites", SITE_HOOK)):
        for body in re.findall(r"useEffect\(\(\) => \{(.*?)\n  \}, \[", source, re.S):
            assert not re.search(r"\b(post|del|put|patch)\(", body), f"{name}: an effect writes"


def test_only_a_way_that_was_worked_out_here_has_a_switch():
    # The engine refuses to turn off any other, and a switch that cannot work is a lie.
    assert "row.origin === 'inferred' ?" in SITES
    assert "forgettable = row.origin === 'agent' || row.origin === 'reader'" in SITES


def test_the_routes_are_the_ones_the_engine_serves():
    served = (
        Path(__file__).resolve().parents[1] / "web" / "routers" / "packs.py"
    ).read_text(encoding="utf-8") + (
        Path(__file__).resolve().parents[1] / "web" / "routers" / "sites.py"
    ).read_text(encoding="utf-8")
    for route in (
        '"/packs/{pack_id}/enabled"',
        '"/packs/{pack_id}/rollback"',
        '"/packs/drafts/{slug}/install"',
        '"/packs/drafts/{slug}"',
        '"/sites/{host}/register"',
        '"/sites/{host}/inferred"',
        '"/sites/{host}"',
    ):
        assert route in served, route
