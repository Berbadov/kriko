"""The core must not learn about cars again.

Goal G6's entire promise is that adding a product category costs data and no
engine code. That promise decays silently: someone hits an awkward case, writes
`if fuel == "diesel"` inside `kriko/`, the car tests still pass, and nobody finds
out until a second category is attempted months later. This is the same failure
mode CLAUDE.md records for `SIBLING_CODE_FAMILIES` and `normalize.py`'s
`_MAKE_MAP` — a hand-maintained car list that went stale because nothing checked.

So this test checks. It scans `kriko/` for car vocabulary in *executable*
positions — identifiers, attribute names, and string literals that are not
docstrings. That alone is not enough: this repository is public, and a reader
arriving to write a pack for a product Kriko has never seen cannot run this
AST check — they just read, and believe what they read. So prose is checked
too, separately: `_offences` still skips docstrings
(comments were never reachable by `ast` at all), and `_prose_offences` is the
scanner that catches banned vocabulary in exactly those two places, docstrings
and comments, against an explicit `ALLOWED_PROSE` allowlist of the category
examples that earn their place.
"""

import ast
import io
import re
import tokenize
from pathlib import Path

CORE = Path(__file__).resolve().parent.parent

# Vocabulary that belongs to a pack, never to the engine.
BANNED = {
    "make", "model", "variant", "trim", "engine", "fuel", "diesel", "petrol",
    "mileage", "odometer", "displacement", "transmission", "gearbox", "dsg",
    "drivetrain", "emissions", "aftertreatment", "car", "vehicle", "sahibinden",
    "ekspertiz",
}

# Prose needs a narrower list than BANNED. BANNED is written for executable
# positions, where `engine` in an identifier (`engine_code`) is a real
# violation. In prose, three of its words are this project's own vocabulary:
#
#   engine  — kriko/ IS "the engine"; "the engine owns orchestration" is
#             correct and appears throughout.
#   make    — the English verb.
#   model   — "data model", "the model".
#
# The executable check still catches all three as identifiers, attributes and
# non-docstring strings, so dropping them here narrows the prose gate without
# weakening the guarantee that matters.
PROSE_BANNED = BANNED - {"engine", "make", "model"}

# Words that legitimately contain a banned substring. Matching is on whole words,
# so this stays short; it exists for the cases where it genuinely is not.
# An empty set, not an empty dict — `{}` here would be a dict and the set
# difference below would raise. Add genuine exceptions ("model" in the
# machine-learning sense, say) explicitly rather than loosening the regex.
ALLOWED_EXACT: set[str] = set()

_WORD = re.compile(r"[a-z][a-z0-9]*")


def _split_identifier(name: str) -> list[str]:
    """snake_case and camelCase both split into their words."""
    return _WORD.findall(re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower())


def _stem(word: str) -> str:
    """A deliberately dumb trailing-s/-es stripper, applied only for matching.

    Whole-word matching alone let plurals through: `cars`, `vehicles`,
    `gearboxes`, `models` all pass a whole-word check against a BANNED list
    written in the singular. This is what let `packs.cars.pipeline.sqlite`
    (Critical, this review) go unseen — it splits to `['packs', 'cars', ...]`
    and `car != cars`.

    The length guards keep this from mangling short words into noise
    (`"gas"` stays `"gas"`), and because `_split_identifier` already yields
    whole words, stripping a suffix can never manufacture a false substring
    match — the risk a plain substring search would carry.
    """
    if word.endswith("es") and len(word) > 4:
        return word[:-2]
    if word.endswith("s") and len(word) > 3:
        return word[:-1]
    return word


def _banned_stems(vocabulary: set[str]) -> set[str]:
    return {_stem(w) for w in vocabulary} | vocabulary


def _hits(words: list[str], vocabulary: set[str]) -> list[str]:
    """Words matching `vocabulary` exactly or once trailing-s/-es is stripped."""
    stems = _banned_stems(vocabulary)
    return sorted({w for w in words if w in vocabulary or _stem(w) in stems})


