"""The reader's word rules, checked in the gate (B162).

The reader asked, on 2026-09-29: "Remove every unprofessional phrase ("what is
this", "throw it away", "cover the gaps", etc.)", "Cut wording everywhere,
there are too many words", "Remove all em dashes". Before this file the rules
lived in a backlog paragraph, and a rule that only a person remembers is
broken by the next screen someone edits.

Two rules, over text a reader sees:

  1. no em dash (`—`, or its escapes `\\u2014`, `&mdash;`, `&#8212;`);
  2. none of the reader's own examples of informal wording, case-insensitive,
     whitespace-tolerant: "what is this", "throw it away", "cover the gaps",
     "one click". The list is `INFORMAL_PHRASES` below and holds the reader's
     words only. Add to it when the reader names another phrase; do not turn it
     into a vocabulary of anything else.

**A ratchet, not a zero.** The tree already holds a couple of hundred hits
that each screen's own item and B187 remove. So the test compares each file's
count with `tools/reader_words_baseline.json`:

  * a count ABOVE its baseline (or any hit in a file the baseline does not
    list) fails, naming file, line and rule;
  * a count BELOW its baseline only WARNS, "lower the baseline to N". It does
    not fail, because several PRs cut text in parallel and a failing drop would
    turn main red after every merge until someone regenerated the baseline. The
    cost is headroom: until the baseline is lowered, a later change in the same
    file could put the same number of dashes back and pass. Lower it (below)
    in the PR that cuts text, or once after a batch of merges. The baseline
    keeps one line per file so two PRs touching different files never conflict.

Every run reports the remaining total (a pytest warning, so it is in the
gate's output), which B187 drives to zero. At zero the baseline holds no files
and the guard is absolute.

Regenerate after a PR that lowers counts (or after other PRs merge). It writes
the current counts and refuses to raise any count or add any file:

    .venv/Scripts/python.exe src/app/tests/test_reader_words.py --write

`--allow-raise` overrides that refusal; it exists for the first generation and
for a file that was renamed (its baseline line moves with it). A raise is a
reviewable diff, never something the test does on its own. With no flag the
script prints the same per-file report the test uses.

**What is read** ("a reader sees it"):

  * `ui/src/**/*.svelte`: template text (element text and attribute values),
    the string literals of every `{...}` expression and block, and the string
    literals of `<script>`. Not `<style>`, not `<!-- -->` comments, not JS/TS
    comments;
  * `ui/src/**/*.ts` except tests (`*.test.ts`, `test-setup.ts`, `tests/`):
    string and template-literal text, not comments;
  * `extension/**/*.js` and `extension/**/*.html` except `extension/tests/`
    and `node_modules/`: the same, plus `extension/manifest.json` and
    `ui/index.html` (the extension's listing text and the app's window title).

**Limits of the heuristic**, so a green run is not read as more than it is:

  * The JS scanner is a small tokenizer (strings, template literals with `${}`,
    comments, regex literals), not a parser. It decides "regex or division" from
    the previous token, so an exotic `}` / `/` sequence can misjudge one line;
    the damage stops at the end of that line.
  * Only literal text is read. A phrase assembled at run time (`"one " +
    "click"`), split across two elements (`<b>One</b> click`) or produced by the
    server never matches. Server messages that reach a screen are B187's walk.
  * Every string literal counts, visible or not: an em dash in a `console.log`
    or an error that never reaches a screen is a hit too. Better a needless
    hit than a hidden one; the fix is to reword it.
  * Regex literals are skipped (a pattern that matches an em dash prints
    nothing), and so are `.css` files (`content: "—"` would slip through; none
    exists today) and code comments, docs and tests, which no reader sees.
  * A string that spells the dash some other way (`String.fromCharCode(8212)`)
    is not caught.

Each rule of the scanner is pinned by a synthetic source below, so a change to
the tokenizer that stops it excluding comments or reading a template literal
fails here rather than silently widening or narrowing the check.
"""

