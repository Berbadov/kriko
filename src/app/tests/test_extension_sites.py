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

This is the gate. It is deliberately a *pack-derived* check rather than a
list of sites to keep in step — a list would be the third place to forget.
Note what it does not do: it does not make the extension pick up a new site
on its own. That is B69, and it registers the scripts at runtime from
`/api/adapters`. Until then this test is what turns a silent gap into a
failing suite, and after B69 it becomes the check that the static manifest
still covers the sites needed before the first successful call to the server.
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
        found.append((path.parent.parent.name, json.loads(path.read_text())))
    return found


def injected_patterns() -> list[str]:
    """Every URL pattern the manifest will inject a content script for."""
    manifest = json.loads(MANIFEST.read_text())
    patterns = []
    for block in manifest.get("content_scripts", []):
        patterns.extend(block.get("matches", []))
    return patterns


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
    hosts = {host_of(p) for p in injected_patterns()}
    assert host_of(site) in hosts, (
        f"{pack_id}/{adapter.get('id')} reads {site}, but the extension "
        f"injects nothing there. Injected hosts: {sorted(hosts)}"
    )


@pytest.mark.parametrize("pack_id,adapter", adapters(), ids=lambda v: str(v)[:40])
def test_the_panel_stylesheet_reaches_every_site_the_scripts_do(pack_id, adapter):
    """A second list, in the same file, that drifts on its own.

    `web_accessible_resources` gates the panel's CSS. A host in
    `content_scripts` and not here gets the scripts and no stylesheet, which
    renders as an unstyled pile of text over the listing — worse than no
    panel, because it looks like the app is broken rather than absent.
    """
    manifest = json.loads(MANIFEST.read_text())
    reachable = set()
    for block in manifest.get("web_accessible_resources", []):
        reachable.update(host_of(p) for p in block.get("matches", []))
    assert host_of(adapter["site"]) in reachable, (
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
        keys = set()

        def walk(node):
            if isinstance(node, dict):
                keys.update(str(k).lower() for k in node)
                for v in node.values():
                    walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)

        walk(adapter)
        assert not (keys & forbidden), f"{pack_id}: adapter carries {keys & forbidden}"
