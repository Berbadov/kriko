"""A scaffolded pack must install, not merely exist.

The contract is short enough to read and still easy to get wrong on a first
attempt, and the failure arrives as a validation error against a directory the
author is still guessing at. So the scaffold's promise is stronger than "wrote
some files": what it writes loads, builds, and answers.
"""

import pytest

from kriko.pack.build import build
from kriko.pack.manifest import load
from kriko.pack.scaffold import scaffold
from kriko.store.db import connect


def test_what_it_writes_loads_and_builds(tmp_path):
    root = tmp_path / "newpack"
    scaffold(
        root,
        pack_id="org.example.thing",
        name="Things",
        identity={"product": ["brand", "series"]},
    )
    manifest = load(root)
    assert manifest.pack_id == "org.example.thing"
    assert manifest.identity_keys == {"product": ["brand", "series"]}

    # And it builds. A scaffold whose output fails the builder is worse than
    # no scaffold: the author cannot tell their own edit from the template's
    # fault.
    out = build(root, tmp_path / "thing.kpack")
    conn = connect(out, read_only=True)
    try:
        assert conn.execute("SELECT count(*) FROM subjects").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM claims").fetchone()[0] == 1
    finally:
        conn.close()


def test_the_vocabulary_declares_exactly_the_keys_the_author_asked_for(tmp_path):
    """The builder refuses an undeclared key, so the template cannot invent one."""
    root = tmp_path / "p"
    scaffold(
        root,
        pack_id="org.example.two",
        name="Two kinds",
        identity={"product": ["brand"], "platform": ["brand", "family"]},
    )
    terms = (root / "vocabulary" / "terms.yaml").read_text(encoding="utf-8")
    for declared in ("product", "platform", "brand", "family"):
        assert f"term_id: {declared}" in terms
    build(root, tmp_path / "two.kpack")


def test_an_empty_identity_table_is_refused_with_the_reason(tmp_path):
    # The same rule `manifest.load` enforces, said before the directory exists
    # rather than after: an author who scaffolds with no identity keys has not
    # yet made the pack's most consequential decision.
    with pytest.raises(ValueError, match="hash to the same id"):
        scaffold(tmp_path / "p", pack_id="org.example.x", name="X", identity={})
    with pytest.raises(ValueError):
        scaffold(
            tmp_path / "p", pack_id="", name="X", identity={"product": ["brand"]}
        )


def test_it_refuses_to_overwrite_an_authored_pack(tmp_path):
    root = tmp_path / "p"
    scaffold(root, pack_id="org.example.x", name="X", identity={"product": ["brand"]})
    (root / "data" / "claims.yaml").write_text("# my work\n", encoding="utf-8")
    with pytest.raises(FileExistsError):
        scaffold(
            root, pack_id="org.example.x", name="X", identity={"product": ["brand"]}
        )
    # Untouched: a scaffold that clobbers authored rows is a data-loss bug
    # wearing a convenience feature's clothes.
    assert (root / "data" / "claims.yaml").read_text(encoding="utf-8") == "# my work\n"


def test_it_carries_no_category_of_its_own(tmp_path):
    """Every category word in the output came from the caller.

    The engine may hold no product vocabulary, derived or not (CLAUDE.md's
    scalability principle). A scaffold is the tempting place to break that —
    a helpful default subject kind — so this pins it: with an identity table
    of nonsense words, nothing else category-shaped appears.
    """
    root = tmp_path / "p"
    scaffold(
        root, pack_id="org.example.x", name="X", identity={"widget": ["zork"]}
    )
    text = "\n".join(
        path.read_text(encoding="utf-8") for path in root.rglob("*") if path.is_file()
    ).lower()
    for banned in ("engine_code", "mileage", "odometer", "gearbox", "fuel"):
        assert banned not in text
