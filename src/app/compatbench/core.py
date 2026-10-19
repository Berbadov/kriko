"""A fixed-corpus compatibility benchmark with a mechanical evidence grader."""

import json
import re
from pathlib import Path

from kriko.extract.grounding import loose_span

CASES = Path(__file__).with_name("cases.json")
OPERATORS = {"equal", "at_least", "member"}
_VERSION = re.compile(r"^\s*(\d+(?:\.\d+)*)\s*$")


def load(path: Path = CASES) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def documents(case: dict) -> dict[str, str]:
    return {str(row.get("url") or ""): str(row.get("text") or "")
            for row in case.get("documents") or [] if isinstance(row, dict)}


def prompt(case: dict) -> str:
    """Build the same supplied-evidence task for every completion model."""
    constraints = ", ".join(str(row.get("id") or "")
                             for row in case.get("comparisons") or [])
    lines = [
        "Decide whether the named component is compatible with the named host or vehicle, using only the supplied pages.",
        f"Question: {case.get('question', '')}",
        "Compare each relevant constraint. A known mismatch means incompatible. "
        "Say compatible only when every listed constraint is supported and matches. "
        "If a decisive detail is absent or the evidence does not establish the match, say unknown.",
        "For each constraint, give one status: match, mismatch, or unknown. Cite exact source URLs and verbatim quotes for known facts; for unknown, explain what is missing and cite no invented evidence.",
        "Do not treat a seller's claim as independent verification. A forum allegation about a seller or counterfeit part is a report, not proof; distinguish fitment from authenticity and seller credibility.",
        "Return only one JSON object with this shape:",
        '{"verdict":"compatible|incompatible|unknown", "checks":[{"id":"constraint id", "status":"match|mismatch|unknown", "reason":"missing detail for unknown", "evidence":[{"url":"https://...", "quote":"verbatim passage"}]}], "authenticity":"genuine|counterfeit|unknown", "authenticity_evidence":[{"url":"https://...", "quote":"verbatim passage", "claim":"genuine|counterfeit", "assessment":"verified|seller_claim|unverified_report", "specificity":"exact_item|not_exact_item"}], "seller_assessment":"credible|concerning|unverified", "seller_evidence":[{"url":"https://...", "quote":"verbatim passage", "status":"verified|reported", "specificity":"exact_item|seller_only|unclear"}]}',
        "Constraint ids to assess: " + (constraints or "none"),
        "Use unknown for authenticity or seller assessment unless independent, relevant evidence supports a stronger conclusion.",
        "## Supplied evidence",
    ]
    for doc in case.get("documents") or []:
        lines += [f"### {doc.get('title') or 'Source'}", f"URL: {doc.get('url', '')}",
                  str(doc.get("text") or ""), ""]
    return "\n".join(lines)


def _version(value: str):
    found = _VERSION.fullmatch(str(value or ""))
    return tuple(int(part) for part in found.group(1).split(".")) if found else None


def _compare(operator: str, left: str, right: str) -> str:
    if not left or not right:
        return "unknown"
    if operator == "equal":
        return "match" if _fold(left) == _fold(right) else "mismatch"
    if operator == "at_least":
        actual, required = _version(left), _version(right)
        if actual is None or required is None:
            return "unknown"
        width = max(len(actual), len(required))
        actual += (0,) * (width - len(actual))
        required += (0,) * (width - len(required))
        return "match" if actual >= required else "mismatch"
    if operator == "member":
        choices = {_fold(value) for value in re.split(r"[,;|]", right) if value.strip()}
        return "match" if _fold(left) in choices else "mismatch"
    return "unknown"


def constraint_results(case: dict) -> list[dict]:
    facts = {str(one.get("id") or ""): one for one in case.get("facts") or []}
    out = []
    for constraint in case.get("comparisons") or []:
        left = facts.get(str(constraint.get("left") or ""))
        right = facts.get(str(constraint.get("right") or ""))
        status = ("unknown" if not left or not right else
                  _compare(str(constraint.get("operator") or ""),
                           str(left.get("value") or ""), str(right.get("value") or "")))
        out.append({"id": constraint.get("id", ""), "status": status,
                    "known_facts": [one for one in (left, right) if one]})
    return out


