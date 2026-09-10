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

import yaml

from app import packdraft

__all__ = ["brief", "CONTRACT", "author", "PackRefused"]

#: Deliberately the same order of magnitude as a research reply. A pack that
#: needs more rows than this is a pack an agent should be growing with
#: `submit_findings` afterwards, not inventing in one breath.
MAX_SUBJECTS = 40
MAX_CLAIMS = 80
MAX_TEMPLATES = 12

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

## Decision 4 — a first row, and only an honest one

Two or three real subjects with the claims you actually found evidence for. A
claim needs a `title`, a `body` in the words a reader would recognise the
problem by, and `advice` — what to do about it before deciding. Severity is
`high`, `medium` or `low`.

**Never invent a claim.** A pack that ships a plausible-looking guess outlives
you in somebody's store. If you found nothing solid for a subject, ship the
subject with no claims; coverage gaps are a first-class thing here and the
research plane fills them later.

{CONTRACT}
"""


CONTRACT = """## How to report the pack (this run)

You have no Kriko tools in this session. Do not attempt to call any; there is
nothing to call. Print the pack as **one JSON object** as the last thing you
say, in a ```json fence. Kriko writes the files — you are proposing data, and
nothing you print is executed.

```json
{"pack_id": "lowercase.dotted.id",
 "name": "What it covers, in a few words",
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
    name = _text(payload.get("name")) or category or pack_id
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
                        text=_readme(name, pack_id, category, payload, table)),
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
        # Stated here rather than by the caller: authoring a pack and putting
        # it in the store are two authorities, and the one that writes the
        # files is the one that should be on record about not installing them.
        "installed": False,
    }


def _readme(name: str, pack_id: str, category: str, payload: dict,
            table: dict) -> str:
    kinds = ", ".join(f"`{kind}`" for kind in table)
    notes = _text(payload.get("notes"))
    return f"""# {name}

`{pack_id}` — authored by an agent from the category "{category or name}", and
not yet installed.

It declares {kinds}. Every claim in it is `confidence: 0.5` and
`detection: reported`: an agent proposed it from what it read, and no source
row is attached yet. A research run through the normal acceptance path is what
turns a proposal into evidence.

## What this pack covers

{_text(payload.get("covers")) or f"See the bar in `research/principle.md`."}

## What the author could not establish

{notes or "Nothing recorded."}

## Before installing

Read `data/claims.yaml`. A claim that reads like general advice about the
category rather than about one of these specific things is the failure mode
worth catching here — it is true, and it is noise.
"""


_FENCE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _payload(text: str) -> dict:
    """The pack object, out of whatever the agent wrapped it in.

    Same tolerance as the research plane's reader, and for the same reason: a
    model told to print a fence usually does and sometimes does not, and losing
    a completed run to a missing backtick would be absurd.
    """
    text = text or ""
    for match in reversed(_FENCE.findall(text)):
        try:
            parsed = json.loads(match)
        except ValueError:
            continue
        if isinstance(parsed, dict):
            return parsed
    start = text.find("{")
    while start != -1:
        try:
            parsed = json.loads(text[start:])
        except ValueError:
            start = text.find("{", start + 1)
            continue
        return parsed if isinstance(parsed, dict) else {}
    return {}
