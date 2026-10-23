"""Every path a client calls must be a route the engine serves.

Four parties speak HTTP to the one local engine: the browser extension
(JavaScript), the desktop window (TypeScript, `kriko-ui/src`), the Tauri shell
around it (Rust, `kriko-ui/src-tauri/src`) and the terminal interface (Python,
`src/app/tui`). Nothing used to check that what they call exists on the server,
so a renamed or dropped route was found by a reader pressing a button. This test
derives both sides from source and fails on the forward direction:

* the server side is the OpenAPI route table of a freshly built app;
* the client side is read from each client's source by a small lexer (JS and
  Rust) or by `ast` (Python), so a new call site is covered without a list of
  endpoints anywhere in this file.

Placeholders are one wildcard: `${...}` in JavaScript, `{}` / `{name}` in Rust
`format!` strings and `{name}` in FastAPI paths. A method is checked whenever
the client's call site names one (`_postApp`, `fetch(..., {method})`,
`api::post`, `self.post`, and so on); a call whose method cannot be read from
the source is checked on path alone.

The reverse direction, routes that no client calls, is reported as a warning
only: the MCP server and the command line use routes the windows never touch.

The warning is only worth reading if the readers are honest, and two ways they
were not are pinned below: a JSX file whose prose has an apostrophe (the
apostrophe used to swallow the next call — `Setup.tsx`'s reveal button), and the
Rust shell, whose whole surface `_client_calls` never asked for.
"""

from __future__ import annotations

import ast
import bisect
import re
import warnings
from dataclasses import dataclass
from pathlib import Path

from app.web.app import create_app
from app.web.settings import Settings

REPO = Path(__file__).resolve().parents[3]
HTTP_VERBS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}

# A `/api/...` path at the start of a string, optionally after a placeholder
# for a base URL, optionally after an HTTP verb (the Rust health probe writes
# "GET /api/health HTTP/1.0" straight onto a socket).
_CANDIDATE = re.compile(r'^(?:(GET|POST|PUT|PATCH|DELETE) )?(/api/[^\s?#\\"\':]*)')
_PLACEHOLDER = re.compile(r"\{[^{}]*\}")
_WILD = re.compile(r"\{[^{}]*\}|\*")
#: Rust's test modules; see `_rust_runtime` for why they are not clients.
_TEST_MODULE = re.compile(r"#\[cfg\(test\)\]")

# JS identifiers after which a `/` starts a regex literal, not a division.
_JS_REGEX_AFTER = {
    "return", "typeof", "instanceof", "in", "of", "new", "delete", "void",
    "throw", "case", "do", "else", "yield", "await",
}
#: Identifiers a string literal may open right after, glued to it: `return'x'`,
#: `case'a':`, `import'x'`. With one of these in front, a quote is a string even
#: though the character before it is a letter. Anything else with a letter in
#: front of it is prose — see `_js_prose_apostrophe`.
_JS_STRING_AFTER = _JS_REGEX_AFTER | {
    "import", "from", "export", "default", "as", "satisfies",
}
#: The client helpers that open a socket, by the name a call site uses and the
#: verb each sends. `kriko-ui/src/engine/api.ts:82-86` exports `get`, `post`,
#: `put`, `patch` and `del` (`delete` is a reserved word), `:92`/`:110` add
#: `postQuestion` and `uploadArtifact`, and the extension carries `_getApp` and
#: `_postApp`. A name whose verb is only in its options maps to None, and a call
#: through it is matched on path alone. This is the app's own way of calling the
#: engine; reading only `_getApp`/`fetch` left the reverse check blind to it.
_JS_HELPERS: dict[str, str | None] = {
    "get": "GET",
    "post": "POST",
    "put": "PUT",
    "patch": "PATCH",
    "del": "DELETE",
    "postQuestion": "POST",
    "uploadArtifact": "POST",
    "_getApp": "GET",
    "_postApp": "POST",
    "fetch": None,
    "_fetchApp": None,
}
_RUST_VERB_CALLS = {"get": "GET", "post": "POST", "put": "PUT", "delete": "DELETE"}


@dataclass(frozen=True)
class Tok:
    kind: str  # "str" | "id" | "num" | "p" | "re"
    text: str
    line: int


@dataclass(frozen=True)
class Call:
    client: str
    where: str
    method: str | None
    path: str


# ── normalisation ──────────────────────────────────────────────────────────


