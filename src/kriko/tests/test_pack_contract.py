"""Every pack in the repo meets the contract docs/PACK_CONTRACT.md states.

The document is the thing a third-party author reads; this test is what stops
it becoming fiction. Both shipped packs are checked, because a contract with
one example is indistinguishable from that example.
"""

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
