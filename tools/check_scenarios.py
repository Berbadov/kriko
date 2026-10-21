"""Run the ten local-agent scenarios in `tools/local_scenarios.json`.

Two different questions, two different measurements:

* `clarifying` — would the agent ask before spending? This runs the
  identification pass alone (`disambiguate.brief` → one completion →
  `disambiguate.parse`), which is the cheap call that guards the expensive
  one. No search, so it measures the model's judgement, not the web.
* `research` — did a real look find the documented problems, and did it keep
  anything else? This runs the actual quick look through `tools/measure_local.py`
  and scores the kept risks against each scenario's expected issue families.
  A risk matching no family is reported, not judged: the families are a
  fixture, not a ground truth.

    .venv/Scripts/python.exe tools/check_scenarios.py --clarify
    .venv/Scripts/python.exe tools/check_scenarios.py --research --only r1,r3
    .venv/Scripts/python.exe tools/check_scenarios.py --all --output .local-evaluation/scenarios/run.jsonl

Every run writes JSONL, so two runs are comparable. Nothing here changes the
app or the scenario file.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from app import disambiguate, localplane  # noqa: E402
from app.providers.local_inference import OpenAICompatSocket  # noqa: E402

FAMILY_WORD = re.compile(r"[^\W\d_]{4,}")


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def summarise_questions(found: dict) -> str:
    if not found.get("ambiguous"):
        return "did not ask"
    parts = []
    for question in found["questions"]:
        parts.append(f"{question['ask']} (default {question['default']!r})")
    return " · ".join(parts)


def clarify(scenario: dict, socket, keys: str = "") -> dict:
    prompt = disambiguate.brief(scenario["request"], keys)
    started = time.perf_counter()
    record = {"id": scenario.get("id"), "request": scenario.get("request"),
              "missing_key": scenario.get("missing_key", ""),
              "expected_question": scenario.get("expected_question", "")}
    before_in, before_out = getattr(socket, "tokens_in", 0), getattr(socket, "tokens_out", 0)
    try:
        raw = socket(prompt)
        found = disambiguate.parse(raw)
        record.update(
            asked=bool(found.get("ambiguous")),
            questions=found.get("questions") or [],
            established=found.get("established") or {},
            error="",
        )
    except Exception as error:  # noqa: BLE001 - a broken call is a result too
        record.update(asked=False, questions=[], established={},
                      error=f"{type(error).__name__}: {error}")
    record["seconds"] = round(time.perf_counter() - started, 2)
    record["tokens_in"] = (getattr(socket, "tokens_in", 0) or 0) - (before_in or 0)
    record["tokens_out"] = (getattr(socket, "tokens_out", 0) or 0) - (before_out or 0)
    # Did it ask about the key that was actually missing? A question about the
    # wrong thing ("what do you use it for?") is not the same as not asking.
    missing = str(scenario.get("missing_key") or "").casefold()
    asks = " ".join(f"{one.get('ask', '')} {one.get('key', '')}"
                    for one in record.get("questions") or []).casefold()
    record["asked_the_missing_key"] = bool(missing) and missing in asks
    guessed = [one for one in scenario.get("guesses_to_avoid") or []
               if one.casefold() in json.dumps(record.get("established") or {}).casefold()]
    record["guesses_in_established"] = guessed
    return record


def _words(text: str) -> set[str]:
    return {word.casefold() for word in FAMILY_WORD.findall(text or "")}


def score(record: dict, families: list[str]) -> dict:
    """Which expected issue families the kept risks actually carry."""
    text = " ".join(f"{risk.get('title', '')} {risk.get('body', '')}"
                    for risk in record.get("risks") or [])
    kept_words = _words(text)
    matched, missed = [], []
    for family in families:
        wanted = _words(family)
        (matched if wanted and wanted <= kept_words else missed).append(family)
    aliases = " ".join(family for family in families)
    stray = [risk.get("title", "") for risk in record.get("risks") or []
             if not (_words(risk.get("title", "") + " " + risk.get("body", "")) & _words(aliases))]
    record["families_matched"] = matched
    record["families_missed"] = missed
    record["risks_without_a_family"] = stray
    record["kept"] = len(record.get("risks") or [])
    record["duplicate_titles"] = len(record.get("risks") or []) - len({
        str(risk.get("title", "")).casefold() for risk in record.get("risks") or []})
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scenarios", type=Path, default=ROOT / "tools" / "local_scenarios.json")
    parser.add_argument("--only", default="", help="comma-separated ids, e.g. c1,r2")
    parser.add_argument("--clarify", action="store_true")
    parser.add_argument("--research", action="store_true")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--max-tokens", type=int, default=1024)
    parser.add_argument("--model", default="",
                        help="a model the server serves; default is the plane's own pick")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    if not (args.clarify or args.research or args.all):
        parser.error("choose --clarify, --research or --all")

    data = load(args.scenarios)
    wanted = {one.strip() for one in args.only.split(",") if one.strip()}
    output = args.output or (ROOT / ".local-evaluation" / "scenarios"
                             / f"{time.strftime('%Y%m%d-%H%M%S')}.jsonl")
    output.parent.mkdir(parents=True, exist_ok=True)

    plan = localplane.resolve(None, model=args.model)
    if not plan["ready"]:
        print(f"the local plane is not ready: {plan['reason']}")
        return 1
    print(f"{plan['model']} on {plan['name']} · ctx {plan['context_tokens']} · {plan['search_label']}")
    written = []

    if args.clarify or args.all:
        socket = OpenAICompatSocket(
            plan["url"], plan["model"], timeout=plan["timeout"],
            max_tokens=min(args.max_tokens, 512),
            reasoning_effort="none", runtime_options=plan.get("runtime_options"),
            context_tokens=plan.get("context_tokens"))
        print("\nclarifying requests (does it ask, and the right thing?)")
        for scenario in data.get("clarifying", []):
            if wanted and scenario["id"] not in wanted:
                continue
            record = clarify(scenario, socket)
            record["group"] = "clarifying"
            print(f"  {scenario['id']} asked={record['asked']} "
                  f"{record['seconds']}s  {summarise_questions({'ambiguous': record['asked'], 'questions': record['questions']})}")
            if record.get("error"):
                print(f"      error: {record['error']}")
            written.append(record)

    if args.research or args.all:
        import measure_local

        print("\nresearch scenarios (what did a look actually keep?)")
        for scenario in data.get("research", []):
            if wanted and scenario["id"] not in wanted:
                continue
            record = measure_local.run_one(scenario["product"], plan, args)
            record["group"] = "research"
            record["id"] = scenario["id"]
            record["expected_issue_families"] = scenario.get("expected_issue_families") or []
            score(record, scenario.get("expected_issue_families") or [])
            print(f"  {scenario['id']} {scenario['product']}: "
                  f"{record['wall_seconds']}s, kept {record['kept']} "
                  f"({len(record['families_matched'])}/{len(scenario.get('expected_issue_families') or [])} families), "
                  f"{record['duplicate_titles']} duplicate title(s)"
                  + (f", ERROR {record['error']}" if record.get("error") else ""))
            if record["families_missed"]:
                print("      missed: " + "; ".join(record["families_missed"]))
            if record["risks_without_a_family"]:
                print("      unmatched titles: " + " | ".join(record["risks_without_a_family"]))
            written.append(record)

    with output.open("a", encoding="utf-8") as handle:
        for record in written:
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    print(f"\nwrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
