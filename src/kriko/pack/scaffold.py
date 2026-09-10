"""Write an empty pack that already passes the contract.

The contract is four things — `pack.toml` with `[pack]` and a non-empty
`[identity]`, at least one YAML file under `data/`, and a `README.md`. Every one
of them is easy to get wrong on a first attempt, and the failure arrives as a
validation error against a directory the author is still guessing the shape of.

So this writes the floor: a directory that installs as-is and holds one subject
and one claim, both marked as placeholders. An author then edits rows rather
than inventing a layout. It is the same floor `packs/drill/` sits at, which is
what makes it worth generating — a starting point nobody has to read the
builder's source to reach.

Category-free by construction: every category-specific word in the output comes
from the caller's own `identity` argument. There is no default subject kind and
no default key here, because a default would be this module having an opinion
about what products are like.
"""

from pathlib import Path

__all__ = ["scaffold"]


def _toml_list(values) -> str:
    return "[" + ", ".join(f'"{value}"' for value in values) + "]"


def _pack_toml(pack_id: str, name: str, version: str, identity: dict) -> str:
    kinds = "\n".join(
        f"{kind} = {_toml_list(keys)}" for kind, keys in identity.items()
    )
    return f"""[pack]
id = "{pack_id}"
name = "{name}"
version = "{version}"

# What makes a subject distinct, per kind. This is the most consequential
# declaration in the file: it decides which of these rows can ever merge with
# another pack's. Too few keys and unrelated things collide into one subject;
# too many and one real thing splits across subjects that never see each
# other's claims. Neither failure raises — they are both silent.
[identity]
{kinds}
"""


def _readme(name: str, pack_id: str, identity: dict) -> str:
    kinds = ", ".join(f"`{kind}`" for kind in identity)
    return f"""# {name}

`{pack_id}` — a new pack, scaffolded and not yet filled in.

It declares {kinds} and ships one placeholder subject with one placeholder
claim, so it installs and answers a lookup from the first minute. Both rows are
marked `placeholder: true`; delete them as real ones arrive.

## What this pack covers

Say it in prose, for someone who has never seen this repository. Which things,
which markets, and what a reader can expect to be told about one. A pack is
something people install — the README is the only place that promise is made.

## The bar for a claim

State it in `research/principle.md`: what is worth surfacing about this
category, and what a reader could get more cheaply elsewhere. The ranking is
the platform's job; the bar is yours, and it is category-specific, which is
exactly why it ships as pack data.

## What to search for

`research/templates.yaml` holds the queries. It was scaffolded from the
identity keys above and knows nothing about this category, so rewrite it in the
words people actually use — and in the language they use them in. Every research
brief prints these as "Searches to run"; a pack that empties this file has a
Research button that says what to keep and never says what to look for.
"""


_PRINCIPLE = """# What this pack surfaces

Write the bar here, then hold every candidate row against it.

A useful bar names both halves:

* **Surface** — what a reader cannot cheaply find out for themselves, is
  specific to this exact configuration and its usage so far, and is expensive
  or consequential enough to change a decision.
* **Do not surface** — anything true of everything in the category, and
  anything a routine inspection or the seller's own paperwork already answers.

The test for a candidate row is one question: *would this reader have learned
it anyway?* If yes, it is noise, however true it is.
"""


#: The searches a pack names for its own subjects, and why a new pack must
#: ship some.
#:
#: `kriko.research.plan_task` reads this file and renders each line with the
#: subject's label, its aliases and its identity keys; `AgentResearcher.brief`
#: prints the result as "Searches to run". A pack with no templates file
#: renders **zero** queries, so its brief tells an agent what to keep and never
#: says what to look for — and until 2026-09-10 the scaffold wrote
#: `principle.md` and not this, which meant every pack authored through it had
#: a Research button that produced half a document.
#:
#: The lines below are derived from the identity keys the author just declared,
#: not from a category this module knows about. Two of them are shaped for
#: whatever `{kind}` and keys came in, which is the difference between a
#: starting point and a guess about the domain.
def _templates(identity: dict) -> str:
    """Query templates keyed off the identity this pack just declared."""
    keys = sorted({key for keys in identity.values() for key in keys})
    lines = [
        "# Search templates for this pack. One query per line.",
        "#",
        "# `{label}` is the subject's own name, `{alias}` is each of its aliases",
        "# in turn (one query is rendered per alias), and any identity key this",
        "# pack declares may be used by name. A template naming a key a subject",
        "# does not carry is skipped for that subject rather than failing, so a",
        "# more specific line costs nothing.",
        "#",
        "# These are a starting point, not a finished set: they were generated",
        "# from the identity keys above and know nothing about what this pack",
        "# covers. Rewrite them in the words people actually use — including",
        "# the language they use them in, if that is not English. The searches",
        "# a category needs are pack knowledge, which is why they live here",
        "# rather than anywhere in Kriko's core.",
        '- "{alias} common problems"',
        '- "{alias} known issues"',
        '- "{label} failure symptoms"',
        '- "{alias} reliability forum"',
    ]
    for key in keys[:2]:
        lines.append(f'- "{{alias}} {{{key}}} problems"')
    return "\n".join(lines) + "\n"


