"""Query planning for the local agent: propose, repair, refine, fall back.

A small model is asked for one thing at the start of a run — *a few web
searches for this product* — and the one thing small models do worst is hold a
shape. The old code sliced the first ``[``...``]`` out of the reply once and
raised if nothing came out, which turned a model that writes one sentence of
polse around its array into a run that never searched at all. Three components
live here, in the order a run meets them:

* :func:`propose` — the first queries, with a **repair loop**: a reply that is
  not a JSON array is quoted back to the model and asked again, bounded, so the
  run spends two cheap calls instead of one failure.
* :func:`plain_queries` — the **last resort**: after the bound is spent, the
  queries a reader would type from the product's own name. A model too small to
  hold the shape still gets a run that searches.
* :func:`refine` — the **second round**: queries for what the first round
  missed, given what was already searched and found. Never raises — a second
  round is a bonus, not a leg the run stands on.

Nothing here knows what a good query for a *product* is; every brief this plane
takes names the product on its first line, and the fallback reads no further
than that.
"""

import json

from app.providers.local_inference import LocalInferenceError

#: Attempts at the JSON array before the fallback takes over. Two re-asks,
#: because the failure mode is one bad reply, not a model that cannot ever do
#: it — a model that cannot ever do it answers the fallback.
ATTEMPTS = 3

_QUERY_ASK = (
    "You are choosing web searches. Read the task below and reply with ONLY a "
    "JSON array of {n} short web search queries that would find documented "
    "problems, failures and owner reports about the product it names. No "
    "prose.\n\n## Task\n\n{task}"
)

_QUERY_AGAIN = (
    "Your last reply was not a JSON array. Reply with ONLY a JSON array of "
    "{n} short web search queries about the product in the task — the first "
    "character of your reply must be [ and the last must be ]. No prose "
    "before or after.\n\n## Task\n\n{task}\n\n## Your last reply\n\n{last}"
)

_REFINE_ASK = (
    "You are choosing web searches. Below are the task, the searches already "
    "run, and the pages they found. Reply with ONLY a JSON array of {n} short "
    "web search queries that would find pages those searches missed — owner "
    "reports, forum threads, warranty and teardown pages, in different "
    "words. No prose.\n\n## Task\n\n{task}\n\n## Searches already "
    "run\n\n{ran}\n\n## Pages already found\n\n{found}"
)


def extract_array(raw: str) -> list:
    """The JSON array in a reply, or ``[]``. Never raises.

    The slicing is the tolerance a chatty model needs: prose before and after
    the array is common and harmless, so only the array is parsed — and only
    a real array counts.
    """
    try:
        found = json.loads(raw[raw.index("["): raw.rindex("]") + 1])
    except ValueError:
        return []
    return found if isinstance(found, list) else []


def _clean(found, queries: int) -> list[str]:
    """Kept queries: non-empty, casefold-deduped, capped."""
    kept: list[str] = []
    seen: set[str] = set()
    for one in found:
        text = str(one).strip()
        low = text.casefold()
        if not text or low in seen:
            continue
        seen.add(low)
        kept.append(text)
        if len(kept) >= queries:
            break
    return kept


def _ask(plan, prompt: str, say, check) -> str:
    if check is not None:
        check()
    if say is not None:
        say("asking for search queries")
    return plan(prompt)


def propose(task: str, plan, *, given: list[str] | None = None,
            queries: int = 3, say=None, check=None) -> list[str]:
    """The first queries for a task, or the plain ones if the model cannot.

    ``given`` is a case's own versioned queries (B185) and wins outright:
    letting the model invent its own would quietly change what the run
    measured.
    """
    if given:
        return _clean(given, queries)
    ask = _QUERY_ASK.format(n=queries, task=task[:4000])
    for attempt in range(ATTEMPTS):
        try:
            raw = _ask(plan, ask, say, check)
        except LocalInferenceError as error:
            # The server answered and the model still wrote nothing the run
            # could read — the reasoning-budget cutoff above all. Asking
            # again cannot fix a budget, so the plain queries take the
            # search and the model gets its chance at the answer instead.
            if say is not None:
                say(f"the model could not be asked for queries ({error}); "
                    "falling back to plain queries")
            fell = plain_queries(task)
            if not fell:
                raise
            return fell
        found = _clean(extract_array(raw), queries)
        if found:
            found = _keep_identity(task, found, queries=queries, say=say)
            from .identity import anchor_queries
            return anchor_queries(task, found)
        # Repair, not restart: the task stays, the bad reply is quoted back,
        # and the next attempt is one call, not a re-read of everything.
        if say is not None:
            say("query reply was not a JSON array; asking again")
        ask = _QUERY_AGAIN.format(n=queries, task=task[:4000], last=raw[:1000])
    fell = plain_queries(task)
    if not fell:
        raise LocalInferenceError(
            "the task named no product and the model proposed no search "
            "query, so nothing was searched.")
    if say is not None:
        say("fell back to plain queries: " + "; ".join(fell))
    return fell


def _keep_identity(task: str, found: list[str], *, queries: int, say=None) -> list[str]:
    """A Quick Look search must retain the brand and model the reader named."""
    import re

    if not task.startswith("# Quick look:"):
        return found
    plain = plain_queries(task, queries=queries)
    if not plain:
        return found
    name = plain[0].removesuffix(" problems")
    identity = [word for word in re.findall(r"\w+", name.casefold())
                if len(word) > 2][:2]
    if len(identity) < 2:
        return found
    kept = [query for query in found
            if set(identity) <= set(re.findall(r"\w+", query.casefold()))]
    if not kept and say is not None:
        say("the planner changed the product identity; using its exact name")
    return kept or plain


def plain_queries(task: str, *, queries: int = 3) -> list[str]:
    """The queries a reader would type: the product's name and the three
    questions a buyer asks. The **last resort** of `propose`, and the only
    place the engine reads a brief's shape — the first non-heading line names
    the product in every brief this plane takes."""
    name = ""
    for line in task.splitlines():
        text = line.strip()
        if not text or text.startswith("#") or text.startswith("```"):
            continue
        name = text.lstrip("*-> ").strip("`").strip()
        name = " ".join(name.split())[:240]
        break
    if not name:
        return []
    questions = ("problems", "failures", "owner reports", "recall service bulletin",
                 "repair failure diagnosis", "long term reliability", "warranty failures",
                 "failure affected versions")
    return [f"{name} {one}" for one in questions[:queries]]


def refine(task: str, ran: list[str], found: list[str], plan, *,
           queries: int = 3, say=None, check=None) -> list[str]:
    """Round-two queries, or ``[]``. Never raises: the second round is a
    bonus on top of a first round that already has pages."""
    seen_titles = "\n".join(f"- {one}" for one in found) or "- (none could be read)"
    prompt = _REFINE_ASK.format(
        n=queries, task=task[:2000],
        ran="\n".join(f"- {one}" for one in ran) or "- (none)",
        found=seen_titles[:2000])
    try:
        raw = _ask(plan, prompt, say, check)
    except Exception:  # noqa: BLE001 - the first round already stands
        return []
    from .identity import anchor_queries
    return anchor_queries(task, _keep_identity(
        task, _clean(extract_array(raw), queries), queries=queries, say=say))