from __future__ import annotations

import json
import re
import sys
import warnings
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
# In tools/, not beside this file: a data file under src/ must be declared as
# package data (test_every_data_file_under_src_is_declared_as_package_data), and
# a dev-only ratchet has no business in the wheel.
BASELINE = REPO / "tools" / "reader_words_baseline.json"

# The reader's own examples, from the backlog entry of 2026-09-29. Extend with
# phrases the reader names; nothing else belongs here.
INFORMAL_PHRASES = (
    "what is this",
    "throw it away",
    "cover the gaps",
    "one click",
)

# Runs of whitespace (a line wrap in a template, a no-break space) count as one
# space, so a phrase wrapped across two source lines is still the phrase.
_GAP = r"[\s ]+"
RULES: dict[str, re.Pattern[str]] = {
    "em_dash": re.compile(
        r"—|\\u2014|\\u\{0*2014\}|&mdash;|&#0*8212;|&#x0*2014;", re.IGNORECASE
    ),
    "informal_phrase": re.compile(
        r"\b(?:" + "|".join(_GAP.join(p.split()) for p in INFORMAL_PHRASES) + r")\b",
        re.IGNORECASE,
    ),
}

#: (character offset in the file, literal text found there)
Segment = tuple[int, str]


# ── reading text out of source ────────────────────────────────────────────

# A `/` starts a regex literal (not a division) after one of these characters
# or one of these keywords. After an identifier, number, `)` or `]` it divides.
_REGEX_AFTER = frozenset("(,=:[!&|?{};+-*%<>~^")
_REGEX_KEYWORDS = frozenset(
    "return typeof instanceof in of new delete void throw case do else yield await".split()
)


def _skip_regex(src: str, i: int, end: int) -> int:
    """Index just past the regex literal (and flags) opening at `src[i]`."""
    j = i + 1
    in_class = False
    while j < end and src[j] != "\n":
        ch = src[j]
        if ch == "\\":
            j += 2
            continue
        if ch == "[":
            in_class = True
        elif ch == "]":
            in_class = False
        elif ch == "/" and not in_class:
            j += 1
            break
        j += 1
    while j < end and src[j].isalpha():
        j += 1
    return j


def _scan_template_literal(src: str, i: int, end: int, out: list[Segment]) -> int:
    """Collect a backtick literal's text; `${...}` is code, scanned for its own
    strings. `i` is just past the opening backtick; returns just past the close."""
    start = i
    while i < end:
        c = src[i]
        if c == "\\":
            i += 2
        elif c == "`":
            out.append((start, src[start:i]))
            return i + 1
        elif c == "$" and src[i + 1 : i + 2] == "{":
            out.append((start, src[start:i]))
            i = _scan_js(src, i + 2, end, out, close_brace=True)
            start = i
        else:
            i += 1
    out.append((start, src[start:end]))
    return end


def _scan_js(
    src: str, i: int, end: int, out: list[Segment], *, close_brace: bool = False
) -> int:
    """Append every string / template-literal segment in `src[i:end]` to `out`.

    Comments and regex literals are skipped. With `close_brace` the scan stops
    at the `}` that closes the `{` the caller already consumed (a template
    `${` or a Svelte `{`) and returns the index just past it; otherwise it runs
    to `end`.
    """
    depth = 0
    prev = ""  # the last significant character
    word = ""  # the identifier that ended at `prev`, if it did
    while i < end:
        c = src[i]
        if c in " \t\r\n":
            i += 1
        elif src.startswith("//", i):
            j = src.find("\n", i, end)
            i = end if j == -1 else j
        elif src.startswith("/*", i):
            j = src.find("*/", i + 2, end)
            i = end if j == -1 else j + 2
        elif c in "\"'":
            j = i + 1
            while j < end and src[j] != c and src[j] != "\n":
                j += 2 if src[j] == "\\" else 1
            out.append((i + 1, src[i + 1 : min(j, end)]))
            i, prev, word = j + 1, c, ""
        elif c == "`":
            i, prev, word = _scan_template_literal(src, i + 1, end, out), "`", ""
        elif c == "/":
            if prev == "" or prev in _REGEX_AFTER or word in _REGEX_KEYWORDS:
                i, prev, word = _skip_regex(src, i, end), ")", ""
            else:
                i, prev, word = i + 1, "/", ""
        elif c.isalnum() or c in "_$":
            j = i + 1
            while j < end and (src[j].isalnum() or src[j] in "_$"):
                j += 1
            i, prev, word = j, src[j - 1], src[i:j]
        else:
            if c == "{":
                depth += 1
            elif c == "}":
                if depth == 0 and close_brace:
                    return i + 1
                depth = max(depth - 1, 0)
            i, prev, word = i + 1, c, ""
    return end


