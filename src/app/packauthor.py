"""A whole pack, from a category named in plain words, in one press.

B96 gave an agent a write surface (`app/packdraft.py`) and gave the reader a
list of what it wrote. What it did not give either of them was a *door*: the
only button in the app that started a pack was `POST /api/packs/scaffold`, and
it asked for a directory, a pack id, a name and an identity table typed as
`kind: key, key`. The reader's verdict, for the third time:

    package bulding still expects user raw input to create which i said many
    times, its gotta be automated with agents man

They are right, and the identity table is the part that proves it. Deciding
which keys make two things the same thing is the most consequential line in a
`pack.toml` — too few and unrelated rows collide into one subject, too many and
one real thing splits across subjects that never see each other's claims, and
*neither failure raises*. Asking a reader to type that before they have seen a
single row of the category is asking them to make the one decision they are
least equipped to make. An agent that has just read a dozen forum threads about
espresso machines is.

So this module is the other end of B96's boundary. One string in — "cordless
drills", "espresso machines", "e-bikes" — and out comes a draft the reader can
read and install with one press.

**Nothing here widens the agent's reach.** The authoring run is the research
plane's spawn, unchanged: the same allowlist, the same neutral working
directory, and no `--mcp-config` at all. The agent gets no tools that touch the
disk; it prints one JSON object and Kriko writes the files, through
`app/packdraft.py`, which is what enforces the directory, the fixed set of
names, the data-only rule and the size caps. An authored pack is therefore
*data an agent proposed*, never code it ran — and it is still not installed
until the reader presses Install on a screen that lists the files.

The division of labour is the whole point:

* **The agent decides taste** — the identity keys, the bar for a claim, the
  searches, the vocabulary. Every one of those is category knowledge, which is
  exactly what `docs/PACK_CONTRACT.md` says belongs in pack data.
* **Kriko decides shape** — the file layout, the YAML, the refusals. An agent
  that gets a key wrong should produce a draft that fails to build with a
  reason, not a directory nobody can name.
"""

import json
import re
from pathlib import Path

import yaml

from app import packdraft

__all__ = ["brief", "CONTRACT", "author", "PackRefused",
           "amend", "amend_brief", "draft_state"]

#: Deliberately the same order of magnitude as a research reply. A pack that
#: needs more rows than this is a pack an agent should be growing with
#: `submit_findings` afterwards, not inventing in one breath.
MAX_SUBJECTS = 40
MAX_CLAIMS = 80
MAX_TEMPLATES = 12

#: The most products a line-up may name. Generous: a category with more than
#: this has sub-categories, and a pack that tried to be all of them would have
#: identity keys that mean nothing.
MAX_LINEUP = 200

#: Words that make a pack *name* a description instead. Every pack here is
#: about problems with things, so these distinguish nothing and cost the reader
#: a line of a list. A closed vocabulary of filler, not category data.
NAME_FILLER = (
    "common problems", "common issues", "known issues", "known faults",
    "problems and", "issues and", "faults and", "reliability guide",
    "buyer's guide", "buying guide", "what goes wrong",
)

#: And the length past which a name is a sentence. Six words is "Samsung
#: Galaxy Buds wireless earbuds"; seven is somebody explaining.
MAX_NAME_WORDS = 6

_ID = re.compile(r"[^a-z0-9_.-]+")


class PackRefused(ValueError):
    """The agent's proposal was not a pack. Carries what was wrong with it."""


