"""backend/core/transmission_signal.py — catalog-derived gearbox-code registry.

This registry used to be a hand-maintained regex in sync.py
(`dq200|dq250|dq381|dq500|dc4|dw5|dw6|edc`) — the same anti-pattern
knowledge/stoplists.py's catalog_code_manufacturers() replaced for the
cross-manufacturer guard: a hardcoded list silently misses any code (or
alias) added after the list was written, and can carry entries no longer
backed by a real part (the old list's "dq500" was never a real part file).
Reading it off each transmission part file's own part_id + known_also_as
means new codes/aliases are covered automatically.
"""

import pytest

from backend.core.transmission_signal import (
    _transmission_code_aliases, mentioned_transmission_codes,
)


@pytest.fixture(autouse=True)
def _fresh_registry_cache():
    _transmission_code_aliases.cache_clear()
    yield
    _transmission_code_aliases.cache_clear()


def test_finds_direct_part_id_mention():
    assert mentioned_transmission_codes("The DQ200 mechatronic unit fails") == {"dq200"}


def test_resolves_known_also_as_alias_to_canonical_part_id():
    # dc4.yaml's known_also_as includes "EDC" — Renault's own marketing name
    # for the DC4 unit, never a literal part_id anywhere in the catalog.
    assert mentioned_transmission_codes("EDC clutch judder is common") == {"dc4"}


def test_resolves_generation_specific_alias():
    # dw6.yaml's known_also_as includes "EDC6"; dw5.yaml's includes "EDC7" —
    # distinct tokens, must resolve to distinct parts.
    assert mentioned_transmission_codes("EDC6 sensor fault reported") == {"dw6"}
    assert mentioned_transmission_codes("EDC7 sensor fault reported") == {"dw5"}


def test_multiword_alias_not_registered_as_a_code():
    # dc4.yaml also lists "Easy Drive Clutch" — descriptive text, not a code
    # someone would cite to name a specific *other* gearbox. Registering it
    # would make ordinary prose look like a sibling-code mention.
    assert mentioned_transmission_codes("Easy Drive Clutch issues are common") == set()


def test_no_false_positive_on_unrelated_text():
    assert mentioned_transmission_codes("Regular oil changes prevent engine wear") == set()


def test_comention_of_two_real_codes():
    assert mentioned_transmission_codes("Affects both DQ200 and DQ250 units") == {"dq200", "dq250"}