_MARKUP_WITH_EXPRESSIONS = re.compile(r"<!--|<script\b[^>]*>|<style\b[^>]*>|\{")
_MARKUP_PLAIN = re.compile(r"<!--|<script\b[^>]*>|<style\b[^>]*>")


def _scan_markup(src: str, *, expressions: bool) -> list[Segment]:
    """Segments of an HTML or Svelte file: text runs, attribute values, the
    strings of `<script>` and (Svelte only) of `{...}` expressions. Not
    `<style>` and not `<!-- -->`."""
    special = _MARKUP_WITH_EXPRESSIONS if expressions else _MARKUP_PLAIN
    out: list[Segment] = []
    i, n = 0, len(src)
    while i < n:
        m = special.search(src, i)
        if m is None:
            out.append((i, src[i:]))
            break
        if m.start() > i:
            out.append((i, src[i : m.start()]))
        token = m.group(0)
        if token == "<!--":
            j = src.find("-->", m.end())
            i = n if j == -1 else j + 3
        elif token.startswith("<script"):
            j = src.find("</script", m.end())
            i = n if j == -1 else j
            _scan_js(src, m.end(), i, out)
        elif token.startswith("<style"):
            j = src.find("</style", m.end())
            i = n if j == -1 else j
        elif src.startswith("/", m.end()):
            # `{/if}`, `{/each}`: a block's close, no text in it.
            j = src.find("}", m.end())
            i = n if j == -1 else j + 1
        else:
            i = _scan_js(src, m.end(), n, out, close_brace=True)
    return out


# Markup carried inside a JS string (the extension builds its panel as HTML in
# template literals) can hold its own comments and styles. Blanked, not
# removed, so line numbers stay true. A comment that itself contains a `${}`
# is split into two segments and escapes this; none does today.
_NOT_SHOWN = re.compile(r"<!--.*?-->|<style\b.*?</style>", re.DOTALL | re.IGNORECASE)


def _segments(path: Path, src: str) -> list[Segment]:
    if path.suffix == ".svelte":
        return _scan_markup(src, expressions=True)
    if path.suffix == ".html":
        return _scan_markup(src, expressions=False)
    if path.suffix == ".json":
        return [(0, src)]  # no comments in JSON; the whole file is data
    out: list[Segment] = []
    _scan_js(src, 0, len(src), out)
    return out


# ── the rules over a file ─────────────────────────────────────────────────


def scan_source(path: Path, src: str) -> list[tuple[str, int, str]]:
    """(rule, line, text) for each hit in one file's reader-visible text."""
    hits: list[tuple[str, int, str]] = []
    lines = src.splitlines()
    for start, text in _segments(path, src):
        text = _NOT_SHOWN.sub(lambda m: re.sub(r"\S", " ", m.group(0)), text)
        for rule, pattern in RULES.items():
            for m in pattern.finditer(text):
                line = src.count("\n", 0, start + m.start()) + 1
                hits.append((rule, line, lines[line - 1].strip()[:100]))
    return sorted(hits, key=lambda h: (h[1], h[0]))


