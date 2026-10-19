"""Block-level scans of untrusted markup that stay linear however the page is broken.

`<name ...>inner</name>` is easy to write as a regex with a lazy `.*?` and a
back-reference, and easy to break: a page of unclosed tags (`<nav>x` repeated)
makes every opener scan to the end of the page for a closer that is not there.
That is quadratic: 32 s for 200 KB, an hour at the 2 MB cap, on a thread nothing
can interrupt. The scans here remember what they have already learned: a name
with no closer left in the page, and where the next `>` is, so no opener rescans
what an earlier one did, and the work stays proportional to the page.

They match exactly what the regexes did: an opener is `<name` not followed by a
word character or a hyphen (so `<button-group>` is not `<button>`), its tag ends
at the first `>`, the closer is `</name>`, names compare without case, and an
opener with no closer is left in the text untouched.
"""

from __future__ import annotations

import re
from collections.abc import Callable


def blocks(markup: str, names: tuple[str, ...], replace: Callable[[str], str], *, limit: int = 0,
           want: Callable[[str], bool] | None = None) -> str:
    """Replace each `<name ...>inner</name>` with `replace(inner)`.

    Stops after `limit` blocks if set. `want` is given an opener's own text
    (`<script type="...">`) and may turn that opener down, leaving it in place.
    """
    opener = re.compile(r"<(" + "|".join(map(re.escape, names)) + r")(?![\w-])", re.IGNORECASE)
    closers = {name.lower(): re.compile("</" + re.escape(name) + ">", re.IGNORECASE) for name in names}
    missing: set[str] = set()
    out: list[str] = []
    at = scan = 0
    gt = -1
    found_blocks = 0
    while True:
        found = opener.search(markup, scan)
        if not found:
            break
        scan = found.end()
        if gt < scan:
            gt = markup.find(">", scan)
            if gt < 0:
                break  # no tag can end after this point, so none can begin and finish either
        name = found.group(1).lower()
        if name in missing or (want is not None and not want(markup[found.start():gt + 1])):
            continue
        close = closers[name].search(markup, gt + 1)
        if not close:
            missing.add(name)
            continue
        out.append(markup[at:found.start()])
        out.append(replace(markup[gt + 1:close.start()]))
        at = scan = close.end()
        found_blocks += 1
        if limit and found_blocks >= limit:
            break
    out.append(markup[at:])
    return "".join(out)


def inner_texts(markup: str, names: tuple[str, ...], *, limit: int = 0,
                want: Callable[[str], bool] | None = None) -> list[str]:
    """What `blocks` would replace, in page order, without changing the page."""
    found: list[str] = []

    def keep(inner: str) -> str:
        found.append(inner)
        return ""

    blocks(markup, names, keep, limit=limit, want=want)
    return found


def last_block(markup: str, name: str) -> str | None:
    """The inner text from the first `<name ...>` to the last `</name>`, which is what `<name ...>(.*)</name>` gives."""
    found = re.search(r"<" + re.escape(name) + r"(?![\w-])", markup, re.IGNORECASE)
    if not found:
        return None
    gt = markup.find(">", found.end())
    if gt < 0:
        return None
    last = None
    for last in re.finditer("</" + re.escape(name) + ">", markup[gt + 1:], re.IGNORECASE):
        pass
    return None if last is None else markup[gt + 1:gt + 1 + last.start()]