def brief(category: str) -> str:
    """What to tell an agent that has never seen this repository.

    Written as a specification of the decisions rather than of the files,
    because the files are `kriko.pack.scaffold`'s job and the decisions are the
    only part an agent can get uniquely right. The two hardest are named
    explicitly and given their failure modes — an instruction that says "choose
    identity keys" without saying what a wrong choice does silently is an
    instruction that will be obeyed carelessly.
    """
    return f"""# Author a Kriko knowledge pack: {category}

Kriko answers one question about a manufactured thing: *what is known to go
wrong with **this specific one***. It knows nothing about any category — every
category arrives as a **pack**, which is data. You are writing that data for:

    {category}

Research the category first. Read what owners, forums, service bulletins and
repair shops actually say about these things, in the languages the people who
buy them use. Then make the decisions below from what you read, not from what
sounds reasonable.

## Decision 1 — identity keys (the consequential one)

`identity` says what makes two of these **the same thing**, per kind of thing.
It is hashed to a subject id, so:

* **Too few keys** and unrelated things collide into one subject — a claim
  about one model's gearbox lands on every model of the brand.
* **Too many** and one real thing splits across subjects that never see each
  other's claims, so nothing ever accumulates evidence.

Neither failure raises an error. Both are silent and permanent. Choose the
smallest set that a person shopping for one of these would use to say "no, I
mean *that* one".

You may declare more than one kind. A pack about power tools might have a
product, the battery platform it runs on, and a component several products
share.

## Decision 2 — the bar for a claim

What is worth telling a reader about one of these, and what is not. The useful
bar names both halves: what a reader cannot cheaply find out for themselves and
which would change their decision, and what is true of everything in the
category or which any routine inspection already answers.

This is **your** category's bar, not Kriko's. Write it about {category}
specifically, in the terms that category uses.

## Decision 3 — what to search for

Query templates, one per line, in the words people actually type — including
the language they type them in, if that is not English. `{{label}}` is the
subject's own name and any identity key you declared may be used by name.

Write phrases somebody has typed. A template that renders a catalog identifier
("1.5_TSI", a power rating) produces a query that runs and finds nothing.

## Decision 4 — the line-up, all of it

**First enumerate, then research.** Before you write a single claim, list every
distinct product in this category that a buyer could plausibly be looking at:
current models and the recent ones still being resold. That list is `lineup`,
and it is part of what you print.

A pack covering three of twenty is worse than useless — it is *confidently*
incomplete: a reader who looks up the fourth gets "nothing known" and concludes
there is nothing to know. So:

* **`lineup` is everything you can name.** If the category has forty products,
  name forty. Naming is cheap; it is the research that is expensive, and the
  list is what makes the remaining work visible instead of invisible.
* **`subjects` is everything you actually cover.** Aim to cover the whole
  line-up. Where you cannot — you ran out of sources, or the evidence is too
  thin — leave the subject out and the difference is computed for you.
* **What you left out is reported, not hidden.** Kriko subtracts `subjects`
  from `lineup` and writes the remainder into the pack as an open gap, with
  your `coverage.note` beside it. A gap that is written down gets filled by
  the next run; a gap nobody recorded is a hole in the knowledge forever.

**Stay inside the category.** Every subject must be an instance of the thing
you were asked about. If a neighbouring product keeps appearing in your sources
— an accessory, a different device from the same brand — name it under
`out_of_scope` instead of adding it. A pack about headphones containing a watch
is not a generous pack, it is a pack whose identity keys no longer mean
anything.

## Decision 5 — the claims themselves

A claim needs a `title`, a `body` in the words a reader would recognise the
problem by, and `advice` — what to do about it before deciding. Severity is
`high`, `medium` or `low`.

**Never invent a claim.** A pack that ships a plausible-looking guess outlives
you in somebody's store. If you found nothing solid for a subject, ship the
subject with no claims; coverage gaps are a first-class thing here and the
research plane fills them later.

## The name

`name` is a **name**, not a description: what somebody would call this pack in
a list of packs. "Samsung earbuds" or "Galaxy Buds" — not "Samsung Galaxy Buds
and wireless headphones common problems", which is a sentence about a pack
rather than a name for one. Six words at most, and no "common problems",
"issues", "known faults": every pack here is about those, so the words
distinguish nothing.

{CONTRACT}
"""


CONTRACT = """## How to report the pack (this run)

You have no Kriko tools in this session. Do not attempt to call any; there is
nothing to call. Print the pack as **one JSON object** as the last thing you
say, in a ```json fence. Kriko writes the files — you are proposing data, and
nothing you print is executed.

```json
{"pack_id": "lowercase.dotted.id",
 "name": "Two or three words, a name and not a sentence",
 "lineup": ["Every product in this category you can name, covered or not"],
 "coverage": {"note": "why anything in lineup has no subject, in one or two sentences",
              "out_of_scope": ["things that kept appearing and are not this category"]},
 "languages": ["en"],
 "markets": ["EU"],
 "identity": {"product": ["brand", "series"], "platform": ["brand", "family"]},
 "principle": "markdown: what this pack surfaces, and what it does not",
 "templates": ["{label} common problems", "{label} {brand} reliability forum"],
 "domains": [{"id": "mechanical", "label": "Mechanical"}],
 "attributes": [{"id": "voltage_v", "label": "Voltage", "datatype": "number"}],
 "subjects": [
   {"kind": "product", "label": "Makita DHP484",
    "identity": {"brand": "makita", "series": "DHP484"},
    "aliases": ["DHP484Z"],
    "attributes": {"voltage_v": 18}}
 ],
 "claims": [
   {"subject": {"kind": "product",
                "identity": {"brand": "makita", "series": "DHP484"}},
    "domain": "mechanical", "severity": "medium",
    "title": "...", "body": "...", "advice": "..."}
 ],
 "notes": "what you read, and what you could not establish"}
```

Rules the writer enforces, so getting them wrong costs you the run:

* Every `domain` a claim names must be in `domains`. Every key in a subject's
  `identity` must be one this pack declared for that kind. Every key in
  `attributes` must be in the `attributes` list.
* A claim's `subject` repeats the identity rather than naming a label, because
  a label is not stable and an identity is.
* `identity` values are the normalised form — lowercase, no spaces where the
  category writes none. The `label` is what a person reads.
* Nothing you print may be Python, a path, or a file name. A pack an agent
  wrote is data; that is the boundary that lets it be written at all.
* `lineup` must be there, and it must be longer than a token gesture. A pack
  that claims a category has three products in it when it has twenty is
  refused: under-claiming the line-up is how an incomplete pack passes for a
  complete one, and it is the one error here that nothing downstream can
  detect.
* `name` is refused if it reads as a description — over six words, or carrying
  "common problems", "issues", "faults", "guide".

Print the whole object in one fence. If you are running out of room, cut
*claims* rather than the line-up: a named subject with no claims is an honest
gap that the research plane fills later, and a missing name is a hole nobody
knows about.
"""


def _clean_id(value, *, what: str) -> str:
    text = str(value or "").strip().lower().replace(" ", "_")
    text = _ID.sub("", text)
    if not text:
        raise PackRefused(f"the {what} is missing or has no usable characters")
    return text


