"""A catalog's second language is written beside the first, and never over it.

`tools/translate_catalog.py` adds a language to claims the engine stored in English. What a
reader of a translated catalog is owed: the evidence is untouched (a quote stays in the
language of its page), a translation someone already wrote is never replaced, and asking
twice costs nothing.
"""

import importlib.util
import textwrap
import tomllib
from pathlib import Path

import pytest
import yaml

TOOL = Path(__file__).resolve().parents[3] / "tools" / "translate_catalog.py"

CLAIMS = """\
# Claims — what is known to go wrong.
- subject: {kind: product, identity: {brand: acme, model: anvil}}
  kind: known_issue
  domain: mech
  severity: high
  text:
    en: {title: Handle cracks, body: It cracks after a year., advice: Check the handle.}
  evidence:
    - {url: "https://forum.invalid/a", quote: Mine cracked after a year.}
- subject: {kind: product, identity: {brand: acme, model: anvil}}
  kind: known_issue
  domain: mech
  severity: low
  text:
    en: {title: Paint chips, body: Paint chips easily., advice: Look at the paint.}
    tr: {title: Boya atar, body: Boya kolay atar., advice: Boyaya bakın.}
- subject: {kind: product, identity: {brand: acme, model: anvil}}
  kind: known_issue
  domain: mech
  severity: medium
  text:
    en: {title: Head loosens, body: The head works loose., advice: Tighten it.}
"""


def _load():
    spec = importlib.util.spec_from_file_location("translate_catalog", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def catalog(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "claims.yaml").write_text(CLAIMS, encoding="utf-8")
    (tmp_path / "pack.toml").write_text('[pack]\nid = "tools"\nname = "Tools"\nlanguages = ["en"]\n', encoding="utf-8")
    return tmp_path


def shout(items, language):
    return [{key: f"{language}: {value}" for key, value in item.items()} for item in items]


def _read(root):
    return yaml.safe_load((root / "data" / "claims.yaml").read_text(encoding="utf-8"))


def test_the_missing_translations_are_written_beside_the_english_and_the_rest_left_alone(catalog):
    assert _load().translate_file(catalog, "tr", shout) == 2
    claims = _read(catalog)
    assert claims[0]["text"]["tr"] == {"title": "Turkish: Handle cracks", "body": "Turkish: It cracks after a year.",
                                       "advice": "Turkish: Check the handle."}
    assert claims[0]["text"]["en"]["title"] == "Handle cracks"
    # A translation someone already wrote is not replaced.
    assert claims[1]["text"]["tr"]["title"] == "Boya atar"
    # The evidence, and the file's own header, come through unchanged.
    assert claims[0]["evidence"] == [{"url": "https://forum.invalid/a", "quote": "Mine cracked after a year."}]
    assert (catalog / "data" / "claims.yaml").read_text(encoding="utf-8").startswith("# Claims")
    assert 'languages = ["en", "tr"]' in (catalog / "pack.toml").read_text(encoding="utf-8")
    # The catalog's own name is written in the language too, beside its English name.
    manifest = tomllib.loads((catalog / "pack.toml").read_text(encoding="utf-8"))
    assert manifest["names"] == {"tr": "Turkish: Tools"} and manifest["pack"]["name"] == "Tools"


def test_asking_twice_translates_nothing_and_changes_no_file(catalog):
    tool = _load()
    tool.translate_file(catalog, "tr", shout)
    before = (catalog / "data" / "claims.yaml").read_bytes(), (catalog / "pack.toml").read_bytes()

    def refuse(items, language):
        raise AssertionError("nothing is left to translate, so nothing may be asked")

    assert tool.translate_file(catalog, "tr", refuse) == 0
    assert ((catalog / "data" / "claims.yaml").read_bytes(), (catalog / "pack.toml").read_bytes()) == before


def test_a_batch_the_translator_gets_wrong_is_asked_again_in_smaller_pieces(catalog):
    asked = []

    def flaky(items, language):
        asked.append(len(items))
        return shout(items, language)[:-1] if len(items) > 1 else shout(items, language)

    assert _load().translate_file(catalog, "tr", flaky) == 2
    assert asked == [2, 1, 1, 1]  # the last one is the catalog's name
    assert all("tr" in claim["text"] for claim in _read(catalog))


def test_a_translation_with_a_field_empty_is_refused_rather_than_written(catalog):
    def hollow(items, language):
        return [{**item, "body": ""} for item in items]

    with pytest.raises(ValueError):
        _load().translate_file(catalog, "tr", hollow)
    # Nothing was written for a run that failed.
    assert textwrap.dedent(CLAIMS) == (catalog / "data" / "claims.yaml").read_text(encoding="utf-8")