def _terms(identity: dict) -> str:
    """Declare exactly the vocabulary the scaffolded rows use, and no more.

    Written from the caller's identity table rather than from a fixed list:
    the builder refuses a row whose key was never declared, so a template with
    invented keys would ship a pack that does not build — the one thing a
    scaffold must never do.
    """
    kinds = "\n".join(
        f"- term_id: {kind}\n  role: subject_kind\n  label: {{en: {kind}}}\n"
        for kind in identity
    )
    keys = sorted({key for values in identity.values() for key in values})
    attributes = "\n".join(
        f"- term_id: {key}\n  role: attribute\n  datatype: text\n"
        f"  label: {{en: {key}}}\n"
        for key in keys
    )
    return f"""# Vocabulary — every key, kind and domain this pack uses.
#
# Declared before use: the builder refuses a row referring to a term that is
# not here, rather than shipping a value nothing can read back. This is also
# the whole reason a category costs no code — the platform learns these names
# by reading them.

# ── subject kinds ────────────────────────────────────────────────────────
{kinds}
# ── identity attributes ──────────────────────────────────────────────────
{attributes}
# ── domains, the grouping a reader sees ──────────────────────────────────
- term_id: general
  role: domain
  label: {{en: General}}
"""


def _subjects(identity: dict) -> str:
    kind, keys = next(iter(identity.items()))
    fields = "\n".join(f"      {key}: TODO" for key in keys)
    return f"""# Subjects — the things this pack knows about.
#
# One placeholder, so the pack installs and answers before any real row exists.
# `identity` must carry exactly the keys `pack.toml` declares for the kind:
# that dictionary is hashed to the subject id, and a missing key silently
# hashes to a different thing.

- kind: {kind}
  label: A placeholder — replace me
  placeholder: true
  identity:
{fields}
"""


def _claims(identity: dict) -> str:
    kind, keys = next(iter(identity.items()))
    fields = ", ".join(f"{key}: TODO" for key in keys)
    return f"""# Claims — what is known to go wrong, and what to do about it.
#
# `subject` repeats the identity rather than naming a label, because a label is
# not stable and an identity is. Evidence is what separates a claim from an
# opinion: a row with no source is ranked below one that has three.

- subject: {{kind: {kind}, identity: {{{fields}}}}}
  kind: known_issue
  domain: general
  severity: medium
  detection: reported
  confidence: 0.5
  placeholder: true
  text:
    en:
      title: A placeholder claim — replace me
      body: >
        What goes wrong, in the words a reader would recognise it by.
      advice: >
        What they should do about it before deciding.
"""


def scaffold(
    root,
    *,
    pack_id: str,
    name: str,
    identity: dict[str, list[str]],
    version: str = "0.1.0",
) -> list[Path]:
    """Write the pack skeleton under `root`. Returns the files written.

    Raises `ValueError` on an identity table the contract would reject, and
    `FileExistsError` if `root` already holds a `pack.toml` — overwriting
    someone's authored rows is not a thing a scaffold gets to do.
    """
    if not pack_id or not name:
        raise ValueError("a pack needs both an id and a name")
    cleaned = {
        str(kind): [str(key) for key in keys if str(key).strip()]
        for kind, keys in (identity or {}).items()
        if str(kind).strip()
    }
    cleaned = {kind: keys for kind, keys in cleaned.items() if keys}
    if not cleaned:
        raise ValueError(
            "[identity] must declare at least one subject kind and the attribute "
            "keys that tell two of them apart — without them every subject of a kind "
            "would hash to the same id"
        )

    root = Path(root)
    if (root / "pack.toml").exists():
        raise FileExistsError(f"{root} already holds a pack.toml")

    files = {
        root / "pack.toml": _pack_toml(pack_id, name, version, cleaned),
        root / "README.md": _readme(name, pack_id, cleaned),
        root / "research" / "principle.md": _PRINCIPLE,
        root / "research" / "templates.yaml": _templates(cleaned),
        root / "vocabulary" / "terms.yaml": _terms(cleaned),
        root / "data" / "subjects.yaml": _subjects(cleaned),
        root / "data" / "claims.yaml": _claims(cleaned),
    }
    written = []
    for path, text in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        written.append(path)
    return written