def _text(value) -> str:
    return str(value or "").strip()


def _identity_table(raw) -> dict[str, list[str]]:
    """The one decision this module refuses to guess at on the agent's behalf.

    An empty or unusable table is a refusal rather than a default, because a
    default identity table is this module having an opinion about what things
    are like — the exact thing `kriko.pack.scaffold` is built not to do.
    """
    if not isinstance(raw, dict) or not raw:
        raise PackRefused(
            "no `identity` table. A pack that does not say what makes two of "
            "its subjects the same thing cannot store a second row"
        )
    table: dict[str, list[str]] = {}
    for kind, keys in raw.items():
        kind_id = _clean_id(kind, what="subject kind")
        if isinstance(keys, str):
            keys = [part for part in re.split(r"[,\s]+", keys) if part]
        cleaned = [
            _clean_id(key, what="identity key")
            for key in (keys or [])
            if _text(key)
        ]
        if cleaned:
            table[kind_id] = list(dict.fromkeys(cleaned))
    if not table:
        raise PackRefused(
            "every kind in `identity` came back with no keys — without them "
            "every subject of a kind hashes to the same id"
        )
    return table


def _terms(table: dict[str, list[str]], payload: dict) -> str:
    """The vocabulary file: every kind, key, domain and attribute, declared.

    Built from the identity table plus whatever the agent added, and the union
    matters — the builder refuses a row naming a term that is not here, so a
    domain the agent used in a claim and forgot to declare would otherwise fail
    the build with an error about the claim rather than the vocabulary.
    """
    domains: dict[str, str] = {}
    for entry in payload.get("domains") or []:
        if isinstance(entry, dict):
            term = _clean_id(entry.get("id") or entry.get("term_id"),
                             what="domain id")
            domains[term] = _text(entry.get("label")) or term
        elif _text(entry):
            term = _clean_id(entry, what="domain id")
            domains[term] = term
    for claim in payload.get("claims") or []:
        if isinstance(claim, dict) and _text(claim.get("domain")):
            term = _clean_id(claim["domain"], what="domain id")
            domains.setdefault(term, term)
    domains.setdefault("general", "General")

    attributes: dict[str, dict] = {}
    for key in sorted({key for keys in table.values() for key in keys}):
        attributes[key] = {"label": key, "datatype": "text"}
    for entry in payload.get("attributes") or []:
        if not isinstance(entry, dict):
            continue
        key = _clean_id(entry.get("id") or entry.get("term_id"),
                        what="attribute id")
        datatype = _text(entry.get("datatype")).lower()
        attributes[key] = {
            "label": _text(entry.get("label")) or key,
            "datatype": datatype if datatype in {"text", "number"} else "text",
        }

    rows = [
        {"term_id": kind, "role": "subject_kind", "label": {"en": kind}}
        for kind in table
    ]
    rows += [
        {"term_id": key, "role": "attribute", "datatype": spec["datatype"],
         "label": {"en": spec["label"]}}
        for key, spec in attributes.items()
    ]
    rows += [
        {"term_id": term, "role": "domain", "label": {"en": label}}
        for term, label in domains.items()
    ]
    header = (
        "# Vocabulary — every kind, key, domain and attribute this pack uses.\n"
        "#\n"
        "# Written from the pack an agent proposed. Declared before use: the\n"
        "# builder refuses a row naming a term that is not here, which is also\n"
        "# why a domain used by a claim and never declared is added above.\n"
    )
    return header + yaml.safe_dump(rows, allow_unicode=True, sort_keys=False)


def _subjects(table: dict[str, list[str]], payload: dict) -> tuple[str, dict]:
    """The subjects file, and the identities the claims file may point at."""
    default_kind = next(iter(table))
    rows, known = [], {}
    for entry in (payload.get("subjects") or [])[:MAX_SUBJECTS]:
        if not isinstance(entry, dict):
            continue
        kind = _clean_id(entry.get("kind") or default_kind, what="subject kind")
        if kind not in table:
            raise PackRefused(
                f"subject of kind {kind!r}, which `identity` never declared"
            )
        identity = {
            _clean_id(key, what="identity key"): _text(value)
            for key, value in (entry.get("identity") or {}).items()
            if _text(value)
        }
        missing = [key for key in table[kind] if key not in identity]
        if missing:
            raise PackRefused(
                f"subject {entry.get('label')!r} is missing identity key(s) "
                f"{', '.join(missing)} — a missing key hashes to a different "
                f"thing rather than failing"
            )
        row = {
            "kind": kind,
            "label": _text(entry.get("label")) or "/".join(identity.values()),
            "identity": {key: identity[key] for key in table[kind]},
        }
        extra = {
            key: value
            for key, value in (entry.get("attributes") or {}).items()
            if _text(key) and _text(value)
        }
        if extra:
            row["attributes"] = extra
        aliases = [_text(alias) for alias in (entry.get("aliases") or [])]
        if any(aliases):
            row["aliases"] = [alias for alias in aliases if alias]
        rows.append(row)
        known[(kind, tuple(sorted(row["identity"].items())))] = row["label"]

    if not rows:
        raise PackRefused(
            "no subjects. A pack with nothing in it installs and answers "
            "nothing, which is indistinguishable from a broken one"
        )
    header = (
        "# Subjects — the things this pack knows about.\n"
        "#\n"
        "# `identity` carries exactly the keys `pack.toml` declares for the\n"
        "# kind: that dictionary is hashed to the subject id.\n"
    )
    return header + yaml.safe_dump(rows, allow_unicode=True, sort_keys=False), known