def verdict(case: dict) -> str:
    statuses = [one["status"] for one in constraint_results(case)]
    if "mismatch" in statuses:
        return "incompatible"
    if not statuses or "unknown" in statuses:
        return "unknown"
    return "compatible"


def authenticity(case: dict) -> str:
    """Only exact-item, verified authoritative evidence can settle authenticity."""
    eligible = {str(row.get("status") or "") for row in case.get("authenticity_evidence") or []
                if row.get("exact_item") and row.get("verified")
                and row.get("source_class") in {"manufacturer", "regulator", "inspection"}
                and row.get("status") in {"genuine", "counterfeit"}}
    return next(iter(eligible)) if len(eligible) == 1 else "unknown"


def seller_assessment(case: dict) -> str:
    """Require two independent, identity-matched verified sources to rate a seller."""
    evidence = [row for row in case.get("seller_evidence") or []
                if row.get("identity_matches") and row.get("verified")
                and row.get("finding") in {"positive", "negative"}]
    publishers = {str(row.get("publisher") or "").casefold() for row in evidence}
    if len(publishers) < 2:
        return "unverified"
    findings = {row.get("finding") for row in evidence}
    if findings == {"positive"}:
        return "credible"
    if findings == {"negative"}:
        return "concerning"
    return "unverified"


def payload(reply: str) -> dict:
    from app.packauthor import _payload

    found = _payload(reply or "")
    return found if isinstance(found, dict) else {}


def _fold(value: str) -> str:
    return " ".join(str(value or "").casefold().split())


def _citation_covers(citation: dict, fact: dict, page_map: dict[str, str]) -> bool:
    url = str(citation.get("url") or "")
    quote = str(citation.get("quote") or "").strip()
    fact_url = str(fact.get("url") or "")
    fact_quote = str(fact.get("quote") or "").strip()
    page = page_map.get(url, "")
    return bool(url == fact_url and quote and loose_span(page, quote)
                and loose_span(quote, fact_quote))


