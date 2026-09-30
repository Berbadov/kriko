"""The *when*, to go with the MCP server's *what*.

Wiring a harness to the MCP server tells an agent which tools exist. It does
not tell it that "the app says nothing is known about this product" is an
invitation to go and find out. That is a skill: a short document a harness
loads by description and applies when the description matches.

**Short on purpose (B178).** The skill was 4,944 words, about 3,300 of them
copied from the installed packs and 1,900 generic, and it named screens, a
repo path, a dated history note and one category's example. It is now under
1,500 words whatever is installed, names no screen, product, harness or model,
and gives each of its five steps one input and one output.

What left it did not disappear. A pack's bar (`research/principle.md`), its
identification method (`research/skill.md`), its domain words and its
rationale minimum arrive through `research_brief`, per subject, where they are
the right size and cannot go stale in a file on disk. The skill keeps the
protocol, and the protocol changes with this build rather than with the packs.

An installation with no packs gets the authoring half of the skill, since
there is nothing to research and the job is to write the first pack.
"""

import re

SKILL_NAME = "kriko-research"

#: The line the generated file carries so a copy on disk can be compared with
#: the one this build would write *without* re-reading every pack twice.
#:
#: This is the whole answer to "you did not change the skill text": the skill
#: is written once, when the reader presses Connect, and then never again — so
#: an overhauled protocol, a new tool, or an updated pack reached the code and
#: not the agent. A stamp makes staleness visible; `agentconfig.skill_status`
#: reads it and the app refreshes it at startup.
STAMP = "kriko-skill-digest:"

#: Fences around the parts of a skill that describe *this moment* rather than
#: the protocol: the agenda's ranking, and how many subjects and claims a pack
#: holds right now. They are worth putting in the file, since a first session
#: gets a head start without a round trip, and they are wrong within the hour,
#: since every analysis and every accepted finding moves them.
#:
#: The digest leaves them out. It answers "is the protocol on disk the one this
#: build would write", and a snapshot cannot be part of that answer: it is
#: computed from the reader's own history, and startup, the status check and
#: the Update button each saw a different one. So the button came back after
#: every restart and every analysis, and pressing it changed nothing that lasted
#: (B157). Comments, like the stamp, so nothing reads them as text.
SNAPSHOT_OPEN = "<!-- kriko-snapshot:begin -->"
SNAPSHOT_CLOSE = "<!-- kriko-snapshot:end -->"

_SNAPSHOT = re.compile(
    re.escape(SNAPSHOT_OPEN) + r".*?" + re.escape(SNAPSHOT_CLOSE), re.DOTALL
)


def snapshot(text: str) -> str:
    """Fence a passage that describes the moment, so `digest` skips it."""
    return f"{SNAPSHOT_OPEN}\n{text}{SNAPSHOT_CLOSE}\n"


def digest(body: str) -> str:
    """A short content hash of the *protocol* in a rendered skill.

    Left out: the stamp line itself, and every fenced snapshot. Everything else
    is in, so a changed loop, tool or pack list still reads as stale, which is
    what the digest exists to say.
    """
    import hashlib

    # Blank lines and trailing whitespace are normalised as well, so
    # `digest(body) == digest(stamped(body))` and a skill with a snapshot hashes
    # like one without. Without the first the stamp a file carries could never
    # equal the digest of the file it is in, and every copy would report itself
    # stale forever — a staleness check that is always true is the same as not
    # having one.
    text = _SNAPSHOT.sub("", body or "")
    stripped = "\n".join(
        line.rstrip()
        for line in text.splitlines()
        if line.strip() and STAMP not in line
    )
    return hashlib.sha256(stripped.encode("utf-8")).hexdigest()[:12]


def stamped(body: str) -> str:
    """The body, carrying its own digest as a trailing comment."""
    if not body:
        return body
    return f"{body.rstrip()}\n\n<!-- {STAMP}{digest(body)} -->\n"


