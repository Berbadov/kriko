"""The *when*, to go with the MCP server's *what*.

Wiring a harness to the MCP server tells an agent which tools exist. It does
not tell it that "the app says nothing is known about this drill" is an
invitation to go and find out, and it does not tell it what this particular
installation considers worth keeping. That is a skill: a short document a
harness loads by description and applies when the description matches.

The document is **assembled from the installed packs**, never written here.
Each pack already ships `research/principle.md` — what is worth surfacing in
its category — and the store already carries it as a pack asset. A skill built
from those states two different bars for a car and a power drill without this
module knowing what either is, and it changes when the pack updates rather than
when the binary does. That is the whole reason it is generated rather than
checked in: the protocol versions with the knowledge.

An installation with no packs gets no skill. There is nothing to research and
nothing to say what would count, and a skill that fires anyway is worse than
none.
"""

from kriko.research import pack_asset

SKILL_NAME = "kriko-research"

#: The loop, in the order an agent must run it. Stated once, here, because both
#: the skill body and the UI's explanation of the protocol come from it.
STEPS = [
    ("coverage_gaps", "find subjects this installation knows nothing about"),
    ("research_brief", "ask the pack what to look for and what counts"),
    ("subject_health", "read back what is already known before adding to it"),
    ("submit_findings", "file what you found, with the quote you found it in"),
]

_HEADER = """\
---
name: {name}
description: {description}
---

# Researching for this Kriko installation

Kriko answers "what is known to go wrong with *this specific one*" from
installed knowledge packs. It gathers nothing on its own: filling a gap is
your job, through the `kriko` MCP server this harness is connected to.

## When to use this

{when}

## The loop

{loop}

Never skip `research_brief`. Its content comes from the pack, not from Kriko,
and it is the only thing that says what this category considers worth keeping —
the same finding is valuable for one pack and noise for another.

## What a finding must carry

Every finding is submitted with the source URL and the **exact quote** from
that document. `submit_findings` re-reads the document and refuses a quote it
cannot find in it: a paraphrase, a tidied-up sentence, or a summary of two
sentences is rejected. This is not a style rule — it is the only thing standing
between a knowledge base and a plausible-sounding one.

Findings arrive as drafts. Submitting is not publishing, so a finding you are
unsure of is better filed with its weak source than dropped.

## What each installed pack considers worth keeping
"""


def _when(packs: list[dict]) -> str:
    """The description's trigger, in the reader's own installed terms.

    Named packs rather than "products" because a harness matches a skill by
    reading this line: "used cars" is a trigger, "domain entities" is not.
    """
    names = [p["name"] for p in packs]
    if len(names) == 1:
        subject = names[0]
    else:
        subject = ", ".join(names[:-1]) + f" or {names[-1]}"
    return (
        f"Use this when asked to research {subject} for Kriko, when Kriko "
        f"reports a coverage gap, or when a lookup returns nothing known about "
        f"a subject one of these packs covers."
    )


def render(conn) -> str | None:
    """Build the skill from what is installed, or None if nothing is.

    Disabled packs are excluded: a reader who turned a pack off has said its
    knowledge should not be used, and researching *into* it would be the same
    surprise from the other direction.
    """
    packs = [
        {
            "pack_id": row["pack_id"],
            "name": row["name"],
            "version": row["version"],
            "principle": pack_asset(conn, row["pack_id"], "research/principle.md").strip(),
        }
        for row in conn.execute(
            "SELECT pack_id, name, version FROM packs WHERE enabled = 1"
            " ORDER BY pack_id"
        )
    ]
    if not packs:
        return None

    when = _when(packs)
    loop = "\n".join(
        f"{i}. **`{tool}`** — {why}" for i, (tool, why) in enumerate(STEPS, 1)
    )
    body = _HEADER.format(
        name=SKILL_NAME,
        # Frontmatter is one line; a description that wraps stops being parsed.
        description=" ".join(when.split()),
        when=when,
        loop=loop,
    )
    for pack in packs:
        body += f"\n### {pack['name']} (`{pack['pack_id']}` {pack['version']})\n\n"
        body += (pack["principle"] or "_This pack ships no principle._") + "\n"
    return body
