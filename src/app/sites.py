"""Sites this installation can read — the packs', and the ones it learned.

An **adapter** says how to read one website: which selectors hold the fields,
what its labels mean, and what the extension may draw from the reader's own
page. Packs ship them, and that is right: an adapter is knowledge about a site,
and a pack is how knowledge travels.

It left one thing with no answer, and it is the reader's: *"I cannot open the
extension on pages that aren't registered — so basically it opens on
sahibinden only."* The panel is not missing on those pages; the **site** is.
Until now the only way to add one was to author a whole pack, which is a
disproportionate answer to "this listing site also sells cars".

So an installation may learn a site by itself, and what it learns lives in
`app.sqlite`:

* **Not in the store**, by the two-file rule. A site this reader taught their
  own copy about is not pack content: it must not enter a `content_digest`, it
  must survive the pack being updated, and it must not travel to anyone else's
  install as though a pack author had reviewed it.
* **Behind the pack's own**, always. `adapter_for` asks the engine first, so a
  pack that later ships an adapter for the same host wins and the local one
  becomes redundant rather than conflicting. The reader is never in a position
  where their own guess overrides a pack author's knowledge.
* **Validated before it is stored**, because an adapter is the one piece of
  pack-shaped data with teeth: its `site` becomes a host permission and an
  injection target in the reader's browser. A hostname and nothing else — no
  wildcard, no path, no scheme, no credentials — which is the same rule
  `background.js` applies on its side, for the same reason.
"""

import re

from kriko.adapters import adapter_for as pack_adapter_for
from kriko.adapters import load_adapters

#: A registrable hostname, and nothing else. The same expression the extension
#: applies to a pack's `site`: a pack — or an agent — that wants to inject
#: Kriko into a bank by writing `site: "*"` gets nothing.
HOSTNAME = re.compile(
    r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$"
)


class SiteRefused(ValueError):
    """The adapter offered cannot be stored, and why."""


def host_of(url: str) -> str:
    """The registrable host of a URL or a bare host. `""` when it is neither."""
    text = str(url or "").strip().lower()
    if "://" in text:
        text = text.split("://", 1)[1]
    text = text.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    text = text.split("@")[-1].split(":")[0]
    text = text.removeprefix("www.")
    return text if HOSTNAME.match(text) else ""


def check(spec: dict, *, host: str = "") -> dict:
    """The adapter, normalised, or `SiteRefused` saying what is wrong with it.

    Deliberately strict about two fields and permissive about the rest: `site`
    and `match` decide what the browser will inject into, and everything else
    only decides how well a page is read. A wrong selector is a poor adapter; a
    wrong `site` is a permission the reader did not mean to give.
    """
    if not isinstance(spec, dict):
        raise SiteRefused("an adapter is a JSON object")
    # The raw value, not a parse of it. `host_of` is lenient because it reads
    # whatever URL a browser reported; `site` is a field an agent *wrote*, and
    # a scheme, a port or a path in it means the agent misunderstood what the
    # field is — which is worth a refusal it can read rather than a quiet
    # normalisation it will repeat next time.
    raw = str(spec.get("site") or host or "").strip().lower()
    site = raw.removeprefix("www.") if HOSTNAME.match(raw.removeprefix("www.")) else ""
    if not site:
        raise SiteRefused(
            f"{spec.get('site') or host!r} is not a hostname. An adapter names "
            "one site — no wildcard, no path, no scheme"
        )
    match = [str(one) for one in (spec.get("match") or []) if str(one).strip()]
    for pattern in match:
        if host_of(pattern) != site and site not in pattern:
            raise SiteRefused(
                f"the match pattern {pattern!r} is not on {site}. An adapter "
                "may not claim a site it is not for"
            )
    if not match:
        match = [f"*://*.{site}/*"]
    fields = spec.get("fields")
    if not isinstance(fields, (dict, list)) or not fields:
        raise SiteRefused(
            "no `fields`. An adapter with no rules reads nothing from the page, "
            "which is the same as not having one"
        )
    return {
        **spec,
        "id": str(spec.get("id") or f"local.{site}"),
        "site": site,
        "match": match,
    }


def adapter_for(store, app_conn, url: str):
    """The adapter for this URL: the packs' first, then this installation's.

    Order is the whole design. A pack author's adapter is knowledge somebody
    published and can be held to; a local one is what this copy worked out. The
    published one wins whenever both exist.
    """
    found = pack_adapter_for(store, url)
    if found is not None:
        return found
    host = host_of(url)
    if not host or app_conn is None:
        return None
    from app.web import state

    for row in state.local_adapters(app_conn):
        spec = row.get("spec") or {}
        if row["host"] != host:
            continue
        spec = {**spec, "pack_id": row.get("pack_id") or "", "local": True}
        return spec
    return None


#: What the two lists on the Sites screen mean, and the rule that keeps a host
#: out of both at once.
#:
#: **Readable here** — an adapter exists for this host, pack-shipped or learned.
#: It is a fact about *this installation*.
#:
#: **Asked for** — somebody stood on a page here and pressed the button, and
#: nothing could read it. It is a fact about *demand*, and it is only true
#: while it is still unmet.
#:
#: They were both true of the same host at once, which is what the reader saw:
#: registering a site left its ask behind as a `done` row that nothing ever
#: cleared, so the screen said "Kriko reads this" and "somebody wants Kriko to
#: read this" about one hostname on one page. `requested` below derives the
#: second from the first rather than trusting a stored state word, so the
#: invariant holds by construction — and a reader who later forgets an adapter
#: gets their ask back, which a delete-on-success would have lost.
TWO_LISTS = "readable here | asked for"