def digest_of_file(text: str) -> str:
    """The digest a file on disk claims, or `""`."""
    for line in (text or "").splitlines():
        if STAMP in line:
            return line.split(STAMP, 1)[1].strip().rstrip("->").strip()
    return ""


#: How many packs the skill lists by name before it says how many more there
#: are. The skill is a prompt with a word budget
#: (`test_the_skill_is_short_and_generic`): its length must not depend on what
#: is installed, and the ninth pack teaches an agent nothing the eighth did
#: not. `research_agenda` names every pack that has work in it.
_MAX_PACKS = 8

#: Longest text taken from a row or a name, in characters. The same reason: a
#: label is its author's, and a long one must not move the budget.
_MAX_LABEL = 80
_MAX_WHY = 160

#: The loop, in the order an agent must run it. Stated once, here, because both
#: the skill body and the route that serves it come from it. Each step names
#: exactly one input and one output (B178): an agent holding a step can see
#: what to hand it and what comes back without reading prose around it.
STEPS = [
    ("research_agenda", "a pack id, or none",
     "subjects ranked by demand, each with subject_id and pack_id"),
    ("coverage_gaps", "a pack id, or none",
     "every subject with nothing known yet"),
    ("research_brief", "subject_id and pack_id",
     "the pack's bar, seed searches and field rules for that subject"),
    ("subject_health", "subject_id and pack_id",
     "what is already known about it, with its sources"),
    ("submit_findings", "subject_id, pack_id and a list of findings",
     "a verdict for each finding"),
]

_HEADER = """\
---
name: {name}
description: {description}
---

# Researching for this installation

Installed packs hold what is known about specific products. They gather
nothing on their own: filling a gap is your job, through the MCP server this
harness is wired to.

## When to use this

{when}

## The five steps

Run them in order. Step 2 is for when step 1 returns nothing.

{loop}

Never skip step 3. Its output comes from the pack, not from the tools, and it
is the only statement of what this category considers worth keeping: the same
finding is valuable for one pack and noise for another.

## A finding

`submit_findings` takes a list of objects. Every field is required:

- `title`: the risk in one line, specific to this configuration
- `domain`: one of the pack's domain words, which the brief lists
- `severity`: `high`, `medium` or `low`
- `quote`: the exact sentence, copied character for character (verbatim)
- `source_url`: where you read it
- `document_text`: the text you read the quote in
- `rationale`: two or three plain sentences for someone about to spend money.
  Say what goes wrong, when, and what it costs to find out. Never restate the
  title.

Optional: `component` or `component_hint` (the concrete part), `advice`.

`document_text` is what makes the grounding check possible: without it there is
nothing to check the quote against. Findings arrive as drafts, so one you are
unsure of is better filed with its weak source than dropped.

## When a finding is refused

Read each refusal as an instruction.

- `quote does not appear in the document text`: the quote was paraphrased,
  tidied or stitched from two sentences. Copy it verbatim.
- No quote, or `document_text` missing: there is nothing to ground. Re-read the
  page and copy the sentence.
- The pack's own gate: grounded, but routine or true of everything in the
  category. The bar from step 3 applies.
- Nothing to anchor it: no `component`, and no identifier, specification or
  usage figure in the title or rationale.
- Rationale too short: the brief states the pack's minimum. Resubmit the same
  finding with the field filled in.

## Finish the subject

The usual failure is a run that stops early and says nothing about stopping.

- Run several of the brief's searches, not one. They are seeds, not a script.
- Two independent sources beat one good one. Say when only one page makes a
  claim.
- Report what you could not establish: pass `queries` with every search you
  ran, and name the ones that returned nothing in your last message.
- Do not stop at the first page that agrees with you.
- A subject with nothing wrong with it is a result. Say so.
- When asked to research a category, `coverage_gaps` is the list, and finishing
  it is the job.
- A pack may ship `research/gold.yaml`, its ground truth for scoring runs. It
  is not a checklist to copy from: a finding filed because it appears there,
  and not because you read it on a page, is a fabrication with a quote
  attached.

## Installed

"""


