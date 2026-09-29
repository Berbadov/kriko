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
from kriko.adapters import adapters_for as pack_adapters_for
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


#: The rule keys `kriko/adapters.py` actually interprets. Anything else in a
#: rule is inert — it neither reads a field nor raises, which is the worst of
#: both. Kept next to the fold below so the two cannot drift.
RULE_KEYS = ("labels", "from", "vocabulary", "segment", "split",
             "parse", "min", "max", "known")


def _rule(key: str, raw) -> dict | None:
    """One field's rule, in the vocabulary the engine reads. None if inert.

    A rule the engine cannot act on is dropped rather than kept, because a
    stored adapter full of rules that read nothing is indistinguishable, from
    every screen in the app, from one that works.
    """
    if not isinstance(raw, dict):
        return None
    out = {k: raw[k] for k in RULE_KEYS if k in raw}
    labels = [str(one).strip() for one in (out.get("labels") or []) if str(one).strip()]
    if labels:
        out["labels"] = labels
    else:
        out.pop("labels", None)
    if out.get("segment") not in ("first", "last"):
        out.pop("segment", None)
        out.pop("split", None)
    if out.get("parse") != "int_range":
        out.pop("parse", None)
        out.pop("min", None)
        out.pop("max", None)
    if str(out.get("from") or "") not in ("title", "description", "url"):
        out.pop("from", None)
        out.pop("vocabulary", None)
    # No labels and no text source means nothing on the page could ever match.
    # The page title plus the packs' own identity vocabulary is the engine's
    # one answer to that, and it is the same one `packs/cars` uses for `make`
    # and `model` — so fall back to it rather than storing a dead rule.
    if not out.get("labels") and not out.get("from"):
        out["from"] = "title"
        out["vocabulary"] = key
    return out or None


def normalise(spec: dict) -> dict:
    """An adapter in the one shape `kriko/adapters.py` reads. Never raises.

    **This is the seam that made a registered site read nothing.** The engine
    interprets `identity` and `context`; the brief this module hands an agent
    asked for `fields` and `title_patterns`, and nothing anywhere ever read
    either. So an adapter would validate, store, list on the Sites screen,
    earn a host permission and inject a content script — and then resolve an
    empty identity on every page, because the only two keys with meaning were
    absent. Both surfaces reported success. The reader got no panel.

    The brief now asks for the engine's own vocabulary. This fold stays
    because adapters written under the old one are already stored in people's
    `app.sqlite`, and a migration that needed a reader to notice and re-run a
    registration is the human-in-the-data-path this project refuses. Applied
    on read, an old row heals itself the next time anything looks at it.
    """
    if not isinstance(spec, dict):
        return {}
    out = dict(spec)
    identity = dict(out.get("identity") or {})
    context = dict(out.get("context") or {})

    # `fields` was the old brief's single bucket: it drew no line between what
    # names the product and what merely describes it. Identity is the safe
    # side — a key the packs declare as identity is one; anything else the
    # engine still carries through as context.
    for key, raw in (out.pop("fields", None) or {}).items():
        name = str(key or "").strip().lower()
        if not name or name in identity or name in context:
            continue
        rule = _rule(name, raw)
        if rule is not None:
            identity[name] = rule

    out.pop("title_patterns", None)  # never interpreted; `from: title` is

    out["identity"] = {k: r for k, r in (
        (str(k).strip().lower(), _rule(str(k).strip().lower(), v))
        for k, v in identity.items()) if k and r is not None}
    out["context"] = {k: r for k, r in (
        (str(k).strip().lower(), _rule(str(k).strip().lower(), v))
        for k, v in context.items()) if k and r is not None}
    out["subject_kind"] = str(out.get("subject_kind") or "product")
    return out


