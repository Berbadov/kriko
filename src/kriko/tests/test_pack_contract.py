"""Every pack in the repo meets the contract docs/PACK_CONTRACT.md states.

The document is the thing a third-party author reads; this test is what stops
it becoming fiction. Both shipped packs are checked, because a contract with
one example is indistinguishable from that example.
"""

import re
from pathlib import Path

import pytest

from kriko.pack.manifest import load

REPO = Path(__file__).resolve().parents[3]
PACKS = sorted(p for p in (REPO / "packs").iterdir() if (p / "pack.toml").exists())


def test_the_repo_ships_more_than_one_pack():
    """A contract validated against a single pack proves nothing."""
    assert len(PACKS) >= 2, f"found only {[p.name for p in PACKS]}"


@pytest.mark.parametrize("root", PACKS, ids=lambda p: p.name)
def test_pack_meets_the_required_minimum(root):
    manifest = load(root)
    assert manifest.pack_id, "[pack] id is required"
    assert manifest.name, "[pack] name is required"
    assert manifest.version, "[pack] version is required"
    assert manifest.identity_keys, (
        "[identity] must declare at least one subject kind, or every subject "
        "of that kind hashes to the same id"
    )
    for kind, keys in manifest.identity_keys.items():
        assert keys, f"[identity] {kind} declares no attribute keys"
    assert manifest.data_dir.is_dir(), "data/ is required — a pack is its rows"
    assert any(manifest.data_dir.rglob("*.yaml")), "data/ holds no rows"


@pytest.mark.parametrize("root", PACKS, ids=lambda p: p.name)
def test_pack_has_a_readme_stating_what_it_covers(root):
    assert (root / "README.md").is_file(), (
        "a pack is a thing someone installs; it must say what it covers"
    )


@pytest.mark.parametrize(
    "root",
    [p for p in PACKS if (p / "research" / "templates.yaml").is_file()],
    ids=lambda p: p.name,
)
def test_a_pack_with_search_queries_also_ships_how_to_aim_them(root):
    """A pack that declares `research/templates.yaml` is telling a harness to
    go search for something. `research/skill.md` is how to identify *what*
    before those queries run — without it a harness has queries but no method,
    and will search a label instead of the attribute that actually
    discriminates. docs/superpowers/specs/2026-09-09-knowledge-building-design.md
    §5 states this as the testing rule directly: a pack cannot ship queries
    without a method."""
    assert (root / "research" / "skill.md").is_file(), (
        f"{root.name} ships research templates but no research/skill.md"
    )


# ── the language a query is written in (B94) ─────────────────────────────────
#
# A pack ships searches. Until 2026-09-10 nothing said what language they were
# in, and `packs/cars` shipped five English templates beside two Turkish ones
# — legitimately, because that is where its claims come from. But the brief
# rendered all seven as one numbered list, so an agent handed it could not
# tell a market convention from a typo, and a reader read the result as the
# defect it looked like: "the researches making turkish-english queries".
#
# The gate is a *mechanism*, not a language classifier. A non-ASCII word in a
# query is a query not written in English, which is detectable without knowing
# which language it IS — the same test `test_the_extension_speaks_no_sites_own_
# language` uses one layer out. A pack that ships one must declare it.


def _templates(root: Path):
    """Every template entry, in either legal shape, or [] if the pack ships none."""
    import yaml

    path = root / "research" / "templates.yaml"
    if not path.is_file():
        return []
    return yaml.safe_load(path.read_text(encoding="utf-8")) or []


def _query_and_lang(entry, primary: str) -> tuple[str, str]:
    if isinstance(entry, str):
        return entry, primary
    if isinstance(entry, dict):
        return str(entry.get("query") or ""), str(entry.get("lang") or primary)
    return "", primary


_NON_ASCII_WORD = re.compile(r"[^\W\d_]*[^\x00-\x7f][^\W\d_]*", re.UNICODE)


@pytest.mark.parametrize("root", PACKS, ids=lambda p: p.name)
def test_a_pack_that_ships_queries_declares_the_language_they_are_in(root):
    """`[pack] languages` is required of any pack with search templates.

    Not of a pack with none: `packs/drill` would still be at the floor if it
    shipped no `research/` at all. What is forbidden is telling an agent to go
    searching without telling it what to search in.
    """
    manifest = load(root)
    if not _templates(root):
        return
    assert manifest.languages, (
        f"{root.name} ships research/templates.yaml but [pack] declares no "
        "languages — a brief cannot tell an agent what language to search in, "
        "and the agent will mix them (backlog B94)"
    )


@pytest.mark.parametrize("root", PACKS, ids=lambda p: p.name)
def test_no_query_is_written_in_a_language_the_manifest_does_not_name(root):
    """The gate that would have caught the cars pack before a reader did.

    Two ways to fail it, and both are the same mistake: a template carrying a
    `lang` the manifest never declared, and a template with a non-ASCII word
    in a pack that declares only one language. The second is the one that was
    actually shipping.
    """
    manifest = load(root)
    declared = set(manifest.languages)
    primary = manifest.primary_language
    for entry in _templates(root):
        query, lang = _query_and_lang(entry, primary)
        if not query:
            continue
        assert lang in declared or not declared, (
            f"{root.name}: template {query!r} declares lang {lang!r}, which "
            f"[pack] languages does not name ({sorted(declared)})"
        )
        words = _NON_ASCII_WORD.findall(query)
        if not words:
            continue
        # A non-ASCII *word* is vocabulary. A lone folded character between
        # delimiters is a spelling variant and stays legal — the same
        # closed-vocabulary exception CLAUDE.md makes for the extension.
        if all(len(word) <= 1 for word in words):
            continue
        assert lang != primary or len(declared) > 1, (
            f"{root.name}: template {query!r} is not written in English but "
            f"the pack declares only {sorted(declared)}. Either declare the "
            f"language on the entry (`- {{query: ..., lang: tr}}`) or add it "
            f"to [pack] languages"
        )