_AUTHORING = """\
## Writing a pack

A category nobody has modelled has no bar, no vocabulary and no searches, so
write the pack first.

- `draft_pack(pack_id, name, identity)`: start a draft. `identity` maps each
  subject kind to the attribute keys that make one of them distinct. Too few
  and unrelated things collide; too many and one thing splits. Neither raises.
- `write_draft_file(draft, path, text)`: data files only, nothing executable.
  `research/principle.md` is quoted into every brief and is the category's bar.
  `research/templates.yaml` holds the seed searches, in the languages
  `pack.toml` declares.
- `build_draft(draft)`: finds out whether the rows load, and names the row that
  broke.
- `list_pack_drafts()`: what is already drafted.
- `amend_draft(draft, note)`: add to a draft that is nearly right without
  rewriting it.

Name the whole line-up before writing claims, as `lineup`. The subjects you
wrote are subtracted from it to record what is still uncovered. A pack that
covers three of twenty is confidently incomplete. Stay inside the category:
neighbours go under `coverage.out_of_scope`. A pack name is at most six words.

Installing is the reader's decision. Draft, build, and report what the pack
covers and what it leaves out.

"""


_EMPTY_HEADER = """\
---
name: {name}
description: {description}
---

# Writing the first pack

Installed packs hold what is known about specific products. **None is
installed**, so the research steps have nothing to run against. Your job is the
one before them: write the pack that says what the category is, what is worth
keeping in it and what to search for.

Ask the reader what to cover, then use the tools below. Once a pack is
installed, ask for this skill again: it is rebuilt from what is installed.

"""


def _when(packs: list[dict]) -> str:
    """The description's trigger, in the reader's own installed terms.

    Named packs rather than "products" because a harness matches a skill by
    reading this line: "used cars" is a trigger, "domain entities" is not. The
    list stops at five so the line stays one line.
    """
    names = [p["name"][:_MAX_LABEL] for p in packs]
    if len(names) > 5:
        names = names[:5] + ["anything else installed"]
    if len(names) == 1:
        subject = names[0]
    else:
        subject = ", ".join(names[:-1]) + f" or {names[-1]}"
    return (
        f"Use this when asked to research {subject}, when a coverage gap is "
        f"reported, or when a lookup returns nothing known about a subject "
        f"one of these packs covers."
    )


def _holdings(conn, pack_id: str) -> dict:
    """How much this pack knows, and how much it admits it does not.

    The gap count is the number that turns a skill into a task list, so it is
    stated even when it is zero: "nothing is missing" is also an answer.
    """
    subjects = conn.execute(
        "SELECT COUNT(*) AS n FROM subjects WHERE pack_id = ?", (pack_id,)
    ).fetchone()["n"]
    claims = conn.execute(
        "SELECT COUNT(*) AS n FROM claims WHERE pack_id = ?", (pack_id,)
    ).fetchone()["n"]
    gaps = conn.execute(
        "SELECT COUNT(*) AS n FROM subjects s WHERE s.pack_id = ?"
        " AND NOT EXISTS (SELECT 1 FROM claims c"
        "                 WHERE c.subject_id = s.subject_id AND c.pack_id = s.pack_id)",
        (pack_id,),
    ).fetchone()["n"]
    return {"subjects": subjects, "claims": claims, "gaps": gaps}


