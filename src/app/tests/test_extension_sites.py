"""A pack that can read a site the extension never runs on.

An adapter is data: `packs/<pack>/adapters/<site>.json` says which labels on
which site mean what, and it is interpreted server-side because a pack must
never be able to ship JavaScript into a content script. That design is right
and it left a seam. The *server* learns about a new site the moment its
adapter file exists; the *extension* learns about it only when somebody
remembers to edit `manifest.json`'s `content_scripts`, in a second
repository-shaped place, by hand.

Nothing fails when they forget. The pack installs, `GET /api/adapters` lists
the site, the coverage report counts it, and the extension simply never
injects there — so the reader opens a listing and no panel appears, which is
indistinguishable from "no knowledge about this car". That is exactly the
class of defect the 1.0.0 audit found four of: a real behaviour with no gate
under it.

This is the gate, and B69 changed what it has to assert. The worker now
learns a site at runtime — it reads `/api/adapters`, converts each `site` to
one match pattern, and registers the content scripts itself
(`syncSites` in `extension/background.js`, tested in
`extension/tests/background_sites.test.js`). So the manifest no longer has to
name every site; it has to leave a *door* for the ones it does not name.

Hence the two ways a site may be covered, and no third: the packaged
`content_scripts` inject there already, or `optional_host_permissions` lets
the reader grant it. A site with neither is unreachable however good its
adapter is, and that is still a failing suite rather than a missing panel.
It is deliberately pack-derived rather than a list of sites to keep in step —
a list would be the third place to forget.
"""

import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
MANIFEST = REPO / "extension" / "manifest.json"


def adapters() -> list[tuple[str, dict]]:
    """Every adapter in the tree, named by the pack that ships it.

    Read off the filesystem rather than out of an installed store: this is a
    repository invariant, and it must fail in CI on a machine with no packs
    installed at all.
    """
    found = []
    for path in sorted((REPO / "packs").glob("*/adapters/*.json")):
        found.append((path.parent.parent.name, json.loads(path.read_text(encoding="utf-8"))))
    return found


def injected_patterns() -> list[str]:
    """Every URL pattern the manifest will inject a content script for."""
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    patterns = []
    for block in manifest.get("content_scripts", []):
        patterns.extend(block.get("matches", []))
    return patterns


def grantable_patterns() -> list[str]:
    """Every pattern the reader can be asked to allow at runtime.

    The other half of the answer since B69. A site here is not injected on
    when the extension is installed — it is injected on once the reader grants
    it in the options page, which is the browser's rule about reading a third
    party's pages and not ours to route around.
    """
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return list(manifest.get("optional_host_permissions", []))


def covers(patterns, host: str) -> bool:
    """Does any of these patterns reach `host`?

    `https://*/*` reaches everything, which is exactly what
    `optional_host_permissions` is for and is meaningless in
    `content_scripts` — so the wildcard is honoured here rather than being
    mangled into a hostname by `host_of`.
    """
    for pattern in patterns:
        tail = pattern.split("://", 1)[-1]
        head = tail.split("/", 1)[0]
        if head in {"*", "*.*"}:
            return True
        if host_of(pattern) == host:
            return True
    return False


def host_of(pattern: str) -> str:
    """The host part of a match pattern or an adapter glob, lowercased.

    Both dialects are globs over a URL and both may lead with a wildcard, so
    the comparison is on the registrable-looking tail rather than on equality:
    `https://*.sahibinden.com/*` and `*sahibinden.com/ilan/*` name the same
    site and are not the same string.
    """
    tail = pattern.split("://", 1)[-1]
    return tail.split("/", 1)[0].lstrip("*.").lower()


@pytest.mark.parametrize("pack_id,adapter", adapters(), ids=lambda v: str(v)[:40])
def test_every_adapter_has_an_extension_that_runs_there(pack_id, adapter):
    """The seam, held shut.

    If this fails, a pack can read a site the extension never visits — the
    reader sees no panel and reads it as "nothing known about this car".
    Either add the host to `extension/manifest.json`'s `content_scripts` (and
    to `web_accessible_resources`, below) or the adapter is dead weight.
    """
    site = adapter.get("site", "")
    assert site, f"{pack_id}: an adapter with no `site` matches nothing"
    host = host_of(site)
    assert covers(injected_patterns(), host) or covers(grantable_patterns(), host), (
        f"{pack_id}/{adapter.get('id')} reads {site}, but the extension "
        f"neither injects there nor can be granted it. Injected: "
        f"{injected_patterns()}; grantable: {grantable_patterns()}"
    )


@pytest.mark.parametrize("pack_id,adapter", adapters(), ids=lambda v: str(v)[:40])
def test_the_panel_stylesheet_reaches_every_site_the_scripts_do(pack_id, adapter):
    """A second list, in the same file, that drifts on its own.

    `web_accessible_resources` gates the panel's CSS. A host in
    `content_scripts` and not here gets the scripts and no stylesheet, which
    renders as an unstyled pile of text over the listing — worse than no
    panel, because it looks like the app is broken rather than absent.

    Since B69 the list is `https://*/*` with `use_dynamic_url`, because a site
    granted at runtime cannot have been named here at build time. The
    stylesheet is reachable from anywhere and its URL is rotated per session,
    so no page can probe it to learn the extension's id — that pairing is
    asserted on the extension side, in `background_sites.test.js`.
    """
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    reachable = []
    for block in manifest.get("web_accessible_resources", []):
        if any(r.endswith("hover_lite.css") for r in block.get("resources", [])):
            reachable.extend(block.get("matches", []))
    assert covers(reachable, host_of(adapter["site"])), (
        f"{pack_id}/{adapter.get('id')}: the panel's stylesheet is not "
        f"exposed on {adapter['site']}"
    )