def _is_test_file(path: Path) -> bool:
    return (
        ".test." in path.name
        or path.name == "test-setup.ts"
        or bool({"tests", "__tests__", "node_modules"} & set(path.parts))
    )


def reader_visible_files() -> list[Path]:
    ui, ext = REPO / "ui", REPO / "extension"
    found: list[Path] = []
    for path in sorted((ui / "src").rglob("*")) if (ui / "src").is_dir() else []:
        if path.suffix in {".svelte", ".ts"}:
            found.append(path)
    if (ui / "index.html").is_file():
        found.append(ui / "index.html")
    if ext.is_dir():
        for path in sorted(ext.rglob("*")):
            if path.suffix in {".js", ".html"}:
                found.append(path)
        if (ext / "manifest.json").is_file():
            found.append(ext / "manifest.json")
    return [p for p in found if not _is_test_file(p.relative_to(REPO))]


def scan_repo() -> dict[str, list[tuple[str, int, str]]]:
    """Repo-relative path -> hits, for every file that has at least one."""
    result: dict[str, list[tuple[str, int, str]]] = {}
    for path in reader_visible_files():
        hits = scan_source(path, path.read_text(encoding="utf-8"))
        if hits:
            result[path.relative_to(REPO).as_posix()] = hits
    return result


def count_hits(
    found: dict[str, list[tuple[str, int, str]]],
) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {}
    for rel, hits in found.items():
        for rule, _line, _text in hits:
            per_file = counts.setdefault(rel, {})
            per_file[rule] = per_file.get(rule, 0) + 1
    return counts


# ── the baseline ──────────────────────────────────────────────────────────


def load_baseline() -> dict[str, dict[str, int]]:
    files = json.loads(BASELINE.read_text(encoding="utf-8"))["files"]
    return {rel: dict(rules) for rel, rules in files.items()}


def format_baseline(counts: dict[str, dict[str, int]]) -> str:
    """One line per file: a diff (and a merge) touches only the files it names."""
    lines = [
        f"    {json.dumps(rel)}: {json.dumps(dict(sorted(rules.items())))}"
        for rel, rules in sorted(counts.items())
    ]
    body = ",\n".join(lines)
    return (
        '{\n  "_about": "B162 ratchet: reader-visible em dashes and informal phrases '
        "left per file. Only ever lowered; see src/app/tests/test_reader_words.py. "
        'Regenerate: python src/app/tests/test_reader_words.py --write",\n'
        f'  "files": {{\n{body}\n  }}\n}}\n'
    )


def _compare(
    found: dict[str, list[tuple[str, int, str]]],
    baseline: dict[str, dict[str, int]],
) -> tuple[list[str], list[str]]:
    """(over, under): messages for counts above and below the baseline."""
    counts = count_hits(found)
    over: list[str] = []
    under: list[str] = []
    for rel in sorted(set(counts) | set(baseline)):
        for rule in RULES:
            now = counts.get(rel, {}).get(rule, 0)
            allowed = baseline.get(rel, {}).get(rule, 0)
            if now > allowed:
                lines = "\n".join(
                    f"    {rel}:{line}: [{r}] {text}"
                    for r, line, text in found[rel]
                    if r == rule
                )
                over.append(
                    f"{rel}: {now} {rule} hit(s), baseline allows {allowed}. "
                    f"Reword the new text; do not raise the baseline. All hits in "
                    f"this file:\n{lines}"
                )
            elif now < allowed:
                under.append(
                    f"{rel}: {rule} is {now}, baseline says {allowed}; "
                    f"lower the baseline to {now}"
                )
    return over, under