def _claims(table: dict[str, list[str]], payload: dict, known: dict) -> str:
    """The claims file. A claim about a subject nobody declared is dropped.

    Dropped rather than refused: an agent that researched eight things and
    wrote seven subjects has produced a usable pack with one loose claim, and
    failing the whole draft for it would throw away the work. The count reaches
    the reader through the draft's own file list.
    """
    default_kind = next(iter(table))
    rows = []
    for entry in (payload.get("claims") or [])[:MAX_CLAIMS]:
        if not isinstance(entry, dict):
            continue
        raw_subject = entry.get("subject")
        subject: dict = raw_subject if isinstance(raw_subject, dict) else {}
        kind = _clean_id(subject.get("kind") or default_kind, what="subject kind")
        if kind not in table:
            continue
        identity = {
            _clean_id(key, what="identity key"): _text(value)
            for key, value in (subject.get("identity") or {}).items()
            if _text(value)
        }
        if any(key not in identity for key in table[kind]):
            continue
        identity = {key: identity[key] for key in table[kind]}
        if (kind, tuple(sorted(identity.items()))) not in known:
            continue
        title = _text(entry.get("title"))
        if not title:
            continue
        severity = _text(entry.get("severity")).lower()
        rows.append({
            "subject": {"kind": kind, "identity": identity},
            "kind": _clean_id(entry.get("kind") or "known_issue",
                              what="claim kind"),
            "domain": _clean_id(entry.get("domain") or "general",
                                what="domain id"),
            "severity": severity if severity in {"high", "medium", "low"} else "medium",
            "detection": "reported",
            "confidence": 0.5,
            "text": {"en": {
                "title": title,
                "body": _text(entry.get("body")),
                "advice": _text(entry.get("advice")),
            }},
        })
    header = (
        "# Claims — what is known to go wrong, and what to do about it.\n"
        "#\n"
        "# Proposed by an agent and not yet evidenced: every row is\n"
        "# `confidence: 0.5` and `detection: reported`, and a research run\n"
        "# through the normal acceptance path is what attaches sources.\n"
    )
    return header + yaml.safe_dump(rows or [], allow_unicode=True, sort_keys=False)


def _pack_toml(payload: dict, pack_id: str, name: str, table: dict) -> str:
    """`pack.toml` with the agent's languages and markets filled in.

    Rewritten rather than patched: `kriko.pack.scaffold` writes `languages =
    ["en"]` with a comment telling the author to change it, and an authored
    pack whose queries are Turkish and whose manifest claims English is the
    defect a reader already reported once as "turkish-english queries".
    """
    languages = [
        _clean_id(lang, what="language code")
        for lang in (payload.get("languages") or ["en"])
        if _text(lang)
    ] or ["en"]
    markets = [_text(market) for market in (payload.get("markets") or []) if _text(market)]
    kinds = "\n".join(
        f"{kind} = [" + ", ".join(f'"{key}"' for key in keys) + "]"
        for kind, keys in table.items()
    )
    return f"""[pack]
id = "{pack_id}"
name = "{name}"
version = "0.1.0"

# Declared by the agent that authored this pack, from the sources it read. The
# languages are the ones this pack's own text and queries are written in,
# primary first; the markets are the ones its claims are about.
languages = [{", ".join(f'"{lang}"' for lang in languages)}]
markets = [{", ".join(f'"{market}"' for market in markets)}]

# What makes a subject distinct, per kind — the most consequential declaration
# in this file. Too few keys and unrelated things collide into one subject; too
# many and one real thing splits across subjects that never see each other's
# claims. Neither failure raises.
[identity]
{kinds}
"""


def _pack_name(payload: dict, category: str, pack_id: str) -> str:
    """A name, and refused when it is a description.

    The reader's pack came back called "Samsung Galaxy Buds and wireless
    headphones common problems", which is a sentence about a pack rather than a
    name for one — and in a list of packs it is the line nobody can scan. Every
    pack here is about what goes wrong with things, so "common problems"
    distinguishes nothing while costing the whole width of the row.

    Refused rather than rewritten. Trimming it here would produce a name the
    agent did not choose and cannot be told about; refusing produces a run
    that says exactly what to do differently, which is the only feedback this
    loop has.
    """
    name = _text(payload.get("name")) or category or pack_id
    low = name.lower()
    for filler in NAME_FILLER:
        if filler in low:
            raise PackRefused(
                f"the pack name {name!r} contains {filler!r}. Every pack here "
                "is about what goes wrong with something, so that phrase "
                "distinguishes nothing — name the things, not the topic"
            )
    if len(name.split()) > MAX_NAME_WORDS:
        raise PackRefused(
            f"the pack name {name!r} is {len(name.split())} words. A name is "
            f"what somebody calls this in a list of packs — {MAX_NAME_WORDS} "
            "words at most. The description belongs in `principle`"
        )
    return name


