"""The self-check: the model reads its own answer against the pages it cites.

`quicklook.parse` already refuses a quote that is not mechanically *in* the
page it cites — that gate is arithmetic and stays. What arithmetic cannot do
is notice a page that contains the quote and does not support the claim: the
quote about battery life sitting on a page about a *different* variant. A
small model composes that kind of line more often than a big one, and the
run's own honesty depends on catching it *before* the panel renders it.

So the last call of a run is the model checking the model: the answer and the
exact pages it was built from go back in, and the reply is one small JSON
object naming the risks its own pages do not carry. The verdict is **kept,
not enforced** — `LocalAsker.verification` carries it beside the answer, and
the run says what it found. Enforcement by deletion belongs to the doors
that render (`quicklook.parse`), which already hold the mechanical half.

Never raises: a self-check that cannot run is a run that answers with no
verdict, never a run that loses its answer.
"""

import json

from kriko.research.window import focus


_CHECK_ASK = (
    "You are checking an answer against the pages it was built from. Below "
    "are the pages and the answer. For every risk the answer states, decide "
    "whether the page it cites really carries its quote and says what the "
    "risk claims. The title and explanation may paraphrase or translate the "
    "source. The source does not need to use the title or call the issue a "
    "risk. A Turkish quote can support an English explanation. Flag only "
    "a missing quote, a different product, or a claim the source contradicts "
    "or does not support. Reply with ONLY a JSON object, no prose outside it:\n\n"
    '{{"unsupported": [{{"title": "the risk title exactly as the answer has '
    'it", "reason": "one sentence on why the page does not carry it"}}], '
    '"note": "one sentence on the answer as a whole"}}\n\n'
    "Risks whose pages carry them go in no list. If every risk is carried, "
    "reply with an empty `unsupported` list.\n\n"
    "## Pages\n\n{pages}\n\n## Answer\n\n{answer}"
)


def extract_object(raw: str) -> dict:
    """The JSON object in a reply, or ``{}``. Never raises."""
    try:
        found = json.loads(raw[raw.index("{"): raw.rindex("}") + 1])
    except ValueError:
        return {}
    return found if isinstance(found, dict) else {}


def check(complete, answer: str, pages, *, say=None) -> dict:
    """The verdict on an answer, or an honest ``{"error": ...}``.

    ``complete`` is the same socket that answered, so the check costs one
    call on the model the reader already chose — no second model, no key.
    """
    if say is not None:
        say("self-check: the model reads its own answer against its pages")
    blocks = "\n\n".join(f"### URL: {url}\n\n{text}" for url, text in pages)
    allowed = getattr(complete, "prompt_chars_allowed", None)
    if callable(allowed):
        overhead = len(_CHECK_ASK.format(pages="", answer=answer))
        room = allowed() - overhead
        if room <= 0:
            return {"unsupported": [], "note": "",
                    "error": "not enough context for self-check"}
        share = room // max(1, len(pages))
        blocks = "\n\n".join(
            f"### URL: {url}\n\n{focus(text, max(0, share - len(url) - 16), [answer])}"
            for url, text in pages)
    schema = getattr(complete, "_schema", None)
    if schema is not None:
        complete._schema = {
            "type": "object", "properties": {
                "unsupported": {"type": "array", "items": {
                    "type": "object", "properties": {
                        "title": {"type": "string"}, "reason": {"type": "string"}},
                    "required": ["title", "reason"]}},
                "note": {"type": "string"}},
            "required": ["unsupported", "note"]}
    try:
        raw = complete(_CHECK_ASK.format(pages=blocks, answer=answer))
    except Exception as error:  # noqa: BLE001 - the answer already stands
        if say is not None:
            say(f"self-check could not run: {error}")
        return {"unsupported": [], "note": "", "error": str(error)}
    finally:
        if schema is not None:
            complete._schema = schema
    found = extract_object(raw)
    if not found:
        if say is not None:
            say("self-check replied with nothing it could be read as")
        return {"unsupported": [], "note": "", "error": "unreadable verdict"}
    unsupported = []
    for one in found.get("unsupported") or []:
        if isinstance(one, dict):
            title = str(one.get("title") or "").strip()
            if title:
                unsupported.append({"title": title,
                                    "reason": str(one.get("reason") or "").strip()})
    verdict = {"unsupported": unsupported,
               "note": str(found.get("note") or "").strip()}
    if say is not None:
        if unsupported:
            say(f"self-check: {len(unsupported)} risk(s) not carried by "
                "their pages")
        else:
            say("self-check: every risk carried by its page")
    return verdict
