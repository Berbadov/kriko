"""A registered site that reads nothing, and a pack no browser can find.

    biggest block: new packs are not working, new added sites arent working
    too

Both were the same *kind* of defect and neither raised anything. A thing was
accepted, stored, listed on a screen, granted a browser permission — and then
did nothing at all, because the two ends of it had been written against
different vocabularies.

* **The site the reader taught their own copy.** `sites.BRIEF` asked an agent
  for `fields` and `title_patterns`. `kriko/adapters.py` reads `identity` and
  `context`. Nothing anywhere read either of the first two, so `adapt()`
  resolved an empty identity on every page and `declared_labels()` returned
  `[]` — meaning the content script was not even told which labels to look
  for. Every surface reported success. This is `arabam.com` in the reader's
  own `app.sqlite`: six correctly chosen identity keys, all inert.

* **The packs an agent authored.** `author()` learned to write an adapter;
  `amend()` never did. So a pack drafted before that — which is every pack
  this installation holds — had no way to gain one, and a reply containing
  only an adapter was refused outright as "already in this draft".

The third failure is the dial the reader asked for twice: `--effort`, which
both `claude` and `agy` declare and neither was ever passed.
"""

import json

import pytest

from app import packauthor, prefs, sites
from app.providers import harness as harness_mod
from kriko.adapters import adapt, declared_labels


# ── The adapter that was accepted and read nothing ───────────────────────────

#: The shape the old brief taught, and the shape the reader's stored adapter
#: is in. Its keys are right — they are the cars pack's own identity keys —
#: which is what made the failure so hard to see from a screen.
OLD_SHAPE = {
    "id": "local.example.com",
    "site": "example.com",
    "match": ["*://*.example.com/*"],
    "fields": {
        "make": {"labels": ["Marka"]},
        "model": {"labels": ["Seri", "Model"]},
        "fuel": {"labels": ["Yakıt Tipi"]},
    },
    "title_patterns": ["(?P<make>\\w+) (?P<model>\\w+)"],
}

PAGE = {"Marka": "Volkswagen", "Seri": "Passat", "Yakıt Tipi": "Dizel"}


def test_the_old_shape_really_did_read_nothing():
    """The bug, pinned. Without this the fix below looks like a refactor."""
    assert adapt(OLD_SHAPE, PAGE).identity == {}
    assert declared_labels(OLD_SHAPE) == []


def test_a_stored_adapter_heals_on_read():
    folded = sites.normalise(OLD_SHAPE)
    assert adapt(folded, PAGE).identity == {
        "make": "Volkswagen", "model": "Passat", "fuel": "Dizel",
    }
    # The content script is given something to find, which is the half of this
    # that happens in the browser rather than in the engine.
    assert "marka" in declared_labels(folded)


def test_the_dead_vocabulary_does_not_survive_the_fold():
    folded = sites.normalise(OLD_SHAPE)
    assert "fields" not in folded
    assert "title_patterns" not in folded


def test_an_engine_shaped_adapter_passes_through_unharmed():
    """A pack's own adapter must not be rearranged by the compatibility fold."""
    spec = {
        "site": "example.com",
        "identity": {"make": {"labels": ["marka"], "from": "title",
                              "vocabulary": "make"}},
        "context": {"usage_km": {"labels": ["km"], "parse": "int_range",
                                 "min": 0, "max": 2000000}},
    }
    folded = sites.normalise(spec)
    assert folded["identity"] == spec["identity"]
    assert folded["context"] == spec["context"]


def test_a_rule_the_engine_cannot_act_on_is_not_stored_as_though_it_could():
    """`selector` was in the old brief and has never been interpreted.

    Dropped rather than kept, because an adapter whose rules are all inert is
    indistinguishable from a working one on every screen in the app — which is
    the whole defect this module is about.
    """
    folded = sites.normalise(
        {"site": "example.com",
         "fields": {"make": {"selector": ".a-class-name", "labels": ["Marka"]}}}
    )
    assert folded["identity"]["make"] == {"labels": ["Marka"]}