def _normalise(raw: str) -> tuple[str | None, str] | None:
    """(method hint, wildcard path) for a string that begins a `/api/` path."""
    text = _PLACEHOLDER.sub("{}", raw)
    text = re.sub(r"^(?:\{\})+", "", text)  # a leading {base} / ${apiBase()}
    match = _CANDIDATE.match(text)
    if not match:
        return None
    method, path = match.groups()
    if path.rstrip("/") in ("", "/api"):
        # `path.starts_with("/api/")` is a prefix check, not a call.
        return None
    return method, _PLACEHOLDER.sub("*", path)


def _glob_regex(pattern: str) -> re.Pattern[str]:
    parts, last = [], 0
    for m in _WILD.finditer(pattern):
        parts.append(re.escape(pattern[last:m.start()]))
        parts.append("[^/]+")
        last = m.end()
    parts.append(re.escape(pattern[last:]))
    return re.compile("".join(parts))


def _path_matches(client: str, server: str) -> bool:
    """Either side's placeholders may stand for any one segment's text."""
    client_sample = client.replace("*", "x")
    server_sample = _PLACEHOLDER.sub("x", server)
    return bool(_glob_regex(server).fullmatch(client_sample)
                or _glob_regex(client).fullmatch(server_sample))


def _serves(call: Call, route: tuple[str, frozenset[str]]) -> bool:
    path, methods = route
    if call.method is not None and call.method not in methods:
        return False
    return _path_matches(call.path, path)


# ── a small lexer for JavaScript and Rust ──────────────────────────────────


def _newlines(src: str) -> list[int]:
    return [m.start() for m in re.finditer("\n", src)]


def _lex_js(src: str, i: int, nl: list[int], stop_at_brace: bool = False):
    toks: list[Tok] = []
    n, depth = len(src), 0
    while i < n:
        c = src[i]
        if c.isspace():
            i += 1
        elif src.startswith("//", i):
            end = src.find("\n", i)
            i = n if end < 0 else end
        elif src.startswith("/*", i):
            end = src.find("*/", i + 2)
            i = n if end < 0 else end + 2
        elif c in "\"'":
            if _js_prose_apostrophe(src, i, toks):
                toks.append(Tok("p", c, _line(nl, i)))
                i += 1
                continue
            j, buf = i + 1, []
            while j < n and src[j] != c and src[j] != "\n":
                if src[j] == "\\":
                    buf.append(src[j:j + 2])
                    j += 2
                    continue
                buf.append(src[j])
                j += 1
            toks.append(Tok("str", "".join(buf), _line(nl, i)))
            i = j + 1
        elif c == "`":
            text, i = _lex_js_template(src, i + 1, nl)
            toks.append(Tok("str", text, _line(nl, i)))
        elif c == "/" and src[i + 1:i + 2] not in ("/", "*") and _js_regex_allowed(toks):
            j, in_class = i + 1, False
            while j < n and src[j] != "\n":
                ch = src[j]
                if ch == "\\":
                    j += 2
                    continue
                if in_class:
                    in_class = ch != "]"
                elif ch == "[":
                    in_class = True
                elif ch == "/":
                    break
                j += 1
            toks.append(Tok("re", "", _line(nl, i)))
            i = j + 1
        elif c.isalpha() or c in "_$":
            m = re.compile(r"[A-Za-z_$][\w$]*").match(src, i)
            toks.append(Tok("id", m.group(0), _line(nl, i)))
            i = m.end()
        elif c.isdigit():
            m = re.compile(r"\d[\w.]*").match(src, i)
            toks.append(Tok("num", m.group(0), _line(nl, i)))
            i = m.end()
        else:
            if c == "{":
                depth += 1
            elif c == "}":
                if stop_at_brace and depth == 0:
                    return toks, i + 1
                depth -= 1
            toks.append(Tok("p", c, _line(nl, i)))
            i += 1
    return toks, i


def _lex_js_template(src: str, i: int, nl: list[int]) -> tuple[str, int]:
    parts, n = [], len(src)
    while i < n:
        c = src[i]
        if c == "\\":
            parts.append(src[i:i + 2])
            i += 2
        elif c == "`":
            return "".join(parts), i + 1
        elif src.startswith("${", i):
            _, i = _lex_js(src, i + 2, nl, stop_at_brace=True)
            parts.append("{}")
        else:
            parts.append(c)
            i += 1
    return "".join(parts), i