def _packs_section(conn, packs: list[dict]) -> str:
    """One line per pack, and nothing of the pack's own prose.

    The pack's bar, its domain words and its identification method used to be
    copied in here, which made the skill as long as the packs were. They reach
    the agent through `research_brief`, per subject.
    """
    lines = []
    for pack in packs[:_MAX_PACKS]:
        held = _holdings(conn, pack["pack_id"])
        # A snapshot: the counts move with every accepted finding.
        counts = snapshot(
            f"{held['subjects']} subjects, {held['claims']} claims,"
            f" {held['gaps']} with none.\n"
        ).rstrip("\n")
        name = pack["name"][:_MAX_LABEL]
        lines.append(f"- {name} (`{pack['pack_id']}` {pack['version']}): {counts}")
    if len(packs) > _MAX_PACKS:
        lines.append(
            f"- and {len(packs) - _MAX_PACKS} more; `research_agenda` names them."
        )
    return "\n".join(lines) + "\n"


_AGENDA_HEADER = """
## What to research next

A snapshot from when this file was written. `research_agenda` is the live
answer; if the two disagree, the tool is right.

"""


def _agenda_section(rows: list[dict]) -> str:
    """The top of the agenda as prose, or nothing at all.

    Five rows, not twenty: this is a prompt, and the sixth row teaches an agent
    nothing the fifth did not. `kind` and `why` travel with each one, because a
    row that says only *what* leaves an agent to guess whether it is filling a
    gap or re-reading a page that moved.
    """
    if not rows:
        return ""
    lines = []
    for row in rows[:5]:
        what = str(row.get("label") or row.get("identity") or row.get("subject_id") or "?")
        asked = row.get("asked") or 0
        seen = f", asked about {asked} times" if asked else ""
        why = str(row["why"])[:_MAX_WHY]
        lines.append(f"- **{what[:_MAX_LABEL]}** (`{row['kind']}`{seen}). {why}")
    # A snapshot by its own admission (the header says so), and fenced so the
    # digest agrees: the ranking is computed from the reader's history.
    return snapshot(_AGENDA_HEADER + "\n".join(lines) + "\n")


def render(conn, agenda_rows: list[dict] | None = None) -> str | None:
    """Build the skill from what is installed. Never None any more.

    An empty installation used to get nothing, on the reasoning that there is
    no protocol for a store with no knowledge in it. That was true about
    *researching* and wrong about the reader: "no agents guideline for brand
    new packages" is how they put it, and an agent connected to an empty store
    was told nothing at all when the obvious job was to author the first pack
    (B96). It now gets the authoring half of the skill and nothing else, since
    a research loop with no bar behind it has nothing to hold anything to.

    `agenda_rows` is the caller's, because the agenda needs the interface's own
    database and the analyses log, and this module is handed only the store.
    Omitting them yields a skill with no snapshot: a shorter skill, not a
    different one, since the snapshot is fenced out of the digest.

    Disabled packs are excluded: a reader who turned a pack off has said its
    knowledge should not be used, and researching *into* it would be the same
    surprise from the other direction.
    """
    packs = [
        {"pack_id": row["pack_id"], "name": row["name"], "version": row["version"]}
        for row in conn.execute(
            "SELECT pack_id, name, version FROM packs WHERE enabled = 1"
            " ORDER BY pack_id"
        )
    ]
    if not packs:
        empty = (
            "This installation has no packs. Author the first one with "
            "`draft_pack`, then ask for this skill again."
        )
        return stamped(
            _EMPTY_HEADER.format(name=SKILL_NAME, description=empty) + _AUTHORING
        )

    when = _when(packs)
    loop = "\n".join(
        f"{i}. `{tool}`. Input: {given}. Output: {got}."
        for i, (tool, given, got) in enumerate(STEPS, 1)
    )
    body = _HEADER.format(
        name=SKILL_NAME,
        # Frontmatter is one line; a description that wraps stops being parsed.
        description=" ".join(when.split()),
        when=when,
        loop=loop,
    )
    body += _packs_section(conn, packs)
    body += _agenda_section(agenda_rows or [])
    body += "\n" + _AUTHORING
    # Stamped last, over the finished document, so an updated pack still reads
    # as a changed protocol.
    return stamped(body)
