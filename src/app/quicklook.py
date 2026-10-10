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

# The local runtime can enforce this shape while it generates the answer.
# Empty lists remain valid: a schema must never force an unsupported claim.
REPLY_SCHEMA: dict = {
    "type": "object",
    "properties": {
        **{key: {"type": "string"} for key in ("assumed", "category", "pack")},
        "specs": {"type": "array", "maxItems": MAX_SPECS, "items": {
            "type": "object", "properties": {
                key: {"type": "string"} for key in ("name", "value", "url")},
            "required": ["name", "value", "url"]}},
        "risks": {"type": "array", "maxItems": MAX_RISKS, "items": {
            "type": "object", "properties": {
                **{key: {"type": "string"} for key in
                   ("title", "why", "check", "url", "quote")},
                "severity": {"type": "string", "enum": list(SEVERITIES)}},
            "required": ["title", "why", "url", "quote", "severity"]}},
    },
    "required": ["risks", "specs"],
}


def brief(product: str, principle: str = "", page: dict | None = None,
          packs: str = "", attributes: str = "", *, compact: bool = False) -> str:
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
    if compact:
        return (
            f"# Quick look: what is known to go wrong with this one?\n\n{product}\n"
            f"{listing}{bar}{belongs}{named}\n"
            "Use only the fetched pages below. Be specific to this variant. "
            "Return one JSON object, with short fields and at most two risks "
            "and three specifications. Every risk needs an exact URL and a "
            "verbatim quote from that page. Leave unsupported items out. "
            "Use empty lists if the pages provide no evidence. State any "
            "variant assumption in assumed. Shape:\n"
            '{"assumed":"", "category":"", "pack":"", '
            '"specs":[{"name":"", "value":"", "url":""}], '
            '"risks":[{"title":"", "why":"", "check":"", '
            '"severity":"medium", "url":"", "quote":""}]}\n')
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
* If the name leaves the variant open, state what is missing in `assumed`.
  Omit claims that depend on an unproven configuration. Do not guess a part
  code or assume that a nearby revision, year or market has the same fault.
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
    if not isinstance(found, dict) or not {"risks", "specs"} & found.keys():
        # A reply cut off at its token budget (a local model on a CPU, in
        # practice) is still mostly whole items. Every item is checked by
        # the same rules below, so a closed-off reply keeps what was
        # finished and drops nothing it would not have dropped anyway.
        found = closed(reply) or found
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
        if sources is not None and url not in sources:
            dropped += 1
            continue
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


def closed(reply: str) -> dict | None:
    """The JSON object in a reply that stopped mid-way, closed at the last
    item it finished. `None` when there is no object to close."""
    import json
    import re

    start = reply.find("{")
    if start < 0:
        return None
    text = reply[start:]
    stack: list[str] = []
    in_string = escaped = False
    safe = 0
    safe_stack: list[str] = []
    for index, char in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in "{[":
            stack.append("}" if char == "{" else "]")
        elif char in "}]":
            if not stack:
                break
            stack.pop()
            if not stack:
                safe, safe_stack = index + 1, []
                break
            safe, safe_stack = index + 1, list(stack)
    if not safe:
        return None
    candidate = text[:safe] + "".join(reversed(safe_stack))
    try:
        found = json.loads(candidate)
    except ValueError:
        # A small model's other habit: a comma before a closing bracket.
        try:
            found = json.loads(re.sub(r",\s*([\]}])", r"\1", candidate))
        except ValueError:
            return None
    return found if isinstance(found, dict) else None


def _line(value) -> str:
    """A short single-line answer, or "". Never more than a name's worth."""
    return " ".join(str(value or "").split())[:80]


def outcome(reply: str, found: dict, *, finish_reason: str = "") -> str:
    """Explain an empty result without claiming that a deadline expired."""
    from app.packauthor import _payload

    if found.get("risks"):
        return f"{len(found['risks'])} risk(s) found"
    if found.get("dropped"):
        return "no risks kept: the proposed claims did not pass the source checks"
    if found.get("specs"):
        return f"{len(found['specs'])} specification(s) found; no sourced risks"
    payload = _payload(reply) or closed(reply)
    if not isinstance(payload, dict) or not any(
            isinstance(payload.get(key), list) for key in ("risks", "specs")):
        return ("the local answer was cut off; retry with a shorter answer or more context"
                if finish_reason == "length" else
                "the agent returned an unreadable answer; retry Quick Look")
    return "the pages read did not yield any sourced findings"


def follow_up(question: str, assumed: str, risks: list[dict],
              specs: list[dict]) -> str:
    """A reader's follow-up, answered from the quick look's own findings.

    The panel's question box (#112). No search, no new pages: the answer is
    what this quick look found, and if the findings do not answer it the reply
    says exactly that — the Sources drawer is where going further belongs.
    """
    lines = [
        "A quick look at a product found the findings below. The reader asks a",
        "follow-up question. Answer it using only these findings; quote nothing",
        "you do not see here. If they do not answer the question, say exactly",
        "that in one sentence and stop. Plain text, no markdown, under 120 words.",
        "",
        f"The reader asks: {question.strip()}",
    ]
    if assumed.strip():
        lines.append(f"The product was taken as: {assumed.strip()}")
    lines.append("")
    lines.append("## The findings")
    for one in risks:
        if not isinstance(one, dict):
            continue
        title = str(one.get("title") or "").strip()
        if not title:
            continue
        lines.append(f"- {title} ({one.get('severity') or 'unknown'}): "
                     f"{str(one.get('body') or '').strip()}")
        if str(one.get("advice") or "").strip():
            lines.append(f"  Worth checking: {str(one['advice']).strip()}")
        for src in one.get("sources") or []:
            lines.append(f"  Source: {src.get('domain', '')} {src.get('url', '')} — "
                         f"\u201c{str(src.get('quote') or '').strip()}\u201d")
    for one in specs:
        if isinstance(one, dict) and one.get("name") and one.get("value"):
            lines.append(f"- {one['name']}: {one['value']} ({one.get('domain', '')})")
    return "\n".join(lines)