def _js_prose_apostrophe(src: str, i: int, toks: list[Tok]) -> bool:
    """Is the quote at `i` an apostrophe inside a word, not a string opener?

    JSX text carries prose, and prose has apostrophes: *"your browser's
    Extensions page"* (`kriko-ui/src/ui/panels/Setup.tsx`). Reading that one as
    a string opener swallowed the rest of the line and the call after it, so a
    real `post('/api/extension/reveal', {})` was never seen and the warning
    below reported a door the window really calls as one nobody calls. A quote
    glued to the end of an identifier or a number — `browser's`, `readers'` — is
    that prose; a string in this code opens after a delimiter, or after a
    keyword an expression follows (`return 'x'`, `case'a':`).
    """
    before = src[i - 1:i] if i else ""
    if not (before.isalnum() or before in "_$"):
        return False
    return not (toks and toks[-1].kind == "id"
                and toks[-1].text in _JS_STRING_AFTER)


def _js_regex_allowed(toks: list[Tok]) -> bool:
    if not toks:
        return True
    prev = toks[-1]
    if prev.kind == "id":
        return prev.text in _JS_REGEX_AFTER
    if prev.kind == "p":
        # `<` is a JSX closing tag (`</p>`), never a regex: reading it as one
        # ate the rest of the line up to the next `/`, which can be the `/` of
        # a `/api/...` path on the same line.
        return prev.text not in ")]}<"
    return False


def _lex_rust(src: str, nl: list[int]) -> list[Tok]:
    toks: list[Tok] = []
    n, i = len(src), 0
    ident = re.compile(r"[A-Za-z_]\w*")
    while i < n:
        c = src[i]
        if c.isspace():
            i += 1
        elif src.startswith("//", i):
            end = src.find("\n", i)
            i = n if end < 0 else end
        elif src.startswith("/*", i):
            end = src.find("*/", i + 2)
            i = n if end < 0 else end + 2
        elif c == "r" and re.match(r'r#*"', src[i:i + 300]) and not (
                i and (src[i - 1].isalnum() or src[i - 1] == "_")):
            m = re.match(r'r(#*)"', src[i:])
            close = '"' + m.group(1)
            end = src.find(close, i + m.end())
            end = n if end < 0 else end
            toks.append(Tok("str", src[i + m.end():end], _line(nl, i)))
            i = end + len(close)
        elif c == '"':
            j = i + 1
            while j < n and src[j] != '"':
                j += 2 if src[j] == "\\" else 1
            toks.append(Tok("str", src[i + 1:j], _line(nl, i)))
            i = j + 1
        elif c == "'":
            if src[i + 1:i + 2] == "\\":
                i = src.find("'", i + 3) + 1
            elif src[i + 2:i + 3] == "'":
                i += 3
            else:
                i += 1  # a lifetime: the name after it is lexed normally
        elif c.isalpha() or c == "_":
            m = ident.match(src, i)
            toks.append(Tok("id", m.group(0), _line(nl, i)))
            i = m.end()
        elif c.isdigit():
            m = re.compile(r"\d[\w.]*").match(src, i)
            toks.append(Tok("num", m.group(0), _line(nl, i)))
            i = m.end()
        elif src.startswith("::", i):
            toks.append(Tok("p", "::", _line(nl, i)))
            i += 2
        else:
            toks.append(Tok("p", c, _line(nl, i)))
            i += 1
    return toks


def _line(nl: list[int], offset: int) -> int:
    return bisect.bisect_right(nl, offset) + 1


def _merge_js_concatenation(toks: list[Tok]) -> list[Tok]:
    """`"a" + \"b\"` is one string: a path can be split across lines with `+`."""
    out: list[Tok] = []
    for tok in toks:
        if (tok.kind == "str" and len(out) >= 2 and out[-1].kind == "p"
                and out[-1].text == "+" and out[-2].kind == "str"):
            out[-2] = Tok("str", out[-2].text + tok.text, out[-2].line)
            out.pop()
        else:
            out.append(tok)
    return out


# ── reading a call site ────────────────────────────────────────────────────


def _open_paren(toks: list[Tok], idx: int) -> int | None:
    """The nearest unmatched `(` before `idx`, within one statement and block.

    A `{` that is not matched by a `}` in between ends the search: the value
    sits in a block, and the call that encloses the block is not its caller.
    """
    depth = braces = 0
    for k in range(idx - 1, -1, -1):
        tok = toks[k]
        if tok.kind != "p":
            continue
        if tok.text == "}":
            braces += 1
        elif tok.text == "{":
            if braces == 0:
                return None
            braces -= 1
        elif braces:
            continue
        elif tok.text == ";":
            return None
        elif tok.text == ")":
            depth += 1
        elif tok.text == "(":
            if depth == 0:
                return k
            depth -= 1
    return None