def _coverage(payload: dict, known: dict) -> dict:
    """The line-up, and what of it this draft does not cover.

    **This is the answer to "the agent wrote three of twenty and said
    nothing".** An author that stops early is not doing anything wrong on its
    own terms — it found what it found — but a pack covering a fraction of a
    category is *confidently* incomplete: the reader who looks up the fourth
    product gets "nothing known" and concludes there is nothing to know.

    So the line-up is data. The agent names everything it can (naming is cheap;
    research is what is expensive), Kriko subtracts what it actually covered,
    and the remainder is written into the draft as an open gap. `pack_amend`
    reads exactly this file to know what to ask for next.

    Matching is by normalised text rather than by identity, because the line-up
    is a list of names a person would recognise and the subjects are rows with
    identity keys. An approximate match here costs a gap being reported as
    covered; requiring identities would cost the agent the ability to name
    something it did not research, which is the whole point.
    """
    raw = payload.get("lineup")
    lineup = [_text(one) for one in (raw or []) if _text(one)][:MAX_LINEUP]
    covered = {_flat(label) for label in known.values()} | {
        _flat(one) for one in known
    }
    uncovered = [one for one in lineup if _flat(one) not in covered and not any(
        _flat(one) in seen or seen in _flat(one) for seen in covered if seen
    )]
    block = payload.get("coverage")
    block = block if isinstance(block, dict) else {}
    return {
        "lineup": lineup,
        "covered": sorted(covered - {""}),
        "uncovered": uncovered,
        "note": _text(block.get("note")) or _text(payload.get("notes")),
        "out_of_scope": [
            _text(one) for one in (block.get("out_of_scope") or []) if _text(one)
        ],
    }


def _flat(value) -> str:
    """Lowercase, punctuation-free, for comparing a name with a name."""
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def author(store_path, reply: str, *, category: str = "") -> dict:
    """Turn what the agent printed into a draft. Returns what was written.

    Every write goes through `app/packdraft.py`, which is where the boundary
    is: the directory is derived from the pack id rather than accepted, each
    name is checked against a fixed list, and nothing may be executed by
    installing it. This function's job is only to decide whether the JSON is a
    pack, and to say what was wrong when it is not.
    """
    payload = _payload(reply)
    if not payload:
        raise PackRefused(
            "the agent printed no JSON object. Nothing was written — the run's "
            "log holds what it did say"
        )
    pack_id = _clean_id(payload.get("pack_id") or payload.get("id"),
                        what="pack id")
    name = _pack_name(payload, category, pack_id)
    table = _identity_table(payload.get("identity"))

    templates = [
        _text(line) for line in (payload.get("templates") or [])[:MAX_TEMPLATES]
    ]
    templates = [line for line in templates if line]
    if not templates:
        raise PackRefused(
            "no query templates. A pack with none renders zero searches, so "
            "its Research button says what to keep and never what to look for"
        )

    principle = _text(payload.get("principle"))
    if not principle:
        raise PackRefused(
            "no `principle`. The bar for a claim is the one thing the engine "
            "will not supply — it ranks, it does not decide taste"
        )

    subjects, known = _subjects(table, payload)
    claims = _claims(table, payload, known)
    gaps = _coverage(payload, known)

    draft = packdraft.create(
        store_path, pack_id=pack_id, name=name, identity=table)
    written = [
        packdraft.write(store_path, slug=draft.slug, path="pack.toml",
                        text=_pack_toml(payload, pack_id, name, table)),
        packdraft.write(store_path, slug=draft.slug,
                        path="research/principle.md",
                        text=principle if principle.startswith("#")
                        else f"# What this pack surfaces\n\n{principle}\n"),
        packdraft.write(
            store_path, slug=draft.slug, path="research/templates.yaml",
            text="# Search templates for this pack. One query per line.\n#\n"
                 "# Written by the agent that authored the pack, in the words\n"
                 "# and the language its sources use.\n"
                 + yaml.safe_dump(templates, allow_unicode=True,
                                  sort_keys=False, default_flow_style=False)),
        packdraft.write(store_path, slug=draft.slug,
                        path="vocabulary/terms.yaml",
                        text=_terms(table, payload)),
        packdraft.write(store_path, slug=draft.slug, path="data/subjects.yaml",
                        text=subjects),
        packdraft.write(store_path, slug=draft.slug, path="data/claims.yaml",
                        text=claims),
        packdraft.write(store_path, slug=draft.slug, path="README.md",
                        text=_readme(name, pack_id, category, payload, table,
                                     gaps)),
        # The line-up, and what of it is not covered, as a file rather than as
        # a sentence in a log. This is the whole answer to "the agent wrote
        # three of twenty and said nothing": the twenty are named, seventeen
        # are marked uncovered, and `pack_amend` reads this file to know what
        # to ask for next. A gap that is written down gets filled.
        packdraft.write(store_path, slug=draft.slug,
                        path="research/coverage.yaml",
                        text=yaml.safe_dump(gaps, allow_unicode=True,
                                            sort_keys=False)),
    ]
    return {
        "slug": draft.slug,
        "pack_id": pack_id,
        "name": name,
        "root": str(draft.root),
        "files": sorted(set(written)),
        "subjects": len(yaml.safe_load(subjects) or []),
        "claims": len(yaml.safe_load(claims) or []),
        "identity": table,
        "notes": _text(payload.get("notes")),
        # Returned as well as written, because the job's last line is where a
        # reader learns the pack is partial — and a partial pack they know
        # about is a next step, while one they do not is a wrong answer
        # waiting.
        "lineup": len(gaps.get("lineup") or []),
        "uncovered": list(gaps.get("uncovered") or []),
        # Stated here rather than by the caller: authoring a pack and putting
        # it in the store are two authorities, and the one that writes the
        # files is the one that should be on record about not installing them.
        "installed": False,
    }