def test_an_adapter_declares_its_match_patterns():
    """Without `match` the server never routes a URL to the adapter, so the
    labels it maps are unreachable however good they are."""
    for pack_id, adapter in adapters():
        assert adapter.get("match"), f"{pack_id}/{adapter.get('id')} matches no URL"


def test_the_adapters_carry_no_executable_anything():
    """The rule that made adapters data in the first place.

    Installing a pack must not grant it the ability to run code on every page
    the extension can see. A key that smells like a script is a design
    violation, not a feature, and it is cheaper to refuse it here than to
    discover a pack relying on it.
    """
    forbidden = {"js", "script", "code", "eval", "function"}
    for pack_id, adapter in adapters():
        keys = _collect_keys(adapter)
        assert not (keys & forbidden), f"{pack_id}: adapter carries {keys & forbidden}"


def _collect_keys(node, keys=None):
    if keys is None:
        keys = set()
    if isinstance(node, dict):
        keys.update(str(k).lower() for k in node)
        for v in node.values():
            _collect_keys(v, keys)
    elif isinstance(node, list):
        for v in node:
            _collect_keys(v, keys)
    return keys


# ── nothing the extension ships may phone out ────────────────────────────


#: Hosts the extension is allowed to name. Two loopback spellings and the
#: sites its own adapters cover — everything else is an outbound request from
#: inside a page the reader is shopping on.
ALLOWED_HOSTS = ("127.0.0.1", "localhost", "[::1]")

#: A URL in a comment paints nothing and fetches nothing. Stripped first, for
#: the same reason `tokens.test.ts` strips comments before hunting colours:
#: the useful comments here are the ones explaining what was removed.
_COMMENTS = (
    (r"/\*[\s\S]*?\*/", ""),   # css and js block comments
    (r"(?m)^\s*//.*$", ""),    # js line comments
    (r"(?m)^\s*\*.*$", ""),    # jsdoc continuation lines
)


def shipped_files():
    """Every file that actually reaches a browser, off the allowlist.

    Derived from `app.extension.SHIPPED` rather than listed again here, so a
    file added to what ships is covered the moment it ships — the same reason
    `adapters()` above reads the pack tree instead of naming a pack.
    """
    import re

    from app.extension import SHIPPED

    root = REPO / "extension"
    for name in SHIPPED:
        target = root / name
        paths = [target] if target.is_file() else sorted(target.rglob("*"))
        for path in paths:
            if not path.is_file() or path.suffix not in {".js", ".css", ".html", ".json"}:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for pattern, replacement in _COMMENTS:
                text = re.sub(pattern, replacement, text)
            yield path.relative_to(REPO), text


def test_nothing_shipped_reaches_a_third_party():
    """A local-first product with one component inside somebody else's page.

    The panel used to inject a `fonts.googleapis.com` stylesheet into every
    listing it opened on, which told Google which cars the reader was looking
    at — from the one part of Kriko running where that is observable. It also
    failed offline, which is the state the whole product is designed for.

    This is the gate that was missing: the defect was a URL in a stylesheet,
    and no test in the suite read a stylesheet. A remote host in anything
    shipped fails here, whether it is a font, an analytics beacon, or a
    convenience someone reached for at 2am.
    """
    import re

    offenders = []
    for path, text in shipped_files():
        for match in re.finditer(r"https?://([^\s\"'()<>]+)", text):
            host = match.group(1).split("/")[0].split(":")[0]
            if host.lower() in ALLOWED_HOSTS or host.startswith("*."):
                continue
            # `http://${...}` is not a host — it is the scheme being prepended
            # to whatever base URL the reader typed into the options page.
            # Their own machine, their own choice.
            if host.startswith("${") or host.startswith("'") or host.startswith("+"):
                continue
            # A `match` pattern in the manifest is a *permission*, not a
            # fetch, and the test above already holds it against the packs.
            if "sahibinden.com" in host or "carchecker.pro" in host:
                continue
            offenders.append(f"{path}: {match.group(0)}")
    assert offenders == []


def test_no_remote_font_is_loaded_by_any_mechanism():
    """The three spellings of the same mistake, named so a fix cannot be a
    rename: a `<link rel=stylesheet>` built in JS, an `@import` in CSS, and a
    `@font-face` pointing at a URL."""
    offenders = []
    for path, text in shipped_files():
        lowered = text.lower()
        if "fonts.googleapis" in lowered or "fonts.gstatic" in lowered:
            offenders.append(f"{path}: names a font CDN")
        if "@import" in lowered and "://" in lowered:
            offenders.append(f"{path}: @import of a remote sheet")
    assert offenders == []
