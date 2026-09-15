"""The *when*, to go with the MCP server's *what*.

Wiring a harness to the MCP server tells an agent which tools exist. It does
not tell it that "the app says nothing is known about this drill" is an
invitation to go and find out, and it does not tell it what this particular
installation considers worth keeping. That is a skill: a short document a
harness loads by description and applies when the description matches.

The document is **assembled from the installed packs**, never written here.
Each pack already ships `research/principle.md` — what is worth surfacing in
its category — and, where it also ships one, `research/skill.md` — how to
resolve a subject's identity before searching for it, since "the make and
model" is a guess and the discriminating attribute is a method. Both arrive
as pack assets the store already carries. A skill built from those states two
different bars and two different identification methods for a car and a
power drill without this module knowing what either is, and it changes when
the pack updates rather than when the binary does. That is the whole reason
it is generated rather than checked in: the protocol versions with the
knowledge.

Everything past the principle is *also* read off the store, for the same
reason and one more: an agent that has to guess a pack's identity keys, its
domain words or its severity words will invent plausible ones, and an invented
domain is a claim nobody can find again. So the skill states them — the keys
that identify a subject, the vocabulary the pack declares, how much it already
holds, where its gaps are, and one worked `submit_findings` call filled in with
a real subject from this very installation. None of that is typed here; a
second category gets its own version of all of it for free.

An installation with no packs gets no skill. There is nothing to research and
nothing to say what would count, and a skill that fires anyway is worse than
none.
"""

from kriko.research import pack_asset

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


def digest(body: str) -> str:
    """A short content hash of a rendered skill, minus its own stamp line."""
    import hashlib

    # Trailing whitespace is normalised as well as the stamp line removed, so
    # `digest(body) == digest(stamped(body))`. Without that the stamp a file
    # carries could never equal the digest of the file it is in, and every copy
    # would report itself stale forever — a staleness check that is always true
    # is the same as not having one.
    stripped = "\n".join(
        line for line in (body or "").splitlines() if STAMP not in line
    ).rstrip()
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

#: How many of a pack's declared words to name before the list stops earning
#: its space. A skill is a prompt: the twentieth domain teaches nothing the
#: fifth did not, and the agent can call `research_brief` for the rest.
_MAX_WORDS = 12