def _enclosing_call(toks: list[Tok], idx: int) -> int | None:
    """Skip macro wrappers (`format!(`) to reach the call that uses the value."""
    k = _open_paren(toks, idx)
    while k is not None and k >= 1 and toks[k - 1].text == "!":
        k = _open_paren(toks, k)
    return k


def _args_end(toks: list[Tok], k: int) -> int:
    depth = 0
    for j in range(k, len(toks)):
        if toks[j].kind == "p" and toks[j].text == "(":
            depth += 1
        elif toks[j].kind == "p" and toks[j].text == ")":
            depth -= 1
            if depth == 0:
                return j
    return len(toks) - 1


def _js_callee(toks: list[Tok], k: int) -> int | None:
    """Index of the identifier called at `(` index `k`, past a TS generic.

    `get('/api/x')` is `get` then `(`. `get<ResearchUsage>('/api/x')` is `get`,
    `<`, `ResearchUsage`, `>`, `(` — the generic sits between the name and the
    call, so reading `toks[k - 1]` alone sees `>` and gives up. That is exactly
    how every newer client module calls the engine (`kriko-ui/src/engine/*.ts`).
    """
    i = k - 1
    if i >= 0 and toks[i].kind == "p" and toks[i].text == ">":
        depth = 0
        while i >= 0:
            token = toks[i]
            if token.kind == "p" and token.text == ">":
                depth += 1
            elif token.kind == "p" and token.text == "<":
                depth -= 1
                if depth == 0:
                    i -= 1
                    break
            i -= 1
    return i if 0 <= i < len(toks) else None


def _js_method(toks: list[Tok], k: int) -> str | None:
    """The verb of a request call at `(` index `k`, or None for other calls.

    A call is one of the app's own helpers (`_JS_HELPERS`) or something else
    entirely — a `Map.get`, a local updater named `patch` — so the name is read
    from the source, past any TS generic, and only a helper's own name gives a
    verb. A call whose name is unknown is still recorded, on path alone.
    """
    index = _js_callee(toks, k)
    if index is None or toks[index].kind != "id":
        return None
    name = toks[index].text
    if name not in _JS_HELPERS:
        return None
    if _JS_HELPERS[name] is not None:
        return _JS_HELPERS[name]
    # `fetch`/`_fetchApp` write their verb in the options object, or GET.
    end = _args_end(toks, k)
    for j in range(k, end):
        if (toks[j].kind == "id" and toks[j].text == "method" and j + 2 < len(toks)
                and toks[j + 1].text == ":" and toks[j + 2].kind == "str"):
            return toks[j + 2].text.upper()
    return "GET"  # fetch's default


def _rust_method(toks: list[Tok], k: int) -> str | None:
    if k < 3 or toks[k - 2].text != "::" or toks[k - 3].text != "api":
        return None
    name = toks[k - 1].text
    if name in _RUST_VERB_CALLS:
        return _RUST_VERB_CALLS[name]
    if name == "request":  # api::request("PATCH", &path, body)
        for j in range(k + 1, _args_end(toks, k)):
            if toks[j].kind == "str":
                return toks[j].text.upper()
    return None


def _rebinds(toks: list[Tok], k: int, name: str) -> bool:
    """Is `toks[k]` the `let` (or `let mut`) that declares `name` again?"""
    if toks[k].kind != "id" or toks[k].text != "let" or k + 1 >= len(toks):
        return False
    following = toks[k + 1]
    if following.text == "mut" and k + 2 < len(toks):
        following = toks[k + 2]
    return following.text == name


def _block_end(toks: list[Tok], idx: int) -> int:
    """Index of the `}` that closes the block `idx` sits in (or the end)."""
    depth = 0
    for k in range(idx + 1, len(toks)):
        tok = toks[k]
        if tok.kind != "p":
            continue
        if tok.text == "{":
            depth += 1
        elif tok.text == "}":
            if depth == 0:
                return k
            depth -= 1
    return len(toks)


def _binding(toks: list[Tok], idx: int, lang: str) -> tuple[str, int] | None:
    """(name, index of its declaration) when the value is bound to a variable."""
    if lang == "js":
        if idx >= 3 and toks[idx - 1].text == "=" and toks[idx - 2].kind == "id":
            if toks[idx - 3].text in ("const", "let", "var"):
                return toks[idx - 2].text, idx - 3
        return None
    # `let x = if c { "..." } else { ... }` binds through a block's `{`, so only
    # the end of the previous statement or block stops the search.
    for k in range(idx - 1, -1, -1):
        if toks[k].text in (";", "}"):
            return None
        if toks[k].kind == "id" and toks[k].text == "let":
            name = toks[k + 1]
            if name.text == "mut":
                name = toks[k + 2]
            return name.text, k
    return None


