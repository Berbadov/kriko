"""What the listing itself says, for an agent researching the product on it.

The reader's words: *"figure it out which more information agents needs by its
own from the product page — because i may not know which engine code is this"*
(B150). A research run used to get the listing's title and nothing else, so it
asked the reader for the engine power the page prints two lines below the
title. The extension now sends the page's own labelled facts beside the name;
this module trims them to something a prompt can carry and says what an agent
must do with them.

Nothing here knows a category. The facts are the site's own labels in the
site's own language, passed through as they were read.
"""

#: Enough for a spec table, few enough that a page full of equipment rows
#: cannot crowd the brief.
MAX_FACTS = 40
MAX_LABEL = 80
MAX_VALUE = 200
MAX_DESCRIPTION = 1500


def clean(facts, description: str = "") -> dict:
    """`{"facts": {label: value}, "description": str}`, trimmed and stringy."""
    out: dict[str, str] = {}
    items = facts.items() if isinstance(facts, dict) else ()
    for label, value in items:
        label = " ".join(str(label or "").split())[:MAX_LABEL]
        value = " ".join(str(value or "").split())[:MAX_VALUE]
        if not label or not value or label == "ld:@type":
            continue
        out[label] = value
        if len(out) == MAX_FACTS:
            break
    text = " ".join(str(description or "").split())[:MAX_DESCRIPTION]
    return {"facts": out, "description": text}


def present(page: dict | None) -> bool:
    return bool(page and (page.get("facts") or page.get("description")))


def block(page: dict | None) -> str:
    """The prompt section, or "" when the listing gave nothing."""
    if page is None or not present(page):
        return ""
    rows = "\n".join(f"* {label}: {value}" for label, value in (page.get("facts") or {}).items())
    said = (f"\n\nThe seller's description (their words — may exaggerate, may "
            f"state the exact version):\n\n> {page['description']}"
            if page.get("description") else "")
    return f"""
## What the listing itself says

The reader is looking at this listing now. Its own labelled facts, copied off
the page in the site's own words:

{rows or "* (no labelled facts)"}{said}

**Settle the exact version from these yourself.** Power, size, year, trim and
the other specs on the page usually pin down the precise model or component
code; where they do not name it, one search from them will. The reader is a
buyer, not a technician: never ask them for a code, a part number, or anything
they would have to look up. If the facts still leave two versions open, take
the more likely one and say which, and why, in your answer.
"""
