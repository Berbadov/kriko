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

#: What the panel's card knows how to colour. Anything else reads as `medium`.
SEVERITIES = ("high", "medium", "low")


def brief(product: str, principle: str = "", page: dict | None = None) -> str:
    """The quick pass, as instructions. Fast on purpose: a few searches, no essay.

    `page` is what the listing itself says (`app.pagefacts`, B150): the
    variant is settled from it, not from the title alone.
    """
    from app import pagefacts

    listing = pagefacts.block(page)
    bar = (
        f"\n## What is worth saying\n\nThe installed pack's own bar, verbatim:\n\n"
        f"{principle.strip()}\n"
        if principle.strip() else ""
    )
    return f"""# Quick look: what is known to go wrong with this one?

    {product}
{listing}
Someone is looking at this exact product right now and wants to know what to
worry about **before** they spend money on it. Answer the way a knowledgeable
friend would in a chat: fast, specific, sourced.

* Do **two to four** web searches. Open **at most three** pages. Stop there.
* {REFUSED_PAGE}
* Be specific to this exact variant. Skip anything true of every product like it.
* If the name leaves the variant open, pick the most likely one and say which
  in `assumed`. Do not ask; there is no one to answer.
{bar}
## Every risk needs its page

Each risk must name a page you actually opened (`url`) and a short quote copied
from it word for word (`quote`). A risk you cannot source that way: leave it
out. Fewer honest lines beat more guessed ones.

## Reply

At most {MAX_RISKS} risks, as one JSON object in a ```json fence, as the last
thing you say:

```json
{{"assumed": "one sentence on which variant you took this to be",
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
        return {"assumed": "", "risks": [], "dropped": 0}

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
        if sources is not None:
            quote = loose_span(sources.get(url, ""), quote)
            if not quote:
                dropped += 1
                continue
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
            "sources": [{"url": url, "domain": host, "quote": quote}],
        })

    return {
        "assumed": str(found.get("assumed") or "").strip(),
        "risks": risks,
        "dropped": dropped,
    }
