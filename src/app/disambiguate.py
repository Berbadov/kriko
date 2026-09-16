"""Ask before spending, once, and never wait for the answer.

The reader's report: *"it never asks me anything."* They name a product, the
agent goes and researches it, and what comes back is good work about possibly
the wrong thing — because the same commercial name is sold market to market
under different codenames, with generation splits and drivetrain variants that
change the failure profile completely. **A pack built on the wrong variant is
worse than no pack, because it is confidently wrong.**

Three rules, and the second is the one that keeps this out of the data path:

**Cheap first.** The identification pass is one short call whose only job is
"is this identity unambiguous?". It runs before the expensive research, because
the point is to not spend the expensive part on the wrong product — a
disambiguation that cost as much as the run it protects would protect nothing.

**Non-blocking, always.** `CLAUDE.md`'s automation principle says nothing in the
data path waits for a human. So nothing here does: every question ships with a
default and its reasoning, the run proceeds on those defaults immediately, and
an answer that arrives later refines the next run rather than unblocking this
one. What the reader gets is not a gate — it is a *statement of what was
assumed*, in plain language, at the top of the pack. An assumed scope that is
invisible is the actual bug; an assumed scope that is stated is a working
default.

**At most five, in one batch.** An agent that asks one question at a time
across a run is an interrogation, and the reader said so. Questions are
collected once, answered once, or not at all.

What this module does *not* do is decide what counts as ambiguous for a
category. The signals below are shapes — a market difference, a generation
split, a name collision — and which of them bite is a property of the product,
so the agent judges it against what it read. The engine holds no opinion about
whether cars or drills have more variants.
"""

import json

#: Never more than this, and the reason is the reader's own: "do not interrogate
#: me one question at a time across the whole run". Five is the point where a
#: batch stops being a form and starts being a questionnaire.
MAX_QUESTIONS = 5

#: The kinds of ambiguity worth a question. Deliberately *shapes* rather than
#: fields: `market` is not an identity key in any pack, it is a reason two
#: things with one name differ. A pack's own keys are what the answers map
#: onto, and those are read off the store, never listed here.
SIGNALS = (
    "the same commercial name sold under a different codename per market",
    "a generation, facelift or model-year split that changes what goes wrong",
    "engine, drivetrain or power-source variants",
    "trim or equipment variants that change which failures apply",
    "regional homologation, regulatory or specification differences",
    "a name collision with an unrelated product",
)


def brief(subject: str, keys: str = "") -> str:
    """The identification pass, as instructions. One or two searches, no more.

    `keys` is the installed packs' own identity vocabulary, passed through so a
    question's answer lands on a key some pack can actually use. An answer
    mapped to a key nobody declares is a fact with nowhere to go.
    """
    signals = "\n".join(f"* {one}" for one in SIGNALS)
    vocabulary = (
        f"\n\nWhere an answer corresponds to one of these keys, name it as "
        f"`key`. They are the installed packs' own:\n\n{keys}\n"
        if keys else ""
    )
    return f"""# Is this product identity unambiguous?

    {subject}

This is a *cheap* pass before an expensive one. One or two searches, no deep
reading. Your only job is to decide whether the name above picks out one
product or several, and if several, what a normal person could be asked to tell
them apart.

## Look for

{signals}

## Then

If the name is unambiguous, say so and ask nothing. That is the common case and
it is worth getting right — a question about a product with one variant wastes
the reader's attention and teaches them to ignore the next one.

If it is ambiguous, write **at most {MAX_QUESTIONS} questions**, in one batch.
Each one must be:

* **Concrete and answerable by a normal person** — the market they are in, a
  model year or range, the engine or trim, the gearbox, what they use it for.
  Never "what would you like me to focus on?", which asks the reader to do your
  job.
* **Carried by a default and its reasoning.** The run does not wait for an
  answer; it proceeds on your defaults, so a default you cannot justify is a
  guess you are about to make on somebody's behalf silently. Justify it from
  what you read — which variant is common, which is most sold, which is the one
  the name usually means.

**Never ask what you can determine yourself.** If the name, the page or the URL
already states the variant, use it and say so in `established` instead.
{vocabulary}
## Reply

One JSON object in a ```json fence, as the last thing you say:

```json
{{"ambiguous": true,
  "why": "one sentence on what is actually ambiguous here",
  "established": {{"key": "what the name itself already settled"}},
  "questions": [
    {{"id": "market",
      "ask": "Which market is this one sold in?",
      "key": "the pack identity key this answers, or \\"\\" if none",
      "options": ["TR", "EU"],
      "default": "TR",
      "because": "why that default, from what you read"}}
  ]}}
```
"""