def requested(store, app_conn) -> list[dict]:
    """Sites somebody asked for that still cannot be read. Derived, not flagged.

    A `state` column said `done` and the row stayed in the list. State words go
    stale; the adapter table cannot.
    """
    if app_conn is None:
        return []
    from app.web import state

    readable = {one["site"] for one in registered(store, app_conn)
                if not one.get("superseded")}
    return [row for row in state.site_requests(app_conn)
            if row["host"] not in readable]


def activation(store, app_conn, host: str) -> dict:
    """Will the panel actually appear on this host, and if not, what is stopping it.

    Four answers, and the reader met the gap between the first two as "I
    registered the site and nothing happened":

    * `no_adapter` — nothing here reads it yet.
    * `needs_permission` — an adapter exists, and Chrome has not been asked for
      the host. **The app cannot ask.** `permissions.request` must come from a
      user gesture inside the extension, so registering a site here can never
      be sufficient, and a screen that implied otherwise was lying by omission.
    * `active` — the extension reports a registered content script.
    * `invalid` — the adapter names something that is not a registrable
      hostname, so the extension refused it.

    `unknown` is the fifth and it is honest too: an app that has never heard
    from the extension knows an adapter exists and nothing about any browser.
    """
    from app.web import state

    wanted = host_of(host) or str(host or "").strip().lower()
    known = {one["site"] for one in registered(store, app_conn)}
    if wanted not in known:
        return {"host": wanted, "state": "no_adapter",
                "detail": "nothing installed here reads this site"}
    if app_conn is None:
        return {"host": wanted, "state": "unknown", "detail": ""}
    row = state.activations(app_conn).get(wanted)
    if row is None:
        return {"host": wanted, "state": "unknown",
                "detail": "the extension has not reported on this site yet"}
    reported = row.get("state") or ""
    if reported == "active":
        return {"host": wanted, "state": "active", "detail": "",
                "pattern": row.get("pattern", "")}
    if reported == "pending":
        return {
            "host": wanted, "state": "needs_permission",
            "pattern": row.get("pattern", ""),
            "detail": "the browser has not granted Kriko permission to read "
                      "this site. Only the extension can ask for it — open its "
                      "options page and press Grant.",
        }
    return {"host": wanted, "state": "invalid",
            "detail": row.get("detail") or "the browser refused this site"}


def registered(store, app_conn) -> list[dict]:
    """Every site this installation can read, and where each one came from.

    One list rather than two, because the reader's question is "will Kriko work
    on this page" and the answer has one shape. `source` is the difference that
    matters afterwards: a pack's adapter updates when the pack does; a local one
    is this installation's own and nothing else will ever fix it.
    """
    out = [
        {
            "site": one.get("site", ""),
            "id": one.get("id", ""),
            "pack_id": one.get("pack_id", ""),
            "match": one.get("match", []),
            "source": "pack",
        }
        for one in load_adapters(store)
    ]
    known = {one["site"] for one in out}
    if app_conn is None:
        return out
    from app.web import state

    for row in state.local_adapters(app_conn):
        if row["host"] in known:
            # A pack now ships one for this host: the local copy is redundant
            # rather than wrong, and saying so is more use than hiding it.
            out.append({
                "site": row["host"], "id": (row.get("spec") or {}).get("id", ""),
                "pack_id": row.get("pack_id", ""), "match": [],
                "source": "local", "superseded": True,
            })
            continue
        spec = row.get("spec") or {}
        out.append({
            "site": row["host"],
            "id": spec.get("id", ""),
            "pack_id": row.get("pack_id", ""),
            "match": spec.get("match", []),
            "source": "local",
            "superseded": False,
        })
    return out


#: What an agent is told when it is asked to teach this installation a site.
#: The adapter contract, in the words of the thing being written — and the
#: reason it is here rather than in a prompt file is that it has to stay next
#: to `check()`, which refuses everything this does not say.
BRIEF = """# Teach Kriko to read a website

Kriko answers "what is known to go wrong with this specific one" for a product
a reader is looking at. To do that on a listing page it needs an **adapter**:
the rules for turning that page into an identity — the handful of `key=value`
pairs that say *which* product this is.

    Site:  {site}
    Page:  {url}

Read that page (and one or two more listings on the same site, so you are
describing the template rather than one advert). Then write the adapter.

## What it must contain

```json
{{"id": "local.{site}",
  "site": "{site}",
  "match": ["*://*.{site}/*"],
  "fields": {{"<identity key>": {{"labels": ["the words the page uses"],
                               "selector": "a CSS selector, if the page has one"}}}},
  "title_patterns": ["regexes over the page title, when the labels are absent"]
}}
```

The identity keys are **not yours to invent**. This installation's packs
declare them, and a value mapped to a key no pack knows is a lookup that
resolves to nothing. The keys available here:

{keys}

## What matters

* **Labels over selectors.** A site's class names change every few months; the
  word next to the value changes rarely. Give both where you can, labels first.
* **The page's own language.** If the site is Turkish, the labels are Turkish.
  Write what is on the page, not a translation of it.
* **Do not guess a field you could not find.** A missing key resolves less
  precisely; a wrong one resolves to the wrong product, and the reader is then
  shown risks for something else entirely.
* **Nothing but this site.** `site` is a bare hostname and `match` may only
  cover it. It becomes a permission in somebody's browser.

Print the adapter as one JSON object in a ```json fence, as the last thing you
say, and nothing after it.
"""
