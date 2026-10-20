"""The quote repair: one bounded re-ask of the claims whose quotes were not carried.

`quicklook.parse` refuses a claim whose quote is not on the page it cites, and
it is right to: a small model paraphrases the sentence it just read, the
paraphrase is not the page's words, and a line the reader cannot find on the
page is the one thing this product must never show. What the refusal does not
do is *help*. The claim was often real; the model had the right sentence in
front of it and re-wrote it.

So, before the self-check and before anything is rendered, the claims whose
quotes are not carried get exactly one more question, and the question is made
one a small model can answer: not "copy this sentence word for word" (the
request it just failed) but **"which of these numbered sentences from the page
says what your claim says, or none?"** The answer is a number. The quote that
goes back into the claim is the page's own characters for that number, copied
here, so it is carried by construction and `quicklook.parse` re-checks it all
the same.

What this is not: a weaker check. A claim whose page offers no sentence that
shares words with it, or for which the model says none, or whose reply cannot
be read, stays exactly as it was and is dropped by the same gate as before.
One call at most, whatever the number of claims; a model that cannot do it
costs one call, not a loop.

Nothing here knows a product or a category: the candidates are the page's own
sentences ranked by the words they share with the claim.
"""

import json
import re

from kriko.extract.grounding import loose_span

#: Claims asked about in the one call, and sentences offered per claim.
MAX_CLAIMS = 6
MAX_SENTENCES = 6
#: A candidate shares at least this many content words with the claim, or it
#: is not offered: the model is asked to *confirm* a match, not to hunt.
MIN_SHARED = 2
#: Sentence length bounds, the same ones the extractive quotes use.
MIN_CHARS, MAX_CHARS = 25, 600

REPAIR_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {"fixes": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "properties": {"claim": {"type": "integer"}, "sentence": {"type": "integer"}},
        "required": ["claim", "sentence"]}}},
    "required": ["fixes"],
}

_ASK = (
    "Some claims in your answer cite a quote that is not written on the page. "
    "Do not rewrite anything. For each claim below, choose the numbered "
    "sentence from its page that says what the claim says, or 0 when no "
    "sentence does. Reply with ONLY JSON: "
    '{{"fixes": [{{"claim": 1, "sentence": 2}}]}}, one entry per claim.\n\n{claims}'
)

_STOP = {"the", "and", "for", "with", "that", "this", "was", "are", "has", "had",
         "have", "not", "but", "from", "its", "their", "they", "can", "will",
         "when", "than", "then", "which", "into", "after", "about", "over"}


def _words(text: str) -> set[str]:
    return {word for word in re.findall(r"\w+", str(text).casefold())
            if len(word) > 2 and word not in _STOP}


def _sentences(page: str) -> list[str]:
    parts = (part.strip() for part in re.split(r"(?<=[.!?])\s+|\n+", page or ""))
    return list(dict.fromkeys(one for one in parts if MIN_CHARS <= len(one) <= MAX_CHARS))


def claims_of(payload: dict) -> list[dict]:
    """Every risk and spec that carries a single url and quote of its own."""
    found: list[dict] = []
    for key in ("risks", "specs"):
        for item in payload.get(key) or []:
            if isinstance(item, dict) and not isinstance(item.get("sources"), list):
                found.append(item)
    return found


def not_carried(payload: dict, sources: dict[str, str]) -> list[dict]:
    """The claims whose quote the page they cite does not carry."""
    return [item for item in claims_of(payload)
            if not (str(item.get("url") or "").strip() in sources
                    and loose_span(sources[str(item["url"]).strip()], str(item.get("quote") or "")))]


def _claim_text(item: dict) -> str:
    return " ".join(str(item.get(key) or "") for key in ("title", "name", "why", "value", "quote"))


def _candidates(item: dict, sources: dict[str, str]) -> tuple[str, list[str]]:
    """The page to read the claim against and the sentences worth offering.

    The cited page when it was read; otherwise the read page whose sentences
    share the most with the claim, because a link the model made up cannot
    name a page, but its claim usually still belongs to one of them.
    """
    wanted = _words(_claim_text(item))
    url = str(item.get("url") or "").strip()
    pages = [url] if url in sources else list(sources)
    best_url, best = "", []
    for one in pages:
        scored = sorted(((len(wanted & _words(sentence)), sentence)
                         for sentence in _sentences(sources[one])), key=lambda pair: -pair[0])
        offered = [sentence for shared, sentence in scored if shared >= MIN_SHARED][:MAX_SENTENCES]
        if offered and (not best or len(wanted & _words(offered[0])) > len(wanted & _words(best[0]))):
            best_url, best = one, offered
    return best_url, best


def repair(complete, payload: dict, sources: dict[str, str], *, say=None) -> tuple[dict, dict]:
    """`(payload, stats)`: the payload with every claim the model could point
    at a sentence for given that sentence as its quote.

    `stats` is `{"asked", "repaired", "unrepairable"}`: what was put to the
    model, what came back carried, and what no sentence of any page offered a
    match for. A payload with nothing to repair costs no call.
    """
    stats = {"asked": 0, "repaired": 0, "unrepairable": 0}
    missing = not_carried(payload, sources)
    if not missing:
        return payload, stats
    asked: list[tuple[dict, str, list[str]]] = []
    for item in missing:
        url, offered = _candidates(item, sources)
        if not offered:
            stats["unrepairable"] += 1
            continue
        if len(asked) < MAX_CLAIMS:
            asked.append((item, url, offered))
    if not asked:
        return payload, stats
    blocks = []
    for number, (item, url, offered) in enumerate(asked, 1):
        title = str(item.get("title") or item.get("name") or "").strip()
        why = str(item.get("why") or item.get("value") or "").strip()
        blocks.append(f"## Claim {number}: {title}. {why}\nPage: {url}\n"
                      + "\n".join(f"{index}. {sentence}" for index, sentence in enumerate(offered, 1)))
    stats["asked"] = len(asked)
    if say is not None:
        say(f"quote repair: {len(asked)} claim(s) cite words the page does not carry; "
            "asking once which page sentence each means")
    prompt = _ASK.format(claims="\n\n".join(blocks))
    try:
        raw = (complete.json(prompt, REPAIR_SCHEMA) if callable(getattr(complete, "json", None))
               else complete(prompt))
    except Exception as error:  # noqa: BLE001 - the answer already stands
        if say is not None:
            say(f"quote repair could not run: {error}")
        return payload, stats
    from app.packauthor import read_payload

    reply = read_payload(raw)[0]
    fixes = reply.get("fixes") if isinstance(reply, dict) else None
    for fix in fixes if isinstance(fixes, list) else []:
        if not isinstance(fix, dict):
            continue
        claim, choice = fix.get("claim"), fix.get("sentence")
        if (not isinstance(claim, int) or isinstance(claim, bool) or not 1 <= claim <= len(asked)
                or not isinstance(choice, int) or isinstance(choice, bool)):
            continue
        item, url, offered = asked[claim - 1]
        if not 1 <= choice <= len(offered):
            continue  # 0 is "none says it": the claim stays, and stays refused
        sentence = offered[choice - 1]
        carried = loose_span(sources[url], sentence)
        if not carried:
            continue
        item["url"], item["quote"] = url, carried
        stats["repaired"] += 1
    if say is not None:
        say(f"quote repair: {stats['repaired']} of {len(asked)} claim(s) now carried by their page")
    return payload, stats


def reserialise(payload: dict) -> str:
    """The repaired payload as the one fenced object every reader of a reply reads."""
    return "```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```"