def _calls_in_tokens(client: str, toks: list[Tok], lang: str, file: str) -> list[Call]:
    method_of = _js_method if lang == "js" else _rust_method
    found: list[Call] = []
    for idx, tok in enumerate(toks):
        if tok.kind != "str":
            continue
        norm = _normalise(tok.text)
        if norm is None:
            continue
        hinted, path = norm
        methods: set[str | None] = {hinted}
        if hinted is None:
            methods = set()
            k = _enclosing_call(toks, idx)
            if k is not None and method_of(toks, k) is not None:
                methods.add(method_of(toks, k))
            bound = _binding(toks, idx, lang)
            if not methods and bound is not None:
                # A name is only the same variable inside the block that binds
                # it, and until something binds it again: `url` and `path`
                # recur in every function of these files.
                name, declared = bound
                for use in range(declared + 1, _block_end(toks, declared)):
                    if _rebinds(toks, use, name):
                        break
                    if toks[use].kind == "id" and toks[use].text == name:
                        k = _enclosing_call(toks, use)
                        if k is not None and method_of(toks, k) is not None:
                            methods.add(method_of(toks, k))
        for method in (methods or {None}):
            found.append(Call(client, f"{file}:{tok.line}", method, path))
    return found


def _js_calls(client: str, path: Path) -> list[Call]:
    src = path.read_text(encoding="utf-8")
    toks, _ = _lex_js(src, 0, _newlines(src))
    toks = _merge_js_concatenation(toks)
    return _calls_in_tokens(client, toks, "js", _rel(path))


def _rust_runtime(src: str) -> str:
    """Rust source without its `#[cfg(test)]` modules, blanked not removed.

    A shell unit test talks to a stub server and names fixture paths — `PATCH
    /api/queue/qa` (`kriko-ui/src-tauri/src/lib.rs`) is one, and this engine
    serves no such route — so a test module is not a client of this engine, the
    same way a `tests/` directory is not for the other clients. The region is
    blanked to spaces and its newlines kept, so a call's line number still
    points at the line in the file.
    """
    kept: list[str] = []
    cursor = 0
    while (match := _TEST_MODULE.search(src, cursor)) is not None:
        body = src.find("{", match.end())
        if body < 0:
            break
        depth, end = 0, body
        while end < len(src):
            if src[end] == "{":
                depth += 1
            elif src[end] == "}":
                depth -= 1
                if depth == 0:
                    break
            end += 1
        kept.append(src[cursor:match.start()])
        kept.append(re.sub(r"[^\n]", "", src[match.start():end + 1]))
        cursor = end + 1
    kept.append(src[cursor:])
    return "".join(kept)


def _rust_calls(client: str, path: Path) -> list[Call]:
    src = _rust_runtime(path.read_text(encoding="utf-8"))
    toks = _lex_rust(src, _newlines(src))
    return _calls_in_tokens(client, toks, "rust", _rel(path))


def _python_calls(client: str, path: Path) -> list[Call]:
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    parents: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    found: list[Call] = []
    for node in ast.walk(tree):
        text = _py_static_text(node, parents)
        if text is None:
            continue
        norm = _normalise(text)
        if norm is None:
            continue
        hinted, route_path = norm
        methods: set[str | None] = {hinted} if hinted else set()
        parent = parents.get(node)
        if not methods and isinstance(parent, ast.Call) and parent.args and parent.args[0] is node:
            methods.add(_py_call_method(parent))
        if not methods and isinstance(parent, ast.Assign) and len(parent.targets) == 1 \
                and isinstance(parent.targets[0], ast.Name):
            # `path = f"/api/..."` then `self.get(path)`: read the calls in the
            # same function, where that name means this value.
            name = parent.targets[0].id
            scope = _enclosing_function(node, parents) or tree
            for call in ast.walk(scope):
                if (isinstance(call, ast.Call) and call.args
                        and isinstance(call.args[0], ast.Name) and call.args[0].id == name):
                    methods.add(_py_call_method(call))
        for method in (methods - {None}) or {None}:
            found.append(Call(client, f"{_rel(path)}:{node.lineno}", method, route_path))
    return found


