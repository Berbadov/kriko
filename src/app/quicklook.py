"""A quick look: what is known to go wrong with a product nobody has researched yet.

The reader's comparison was the fair one: *"in normal claude or Mistral vibe chat
they can search web and answer instantly"*, while Kriko's only door for an
unknown product was a whole pack authored from scratch — a forty-minute brief
whose output was an uninstalled draft, so the listing showed nothing either way.

This is the chat-speed half of "quick answer, then deepen" (B148). One short
call at low effort, a handful of searches, and a few risks that each carry the
page they came from and a quote from it. The deeper run starts beside it and
is what grows the packs; this one writes nothing to the store. It is a job
result the panel renders, which is why it may be quick: nothing here becomes
knowledge, so nothing here needs the ledger's bar — only the honesty of saying
where each line came from.

**A risk with no page and no quote is dropped, never shown.** The same rule as
every other door, applied the cheap way: we cannot re-read the page in two
minutes, but we can refuse a line that does not even claim a source.
"""

from urllib.parse import urlparse

from kriko.research.agent import REFUSED_PAGE

#: Enough to be worth reading on a listing, few enough to be done in the time.
MAX_RISKS = 6

#: Specifications kept, for the same reason: a line to read, not a datasheet.
MAX_SPECS = 10

#: What the panel's card knows how to colour. Anything else reads as `medium`.
SEVERITIES = ("high", "medium", "low")


def brief(product: str, principle: str = "", page: dict | None = None,
          packs: str = "", attributes: str = "") -> str:
    """The quick pass, as instructions. Fast on purpose: a few searches, no essay.

    `page` is what the listing itself says (`app.pagefacts`, B150): the
    variant is settled from it, not from the title alone.

    `packs` is the installed category packs, one per line
    (`categorypack.choice_block`). The answer's `pack` is one of their ids or
    empty, and `category` says in a few words what kind of product this is, so
    a product joins a pack for its kind instead of starting its own (B169).

    `attributes` is the specification names the product's pack already uses,
    one per line, so the figures come back under the pack's own words (B173).
    """
    from app import pagefacts

    listing = pagefacts.block(page)
    bar = (
        f"\n## What is worth saying\n\nThe installed pack's own bar, verbatim:\n\n"
        f"{principle.strip()}\n"
        if principle.strip() else ""
    )
    belongs = (
        "\n## Where it belongs\n\nThese installed packs each hold one kind of "
        f"product:\n\n{packs.strip()}\n\nIf this product is that kind, give the "
        "pack's id in `pack`. If none of them fits, leave `pack` empty.\n"
        if packs.strip() else ""
    )
    named = (
        "\nUse these names for a specification where they fit:\n\n"
        f"{attributes.strip()}\n"
        if attributes.strip() else ""
    )
    return f"""# Quick look: what is known to go wrong with this one?

    {product}
{listing}
Someone is looking at this exact product right now and wants to know what to
worry about **before** they spend money on it. Answer the way a knowledgeable
friend would in a chat: fast, specific, sourced.

* Do **two to four** web searches. Open **at most three** pages; a page that
  refuses you does not count toward the three. Stop there.
* {REFUSED_PAGE}
* Be specific to this exact variant. Skip anything true of every product like it.
* If the name leaves the variant open, pick the most likely one and say which
  in `assumed`. Do not ask; there is no one to answer.
{bar}{belongs}
## Every risk needs its page

Each risk must name a page you actually opened (`url`) and a short quote copied
from it word for word (`quote`). A risk you cannot source that way: leave it
out. Fewer honest lines beat more guessed ones.

## Specifications

Also give up to {MAX_SPECS} specifications a buyer would compare this product
on (for example chipset, battery or display for a phone). Each needs the page
it was read from (`url`). Leave out any figure you cannot source.
{named}
## Reply

At most {MAX_RISKS} risks, as one JSON object in a ```json fence, as the last
thing you say. `category` is what kind of product this is, in two to four
words, with no brand or model in it (for example "wireless earbuds").

```json
{{"assumed": "one sentence on which variant you took this to be",
  "category": "what kind of product this is",
  "pack": "the id of a listed pack this belongs in, or an empty string",
  "specs": [
    {{"name": "what the figure is", "value": "the figure with its unit",
      "url": "https://the page you read"}}
  ],
  "risks": [
    {{"title": "short name of the problem",
      "why": "one or two sentences: what fails, when, what it costs",
      "check": "what to look or ask for before buying, or \\"\\"",
      "severity": "high",
      "url": "https://the page you read",
      "quote": "a sentence copied from that page"}}
  ]}}
```
"""


def parse(reply: str, sources: dict[str, str] | None = None) -> dict:
    """The agent's answer as cards, or an honest nothing. Never raises.

    `sources` is url -> the text a search tool returned for it, when the
    plane can say (the API agent, B153). Then a quote has to be *in* that
    text, and is shown as the page's own characters (`loose_span`); a CLI's
    reply carries no such text, so there it is only required to exist.
    """
    from app.packauthor import _payload  # the one fence reader every door uses
    from kriko.extract.grounding import loose_span

    found = _payload(reply)
    if not isinstance(found, dict):
        return {"assumed": "", "category": "", "pack": "", "specs": [],
                "risks": [], "dropped": 0}

    risks: list[dict] = []
    dropped = 0
    for raw in found.get("risks") or []:
        if not isinstance(raw, dict):
            dropped += 1
            continue
        title = str(raw.get("title") or "").strip()
        url = str(raw.get("url") or "").strip()
        quote = str(raw.get("quote") or "").strip()
        host = urlparse(url).netloc if url.startswith(("http://", "https://")) else ""
        if not title or not host or not quote:
            dropped += 1
            continue
        checked = False
        if sources is not None:
            quote = loose_span(sources.get(url, ""), quote)
            if not quote:
                dropped += 1
                continue
            checked = True
        if len(risks) == MAX_RISKS:
            break
        severity = str(raw.get("severity") or "").strip().lower()
        host = host.removeprefix("www.")
        risks.append({
            # The shape the panel's claim card already renders. No `claim_id`
            # on purpose: a verdict button needs a stored claim to attach to,
            # and this is not one yet.
            "title": title,
            "body": str(raw.get("why") or "").strip(),
            "advice": str(raw.get("check") or "").strip(),
            "severity": severity if severity in SEVERITIES else "medium",
            "strength": "reported",
            "source_count": 1,
            "domain": host,
            "quick": True,
            "sources": [{"url": url, "domain": host, "quote": quote,
                         # Only when the plane kept the text this quote was
                         # found in. Otherwise the store reads the page again
                         # before it keeps the quote (`categorypack.ground`).
                         **({"grounded": True} if checked else {})}],
        })

    specs: list[dict] = []
    for raw in found.get("specs") or []:
        if not isinstance(raw, dict) or len(specs) == MAX_SPECS:
            continue
        name, value = _line(raw.get("name")), _line(raw.get("value"))
        url = str(raw.get("url") or "").strip()
        host = urlparse(url).netloc if url.startswith(("http://", "https://")) else ""
        if name and value and host:
            specs.append({"name": name, "value": value, "url": url,
                          "domain": host.removeprefix("www.")})

    return {
        "assumed": str(found.get("assumed") or "").strip(),
        "category": _line(found.get("category")),
        "pack": _line(found.get("pack")).lower(),
        "specs": specs,
        "risks": risks,
        "dropped": dropped,
    }


def _line(value) -> str:
    """A short single-line answer, or "". Never more than a name's worth."""
    return " ".join(str(value or "").split())[:80]
