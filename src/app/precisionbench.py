"""Deterministic scoring of the controlled corpus, before output filtering.

Measures source attribution, explicit applicability, exact specifications,
and abstention. Phrase alternatives tolerate short paraphrases, not arbitrary
semantic equivalence. This is a bounded fixture check, not an LLM judge.
"""

from kriko.extract.grounding import loose_span


def payload(reply: str) -> dict:
    from app.packauthor import _payload
    from app.quicklook import closed
    found = _payload(reply) or closed(reply)
    return found if isinstance(found, dict) else {}


def risks(reply: str) -> list[dict]:
    items = payload(reply).get("risks")
    return [one for one in items if isinstance(one, dict)] if isinstance(items, list) else []


def _flat(value) -> str:
    return " ".join(str(value or "").casefold().split())


def _terms(entry: dict, risk: dict) -> bool:
    text = _flat(str(risk.get("title") or "") + " " + str(risk.get("why") or ""))
    return all(any(_flat(term) in text for term in group)
               for group in entry["terms"])


def _supports(entry: dict, risk: dict) -> bool:
    quote = str(risk.get("quote") or "").strip()
    return (risk.get("url") == entry["url"] and len(quote) >= 16
            and bool(loose_span(entry["quote"], quote)) and _terms(entry, risk))


def judge(case: dict, reply: str, sources: dict[str, str]) -> dict:
    raw = payload(reply)
    items = raw.get("risks")
    proposals = items if isinstance(items, list) else []
    supported = case.get("supported") or []
    found_ids: set[str] = set()
    errors = []
    quote_errors = 0
    for index, risk in enumerate(proposals):
        if not isinstance(risk, dict):
            errors.append({"index": index, "reason": "invalid-risk"})
            continue
        url, quote = str(risk.get("url") or ""), str(risk.get("quote") or "")
        if not quote.strip() or not loose_span(sources.get(url, ""), quote):
            quote_errors += 1
            errors.append({"index": index, "title": risk.get("title", ""),
                           "reason": "unsupported-quote"})
            continue
        matches = [entry for entry in supported if _supports(entry, risk)]
        if not matches:
            errors.append({"index": index, "title": risk.get("title", ""),
                           "reason": "unsupported-configuration-or-claim"})
        found_ids.update(entry["id"] for entry in matches)
    wanted = [entry["id"] for entry in supported]
    expected_specs = case.get("expected_specs") or []
    spec_items = raw.get("specs")
    specs = spec_items if isinstance(spec_items, list) else []
    spec_found = []
    spec_errors = []
    for spec in specs:
        if not isinstance(spec, dict):
            spec_errors.append("invalid-spec")
            continue
        name, value = _flat(spec.get("name")), _flat(spec.get("value"))
        exact = next((entry for entry in expected_specs
                      if name == _flat(entry["name"]) and value in {
                          _flat(one) for one in [entry["value"], *entry.get("aliases", [])]}
                      and spec.get("url") == entry["url"]), None)
        if exact:
            spec_found.append(exact["name"])
        else:
            spec_errors.append(f"{name}: {value}")
    valid_shape = isinstance(raw.get("risks"), list) and isinstance(raw.get("specs"), list)
    abstained = valid_shape and not proposals and not specs
    abstention_expected = bool(case.get("expect_abstention"))
    return {
        "case": case["id"], "kind": "fixed", "mode": "controlled",
        "dimension": case.get("dimension", ""), "valid_shape": valid_shape,
        "found": [key for key in wanted if key in found_ids],
        "missed": [key for key in wanted if key not in found_ids],
        "hallucinated": [str(error.get("title") or error["reason"]) for error in errors],
        "unlisted": [], "errors": errors,
        "raw_produced": len(proposals), "unsupported_quotes": quote_errors,
        "recall": round(len(found_ids) / len(wanted), 3) if wanted else None,
        "hallucination_rate": round(len(errors) / len(proposals), 3) if proposals else None,
        "spec_found": sorted(set(spec_found)),
        "spec_missed": [entry["name"] for entry in expected_specs if entry["name"] not in spec_found],
        "spec_errors": spec_errors, "spec_produced": len(specs),
        "abstention_expected": abstention_expected,
        "abstention_correct": abstained if abstention_expected else None,
        "pass": valid_shape and not errors and not spec_errors
                and len(found_ids) == len(wanted)
                and len(set(spec_found)) == len(expected_specs)
                and (not abstention_expected or abstained),
    }


def brief(case: dict) -> str:
    from app.quicklook import brief as quick_brief
    # Compact form has no instruction to search or guess a missing variant.
    task = quick_brief(case["product"], compact=True)
    task += ("\n## Controlled evidence experiment\n"
             "These are fictional products. Use only the supplied documents. "
             "Do not search or fetch URLs. Do not guess an unknown configuration. "
             "Source URLs identify documents in this experiment. "
             "Copy quotes exactly. An exclusion or correction takes precedence. "
             "Return empty risks and specs when unsupported.\n")
    requested = case.get("requested_specs") or []
    task += ("\nExtract only these requested specification fields, with exactly "
             "these names and a concise value (not a whole sentence): "
             + ", ".join(requested) + ".\n" if requested else
             "\nNo specification fields are requested; return an empty specs list.\n")
    return task