def _readme(name: str, pack_id: str, category: str, payload: dict,
            table: dict, gaps: dict | None = None) -> str:
    kinds = ", ".join(f"`{kind}`" for kind in table)
    notes = _text(payload.get("notes"))
    gaps = gaps or {}
    uncovered = gaps.get("uncovered") or []
    coverage = (
        f"{len(gaps.get('lineup') or [])} named in the category, "
        f"{len(gaps.get('covered') or [])} covered here."
        + (
            "\n\nNot covered yet: " + ", ".join(uncovered[:40])
            + ("…" if len(uncovered) > 40 else "")
            + "\n\nThese are in `research/coverage.yaml`, and **Cover the gaps** "
              "on this draft asks an agent for exactly them."
            if uncovered
            else "\n\nNothing in the line-up is uncovered."
        )
    )
    return f"""# {name}

`{pack_id}` — authored by an agent from the category "{category or name}", and
not yet installed.

It declares {kinds}. Every claim in it is `confidence: 0.5` and
`detection: reported`: an agent proposed it from what it read, and no source
row is attached yet. A research run through the normal acceptance path is what
turns a proposal into evidence.

## What this pack covers

{_text(payload.get("covers")) or f"See the bar in `research/principle.md`."}

## Coverage

{coverage}

## What the author could not establish

{notes or "Nothing recorded."}

## Before installing

Read `data/claims.yaml`. A claim that reads like general advice about the
category rather than about one of these specific things is the failure mode
worth catching here — it is true, and it is noise.
"""


_FENCE = re.compile(r"```(?:json)?\s*(\{.*)?```", re.DOTALL)

_DECODER = json.JSONDecoder()


def _objects(text: str) -> list[dict]:
    """Every JSON object in `text`, in the order it appears.

    `raw_decode` rather than `json.loads`, which is the whole difference
    between this and what it replaces: `loads` demands that the object be the
    *entire* string, so an agent that printed a perfectly good object and then
    said "let me know if you want more" lost the run. Prose either side, two
    objects, an object in a fence and an object beside it all reduce to the
    same list here.
    """
    found: list[dict] = []
    index = (text or "").find("{")
    while index != -1:
        try:
            parsed, end = _DECODER.raw_decode(text, index)
        except ValueError:
            index = text.find("{", index + 1)
            continue
        if isinstance(parsed, dict):
            found.append(parsed)
            index = text.find("{", max(end, index + 1))
        else:
            index = text.find("{", index + 1)
    return found


def _repair(text: str) -> tuple[dict, str]:
    """The longest prefix of a cut-off object that is still an object.

    A run that was killed by a token ceiling prints a complete category read
    and half a closing brace, and throwing all of it away is the most
    expensive possible response to the cheapest possible fault. So the scan
    remembers every point at which the object could legally have ended — after
    a closed container, or before a comma — and closes it there.

    The result is a *partial* pack, and it is never pretended otherwise: the
    note comes back with it and every rule below still has to pass.
    """
    start = (text or "").find("{")
    if start == -1:
        return {}, ""
    chunk = text[start:]
    stack: list[str] = []
    cuts: list[tuple[int, str]] = []
    in_string = escaped = False
    for position, character in enumerate(chunk):
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character in "{[":
            stack.append("}" if character == "{" else "]")
        elif character in "}]":
            if stack:
                stack.pop()
            if stack:
                cuts.append((position + 1, "".join(reversed(stack))))
        elif character == "," and stack:
            cuts.append((position, "".join(reversed(stack))))
    for position, closers in reversed(cuts):
        try:
            parsed = json.loads(chunk[:position] + closers)
        except ValueError:
            continue
        if isinstance(parsed, dict):
            dropped = len(chunk) - position
            return parsed, (
                f"the reply stopped mid-object; {dropped} character(s) after "
                f"the last complete entry were dropped"
            )
    return {}, ""


def read_payload(text: str) -> tuple[dict, str]:
    """The pack object plus a note about how it had to be recovered.

    Order matters. A fenced object is what the contract asked for, so it wins;
    an unfenced one is the same agent being slightly less careful and is worth
    just as much. The *last* object wins among equals, because a model that
    reconsiders prints the correction after the draft — and the repair pass is
    last of all, because a truncated object is a partial answer and a complete
    one is never worth passing over for it.
    """
    text = text or ""
    fenced: list[dict] = []
    for match in _FENCE.findall(text):
        fenced.extend(_objects(match or ""))
    if fenced:
        return fenced[-1], ""
    loose = _objects(text)
    if loose:
        return loose[-1], ""
    return _repair(text)


def _payload(text: str) -> dict:
    return read_payload(text)[0]


# ── amending a draft, rather than authoring it again ─────────────────────────
#
# B127, and the reader's own words: *"this pack seems very solid but it includes
# 19 products and lacks the 20th. I don't want to rebuild the whole thing —
# what about I tell the agent that it lacks some products and it covers those
# gaps."*
#
# Authoring was all-or-nothing: the only way to change a draft was to run the
# whole thing again, which re-spends the run and can come back *worse* — the
# reader's second attempt returned nothing at all. That is not a generosity
# problem, it is a missing verb. A generator you cannot correct is a slot
# machine; a tool you can is worth keeping.


