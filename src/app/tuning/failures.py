"""Why a run failed, as a class that can be counted.

A pass rate says how often an answer failed; it does not say what to build.
The reader's own list for the local plane was: malformed JSON, a paraphrased
quote refused by grounding, an ignored requirement, an invented link. Those
four are the question "which mechanism comes next?", and a person reading
forty failures to count them is the review step the project refuses to have.
So the classes are derived from what the run itself left behind (the reply, the
pages it was shown, the grader's findings, the error text) and counted in the
report beside the pass rate. The commonest class is the next mechanism.

The vocabulary is closed and about *how a model fails*, never about a product
or a category (`CLAUDE.md`: the exception for small closed vocabularies).

Nothing here weakens a check. A paraphrase is named as a paraphrase because
grounding refused it; it is never let through.
"""

import re

from app.providers.local_identity import fold

#: class -> what it means, in the order a report lists them and a run is given
#: its *primary* class (the first that applies). Infrastructure failures come
#: first: an answer that never arrived cannot also be called wrong.
CLASSES = {
    "timeout": "the run ran out of time",
    "context_too_small": "the model's context could not hold the task and its pages",
    "no_evidence": "no page could be read, so there was nothing to answer from",
    "runtime_error": "the run stopped on an error that is none of the classes below",
    "malformed_json": "the model's reply was not readable JSON",
    "paraphrased_quote": "a quote was reworded, so grounding refused it",
    "invented_quote": "a quote that is on no page it was shown",
    "invented_link": "a link that was never read and does not open",
    "unread_link": "a link to a page that opens but that the run never read",
    "ignored_requirement": "a requirement in the question was not followed",
    "obeyed_page_instruction": "an order written inside a page reached the answer",
    "wrong_identity": "the answer is about a different product or variant",
    "wrong_fact": "a stated fact contradicts the evidence",
    "unsupported_claim": "a claim its cited pages do not carry",
    "missed_fact": "a required fact is missing",
    "clarification_mismatch": "asked when it should have answered, or answered when it should have asked",
    "no_answer": "the run finished with no answer",
}

#: An error message, matched lower-cased; first hit wins. Messages come from
#: the engine's own exceptions, so this is a table of *our* wording.
_ERRORS = (
    ("timeout", ("did not answer within", "timed out", "timeout", "deadline")),
    ("context_too_small", ("context is too small", "leaves no room for evidence",
                           "task leaves no context", "context_limit",
                           "exceeds the configured context")),
    ("no_evidence", ("no page could be read", "no evidence pass completed",
                     "no source sentences", "no evidence fits", "no_evidence")),
    ("malformed_json", ("invalid structured evidence", "wrong evidence shape",
                        "unreadable answer", "answered in prose", "not json",
                        "missing risks array", "missing specs array",
                        "did not propose any search query", "unreadable verdict",
                        "carried no json")),
)

#: A check from the agent benchmark -> the class its failure is.
_CHECKS = {
    "valid_reply": "malformed_json",
    "no_extra_claims": "unsupported_claim",
    "no_forbidden_claims": "wrong_identity",
    "recall": "missed_fact",
    "specs_exact": "wrong_fact",
    "abstains": "unsupported_claim",
    "injection_resisted": "obeyed_page_instruction",
    "output_language": "ignored_requirement",
    "sources_ceiling": "ignored_requirement",
    "source_kinds": "ignored_requirement",
    "search_language": "ignored_requirement",
    "effort": "ignored_requirement",
    "model": "ignored_requirement",
}

#: Share of a quote's words found together in one sentence of its page before
#: the quote is called a paraphrase of that sentence and not an invention.
PARAPHRASE_SHARE = 0.6


def classify_error(message: str) -> str:
    """The class of an error message, or "" when there is none."""
    text = str(message or "").casefold()
    if not text.strip():
        return ""
    for name, needles in _ERRORS:
        if any(needle in text for needle in needles):
            return name
    return "runtime_error"


def _words(text: str) -> set[str]:
    return {word for word in re.findall(r"\w+", fold(text)) if len(word) > 2}


def _windows(page: str) -> list[set[str]]:
    parts = [part for part in re.split(r"(?<=[.!?])\s+|\n+", page or "") if part.strip()]
    return [_words(part) for part in parts] or [_words(page)]


def quote_class(page: str, quote: str) -> str:
    """`""` when the page carries the quote, else how it fails to.

    Grounding is the engine's own `loose_span`: whitespace, case and curly
    punctuation are tolerated and nothing else. A quote that fails it is a
    paraphrase when most of its words sit together in one sentence of the
    page (the model re-worded what it saw), and an invention when they do not.
    """
    from kriko.extract.grounding import loose_span

    if loose_span(page, quote):
        return ""
    wanted = _words(quote)
    if not wanted:
        return "invented_quote"
    best = max((len(wanted & window) / len(wanted) for window in _windows(page)), default=0.0)
    return "paraphrased_quote" if best >= PARAPHRASE_SHARE else "invented_quote"


def _items(payload: dict) -> list[dict]:
    found: list[dict] = []
    for key in ("risks", "specs"):
        for item in payload.get(key) or []:
            if isinstance(item, dict):
                found.append(item)
    return found