def _enclosing_function(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> ast.AST | None:
    current = parents.get(node)
    while current is not None and not isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
        current = parents.get(current)
    return current


def _py_static_text(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        if isinstance(parents.get(node), ast.JoinedStr):
            return None  # a fragment of an f-string, read through the whole
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(
            part.value if isinstance(part, ast.Constant) else "{}"
            for part in node.values)
    return None


def _py_call_method(call: ast.Call) -> str | None:
    func = call.func
    if not isinstance(func, ast.Attribute):
        return None
    if func.attr in ("get", "post", "put", "delete"):
        return func.attr.upper()
    if func.attr == "request" and call.args and isinstance(call.args[0], ast.Constant):
        return str(call.args[0].value).upper()
    return None


def _rel(path: Path) -> str:
    return path.relative_to(REPO).as_posix()


# ── the two sides ──────────────────────────────────────────────────────────


def _client_calls() -> dict[str, list[Call]]:
    """Every call site, grouped by client. Tests and fixtures are not clients.

    That includes the shell's Rust `#[cfg(test)]` modules (`_rust_runtime`): the
    window's own health probe and its response-size override are the shell's
    surface, and a unit test talking to a stub server is not.
    """
    clients: dict[str, list[Call]] = {}
    js = [p for p in (REPO / "extension").rglob("*.js")
          if not {"tests", "assets", "node_modules"} & set(p.parts)]
    clients["the browser extension"] = [c for p in sorted(js) for c in _js_calls("the browser extension", p)]
    web = sorted(p for suffix in ("*.ts", "*.tsx") for p in (REPO / "kriko-ui" / "src").rglob(suffix))
    clients["the desktop app"] = [c for p in web for c in _js_calls("the desktop app", p)]
    shell = sorted((REPO / "kriko-ui" / "src-tauri" / "src").rglob("*.rs"))
    clients["the desktop shell"] = [c for p in shell for c in _rust_calls("the desktop shell", p)]
    py = [p for p in (REPO / "src" / "app" / "tui").rglob("*.py")
          if "tests" not in p.parts and "__pycache__" not in p.parts]
    clients["the terminal interface"] = [c for p in sorted(py) for c in _python_calls("the terminal interface", p)]
    return clients


def _http_python_calls() -> list[Call]:
    """Calls made by Python that speak HTTP: the tools and packaging smoke tests.

    The reverse check counts them, so a route only they use is not "dead". The
    modules are found by what they import, not listed here. The MCP server and
    the command line call the engine's functions directly and never open a
    socket, so they are not among them; a future HTTP caller in either is found
    the same way.
    """
    markers = ("urllib.request", "http.client", "import httpx", "import requests")
    files = [p for root in (REPO / "src" / "app", REPO / "tools", REPO / "packaging")
             for p in root.rglob("*.py")
             if not {"tests", "__pycache__"} & set(p.parts)]
    found: list[Call] = []
    for path in sorted(files):
        if any(marker in path.read_text(encoding="utf-8") for marker in markers):
            found.extend(_python_calls("python HTTP caller", path))
    return found


def _server_routes(tmp_path: Path) -> list[tuple[str, frozenset[str]]]:
    """Every `/api` path template with its verbs, as the engine serves them.

    Read from the OpenAPI schema rather than `app.routes`: a FastAPI that wraps
    included routers (0.13x and later) does not list their paths there. Nothing
    in `src/app/web` hides a route from the schema, so this is the full set.
    """
    app = create_app(Settings(
        store_path=tmp_path / "knowledge.sqlite",
        app_state_path=tmp_path / "app.sqlite",
        analysis_log_path=tmp_path / "analyses.jsonl",
    ))
    routes = []
    for path, operations in app.openapi()["paths"].items():
        if path.startswith("/api"):
            methods = frozenset(m.upper() for m in operations if m.upper() in HTTP_VERBS)
            routes.append((path, methods))
    return sorted(routes)


# ── the test ───────────────────────────────────────────────────────────────


def test_every_client_call_names_a_route_the_engine_serves(tmp_path):
    routes = _server_routes(tmp_path)
    clients = _client_calls()
    for name, calls in clients.items():
        assert calls, f"found no call sites in {name}; the reader is broken, not the code"

    failures: dict[str, list[str]] = {}
    for name, calls in clients.items():
        for call in sorted(set(calls), key=lambda c: (c.where, c.path)):
            if any(_serves(call, route) for route in routes):
                continue
            same_path = sorted({m for p, ms in routes if _path_matches(call.path, p) for m in ms})
            verb = call.method or "any verb"
            if same_path:
                why = f"the route exists, but only for {', '.join(same_path)}"
            else:
                why = "no route with this path"
            failures.setdefault(name, []).append(f"    {verb:<8} {call.path}  at {call.where}  -- {why}")

    if failures:
        lines = [
            "client calls that name no route the engine serves "
            "(a renamed or dropped route, or a call that should be removed):",
        ]
        for name, rows in failures.items():
            lines.append(f"\n  {name} ({len(rows)}):")
            lines.extend(rows)
        raise AssertionError("\n".join(lines))

    # The reverse direction is per verb: a route that only its GET is called
    # through is still a dead POST. Callers are the windows, the extension and
    # the terminal interface, plus any Python tool or smoke test that speaks HTTP.
    callers = [c for calls in clients.values() for c in calls] + _http_python_calls()
    unused = [(path, method) for path, methods in routes for method in sorted(methods)
              if not any(_serves(call, (path, frozenset({method}))) for call in callers)]
    if unused:
        warnings.warn(
            f"{len(unused)} of {sum(len(m) for _, m in routes)} engine verbs are called by "
            "no window, shell, extension, terminal interface, tool or smoke test (MCP and the "
            "command line call the functions, not HTTP): "
            + ", ".join(f"{method} {path}" for path, method in unused),
            stacklevel=1,
        )


# ── the extractor, on snippets, so a change to it cannot quietly go blind ──


def test_the_reader_finds_split_templates_format_strings_and_methods(tmp_path):
    js = (
        "const base = await apiBase();\n"
        "const url = `${base}/api/marks/${encodeURIComponent(a)}`\n"
        "  + `/${encodeURIComponent(b)}`;\n"
        "await _fetchApp(url, { method: 'DELETE' });\n"
        "const path = `/api/lookup/${id}/questions`;\n"
        "_postApp(path, { question });\n"
        "// _postApp('/api/commented/out', {})\n"
        "const re = /\\/api\\/regex/;\n"
    )
    toks = _merge_js_concatenation(_lex_js(js, 0, _newlines(js))[0])
    calls = {(c.method, c.path) for c in _calls_in_tokens("js", toks, "js", "snippet.js")}
    assert calls == {("DELETE", "/api/marks/*/*"), ("POST", "/api/lookup/*/questions")}

    rust = (
        'fn a() {\n'
        '    let path = format!("/api/queue/{}", api::seg(&id));\n'
        '    api::request("PATCH", &path, None);\n'
        '    write!(stream, "GET /api/health HTTP/1.0\\r\\n");\n'
        '    api::post(\n        &format!("/api/jobs/{id}/say"),\n        json!({}),\n    );\n'
        '    // api::get("/api/commented/out")\n'
        '    let msg = "Could not reach /api/x";\n'
        '}\n'
    )
    toks = _lex_rust(rust, _newlines(rust))
    calls = {(c.method, c.path) for c in _calls_in_tokens("rust", toks, "rust", "snippet.rs")}
    assert calls == {
        ("PATCH", "/api/queue/*"),
        ("GET", "/api/health"),
        ("POST", "/api/jobs/*/say"),
    }

    assert _path_matches("/api/marks/*/*", "/api/marks/{pack_id}/{claim_id}")
    assert _path_matches("/api/jobs/*/cancel", "/api/jobs/{job_id}/cancel")
    assert not _path_matches("/api/jobs/*", "/api/jobs/{job_id}/cancel")
    assert not _path_matches("/api/packs/drafts", "/api/packs/{slug}/x")

    cancel = ("/api/jobs/{job_id}/cancel", frozenset({"POST"}))
    assert _serves(Call("c", "w", "POST", "/api/jobs/*/cancel"), cancel)
    assert _serves(Call("c", "w", None, "/api/jobs/*/cancel"), cancel)
    assert not _serves(Call("c", "w", "GET", "/api/jobs/*/cancel"), cancel)


def test_a_call_after_a_prose_apostrophe_is_still_found():
    """Prose has apostrophes, and one must not swallow the call after it.

    `Setup.tsx` says *"your browser's Extensions page"* above a real
    `post('/api/extension/reveal', {})`. Reading that apostrophe as a string
    opener hid the call, and the reverse warning then reported a route the
    window really calls as one nobody calls — which is worse than a missed
    warning, because it sends someone to delete a live route.
    """
    panel = REPO / "kriko-ui" / "src" / "ui" / "panels" / "Setup.tsx"
    specimen = [one for one in panel.read_text(encoding="utf-8").splitlines()
                if "browser's" in one or "/api/extension/reveal" in one]
    assert len(specimen) == 2, (
        "the specimen moved: find the line with an apostrophe in its prose and "
        "the call after it, and point this test at those two lines"
    )
    excerpt = "\n".join(specimen) + "\n"
    toks = _lex_js(excerpt, 0, _newlines(excerpt))[0]
    calls = {(c.method, c.path) for c in _calls_in_tokens("js", toks, "js", "Setup.tsx")}
    assert calls == {("POST", "/api/extension/reveal")}

    # And on the file as it really is, not only the two lines.
    assert "/api/extension/reveal" in {call.path for call in _js_calls("the desktop app", panel)}


def test_the_reader_reads_the_shells_route_strings():
    """The Tauri shell speaks HTTP to the same engine, from Rust.

    Its health probe writes the request line onto a socket (`GET /api/health
    HTTP/1.0`) and its response-size override compares a path. `_rust_calls`
    existed and `_client_calls` never called it, so the shell's whole surface
    was invisible to the reverse check. A `starts_with("/api/")` guard is a
    prefix check, not a call, and is not read as one.
    """
    rust = (
        "fn probe(host: &str, port: u16, stream: &mut TcpStream, path: &str) {\n"
        '    let _ = write!(stream, "GET /api/health HTTP/1.0\\r\\nHost: {host}:{port}\\r\\n\\r\\n");\n'
        '    let limit = if path == "/api/backups/export" { 48 * 1024 * 1024 } else { 10 };\n'
        '    if !path.starts_with("/api/") { return; }\n'
        "}\n"
    )
    toks = _lex_rust(rust, _newlines(rust))
    calls = {(c.method, c.path) for c in _calls_in_tokens("the desktop shell", toks, "rust", "engine.rs")}
    assert ("GET", "/api/health") in calls
    assert (None, "/api/backups/export") in calls
    assert not any(path == "/api/" for _, path in calls)


def test_the_windows_own_helpers_are_read_with_their_verbs():
    """The app calls the engine through its own helpers, not `fetch` directly.

    `kriko-ui/src/engine/api.ts:82-86` exports `get`, `post`, `put`, `patch` and
    `del`, `:92`/`:110` add `postQuestion` and `uploadArtifact`, and every newer
    client module uses them with a TS generic in front of the parens
    (`get<ResearchUsage>('/api/usage')`). Reading only `_getApp`/`fetch` recorded
    such a call with **no verb**, and a call with no verb vouches for every verb
    on its path — so a GET hid a route's DELETE from the reverse check, exactly
    where the app has the most call sites.
    """
    snippet = (
        "await get<Foo>('/api/a');\n"
        "await post('/api/b', {});\n"
        "await put<Foo>(`/api/c/${seg(id)}`, {});\n"
        "await del<Foo>('/api/d');\n"
        "await fetch('/api/e', { method: 'PATCH' });\n"
        "const link = engineUrl('/api/f');\n"
    )
    toks = _merge_js_concatenation(_lex_js(snippet, 0, _newlines(snippet))[0])
    calls = {(c.method, c.path) for c in _calls_in_tokens("js", toks, "js", "snippet.ts")}
    assert ("GET", "/api/a") in calls
    assert ("POST", "/api/b") in calls
    assert ("PUT", "/api/c/*") in calls          # a template segment is {id}
    assert ("DELETE", "/api/d") in calls
    assert ("PATCH", "/api/e") in calls          # fetch still reads its options
    # `engineUrl` is not a request: it builds a link the reader may press. The
    # reader records its path with no verb, which is the honest reading of a
    # link the window offers — a route reachable by a link is not a dead route.
    assert (None, "/api/f") in calls

    # The specimen is the app's own spend surface, where this was found.
    runs = {(c.method, c.path)
            for c in _js_calls("the desktop app", REPO / "kriko-ui" / "src" / "engine" / "research.ts")}
    assert ("GET", "/api/research-runs") in runs
    assert ("GET", "/api/usage") in runs
    assert ("DELETE", "/api/research-runs/*") in runs


def test_the_shell_is_a_client_and_a_rust_test_module_is_not():
    """The shell's runtime surface is read; its unit tests are not clients.

    `PATCH /api/queue/qa` is named only inside `#[cfg(test)] mod tests` in
    `kriko-ui/src-tauri/src/lib.rs`, and this engine serves no `/api/queue/qa`
    at all: a fixture path for a stub server is not a call the engine must
    answer, the same way a `tests/` directory is not for the other clients.
    """
    shell = {call.path for call in _client_calls()["the desktop shell"]}
    assert "/api/health" in shell
    assert "/api/backups/export" in shell
    assert "/api/queue/qa" not in shell