def _docstring_nodes(tree: ast.AST) -> set[int]:
    """Every string node that is a docstring, by identity, so prose is exempt."""
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                out.add(id(body[0].value))
    return out


def _concatenated(node) -> str | None:
    """The whole string a node builds, when it builds one out of literals.

    `_offences` reads one `ast.Constant` at a time, which is enough for every
    honest way of writing a word and useless against `"fu" + "el"`: neither
    half is a banned word, and the vocabulary the engine may not know is back.
    Adjacent literals (`"fu" "el"`) are folded by the parser and were already
    caught; an explicit `+`, an f-string, and `"".join([...])` were not.
    """
    if isinstance(node, ast.Constant):
        return node.value if isinstance(node.value, str) else None
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _concatenated(node.left), _concatenated(node.right)
        return None if left is None or right is None else left + right
    if isinstance(node, ast.JoinedStr):
        parts = [_concatenated(one) for one in node.values]
        return None if any(one is None for one in parts) else "".join(parts)
    if isinstance(node, ast.FormattedValue):
        return ""
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "join"
        and len(node.args) == 1
        and isinstance(node.args[0], (ast.List, ast.Tuple))
    ):
        glue = _concatenated(node.func.value)
        parts = [_concatenated(one) for one in node.args[0].elts]
        if glue is None or any(one is None for one in parts):
            return None
        return glue.join(parts)
    return None


def _offences(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = _docstring_nodes(tree)
    found = []

    for node in ast.walk(tree):
        words: list[str] = []
        where = ""

        if isinstance(node, ast.Name):
            words, where = _split_identifier(node.id), f"name {node.id!r}"
        elif isinstance(node, ast.Attribute):
            words, where = _split_identifier(node.attr), f"attribute {node.attr!r}"
        elif isinstance(node, ast.arg):
            words, where = _split_identifier(node.arg), f"argument {node.arg!r}"
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            words, where = _split_identifier(node.name), f"definition {node.name!r}"
        elif isinstance(node, (ast.BinOp, ast.JoinedStr, ast.Call)):
            built = _concatenated(node)
            if not built:
                continue
            words, where = _split_identifier(built), f"built string {built[:40]!r}"
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) in docstrings:
                continue
            words, where = _split_identifier(node.value), f"string {node.value[:40]!r}"

        hits = sorted(set(_hits(words, BANNED)) - ALLOWED_EXACT)
        if hits:
            line = getattr(node, "lineno", 0)
            found.append(f"{path.name}:{line}: {where} contains {hits}")

    return found


def _comments(path: Path) -> list[tuple[int, str]]:
    """Every comment in a file, as (lineno, text). ast discards comments."""
    src = path.read_text(encoding="utf-8")
    out = []
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == tokenize.COMMENT:
            out.append((tok.start[0], tok.string))
    return out


# Prose in the engine may not explain a generic mechanism through one
# category's vocabulary — a reader writing a pack for dishwashers should not
# find every explanation phrased in gearboxes. A category example is allowed
# where it genuinely clarifies a rule, and each one is named here so that the
# exception is a visible decision rather than an oversight.
#
# filename -> the banned terms that file may use in prose.
ALLOWED_PROSE: dict[str, set[str]] = {
    # Locale-dependent number formatting is hard to convey abstractly; the
    # "148.000 km" case is a real hazard this module exists to handle, and it
    # is framed as one instance of the hazard rather than the definition of it.
    "adapters.py": {"mileage"},
    # `resolve()`'s docstring explains why resolution is per-pack, not merged,
    # by naming a real collision it prevents: two installed packs disagreeing
    # about what to call the same attribute (cars' `make`/`brand` vs drill's
    # opposite convention). Two categories side by side is the illustration,
    # not a mechanism explained through one category's vocabulary — the case
    # this gate exists to catch.
    "match.py": {"cars"},
    # base.py's docstring makes the same point the same way: "what makes a
    # claim worth keeping" differs by category, shown as cars vs. a washing
    # machine — two examples, neither treated as the definition.
    "base.py": {"cars"},
}