def amend_brief(draft_state: dict, note: str = "") -> str:
    """What to tell an agent holding a draft that is nearly right.

    It is handed what exists — the pack's own principle, its identity keys, the
    subjects it already has, and the line-up entries nothing covers — and asked
    for **additions only**. Everything already in the draft is off limits: a
    rewrite is how "nearly right" becomes "different, and now also wrong
    somewhere else", and the reader asked for the opposite of that.
    """
    uncovered = draft_state.get("uncovered") or []
    covered = draft_state.get("subjects") or []
    identity = draft_state.get("identity") or {}
    keys = "; ".join(
        f"{kind}: {', '.join(names)}" for kind, names in identity.items()
    )
    wanted = note.strip() or (
        "everything under 'Not covered yet' below" if uncovered
        else "whatever the line-up is still missing"
    )
    return f"""# Extend an existing Kriko pack: {draft_state.get('name') or ''}

This pack already exists as a draft. You are **adding to it**, not rewriting
it. Nothing already in it may be changed, renamed or removed — a correction
that arrives as a rewrite is how a nearly-right pack becomes a differently
wrong one.

## What is being asked for

{wanted}

## What the pack already is

* **Pack id**: `{draft_state.get('pack_id') or ''}`
* **Identity keys** (use exactly these; a subject missing one is refused):
  {keys}
* **The bar for a claim** — this pack's own, and your additions must clear it:

{_indent(draft_state.get('principle') or '(none recorded)')}

## Already covered — do not repeat these

{_bullets(covered) or '(nothing yet)'}

## Not covered yet

{_bullets(uncovered) or '(the line-up records no gap; use the request above)'}

## What to do

Research the missing ones the way the pack's own templates would, and add
**subjects** for them, with the claims you actually found evidence for. A
subject you can name but found nothing solid for is still worth adding with no
claims: it is an honest gap the research plane fills later, and it stops the
next reader concluding there is nothing to know.

Never invent a claim. Never add something that is not an instance of this
category — if a neighbouring product keeps appearing, list it under
`coverage.out_of_scope` instead.

{AMEND_CONTRACT}
"""


AMEND_CONTRACT = """## How to report the additions (this run)

Print **one JSON object** as the last thing you say, in a ```json fence. Only
the additions — Kriko merges them into the existing draft, and anything you
repeat is ignored rather than duplicated.

```json
{"subjects": [
   {"kind": "product", "label": "The one that was missing",
    "identity": {"...": "..."}, "aliases": ["..."]}
 ],
 "claims": [
   {"subject": {"kind": "product", "identity": {"...": "..."}},
    "domain": "...", "severity": "medium",
    "title": "...", "body": "...", "advice": "..."}
 ],
 "lineup": ["anything else you can now name that the line-up was missing"],
 "coverage": {"note": "what you still could not cover, and why",
              "out_of_scope": ["..."]},
 "notes": "what you read"}
```

Every `identity` key must be one this pack already declares, and every `domain`
one it already lists — you are adding rows to a table whose columns are fixed.
"""


def _indent(text: str) -> str:
    return "\n".join(f"    {line}" for line in str(text or "").splitlines()[:40])


def _bullets(items) -> str:
    return "\n".join(f"* {one}" for one in list(items or [])[:120])


def draft_state(store_path, slug: str) -> dict:
    """What a draft currently holds, for the amend brief and for the screen.

    Read off the files rather than remembered, because the draft is the record:
    an agent may have written to it through `write_draft_file` since, and a
    brief built from a stale memory would ask for work that is already done.
    """
    draft = packdraft.open_draft(store_path, slug)
    root = draft.root

    def _yaml(relative: str, default):
        path = root / relative
        if not path.exists():
            return default
        try:
            return yaml.safe_load(path.read_text(encoding="utf-8")) or default
        except Exception:  # noqa: BLE001 — a broken file is an empty answer
            return default

    subjects = _yaml("data/subjects.yaml", [])
    claims = _yaml("data/claims.yaml", [])
    coverage = _yaml("research/coverage.yaml", {})
    manifest = {}
    try:
        loaded = packdraft.load(root)
        manifest = {
            "pack_id": loaded.pack_id,
            "name": loaded.name,
            "version": loaded.version,
        }
    except Exception:  # noqa: BLE001 — reported by `listing`, not here
        manifest = {"pack_id": "", "name": slug, "version": ""}

    identity: dict[str, list[str]] = {}
    for row in subjects if isinstance(subjects, list) else []:
        if isinstance(row, dict) and row.get("kind"):
            identity.setdefault(
                str(row["kind"]), sorted((row.get("identity") or {}).keys())
            )
    principle = ""
    principle_path = root / "research" / "principle.md"
    if principle_path.exists():
        principle = principle_path.read_text(encoding="utf-8")

    return {
        **manifest,
        "slug": draft.slug,
        "identity": identity,
        "principle": principle,
        "subjects": [
            str(row.get("label") or "")
            for row in (subjects if isinstance(subjects, list) else [])
            if isinstance(row, dict)
        ],
        "claims": len(claims if isinstance(claims, list) else []),
        "uncovered": list((coverage or {}).get("uncovered") or []),
        "lineup": list((coverage or {}).get("lineup") or []),
    }