def local_rows(app_conn) -> list[dict]:
    """This installation's learned adapters, every one of them normalised.

    One read path on purpose. Three call sites used to read `local_adapters`
    straight off the table — the lookup, the Sites screen and the extension's
    own `/api/adapters` — and a fold applied in two of them would have been a
    site that works in the browser and not in the app, or the reverse.
    """
    if app_conn is None:
        return []
    from app.web import state

    out = []
    for row in state.local_adapters(app_conn):
        one = dict(row)
        one["spec"] = normalise(one.get("spec") or {})
        out.append(one)
    return out


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
    # Normalised *before* the emptiness test, because "has rules" has to mean
    # "has rules the engine will act on". The old test asked whether a `fields`
    # key was present, which every adapter that read nothing also passed.
    folded = normalise(spec)
    if not folded.get("identity"):
        raise SiteRefused(
            "no `identity` rules the engine can act on. An adapter that names "
            "no identity key resolves every page to nothing, which is the same "
            "as not having one — give each key either `labels` the page shows "
            "or `from: \"title\"`"
        )
    return {
        **folded,
        "id": str(spec.get("id") or f"local.{site}"),
        "site": site,
        "match": match,
    }


def adapters_for(store, app_conn, url: str) -> list[dict]:
    """Every adapter that claims this URL: the packs' own, or else this
    installation's. Several packs may claim one site; the page decides which
    of them reads it (`kriko.adapters.best_reading`)."""
    found = pack_adapters_for(store, url)
    if found:
        return found
    local = adapter_for(store, app_conn, url)
    return [local] if local is not None else []


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
    for row in local_rows(app_conn):
        if row["host"] != host:
            continue
        return {**row["spec"], "pack_id": row.get("pack_id") or "", "local": True}
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
    for row in local_rows(app_conn):
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
  "subject_kind": "product",
  "match": ["*://*.{site}/*"],
  "identity": {{
    "<identity key>": {{"labels": ["the words the page puts next to the value"]}},
    "<identity key>": {{"from": "title", "vocabulary": "<identity key>"}}
  }},
  "context": {{
    "<context key>": {{"labels": ["km", "mileage"],
                     "parse": "int_range", "min": 0, "max": 2000000}}
  }}
}}
```

## The rule vocabulary — these keys and no others

Anything else you write is **ignored silently**: it will not read a field and
it will not raise, so an adapter full of invented keys looks exactly like one
that works. There are seven.

* `labels` — the words the page prints beside the value. This is the main
  mechanism; prefer it to everything below.
* `from` — `"title"`, `"description"` or `"url"`. Read from that text instead,
  when the page has no label. Only consulted if no label matched.
* `vocabulary` — with `from`, look in that text for any value the installed
  packs already know for this key. This is how a make or a brand is read out
  of a title without either being written down here.
* `segment` — `"first"` or `"last"`, with optional `split` (default `"/"`),
  when one cell packs several facts: `"Otomatik / Onden Cekis"`.
* `parse` — only `"int_range"`, with `min` and `max`. Use it for every number.
  It strips thousands separators and **discards a value outside the range**,
  which is what stops "1.461 cm3" being read as a mileage.

There is no `selector` and no `title_patterns`. CSS selectors are not part of
the format — a site's class names change every few months and its labels
rarely do, which is why labels are the whole design.

## identity vs context

`identity` decides *which product this is*, and its keys are **not yours to
invent** — this installation's packs declare them, and a value mapped to a key
no pack knows is a lookup that resolves to nothing. The keys available here:

{keys}

`context` is everything else worth knowing about this particular one — the
mileage, the year, the free text. Its keys are yours to name.

## What matters

* **The page's own language.** If the site is Turkish, the labels are Turkish.
  Write what is on the page, not a translation of it.
* **Give several spellings.** `labels` is a list; a site writing a field two
  ways in two languages is ordinary.
* **Do not guess a field you could not find.** A missing key resolves less
  precisely; a wrong one resolves to the wrong product, and the reader is then
  shown risks for something else entirely.
* **Nothing but this site.** `site` is a bare hostname and `match` may only
  cover it. It becomes a permission in somebody's browser.

Print the adapter as one JSON object in a ```json fence, as the last thing you
say, and nothing after it.
"""