def test_a_field_with_no_labels_falls_back_to_the_title():
    """The engine's one answer to "no label on the page", so use it."""
    folded = sites.normalise({"site": "x.com", "fields": {"make": {}}})
    assert folded["identity"]["make"] == {"from": "title", "vocabulary": "make"}


# ── What `check` now refuses, and what it no longer does ─────────────────────


def test_check_refuses_an_adapter_that_could_only_ever_read_nothing():
    with pytest.raises(sites.SiteRefused) as caught:
        sites.check({"site": "example.com"}, host="example.com")
    assert "identity" in str(caught.value)


def test_check_accepts_the_shape_a_pack_actually_ships():
    """The old test asked whether a `fields` key was present, so a pack's own
    adapter — which has never had one — would have been refused."""
    checked = sites.check(
        {"site": "example.com", "identity": {"make": {"labels": ["marka"]}}},
        host="example.com",
    )
    assert checked["identity"]["make"]["labels"] == ["marka"]
    assert checked["site"] == "example.com"


def test_check_still_refuses_a_site_that_is_not_a_hostname():
    """Unchanged, and the one rule that must not soften: `site` becomes a host
    permission and an injection target in somebody's browser."""
    for bad in ("*", "https://example.com/path", "example.com/ilan"):
        with pytest.raises(sites.SiteRefused):
            sites.check({"site": bad, "identity": {"make": {"labels": ["m"]}}})


def test_the_brief_teaches_the_vocabulary_the_engine_reads():
    text = sites.BRIEF.format(site="example.com", url="https://example.com/",
                              keys="product: make, model")
    assert '"identity"' in text
    # Named only to forbid it — the old brief asked for it as a field.
    assert '"title_patterns"' not in text
    assert "no `title_patterns`" in text


# ── The pack that no browser could find ──────────────────────────────────────


ADAPTER_REPLY = {
    "adapters": [{"site": "shop.example.com", "subject_kind": "product",
                  "identity": {"brand": {"labels": ["Marka"]}}}],
}


def _fence(payload: dict) -> str:
    return "```json\n" + json.dumps(payload) + "\n```"


def _store(tmp_path):
    return tmp_path / "k.sqlite"


def _draft(tmp_path, adapters=True) -> str:
    """A minimal draft, authored the way the app authors one. Returns its slug."""
    payload = {
        "name": "Test Widgets",
        "pack_id": "test.widgets",
        "identity": {"product": ["brand", "model"]},
        "principle": "What a buyer cannot cheaply find out for themselves.",
        "subjects": [{"kind": "product", "label": "Widget One",
                      "identity": {"brand": "Acme", "model": "One"}}],
        "claims": [],
        "lineup": ["Widget One"],
        "templates": ["{label} problems", "{label} reliability"],
    }
    if adapters:
        payload |= ADAPTER_REPLY
    return packauthor.author(_store(tmp_path), _fence(payload),
                             category="test widgets")["slug"]


def test_a_draft_authored_without_an_adapter_can_gain_one(tmp_path):
    """**The reader's four installed packs, exactly.** Every one was authored
    before `_adapters` existed, so every one is invisible in the browser and
    had no route to stop being."""
    slug = _draft(tmp_path, adapters=False)
    assert packauthor.draft_state(_store(tmp_path), slug)["adapters"] == []

    result = packauthor.amend(_store(tmp_path), slug, _fence(ADAPTER_REPLY))

    assert result["adapters_added"] == ["shop.example.com"]
    assert packauthor.draft_state(_store(tmp_path), slug)["adapters"] == [
        "shop.example.com"]


def test_an_adapter_only_amendment_is_not_refused_as_empty(tmp_path):
    """It was: `amend` counted subjects and claims, saw neither, and raised
    "everything in the reply is already in this draft" — about a file it had
    just been handed and would never write."""
    slug = _draft(tmp_path, adapters=False)
    result = packauthor.amend(_store(tmp_path), slug, _fence(ADAPTER_REPLY))
    assert result["subjects_added"] == 0 and result["claims_added"] == 0
    assert result["adapters_added"] == ["shop.example.com"]