def _prose_offences(path: Path) -> list[str]:
    """Banned vocabulary in docstrings and comments, minus the allowlist."""
    permitted = ALLOWED_PROSE.get(path.name, set())
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = []

    for node in ast.walk(tree):
        if not (isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                  ast.AsyncFunctionDef))):
            continue
        text = ast.get_docstring(node)
        if not text:
            continue
        hits = sorted(set(_hits(_split_identifier(text), PROSE_BANNED)) - permitted)
        if hits:
            line = getattr(node, "lineno", 1)
            found.append(f"{path.name}:{line}: docstring contains {hits}")

    for lineno, text in _comments(path):
        hits = sorted(set(_hits(_split_identifier(text), PROSE_BANNED)) - permitted)
        if hits:
            found.append(f"{path.name}:{lineno}: comment contains {hits}")

    return found


def test_the_engine_contains_no_car_vocabulary():
    offences = []
    for path in sorted(CORE.rglob("*.py")):
        if "/tests/" in path.as_posix() or "__pycache__" in path.as_posix():
            continue
        offences.extend(_offences(path))

    assert offences == [], (
        "kriko/ has learned about a specific product category:\n  "
        + "\n  ".join(offences)
        + "\n\nThis belongs in a pack, as rows. If the engine genuinely needs "
          "the concept, name it generically (usage, identity, subject) and let "
          "the pack supply the vocabulary."
    )


def test_the_engine_does_not_explain_itself_in_one_category():
    """The code is category-free; the prose must be too.

    A reader arriving to write a pack for a product Kriko has never seen
    should not find every explanation phrased in another category's terms.
    That reader cannot run the AST check — they just read, and believe what
    they read.
    """
    offences = []
    for path in sorted(CORE.rglob("*.py")):
        if "/tests/" in path.as_posix() or "__pycache__" in path.as_posix():
            continue
        offences.extend(_prose_offences(path))

    assert offences == [], (
        "kriko/ explains itself in one product category:\n  "
        + "\n  ".join(offences)
        + "\n\nState the generic rule first. A category example may follow "
          "where it genuinely clarifies — add it to ALLOWED_PROSE so the "
          "exception is a decision someone made on purpose."
    )


def test_the_guard_actually_catches_something():
    """A guard nobody has seen fail is a guard nobody knows is wired up."""
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as fh:
        fh.write('"""A docstring may mention fuel freely."""\n'
                 'def check_fuel_type(engine_code):\n'
                 '    return engine_code == "diesel"\n')
        path = Path(fh.name)

    try:
        offences = _offences(path)
        assert any("check_fuel_type" in o for o in offences)
        assert any("engine_code" in o for o in offences)
        assert any("diesel" in o for o in offences)
        # ...and the docstring did not trip _offences: it exempts docstrings,
        # leaving that job to _prose_offences.
        assert not any("A docstring may mention" in o for o in offences)

        # _prose_offences is the half that does catch it: the module
        # docstring at line 1 trips on "fuel".
        prose_offences = _prose_offences(path)
        assert any("docstring contains" in o and "fuel" in o for o in prose_offences)
    finally:
        path.unlink()


def test_a_banned_word_cannot_be_assembled_out_of_innocent_halves():
    """Neither half is vocabulary; the whole is, and the whole is what runs.

    A gate that reads one literal at a time is not a gate against anyone who
    has noticed it reads one literal at a time -- and the engine knowing what
    a car is remains the one unforgivable violation however the word got
    spelled.
    """
    import tempfile

    written = (
        'def pick(row):\n'
        '    a = "fu" + "el"\n'
        '    b = "".join(["engine", "_", "code"])\n'
        '    c = f"{a}_type"\n'
        '    return row[a], row[b], row[c]\n'
    )
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as fh:
        fh.write(written)
        path = Path(fh.name)

    try:
        offences = _offences(path)
        assert any("fuel" in o for o in offences), offences
        assert any("engine" in o for o in offences), offences
    finally:
        path.unlink()
