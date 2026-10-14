"""#188: Kriko is for every product, and no shipped catalog says otherwise.

The only catalog with data was named "Used cars", and its bar opened "Kriko
surfaces the risks a used-car buyer...". Browse shows a catalog's name, the
agent skill builds its trigger line from installed names, and every research
brief quotes the bar, so readers and agents alike took Kriko for a used-car
tool. The second catalog's bar said "second-hand buyer" and repeated it.

Two rules, read from the files rather than typed as a list of catalogs:

* A bar speaks for its catalog. `research/principle.md` is one catalog's
  judgement, so it never says what *Kriko* surfaces.
* What a shipped catalog shows a reader or an agent (its name, every text
  asset a `.kpack` carries, the strings its pipeline sends a model) does not
  narrow a purchase to used or second-hand, whatever the category.

Claim texts are not read here. The framing in them was written by models that
had been handed the old bar and prompts; those claims were reworded once, and
this guards the bar and the prompts, which are what wrote it.
"""

import ast
import re
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
PACKS = sorted(p for p in (REPO / "packs").iterdir() if (p / "pack.toml").exists())

#: Wording that narrows a purchase to second-hand, for any category and in the
#: languages the shipped catalogs declare. A small closed vocabulary, not
#: category data: "used-<anything>" and "used <anything> buyer" cover cars,
#: phones and whatever comes next.
_SECOND_HAND = re.compile(
    r"\bused-[a-z]+|\bused [a-z]+ buyers?\b|\bsecond[- ]?hand\b|\bpre-owned\b"
    r"|ikinci el",
    re.IGNORECASE,
)
#: A name is a few words; "used" anywhere in it is the framing.
_SECOND_HAND_NAME = re.compile(rf"\bused\b|{_SECOND_HAND.pattern}", re.IGNORECASE)


def _strings_sent(path: Path) -> str:
    """The string literals a pipeline module can send, without its docstrings.

    Comments and docstrings are notes for whoever reads the code; a prompt is a
    string. Reading only strings keeps a historical comment from failing this.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef))
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    }
    return "\n".join(
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        and id(node) not in docstrings
    )


def _shown_text(pack: Path) -> dict[str, str]:
    """What of this pack a reader or an agent reads, apart from its name and claims."""
    shown = {}
    research = pack / "research"
    if research.is_dir():
        for path in sorted(research.iterdir()):
            if path.suffix in {".md", ".yaml", ".yml"}:
                shown[f"research/{path.name}"] = path.read_text(encoding="utf-8")
    for path in sorted((pack / "adapters").glob("*.json")):
        shown[f"adapters/{path.name}"] = path.read_text(encoding="utf-8")
    pipeline = pack / "pipeline"
    if pipeline.is_dir():
        for path in sorted(pipeline.rglob("*.py")):
            if "tests" not in path.parts:
                shown[str(path.relative_to(pack))] = _strings_sent(path)
    return shown


def test_there_are_catalogs_to_check():
    assert PACKS, "no pack.toml under packs/: this guard would pass on nothing"


def test_a_bar_speaks_for_its_catalog_not_for_kriko():
    for pack in PACKS:
        bar = pack / "research" / "principle.md"
        if bar.exists():
            assert "Kriko" not in bar.read_text(encoding="utf-8"), (
                f"{pack.name}: research/principle.md speaks for Kriko, "
                "not for this catalog"
            )


def test_no_catalog_name_narrows_a_purchase_to_second_hand():
    for pack in PACKS:
        name = tomllib.loads(
            (pack / "pack.toml").read_text(encoding="utf-8"))["pack"]["name"]
        assert not _SECOND_HAND_NAME.search(name), f"{pack.name}: {name!r}"


def test_no_shipped_catalog_text_narrows_a_purchase_to_second_hand():
    found = [
        f"{pack.name}/{where}: {match.group(0)!r}"
        for pack in PACKS
        for where, text in _shown_text(pack).items()
        for match in _SECOND_HAND.finditer(text)
    ]
    assert not found, "\n".join(found)


def test_the_guard_catches_any_category_not_only_cars():
    assert _SECOND_HAND_NAME.search("Used phones")
    assert _SECOND_HAND.search("the risks a used-phone buyer cannot see")
    assert _SECOND_HAND.search("what a used laptop buyer misses")
    assert not _SECOND_HAND.search("a part used by every model is used in the brief")