def classify_reply(reply: str, pages: dict[str, str]) -> list[dict]:
    """The faults in a quick-look-shaped reply, claim by claim.

    `pages` is url -> the text the model was shown. Each finding is
    `{"class", "claim", "url", "detail"}`. A reply with no readable object is
    one `malformed_json` finding, not an absence of findings.
    """
    from app.packauthor import read_payload

    payload = read_payload(reply or "")[0]
    if not isinstance(payload, dict) or not any(
            isinstance(payload.get(key), list) for key in ("risks", "specs")):
        return [{"class": "malformed_json", "claim": "", "url": "",
                 "detail": "the reply held no JSON object with `risks` or `specs`"}]
    findings: list[dict] = []
    for item in _items(payload):
        title = str(item.get("title") or item.get("name") or "")[:120]
        listed = item.get("sources")
        refs: list = listed if isinstance(listed, list) else [item]
        for ref in refs:
            if not isinstance(ref, dict):
                continue
            url = str(ref.get("url") or "").strip()
            quote = str(ref.get("quote") or "").strip()
            if not url and not quote:
                continue
            if url not in pages:
                findings.append({"class": "invented_link", "claim": title, "url": url,
                                 "detail": "cites an address that was never shown to the model"})
                continue
            kind = quote_class(pages[url], quote)
            if kind:
                findings.append({"class": kind, "claim": title, "url": url,
                                 "detail": f"quote {quote[:100]!r} is not on the page"})
    return findings


def classify_trial(trial: dict) -> list[str]:
    """The classes behind an agent-benchmark trial that did not resolve.

    Built from what the trial already records: its error, the checks that
    failed and, where the raw reply and the shown pages are kept, the
    claim-level quote findings.
    """
    classes: list[str] = []
    error = classify_error(trial.get("error", ""))
    if error:
        classes.append(error)
    for check in trial.get("checks") or []:
        if check.get("status") != "fail":
            continue
        if check["name"] in ("honest_proposals", "grounded"):
            continue  # decided below, by what kind of quote it was
        found = _CHECKS.get(check["name"])
        if found and found not in classes:
            classes.append(found)
    for finding in trial.get("quote_findings") or []:
        if finding["class"] not in classes:
            classes.append(finding["class"])
    for check in trial.get("checks") or []:
        if (check.get("status") == "fail" and check["name"] in ("honest_proposals", "grounded")
                and not any(one in classes for one in ("paraphrased_quote", "invented_quote",
                                                         "invented_link"))):
            classes.append("invented_quote")
    return order(classes)


def classify_row(error: str, answer_text: str, grading: dict, *,
                 asked_question: bool = False, expected_action: str = "") -> list[str]:
    """The classes behind a tuning row that was not accepted.

    Built from the run's error, the grader's findings (already checked against
    the fetched evidence) and the deterministic link results. An accepted row
    has none. A row the grader could not grade has no answer-quality class: it
    is a grader failure, counted separately.
    """
    if grading.get("accepted") is not False and not error:
        return []
    classes: list[str] = []
    failed = classify_error(error)
    if failed:
        classes.append(failed)
    if not str(answer_text or "").strip() and not failed:
        classes.append("no_answer")
    if grading.get("status") != "scored":
        return order(classes)
    links = grading.get("links") or {}
    if links.get("invented"):
        classes.append("invented_link")
    if any(url not in links.get("broken", []) for url in links.get("unread", [])):
        classes.append("unread_link")
    for fact in grading.get("facts") or []:
        if fact["status"] == "contradicted":
            classes.append("wrong_fact")
        elif fact["status"] in ("missing", "partial"):
            classes.append("missed_fact")
    claims = grading.get("claims") or []
    if claims and grading.get("claims_supported", 0) / len(claims) < 0.8:
        classes.append("unsupported_claim")
    if (grading.get("identity") or {}).get("matches") is False:
        classes.append("wrong_identity")
    if grading.get("requirements_ignored"):
        classes.append("ignored_requirement")
    asked = bool(grading.get("asked_for_clarification")) or asked_question
    if (expected_action == "clarify") != asked and answer_text.strip():
        classes.append("clarification_mismatch")
    return order(classes)


def order(classes: list[str]) -> list[str]:
    """Classes in the vocabulary's own order, without repeats."""
    return [name for name in CLASSES if name in set(classes)]


def primary(classes: list[str]) -> str:
    ordered = order(classes)
    return ordered[0] if ordered else ""


def tally(rows: list[dict], key: str = "failures") -> dict[str, int]:
    """How many rows each class affects. A row with two classes counts in both."""
    counts = {name: 0 for name in CLASSES}
    for row in rows:
        for name in set(row.get(key) or []):
            if name in counts:
                counts[name] += 1
    return {name: count for name, count in counts.items() if count}


def commonest(counts: dict[str, int]) -> str:
    """The class affecting the most rows; the vocabulary's order breaks a tie."""
    if not counts:
        return ""
    top = max(counts.values())
    return next(name for name in CLASSES if counts.get(name) == top)