def grade(case: dict, reply: str) -> dict:
    """Compare a proposed decision to constraints derived from fixture facts."""
    raw = payload(reply)
    expected_checks = constraint_results(case)
    got_rows = raw.get("checks") if isinstance(raw.get("checks"), list) else []
    got = {str(row.get("id") or ""): row for row in got_rows if isinstance(row, dict)}
    pages = documents(case)
    errors = []
    if len(got) != len(got_rows):
        errors.append("duplicate or malformed constraint check")
    # A correct required citation does not excuse an extra invented one.
    for row in got_rows:
        if not isinstance(row, dict):
            continue
        refs = row.get("evidence") if isinstance(row.get("evidence"), list) else []
        for ref in refs:
            if not isinstance(ref, dict):
                errors.append("constraint evidence: malformed citation")
                continue
            url, quote = str(ref.get("url") or ""), str(ref.get("quote") or "").strip()
            if url not in pages or not quote or not loose_span(pages.get(url, ""), quote):
                errors.append(f"{row.get('id', '?')}: citation is not a grounded supplied page span")
    for expected in expected_checks:
        row = got.get(str(expected["id"]))
        if row is None:
            errors.append(f"missing check {expected['id']}")
            continue
        if row.get("status") != expected["status"]:
            errors.append(f"{expected['id']}: expected {expected['status']}, got {row.get('status')!r}")
        citations = row.get("evidence") if isinstance(row.get("evidence"), list) else []
        if expected["status"] == "unknown" and not str(row.get("reason") or "").strip():
            errors.append(f"{expected['id']}: unknown needs a reason naming the missing evidence")
        for fact in expected["known_facts"]:
            if not any(isinstance(ref, dict) and _citation_covers(ref, fact, pages)
                       for ref in citations):
                errors.append(f"{expected['id']}: missing grounded quote for {fact['id']}")
    extra = sorted(set(got) - {str(one["id"]) for one in expected_checks})
    if extra:
        errors.append("unexpected check(s): " + ", ".join(extra))
    expected_verdict = verdict(case)
    answer_verdict = raw.get("verdict")
    if not isinstance(answer_verdict, str) or answer_verdict != expected_verdict:
        errors.append(f"verdict: expected {expected_verdict}, got {raw.get('verdict')!r}")
    seller_expected = bool(case.get("seller_evidence") or case.get("authenticity_evidence"))
    expected_authenticity = authenticity(case)
    expected_seller = seller_assessment(case)
    if seller_expected and raw.get("authenticity") != expected_authenticity:
        errors.append(f"authenticity: expected {expected_authenticity}, got {raw.get('authenticity')!r}")
    if seller_expected and raw.get("seller_assessment") != expected_seller:
        errors.append(f"seller assessment: expected {expected_seller}, got {raw.get('seller_assessment')!r}")
    if case.get("seller_evidence"):
        supplied = raw.get("seller_evidence") if isinstance(raw.get("seller_evidence"), list) else []
        for expected in case.get("seller_evidence") or []:
            status = "verified" if expected.get("verified") else "reported"
            specificity = ("exact_item" if expected.get("exact_item") else
                           "seller_only" if expected.get("identity_matches") else "unclear")
            found = next((item for item in supplied
                          if isinstance(item, dict)
                          and item.get("url") == expected.get("url")
                          and item.get("status") == status
                          and item.get("specificity") == specificity
                          and _citation_covers(item, expected, pages)), None)
            if found is None:
                errors.append("seller evidence: missing grounded quote or it was overstated")
        if len(supplied) != len(case.get("seller_evidence") or []):
            errors.append("seller evidence: unexpected or missing report")
    if case.get("authenticity_evidence"):
        supplied = (raw.get("authenticity_evidence")
                    if isinstance(raw.get("authenticity_evidence"), list) else [])
        for expected in case.get("authenticity_evidence") or []:
            assessment = ("verified" if expected.get("verified")
                          and expected.get("exact_item")
                          and expected.get("source_class") in {"manufacturer", "regulator", "inspection"}
                          else "seller_claim" if expected.get("source_class") == "seller_listing"
                          else "unverified_report")
            specificity = "exact_item" if expected.get("exact_item") else "not_exact_item"
            found = next((item for item in supplied
                          if isinstance(item, dict)
                          and item.get("url") == expected.get("url")
                          and item.get("claim") == expected.get("status")
                          and item.get("assessment") == assessment
                          and item.get("specificity") == specificity
                          and _citation_covers(item, expected, pages)), None)
            if found is None:
                errors.append("authenticity evidence: missing grounded quote or it was overstated")
        if len(supplied) != len(case.get("authenticity_evidence") or []):
            errors.append("authenticity evidence: unexpected or missing report")
    shape = (isinstance(answer_verdict, str)
             and answer_verdict in {"compatible", "incompatible", "unknown"}
             and isinstance(raw.get("checks"), list))
    return {"case": case.get("id", ""), "dimension": case.get("dimension", ""),
            "expected_verdict": expected_verdict,
            "answer_verdict": raw.get("verdict"), "valid_shape": shape,
            "check_count": len(expected_checks), "errors": errors,
            "pass": shape and not errors}