def amend(store_path, slug: str, reply: str) -> dict:
    """Merge an agent's additions into an existing draft. Adds, never replaces.

    Deduplicated by identity for subjects and by (subject, title) for claims,
    so an agent that repeats what it was shown costs nothing — which is the
    behaviour to design for, because the brief hands it the existing list and a
    model reading a list will sometimes echo it.

    The whole point is that a *wrong* amendment cannot damage what was already
    right: nothing existing is rewritten, and a refused amendment leaves the
    draft exactly as it was.
    """
    payload = _payload(reply)
    if not payload:
        raise PackRefused(
            "the agent printed no JSON object. The draft is unchanged — the "
            "run's log holds what it did say"
        )
    state = draft_state(store_path, slug)
    draft = packdraft.open_draft(store_path, slug)
    root = draft.root

    def _load(relative, default):
        path = root / relative
        if not path.exists():
            return default
        return yaml.safe_load(path.read_text(encoding="utf-8")) or default

    subjects = _load("data/subjects.yaml", [])
    claims = _load("data/claims.yaml", [])
    coverage = _load("research/coverage.yaml", {})

    table = {kind: list(keys) for kind, keys in (state.get("identity") or {}).items()}
    if not table:
        raise PackRefused(
            "this draft declares no subjects yet, so there is nothing to "
            "extend — author it again rather than amending it"
        )

    added_subjects, known = _subjects(table, payload)
    added_subjects = yaml.safe_load(added_subjects) or []
    seen = {
        _identity_key(row.get("kind"), row.get("identity"))
        for row in subjects
        if isinstance(row, dict)
    }
    fresh = [
        row for row in added_subjects
        if _identity_key(row.get("kind"), row.get("identity")) not in seen
    ]

    added_claims = yaml.safe_load(_claims(table, payload, known)) or []
    have = {
        (_identity_key(row.get("kind"), row.get("subject")), _flat(row.get("title")))
        for row in claims
        if isinstance(row, dict)
    }
    fresh_claims = [
        row for row in added_claims
        if (
            _identity_key(row.get("kind"), row.get("subject")),
            _flat(row.get("title")),
        ) not in have
    ]

    if not fresh and not fresh_claims:
        raise PackRefused(
            "every subject and claim in the reply is already in this draft. "
            "Nothing was written — the request may already be covered, or the "
            "agent echoed the list it was shown"
        )

    written = []
    if fresh:
        written.append(packdraft.write(
            store_path, slug=slug, path="data/subjects.yaml",
            text=_preamble(root / "data" / "subjects.yaml")
            + yaml.safe_dump(list(subjects) + fresh, allow_unicode=True,
                             sort_keys=False)))
    if fresh_claims:
        written.append(packdraft.write(
            store_path, slug=slug, path="data/claims.yaml",
            text=_preamble(root / "data" / "claims.yaml")
            + yaml.safe_dump(list(claims) + fresh_claims, allow_unicode=True,
                             sort_keys=False)))

    # The line-up grows and the gap shrinks, in one place, so a second amend
    # asks for what is still missing rather than for what was just done.
    lineup = list(coverage.get("lineup") or [])
    for one in (payload.get("lineup") or []):
        text = _text(one)
        if text and _flat(text) not in {_flat(seen) for seen in lineup}:
            lineup.append(text)
    labels = {_flat(row.get("label")) for row in list(subjects) + fresh
              if isinstance(row, dict)}
    block = payload.get("coverage")
    block = block if isinstance(block, dict) else {}
    coverage = {
        "lineup": lineup,
        "covered": sorted(one for one in labels if one),
        "uncovered": [one for one in lineup if _flat(one) not in labels],
        "note": _text(block.get("note")) or coverage.get("note", ""),
        "out_of_scope": sorted(set(
            list(coverage.get("out_of_scope") or [])
            + [_text(one) for one in (block.get("out_of_scope") or []) if _text(one)]
        )),
    }
    written.append(packdraft.write(
        store_path, slug=slug, path="research/coverage.yaml",
        text=yaml.safe_dump(coverage, allow_unicode=True, sort_keys=False)))

    return {
        "slug": slug,
        "pack_id": state.get("pack_id", ""),
        "name": state.get("name", ""),
        "files": written,
        "subjects_added": len(fresh),
        "claims_added": len(fresh_claims),
        "subjects": len(subjects) + len(fresh),
        "claims": len(claims) + len(fresh_claims),
        "uncovered": coverage["uncovered"],
        "notes": _text(payload.get("notes")),
    }


def _preamble(path: Path) -> str:
    """The comment block a file opens with, kept across a rewrite.

    `yaml.safe_dump` produces rows and no prose, so appending to a file by
    dumping it whole would silently delete the header that says what the file
    is. Small, and exactly the kind of erosion that makes an amended draft look
    like a different tool wrote half of it.
    """
    if not path.exists():
        return ""
    lines = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or not line.strip():
            lines.append(line)
            continue
        break
    return "\n".join(lines).rstrip("\n") + "\n" if lines else ""


def _identity_key(kind, identity) -> tuple:
    """A comparable key for a subject or a claim's subject reference."""
    pairs = tuple(sorted(
        (str(key), _flat(value)) for key, value in (identity or {}).items()
    ))
    return (str(kind or ""), pairs)