def parse(reply: str) -> dict:
    """The agent's answer, or a safe nothing. Never raises.

    A disambiguation pass that fails must cost the reader a *question*, never
    the run behind it: this is the cheap step guarding the expensive one, and
    an exception here would turn "we could not tell whether this was ambiguous"
    into "you get no pack". So an unparseable reply is read as "unambiguous",
    which is exactly what the run did before this module existed.
    """
    from app.packauthor import _payload  # the same fence reader every door uses

    found = _payload(reply)
    if not isinstance(found, dict):
        return {"ambiguous": False, "questions": [], "established": {}, "why": ""}

    questions: list[dict] = []
    for raw in (found.get("questions") or [])[:MAX_QUESTIONS]:
        if not isinstance(raw, dict):
            continue
        ask = str(raw.get("ask") or "").strip()
        default = str(raw.get("default") or "").strip()
        # Both, or neither. A question with no default would block the run, and
        # blocking is the one thing this may not do; a default with no question
        # is an assumption nobody was offered the chance to correct.
        if not ask or not default:
            continue
        questions.append({
            "id": str(raw.get("id") or "").strip() or f"q{len(questions) + 1}",
            "ask": ask,
            "key": str(raw.get("key") or "").strip(),
            "options": [str(one) for one in (raw.get("options") or [])][:8],
            "default": default,
            "because": str(raw.get("because") or "").strip(),
        })

    established = {
        str(key): str(value)
        for key, value in (found.get("established") or {}).items()
        if str(key) and str(value)
    } if isinstance(found.get("established"), dict) else {}

    return {
        "ambiguous": bool(found.get("ambiguous")) and bool(questions),
        "why": str(found.get("why") or "").strip(),
        "established": established,
        "questions": questions,
    }


def scope(found: dict, answers: dict | None = None) -> dict:
    """What this run is actually about, and which parts of it were assumed.

    The record §1.1's matching wants and the reader's pack needs at the top of
    it. `assumed` is the load-bearing half: it is what lets the extension say
    *"there is a pack, but for a different variant"* rather than either
    matching wrongly or saying nothing, and it is what stops an assumed scope
    from being invisible.
    """
    answers = answers or {}
    settled, assumed = dict(found.get("established") or {}), []
    for question in found.get("questions") or []:
        given = str(answers.get(question["id"]) or "").strip()
        settled[question["key"] or question["id"]] = given or question["default"]
        if not given:
            assumed.append(question["key"] or question["id"])
    return {
        "identity": settled,
        # Sorted so two runs that assumed the same things produce the same
        # record — a scope that reshuffles is a scope that looks like it
        # changed.
        "assumed": sorted(assumed),
        "established_by": "disambiguation",
    }


def sentence(record: dict) -> str:
    """The scope in plain language, for the top of a pack.

    "built for the 2014–2017 1.6 TDI manual, Turkish market" — the reader's own
    example of what they wanted to see, and the whole of what `assumed` is for.
    A pack that does not say what it is about is a pack whose wrongness is
    indistinguishable from a coverage gap.
    """
    identity = record.get("identity") or {}
    if not identity:
        return ""
    parts = ", ".join(f"{key} {value}" for key, value in sorted(identity.items()))
    assumed = record.get("assumed") or []
    if not assumed:
        return f"Built for {parts}."
    which = ", ".join(sorted(assumed))
    return (f"Built for {parts} — of which {which} "
            f"{'was' if len(assumed) == 1 else 'were'} assumed, not confirmed.")


def as_json(record: dict) -> str:
    return json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2)