def reference_reply(case: dict) -> str:
    """A deterministic control assembled from fixture facts, not a model answer."""
    checks = []
    for item in constraint_results(case):
        citations = [{"url": fact["url"], "quote": fact["quote"]}
                     for fact in item["known_facts"]]
        checks.append({"id": item["id"], "status": item["status"],
                       "reason": ("One or more required facts are absent from the supplied pages."
                                  if item["status"] == "unknown" else ""),
                       "evidence": citations})
    response = {"verdict": verdict(case), "checks": checks}
    if case.get("seller_evidence") or case.get("authenticity_evidence"):
        response["authenticity"] = authenticity(case)
        response["seller_assessment"] = seller_assessment(case)
    if case.get("seller_evidence"):
        response["seller_evidence"] = [{
            "url": item["url"], "quote": item["quote"],
            "status": "verified" if item.get("verified") else "reported",
            "specificity": ("exact_item" if item.get("exact_item") else
                            "seller_only" if item.get("identity_matches") else "unclear"),
        } for item in case["seller_evidence"]]
    if case.get("authenticity_evidence"):
        response["authenticity_evidence"] = [{
            "url": item["url"], "quote": item["quote"], "claim": item["status"],
            "assessment": ("verified" if item.get("verified") and item.get("exact_item")
                           and item.get("source_class") in {"manufacturer", "regulator", "inspection"}
                           else "seller_claim" if item.get("source_class") == "seller_listing"
                           else "unverified_report"),
            "specificity": "exact_item" if item.get("exact_item") else "not_exact_item",
        } for item in case["authenticity_evidence"]]
    return json.dumps(response)


def validate(cases: list[dict]) -> list[str]:
    problems = []
    case_ids = set()
    for case in cases:
        case_id = str(case.get("id") or "?")
        if case_id in case_ids:
            problems.append(f"{case_id}: duplicate case id")
        case_ids.add(case_id)
        pages = documents(case)
        if not pages:
            problems.append(f"{case_id}: no supplied documents")
        for fact in case.get("facts") or []:
            url, quote = str(fact.get("url") or ""), str(fact.get("quote") or "")
            if url not in pages:
                problems.append(f"{case_id}/{fact.get('id')}: fact url is not in the supplied pages")
            elif not loose_span(pages[url], quote):
                problems.append(f"{case_id}/{fact.get('id')}: fact quote is not in its supplied page")
        for section in ("seller_evidence", "authenticity_evidence"):
            for item in case.get(section) or []:
                url, quote = str(item.get("url") or ""), str(item.get("quote") or "")
                if url not in pages:
                    problems.append(f"{case_id}/{section}: evidence url is not in the supplied pages")
                elif not loose_span(pages[url], quote):
                    problems.append(f"{case_id}/{section}: evidence quote is not in its supplied page")
        facts = {str(one.get("id") or "") for one in case.get("facts") or []}
        unknown_facts = {str(one) for one in case.get("unknown_facts") or []}
        comparison_ids = set()
        for comparison in case.get("comparisons") or []:
            identifier = str(comparison.get("id") or "")
            if not identifier or identifier in comparison_ids:
                problems.append(f"{case_id}: missing or duplicate comparison id {identifier!r}")
            comparison_ids.add(identifier)
            if comparison.get("operator") not in OPERATORS:
                problems.append(f"{case_id}/{identifier}: unsupported operator")
            for side in ("left", "right"):
                ref = str(comparison.get(side) or "")
                if ref and ref not in facts and ref not in unknown_facts:
                    problems.append(f"{case_id}/{identifier}: {side} references undeclared fact {ref!r}")
        if not case.get("comparisons"):
            problems.append(f"{case_id}: no fitment comparisons")
    return problems


def verify() -> dict:
    corpus = load()
    cases = corpus.get("cases") or []
    problems = validate(cases)
    if problems:
        raise ValueError("invalid compatibility corpus: " + "; ".join(problems))
    rows = [grade(case, reference_reply(case)) for case in cases]
    failed = [row for row in rows if not row["pass"]]
    outcomes = {value: sum(row["expected_verdict"] == value for row in rows)
                for value in ("compatible", "incompatible", "unknown")}
    if failed:
        raise AssertionError(f"reference answer failed fixture checks: {failed}")
    if not all(outcomes.values()):
        raise AssertionError(f"the corpus must exercise all three verdicts: {outcomes}")
    return {"suite": corpus.get("id"), "version": corpus.get("version"),
            "cases": len(cases), "outcomes": outcomes, "rows": rows}
