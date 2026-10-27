"""A draft becomes a shipped catalog only with what a reader can check.

`tools/import_draft.py` copies a finished draft into `packs/`. What a reader of the catalog is
owed: every claim carries a page and a quote, the words say what is reported about the product
and not how the agent came by it, and nothing written from memory (an adapter) rides along.
"""

import importlib.util
from pathlib import Path

import pytest
import yaml

TOOL = Path(__file__).resolve().parents[3] / "tools" / "import_draft.py"

CLAIMS = """\
# Claims — proposed.
- subject: {kind: product, identity: {brand: acme, model: anvil}}
  kind: known_issue
  confidence: 0.6
  text:
    en:
      title: Handle cracks
      body: Found via the 'acme anvil problems' search (a forum). The handle cracks after a year of ordinary use, and the maker offers no replacement.
      advice: Check the handle.
  evidence:
    - {url: "https://forum.invalid/a", quote: Mine cracked after a year.}
- subject: {kind: product, identity: {brand: acme, model: anvil}}
  kind: known_issue
  confidence: 0.5
  text:
    en: {title: Paint chips, body: Paint chips easily and the bare metal rusts within a season of outdoor use., advice: Look at the paint.}
- subject: {kind: product, identity: {brand: acme, model: anvil}}
  kind: known_issue
  confidence: 0.6
  text:
    en: {title: Head loosens, body: Came from the 'acme head' search., advice: Tighten it.}
  evidence:
    - {url: "https://forum.invalid/b", quote: The head works loose.}
"""

PACK = """\
[pack]
id = "tools"
name = "Tools"
version = "0.1.1"
languages = ["en"]
"""


def _load():
    spec = importlib.util.spec_from_file_location("import_draft", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def draft(tmp_path):
    root = tmp_path / "work" / "tools"
    (root / "data").mkdir(parents=True)
    (root / "adapters").mkdir()
    (root / "adapters" / "shop.json").write_text("{}", encoding="utf-8")
    (root / ".installed").write_text("x", encoding="utf-8")
    (root / "data" / "claims.yaml").write_text(CLAIMS, encoding="utf-8")
    (root / "data" / "subjects.yaml").write_text("- {kind: product, label: Acme Anvil, identity: {brand: acme, model: anvil}}\n",
                                                  encoding="utf-8")
    (root / "pack.toml").write_text(PACK, encoding="utf-8")
    (root / "README.md").write_text("This draft is not yet installed.\n", encoding="utf-8")
    return root


def test_only_sourced_claims_with_words_about_the_product_are_imported(draft, tmp_path):
    packs = tmp_path / "packs"
    packs.mkdir()
    target, kept, dropped = _load().import_draft(draft, packs, "tools")
    claims = yaml.safe_load((target / "data" / "claims.yaml").read_text(encoding="utf-8"))

    # The unsourced claim goes; the sourced one whose only words narrated the search goes too.
    assert (kept, dropped) == (1, 2)
    assert [c["text"]["en"]["title"] for c in claims] == ["Handle cracks"]
    assert claims[0]["text"]["en"]["body"].startswith("The handle cracks after a year")
    assert "Found via" not in claims[0]["text"]["en"]["body"]
    assert claims[0]["evidence"] == [{"url": "https://forum.invalid/a", "quote": "Mine cracked after a year."}]


@pytest.mark.parametrize("body, expected", [
    # The ways an agent narrated its search in the first catalogs, each followed by the claim.
    ("Found via the 'x y problems' search (Darty forum, FR market). The pump fails to draw water after a month.",
     "The pump fails to draw water after a month."),
    ("From the seed search 'x y screen flicker forum'. A report describes colour bleed and a scrambled picture.",
     "A report describes colour bleed and a scrambled picture."),
    ("From the 'x y reliability' search; a Best Buy owner reports battery failure within the first year of use.",
     "A Best Buy owner reports battery failure within the first year of use."),
    ("Came from the 'reliability forum' search. The dock seal degrades at twelve to eighteen months of use.",
     "The dock seal degrades at twelve to eighteen months of use."),
    ("From the Computerbase.de forum (a German thread, query: 'x y Probleme forum'). A repairer describes a broken hinge.",
     "A repairer describes a broken hinge."),
    ("The owner reports the hinge cracked. Note the page refused my fetcher, so this quote comes from the search-returned text.",
     "The owner reports the hinge cracked."),
    # What is not narration is left alone, even when it opens the same way.
    ("From the manufacturer's official troubleshooting page: a wet filter can cause abnormal noise.",
     "From the manufacturer's official troubleshooting page: a wet filter can cause abnormal noise."),
    # Nothing but a pointer to the search is not a claim.
    ("Found via the 'x y problems forum' search; Xiaomi's own FAQ.", ""),
])
def test_the_sentence_about_the_agents_own_search_goes_and_the_claim_stays(body, expected):
    assert _load().plain(body) == expected


def test_the_copy_carries_no_working_files_and_a_manifest_a_shared_catalog_can_stand_on(draft, tmp_path):
    packs = tmp_path / "packs"
    packs.mkdir()
    target, _, _ = _load().import_draft(draft, packs, "tools")

    assert not (target / ".installed").exists()
    assert not (target / "adapters").exists()
    manifest = (target / "pack.toml").read_text(encoding="utf-8")
    assert 'id = "org.kriko.tools"' in manifest
    assert 'license = "CC-BY-SA-4.0"' in manifest and 'publisher = "kriko"' in manifest
    readme = (target / "README.md").read_text(encoding="utf-8")
    assert "not yet installed" not in readme and "holds 1 sourced claims" in readme


def test_importing_over_a_catalog_that_exists_is_refused(draft, tmp_path):
    packs = tmp_path / "packs"
    (packs / "tools").mkdir(parents=True)
    with pytest.raises(FileExistsError):
        _load().import_draft(draft, packs, "tools")