def _remaining(counts: dict[str, dict[str, int]]) -> str:
    per_rule = {r: sum(c.get(r, 0) for c in counts.values()) for r in RULES}
    total = sum(per_rule.values())
    by_file = sorted(counts.items(), key=lambda kv: -sum(kv[1].values()))[:5]
    worst = ", ".join(f"{Path(rel).name} {sum(c.values())}" for rel, c in by_file)
    return (
        f"reader words: {total} left to remove "
        f"({', '.join(f'{r} {n}' for r, n in per_rule.items())}) in "
        f"{len(counts)} file(s); most in {worst or 'none'}. "
        f"B187 takes this to zero."
    )


class ReaderWordsRemaining(UserWarning):
    """The count B187 drives to zero, shown in the gate's warning summary."""


class ReaderWordsBelowBaseline(UserWarning):
    """A count dropped below its baseline: good, and worth recording."""


def _lower_message(under: list[str]) -> str:
    return (
        "the count went down; record it so it cannot come back. Lower the "
        "baseline with\n  "
        + _REGENERATE
        + "\nand commit tools/reader_words_baseline.json:\n"
        + "\n".join(f"  {u}" for u in under)
    )


_REGENERATE = (
    "python src/app/tests/test_reader_words.py --write"
    "   (from the repo root, with the project's Python)"
)


# ── the guard ─────────────────────────────────────────────────────────────


def test_reader_visible_words_only_go_down():
    """No new em dash or informal phrase; a drop warns, it does not fail."""
    found = scan_repo()
    counts = count_hits(found)
    over, under = _compare(found, load_baseline())
    message = _remaining(counts)
    print(message)
    warnings.warn(message, ReaderWordsRemaining, stacklevel=1)
    assert not over, (
        "reader-visible text broke the word rules (no em dash, no informal "
        "phrase; B162):\n" + "\n".join(over)
    )
    if under:
        warnings.warn(_lower_message(under), ReaderWordsBelowBaseline, stacklevel=1)


def test_a_count_below_the_baseline_warns_and_does_not_fail(monkeypatch):
    real = load_baseline()
    if not real:
        # B187 landed: the baseline is empty and the guard absolute. A drop
        # no longer exists to warn about, so the ratchet's one soft path is
        # unreachable and this self-test retires by passing.
        return
    rel = next(iter(real))
    higher = {**real, rel: {r: n + 3 for r, n in real[rel].items()}}
    monkeypatch.setattr(sys.modules[__name__], "load_baseline", lambda: higher)
    with pytest.warns(ReaderWordsBelowBaseline, match="lower the baseline to"):
        test_reader_visible_words_only_go_down()


def test_the_scan_reads_the_files_a_reader_sees():
    """A guard that scanned nothing would stay green forever."""
    files = [p.relative_to(REPO).as_posix() for p in reader_visible_files()]
    svelte = [f for f in files if f.startswith("ui/src/") and f.endswith(".svelte")]
    ts = [f for f in files if f.startswith("ui/src/") and f.endswith(".ts")]
    ext = [f for f in files if f.startswith("extension/")]
    assert len(svelte) >= 20, f"only {len(svelte)} .svelte file(s) scanned"
    assert len(ts) >= 5, f"only {len(ts)} .ts file(s) scanned"
    assert len(ext) >= 5, f"only {len(ext)} extension file(s) scanned"
    assert "extension/options/options.html" in files
    assert "extension/manifest.json" in files
    # Tests and fixtures hold realistic text a reader never sees.
    assert not [f for f in files if ".test." in f or "/tests/" in f]


def test_the_baseline_is_well_formed():
    baseline = load_baseline()
    for rel, rules in baseline.items():
        assert (REPO / rel).is_file() or not rules, f"{rel} is gone; drop its line"
        assert set(rules) <= set(RULES), f"{rel}: unknown rule in {sorted(rules)}"
        assert all(isinstance(n, int) and n > 0 for n in rules.values()), (
            f"{rel}: a zero belongs as no entry at all"
        )
    assert BASELINE.read_text(encoding="utf-8") == format_baseline(baseline), (
        "reader_words_baseline.json is hand-edited out of shape; write it with "
        + _REGENERATE
    )