def test_an_amendment_never_overwrites_an_adapter_the_draft_has(tmp_path):
    """Adds, never replaces — the rule the whole amend path is built on."""
    slug = _draft(tmp_path, adapters=True)
    with pytest.raises(packauthor.PackRefused):
        packauthor.amend(_store(tmp_path), slug, _fence({
            "adapters": [{"site": "shop.example.com", "subject_kind": "product",
                          "identity": {"brand": {"labels": ["Something Else"]}}}],
        }))


def test_the_amend_brief_asks_for_an_adapter_when_there_is_none(tmp_path):
    slug = _draft(tmp_path, adapters=False)
    brief = packauthor.amend_brief(packauthor.draft_state(_store(tmp_path), slug))
    assert "no adapter" in brief
    assert '"adapters"' in brief


def test_the_amend_brief_does_not_ask_again_once_there_is_one(tmp_path):
    slug = _draft(tmp_path, adapters=True)
    brief = packauthor.amend_brief(packauthor.draft_state(_store(tmp_path), slug))
    assert "shop.example.com" in brief
    assert "cannot be recognised in a browser" not in brief


def test_an_authored_adapter_is_in_the_shape_the_engine_reads():
    """Where the two halves of this module meet: what an agent writes through
    `packauthor` must be readable by `kriko/adapters.py` with no fold between."""
    built = packauthor._adapters(ADAPTER_REPLY, {"product": ["brand", "model"]})
    assert adapt(built[0], {"Marka": "Acme"}).identity == {"brand": "Acme"}


# ── The dial that was never passed ───────────────────────────────────────────


def _one(ident: str):
    return next(h for h in harness_mod.KNOWN if h.id == ident)


@pytest.mark.parametrize("ident,levels", [
    ("claude-code", ("low", "medium", "high", "xhigh", "max")),
    ("antigravity-cli", ("low", "medium", "high")),
])
def test_the_levels_are_the_ones_the_cli_documents(ident, levels):
    """Read out of each CLI's own `--help`, never invented: a level neither
    accepts is a run that dies on argument parsing rather than costing less."""
    assert _one(ident).effort_choices == levels


def test_effort_reaches_the_command_vector():
    one = _one("claude-code")
    if not harness_mod.efforts_for(one):
        pytest.skip("this machine's claude does not declare --effort")
    built = harness_mod.command_for(one, effort="low")
    assert built[built.index("--effort") + 1] == "low"


def test_an_effort_a_cli_cannot_take_is_refused_not_dropped():
    """The same rule the model switch follows. A reader who asked for `low` and
    silently got the default has been billed for a choice they did not make,
    and the run looks identical from every screen."""
    one = _one("mistral-vibe")
    assert harness_mod.efforts_for(one) == ["high"]
    with pytest.raises(harness_mod.NoHarness):
        harness_mod.command_for(one, effort="low")


def test_claude_code_can_be_given_a_ceiling():
    """`--max-budget-usd`, which its `--help` documents as working with
    `--print` — the only mode this plane runs in. The scale dial reached one
    CLI before this, and the harness the reader is trying *not* to spend on was
    the one with no ceiling at all."""
    assert _one("claude-code").budget_flag == "--max-budget-usd"


# ── The preference keys that were a hand-written list ────────────────────────


def test_every_harness_can_store_a_model_and_an_effort():
    """The tuple this replaces named three harnesses. Mistral Vibe — added
    precisely so the reader could stop spending Claude tokens — was not one of
    them, so a model chosen for it was dropped on write and it silently ran the
    CLI's default."""
    for one in harness_mod.KNOWN:
        assert prefs.harness_model_key(one.id) in prefs.KEYS
        assert prefs.harness_effort_key(one.id) in prefs.KEYS


def test_a_model_switch_that_is_an_environment_variable_still_counts():
    """`llm_selectable` keyed on `model_flag` alone, and Vibe's switch is
    `VIBE_ACTIVE_MODEL` — so the screen hid the picker for a CLI that has four
    models and a documented way to choose one."""
    vibe = _one("mistral-vibe")
    assert not vibe.model_flag and vibe.model_env