#: The loop, in the order an agent must run it. Stated once, here, because both
#: the skill body and the UI's explanation of the protocol come from it.
STEPS = [
    ("research_agenda", "ask what to research next — ranked by what this"
                        " installation was actually asked about"),
    ("coverage_gaps", "list everything still missing, when the agenda runs dry"),
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

Submit findings with `submit_findings(subject_id, pack_id, findings)`. Each
finding is an object, and these five fields are not optional:

| field | what it is |
|-------|------------|
| `title` | the risk, in one line, specific to this configuration |
| `domain` | one of the pack's declared domain words, listed per pack below |
| `severity` | `high`, `medium` or `low` |
| `quote` | the **exact** sentence from the document, copied character for character |
| `source_url` | where you read it |
| `document_text` | the text you read the quote in |

Optional but worth setting: `component` or `component_hint` (the concrete part
the finding is about), `rationale`, `advice`.

`document_text` is what makes the grounding check possible. Without it there is
nothing to check the quote against, and "trust me" is not an evidence model.

## How a finding gets refused

`submit_findings` returns a per-finding verdict, so you learn immediately which
of your work did not survive. It refuses a finding for one of these reasons,
and each is worth reading as instruction rather than as an error:

- **`no quote` / `document_text missing`** — nothing to ground. Re-read the
  page and copy the sentence.
- **`quote does not appear in the document text`** — the quote was paraphrased,
  tidied, translated, or stitched from two sentences. Copy it verbatim,
  including its punctuation. This is the single most common refusal.
- **the pack's own gate** — grounded, but routine, generic, or true of every
  product in the category. The pack's principle below is the bar; a refusal
  here means the finding cleared evidence and failed *taste*.
- **nothing to anchor it** — no `component`, and neither the title nor the
  rationale names an identifier, a specification, or a usage figure. A risk
  that could belong to any configuration belongs to none.

Findings arrive as drafts. Submitting is not publishing, so a finding you are
unsure of is better filed with its weak source than dropped.

## The operations you can run here

Kriko calls one unit of agent-driven work an **operation**
(`docs/AGENT_OPERATIONS.md`). Naming them matters because the app shows them
back to the reader under these names, live, while they run — what you do here
appears on their Activity screen as it happens, labelled with the door it came
in by.

| Operation | What it is | The tools |
|---|---|---|
| `research` | grow one subject's claims from sources | `research_brief`, `submit_findings` |
| `agenda` | work through what is weakest, in order | `research_agenda`, `coverage_gaps` |
| `author` | write a pack for a category nobody has modelled | `draft_pack`, `write_draft_file`, `build_draft` |
| `author` (amend) | add to a draft that is nearly right | `amend_draft` |
| `recheck` | ask whether a cited page still says it | the reader's **Verify** button |
| `lookup` | answer about one product | `lookup`, `get_subject` |

Two of these are worth knowing about even though you do not call them:

* **Verify** re-reads the pages behind stored claims and records `quoted`,
  `missing`, `unreadable` or `unreachable`. It is mechanical, free, and
  retracts nothing — so a `missing` verdict is a signal to research the subject
  again, not evidence the claim was wrong.
* **Sites.** The reader's browser extension can only read a listing page a site
  *adapter* covers. When they open one nothing covers, it lands on their Sites
  screen and an agent is asked to write the adapter. If you are ever handed
  that job: the identity keys are the pack's, not yours to invent.

## Finish the subject

The failure this installation actually sees is not a wrong finding. It is a run
that **stops early and says nothing about stopping**: three findings filed for a
subject with eleven known problems, or four products covered in a category with
twenty. Nothing errors, the reader is told "done", and the gap is invisible
because an absence looks identical to a subject with nothing wrong with it.

So, per subject:

* **Run the brief's searches, not one of them.** The brief hands you seeds in
  the pack's own language and expects you to adapt them. A single query
  answered is a sample, not research.
* **Two independent sources beat one good one.** A claim only one page makes is
  worth filing and worth saying so — `stance` and a second source are what turn
  "somebody said" into evidence.
* **Report what you could not establish.** `submit_findings` takes `queries`;
  use the run's last message to say plainly which searches returned nothing and
  what you would need to go further. A gap somebody wrote down gets filled; one
  that is only implied by an absence does not.
* **Do not stop at the first page that agrees with you.** The pack's principle
  is a bar, not a target — clearing it three times when ten would clear it is
  the same run costing the reader ten times over.
* **A subject with nothing wrong with it is a finding too.** Say so in the run
  rather than leaving silence: an absence and an unresearched subject look
  identical afterwards, and only one of them is finished.

### If the pack ships a gold set

`research/gold.yaml` is a pack's own ground truth — what a competent run should
find, and what it must never claim. It exists to score *benchmarks*, and it is
not a checklist to copy from: a finding submitted because it appears there,
rather than because you read it on a page, is a fabrication with a quote
attached and the grounding check is the only thing standing between it and the
reader. Research the subject; the gold set will agree with you or it will not.

And across subjects: when you were asked to research *a category* rather than
one thing, `coverage_gaps` is the list to work through, and finishing it is the
job. Working three of its rows and reporting success is the behaviour this
paragraph exists to name.

## What is installed here
"""


_AUTHORING = """\
## Authoring a pack

A category Kriko does not model yet has no principle, no vocabulary and no
searches, so there is nothing to research *into*. Write the pack first. You can:

- `draft_pack(pack_id, name, identity)` — start a draft. `identity` is the
  consequential argument: it maps each subject kind to the attribute keys that
  make one of them distinct. Too few and unrelated things collide into one
  subject; too many and one real thing splits across subjects that never see
  each other's claims. Neither failure raises.
- `write_draft_file(draft, path, text)` — fill it in. Data files only; a pack
  an agent wrote may not contain code. The two that matter most are
  `research/principle.md`, which is quoted verbatim into every future brief and
  is this category's own bar, and `research/templates.yaml`, the seed searches
  — whose language `pack.toml` must declare in `[pack] languages`.
- `build_draft(draft)` — find out whether the rows load. A build that fails
  names the row that broke it.
- `list_pack_drafts()` — what is already drafted here.

- `amend_draft(draft, note)` — **add to a draft that is nearly right.** The
  correction verb: the reader says "it has nineteen products and lacks the
  twentieth", and this asks for the twentieth without touching the nineteen.
  Nothing existing is rewritten and a refused amendment leaves the draft
  exactly as it was, so this is the tool to reach for rather than authoring the
  category again — re-authoring re-spends the whole run and can come back
  worse.

### Cover the category, not a corner of it

Before writing claims, **enumerate the line-up**: every product in the category
a buyer could plausibly be looking at, current and recently resold. That list
goes in the draft as `lineup`, and Kriko subtracts the subjects you actually
wrote to record what is still uncovered.

A pack covering three of twenty is worse than useless — it is *confidently*
incomplete: the reader who looks up the fourth gets "nothing known" and
concludes there is nothing to know. Naming is cheap and research is expensive,
so name everything and cover what you can; the remainder is written down as a
gap and `amend_draft` fills it later.

Two rules that are enforced rather than requested, so getting them wrong costs
you the run:

* **Stay inside the category.** Every subject must be an instance of the thing
  you were asked about. A neighbouring product from the same brand goes under
  `coverage.out_of_scope`, not into `subjects`.
* **The pack's `name` is a name**, at most six words, and never "common
  problems" / "issues" / "known faults" — every pack here is about those.

Installing is the reader's press, on the Knowledge screen. Draft it, build it,
tell them what it covers and what it deliberately leaves out; do not install it
for them.

"""


_EMPTY_HEADER = """\
---
name: {name}
description: {description}
---

# Authoring for an empty Kriko installation

Kriko answers "what is known to go wrong with *this specific one*" from
installed knowledge packs. **This installation has none.** So the loop this
skill normally carries — ask the agenda, read the brief, submit findings — has
nothing to run against yet, and your job is the one before it: write the pack that says what this
category is, what counts as worth surfacing in it, and what to search for.

Ask the reader what they want covered, then use the authoring tools below. Once
a pack is installed, ask for this skill again: it is rebuilt from what is
installed, and it will then carry that pack's own principle, vocabulary and
research loop.

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


def _words(conn, pack_id: str, role: str) -> list[str]:
    """A pack's declared vocabulary for one role, in its own order."""
    return [
        row["term_id"]
        for row in conn.execute(
            "SELECT term_id FROM terms WHERE pack_id = ? AND role = ?"
            " ORDER BY term_id",
            (pack_id, role),
        )
    ]


def _listed(words: list[str]) -> str:
    """Render a vocabulary, saying so when it was cut rather than pretending."""
    if not words:
        return "_none declared_"
    shown = ", ".join(f"`{w}`" for w in words[:_MAX_WORDS])
    if len(words) > _MAX_WORDS:
        shown += f", and {len(words) - _MAX_WORDS} more (`research_brief` lists them)"
    return shown


def _identity_keys(conn, pack_id: str) -> dict[str, list[str]]:
    """Which attributes select a subject, per subject kind.

    Read off the rows rather than off the manifest: the manifest states the
    author's intent, the rows are what lookup actually matches on, and a skill
    that describes the intent would send an agent looking for a key no subject
    carries.
    """
    keys: dict[str, list[str]] = {}
    for row in conn.execute(
        "SELECT DISTINCT s.kind, a.key FROM attributes a"
        " JOIN subjects s ON s.subject_id = a.subject_id AND s.pack_id = a.pack_id"
        " WHERE a.pack_id = ? AND a.is_identity = 1 ORDER BY s.kind, a.key",
        (pack_id,),
    ):
        keys.setdefault(row["kind"], []).append(row["key"])
    return keys


def _holdings(conn, pack_id: str) -> dict:
    """How much this pack knows, and how much it admits it does not.

    The gap count is the number that turns a skill into a task list, so it is
    stated even when it is zero — "nothing is missing" is also an answer.
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


def _example(conn, pack_id: str) -> dict | None:
    """A real subject from this installation, preferring one with a gap.

    A worked example with a made-up id teaches an agent to make up ids. This
    one can be pasted into `research_brief` and will work, and if there is a
    gap it is a subject actually worth researching — the example doubles as
    the first task.
    """
    row = conn.execute(
        "SELECT s.subject_id, s.label, s.kind,"
        "       EXISTS (SELECT 1 FROM claims c WHERE c.subject_id = s.subject_id"
        "               AND c.pack_id = s.pack_id) AS has_claims"
        " FROM subjects s WHERE s.pack_id = ?"
        " ORDER BY has_claims ASC, s.label ASC LIMIT 1",
        (pack_id,),
    ).fetchone()
    if row is None:
        return None
    identity = {
        r["key"]: r["value_text"]
        for r in conn.execute(
            "SELECT key, value_text FROM attributes"
            " WHERE pack_id = ? AND subject_id = ? AND is_identity = 1 ORDER BY key",
            (pack_id, row["subject_id"]),
        )
    }
    return {
        "subject_id": row["subject_id"],
        "label": row["label"],
        "kind": row["kind"],
        "identity": identity,
        "has_claims": bool(row["has_claims"]),
    }


def _pack_section(conn, pack: dict) -> str:
    """One pack, described entirely in its own declared words."""
    pack_id = pack["pack_id"]
    held = _holdings(conn, pack_id)
    out = f"\n### {pack['name']} (`{pack_id}` {pack['version']})\n\n"
    out += (
        f"Holds **{held['subjects']} subject(s)** and **{held['claims']} claim(s)**."
        f" **{held['gaps']}** of those subjects have no claim at all"
        + (" — those are the work.\n" if held["gaps"] else ".\n")
    )

    keys = _identity_keys(conn, pack_id)
    if keys:
        out += "\nWhat identifies a subject here:\n\n"
        for kind, fields in keys.items():
            out += f"- `{kind}` — {', '.join(f'`{f}`' for f in fields)}\n"
        out += (
            "\nThese are the pack's own keys. Do not invent others, and do not"
            " rename them: a finding filed under a key this pack does not"
            " declare is a finding nobody looks up again.\n"
        )

    out += f"\nDomains it accepts: {_listed(_words(conn, pack_id, 'domain'))}\n"
    kinds = _words(conn, pack_id, "subject_kind")
    if kinds:
        out += f"\nSubject kinds: {_listed(kinds)}\n"

    example = _example(conn, pack_id)
    if example:
        out += f"\nA subject that exists right now"
        out += (
            " and has nothing known about it"
            if not example["has_claims"]
            else ""
        )
        out += f" — start here:\n\n```\n"
        out += f"research_brief(subject_id=\"{example['subject_id']}\", pack_id=\"{pack_id}\")\n```\n"
        if example["identity"]:
            out += f"\nIt is `{example['label']}`, identified as "
            out += ", ".join(f"{k}={v!r}" for k, v in example["identity"].items())
            out += ".\n"

    out += f"\n#### What {pack['name']} considers worth keeping\n\n"
    out += (pack["principle"] or "_This pack ships no principle._") + "\n"

    if pack["skill"]:
        out += f"\n#### How to identify a {pack['name']} subject before searching\n\n"
        out += pack["skill"] + "\n"
    return out


_AGENDA_HEADER = """
## What to research next

This ordering was current when this file was written, and this file lives on
your disk while the installation changes underneath it. **`research_agenda` is
the live answer; if the two disagree, the tool is right.** The snapshot is here
so a first session has somewhere to start without a round trip, not as a
substitute for asking.

"""


def _agenda_section(rows: list[dict]) -> str:
    """The top of the agenda as prose, or nothing at all.

    Five rows, not twenty: this is a prompt, and the sixth row teaches an agent
    nothing the fifth did not — the same reason `_MAX_WORDS` caps the
    vocabulary lists. `kind` and `why` travel with each one, because a row that
    says only *what* leaves an agent to guess whether it is filling a gap or
    re-reading a page that moved.
    """
    if not rows:
        return ""
    lines = []
    for row in rows[:5]:
        what = row.get("label") or row.get("identity") or row.get("subject_id") or "?"
        asked = row.get("asked") or 0
        seen = f" — asked about {asked}×" if asked else ""
        lines.append(f"- **{what}** (`{row['kind']}`){seen}. {row['why']}")
    return _AGENDA_HEADER + "\n".join(lines) + "\n"


def render(conn, agenda_rows: list[dict] | None = None) -> str | None:
    """Build the skill from what is installed. Never None any more.

    An empty installation used to get nothing, on the reasoning that there is
    no protocol for a store with no knowledge in it. That was true about
    *researching* and wrong about the reader: "no agents guideline for brand
    new packages" is how they put it, and an agent connected to an empty Kriko
    was told nothing at all when the obvious job was to author the first pack
    (B96). It now gets the authoring half of the skill and nothing else, since
    a research loop with no principle behind it has no bar to hold anything to.

    `agenda_rows` is the caller's, because the agenda needs the interface's own
    database and the analyses log, and this module is handed only the store.
    Omitting them yields a skill with no snapshot — which is the right answer
    for a caller that has no business reading a reader's history.

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
            "skill": pack_asset(conn, row["pack_id"], "research/skill.md").strip(),
        }
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
        f"{i}. **`{tool}`** — {why}" for i, (tool, why) in enumerate(STEPS, 1)
    )
    body = _HEADER.format(
        name=SKILL_NAME,
        # Frontmatter is one line; a description that wraps stops being parsed.
        description=" ".join(when.split()),
        when=when,
        loop=loop,
    )
    body += _agenda_section(agenda_rows or [])
    # After the loop and before the packs: an agent holding a full store still
    # needs this the moment the reader names a category nobody has modelled.
    body += _AUTHORING
    for pack in packs:
        body += _pack_section(conn, pack)
    # Stamped last, over the finished document: the digest has to cover the
    # packs' own sections too, or an updated pack would leave a skill that
    # reports itself current while describing knowledge that has moved.
    return stamped(body)