# ── the scanner, pinned on synthetic sources ──────────────────────────────
# Each case is a source the real tree could hold. A tokenizer change that
# starts excluding text a reader sees, or reading text one never does, fails
# here first.

DASH = "—"


def _hits(name: str, src: str) -> list[tuple[str, int]]:
    return [(rule, line) for rule, line, _ in scan_source(Path(name), src)]


def test_template_text_and_attribute_values_are_read():
    src = f'<h1>Done {DASH} really</h1>\n<input placeholder="a {DASH} b" />\n'
    assert _hits("x.svelte", src) == [("em_dash", 1), ("em_dash", 2)]


def test_style_blocks_and_comments_are_not_read():
    src = (
        f"<!-- a {DASH} comment, and a <style> mention -->\n"
        f"<style>\n  /* {DASH} */\n  .a::after {{ content: 'x'; }}\n</style>\n"
        f"<script lang=\"ts\">\n  // {DASH} line comment\n  /* {DASH}\n     block */\n"
        f"  const x = 1;\n</script>\n<p>fine</p>\n"
    )
    assert _hits("x.svelte", src) == []


def test_script_and_expression_strings_are_read_with_their_line():
    src = (
        '<script lang="ts">\n'
        f'  const a = "one {DASH} two";\n'
        f"  const b = `three {DASH} ${{a}}`;\n"
        "</script>\n"
        f'<p>{{ok ? "x" : "y {DASH} z"}}</p>\n'
        f"{{#if ok}}<b>fine</b>{{/if}}\n"
    )
    assert _hits("x.svelte", src) == [("em_dash", 2), ("em_dash", 3), ("em_dash", 5)]


def test_a_template_literal_reads_its_text_and_the_strings_inside_its_code():
    src = f"const s = `plain ${{f('inner {DASH}')}} tail`;\n"
    assert _hits("x.ts", src) == [("em_dash", 1)]
    assert _hits("x.ts", "const s = `a ${1 // c\n} b`;\n") == []


def test_the_dash_spelled_as_an_escape_or_an_entity_is_read():
    assert _hits("x.ts", r'const a = "a — b";' + "\n") == [("em_dash", 1)]
    assert _hits("x.ts", r'const a = "a \u{2014} b";' + "\n") == [("em_dash", 1)]
    assert _hits("x.svelte", "<p>a &mdash; b</p>\n") == [("em_dash", 1)]
    assert _hits("x.svelte", "<p>a &#8212; b</p>\n") == [("em_dash", 1)]
    assert _hits("x.svelte", "<p>a &#x2014; b</p>\n") == [("em_dash", 1)]


def test_a_regex_literal_neither_hides_a_string_nor_is_read():
    # The quote inside the regex must not open a string that swallows the next
    # line, and a dash the regex matches on is not printed text.
    src = (
        f"const re = /['\"{DASH}]/g;\n"
        f'const t = "shown {DASH}";\n'
        "const n = a / b; const u = 'x' + c / d;\n"
    )
    assert _hits("x.ts", src) == [("em_dash", 2)]


def test_a_url_with_slashes_is_a_string_not_a_comment():
    src = f'const u = "http://example.test/a"; const t = "x {DASH}";\n'
    assert _hits("x.ts", src) == [("em_dash", 1)]


def test_markup_inside_a_js_string_keeps_its_comments_and_styles_out():
    src = (
        f"el.innerHTML = `<b>fine</b><!-- {DASH}\n   {DASH} --><style>a{{}} /* {DASH} */"
        f"</style><i>x {DASH}</i>`;\n"
    )
    assert _hits("x.js", src) == [("em_dash", 2)]


def test_html_reads_text_and_inline_script_but_not_comments_or_styles():
    src = (
        f"<!doctype html>\n<title>Kriko {DASH} settings</title>\n"
        f"<!-- {DASH} -->\n<style>a::after{{content:'{DASH}'}}</style>\n"
        f"<script>\n  // {DASH}\n  var s = 'x {DASH}';\n</script>\n"
        f"<p>curly {{braces}} are text here, {DASH}</p>\n"
    )
    assert _hits("x.html", src) == [("em_dash", 2), ("em_dash", 7), ("em_dash", 9)]


def test_the_informal_phrases_match_case_insensitively_across_a_line_wrap():
    src = (
        "<h3>One click</h3>\n"
        "<p>Really throw\n    it away?</p>\n"
        '<button>{n ? "Cover the gaps" : "What is this"}</button>\n'
        "<p>Phone: one clicker, at once</p>\n"  # a different word; no match
    )
    assert [r for r, _ in _hits("x.svelte", src)] == ["informal_phrase"] * 4
    assert [ln for _, ln in _hits("x.svelte", src)] == [1, 2, 4, 4]


def test_each_informal_phrase_of_the_reader_is_a_rule():
    for phrase in INFORMAL_PHRASES:
        assert _hits("x.svelte", f"<p>{phrase.upper()}</p>") == [("informal_phrase", 1)]


def test_test_files_are_out_of_scope():
    for rel in (
        "ui/src/App.test.ts",
        "ui/src/test-setup.ts",
        "extension/tests/content.test.js",
        "extension/tests/pages/x.html",
    ):
        assert _is_test_file(Path(rel)), rel
    assert not _is_test_file(Path("ui/src/routes/Bench.svelte"))
    assert not _is_test_file(Path("extension/content.js"))


def test_the_baseline_comparison_names_growth_and_drops():
    found = {
        "a.svelte": [("em_dash", 3, "x"), ("em_dash", 9, "y")],
        "new.ts": [("informal_phrase", 1, "one click")],
    }
    baseline = {"a.svelte": {"em_dash": 1}, "gone.ts": {"em_dash": 4}}
    over, under = _compare(found, baseline)
    assert len(over) == 2
    assert "a.svelte: 2 em_dash hit(s), baseline allows 1" in over[0]
    assert "a.svelte:3: [em_dash]" in over[0] and "a.svelte:9: [em_dash]" in over[0]
    assert "new.ts: 1 informal_phrase hit(s), baseline allows 0" in over[1]
    assert under == ["gone.ts: em_dash is 0, baseline says 4; lower the baseline to 0"]
    assert _compare({"a.svelte": found["a.svelte"][:1]}, {"a.svelte": {"em_dash": 1}}) == (
        [],
        [],
    )


# ── regenerating the baseline ─────────────────────────────────────────────


def _main(argv: list[str]) -> int:
    # The tree's text is UTF-8; a Windows console defaults to a code page that
    # cannot print half of it.
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    found = scan_repo()
    counts = count_hits(found)
    if "--write" not in argv:
        for rel, hits in found.items():
            for rule, line, text in hits:
                print(f"{rel}:{line}: [{rule}] {text}")
        print(_remaining(counts))
        return 0
    old = load_baseline() if BASELINE.is_file() else {}
    raised = [
        f"{rel}: {rule} {old.get(rel, {}).get(rule, 0)} -> {n}"
        for rel, rules in sorted(counts.items())
        for rule, n in sorted(rules.items())
        if n > old.get(rel, {}).get(rule, 0)
    ]
    if raised and "--allow-raise" not in argv:
        print(
            "refusing to raise the baseline (new hits must be reworded; a renamed "
            "file or the first generation needs --allow-raise):\n  "
            + "\n  ".join(raised),
            file=sys.stderr,
        )
        return 1
    BASELINE.write_text(format_baseline(counts), encoding="utf-8", newline="\n")
    print(f"wrote {BASELINE.relative_to(REPO).as_posix()}")
    print(_remaining(counts))
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
