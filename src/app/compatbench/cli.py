"""Offline verification and an explicitly opt-in CompletionAsker model run."""

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.compatbench import core


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.compatbench",
        description="Grade sourced PC and vehicle-part compatibility decisions.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("verify", help="validate the fixture corpus and deterministic grader offline")
    run = sub.add_parser("run", help="ask a configured completion model on supplied evidence")
    run.add_argument("--model", required=True, help="configured API model id")
    run.add_argument("--local-url", default="",
                     help="local OpenAI-compatible server base URL, e.g. http://127.0.0.1:11434/v1")
    run.add_argument("--yes", action="store_true",
                     help="allow completion requests; these may incur provider charges")
    run.add_argument("--budget-usd", type=float, default=None,
                     help="API only: maximum conservative cost per case; use 0 to explicitly uncap")
    run.add_argument("--max-tokens", type=int, default=800)
    run.add_argument("--cases", default="", help="comma-separated case ids (default: all)")
    run.add_argument("--out", default="compatbench-results.json",
                     help="where to write the full result JSON")
    args = parser.parse_args(argv)
    if args.command == "verify":
        return _verify()
    return _run(args)


def _verify() -> int:
    try:
        summary = core.verify()
    except Exception as exc:  # noqa: BLE001 — report corpus defects as a command failure
        print(f"compatibility benchmark verification failed: {exc}", file=sys.stderr)
        return 1
    print(f"{summary['suite']} {summary['version']}: {summary['cases']} cases; "
          f"derived outcomes {summary['outcomes']}")
    for row in summary["rows"]:
        print(f"  pass  {row['case']:<36} {row['expected_verdict']}")
    print("Fixture checker and evidence grader passed. No model or network was used.")
    return 0


def _run(args) -> int:
    try:
        cases = _cases(args.cases)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if not args.yes:
        budget = (f"the conservative per-case ceiling is ${args.budget_usd:g}. "
                  if args.budget_usd is not None else
                  ("the API per-case budget is not set. " if not args.local_url else
                   "the model is self-hosted and no dollar cost is estimated. "))
        print("No model was called. This run sends "
              f"{len(cases)} supplied-evidence prompt(s) to {args.model!r}; "
              + budget + "Add --yes to allow those requests.", file=sys.stderr)
        return 2
    if args.budget_usd is not None and (
            not math.isfinite(args.budget_usd) or args.budget_usd < 0):
        print("budget must be finite and non-negative", file=sys.stderr)
        return 2
    if args.max_tokens < 1:
        print("max tokens must be positive", file=sys.stderr)
        return 2
    if args.local_url and args.budget_usd is not None:
        print("--budget-usd applies to API runs; local model cost is reported as self_hosted",
              file=sys.stderr)
        return 2
    if not args.local_url and args.budget_usd is None:
        print("API runs require --budget-usd (use 0 to explicitly uncap)", file=sys.stderr)
        return 2
    try:
        if args.local_url:
            from app.providers.local_inference import OpenAICompatSocket

            complete = OpenAICompatSocket(args.local_url, args.model,
                                          timeout=90.0, max_tokens=args.max_tokens,
                                          temperature=0.0)
            asker = _SocketAsker(complete)
            model = args.model
            adapter, cost_basis = "OpenAICompatSocket", "self_hosted"
        else:
            from app.providers import completer_for, llm
            from app.providers.completion_asker import CompletionAsker

            model = llm.model_name(args.model)
            complete = completer_for(model, max_tokens=args.max_tokens)
            asker = CompletionAsker(complete, budget_usd=args.budget_usd,
                                    max_tokens=args.max_tokens)
            adapter, cost_basis = "CompletionAsker", "per_token"
    except Exception as exc:  # noqa: BLE001
        print(f"could not configure {args.model!r}: {type(exc).__name__}: {exc}",
              file=sys.stderr)
        return 1

    rows = []
    for index, case in enumerate(cases, 1):
        before_in = _int_or_none(getattr(asker, "tokens_in", None))
        before_out = _int_or_none(getattr(asker, "tokens_out", None))
        answer = ""
        error = ""
        try:
            if args.local_url:
                complete.last_usage_complete = False
            answer = asker.ask(core.prompt(case))
        except Exception as exc:  # noqa: BLE001 — retain every completed case row
            error = f"{type(exc).__name__}: {exc}"
        after_in = _int_or_none(getattr(asker, "tokens_in", None))
        after_out = _int_or_none(getattr(asker, "tokens_out", None))
        usage_complete = bool(getattr(
            complete, "last_usage_complete" if args.local_url else "usage_complete", False))
        tokens_in = (_delta(after_in, before_in, first=index == 1)
                     if usage_complete else None)
        tokens_out = (_delta(after_out, before_out, first=index == 1)
                      if usage_complete else None)
        spent = None
        if not args.local_url and tokens_in is not None and tokens_out is not None:
            from app import modelcatalogue

            spent = modelcatalogue.price(model, tokens_in, tokens_out)
        score = core.grade(case, answer) if answer else {
            "case": case["id"], "dimension": case.get("dimension", ""),
            "expected_verdict": core.verdict(case), "answer_verdict": None,
            "valid_shape": False, "check_count": len(case.get("comparisons") or []),
            "errors": [error or "empty answer"], "pass": False}
        rows.append({
            **score, "model": model, "error": error,
            "cost_basis": cost_basis,
            "tokens_in": tokens_in, "tokens_out": tokens_out,
            "usd": spent, "answer": answer,
        })
        mark = "pass" if score["pass"] else "FAIL"
        print(f"  {mark:<4} {index}/{len(cases)} {case['id']}: "
              f"{score.get('answer_verdict') or 'no verdict'}"
              + (f" ({error[:100]})" if error else ""), flush=True)

    corpus = core.load()
    passed = sum(bool(row["pass"]) for row in rows)
    result = {
        "suite": corpus.get("id"), "version": corpus.get("version"),
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "model": model, "adapter": adapter, "cost_basis": cost_basis,
        "budget_usd_per_case": args.budget_usd, "max_tokens": args.max_tokens,
        "cases": len(rows), "passed": passed, "pass_rate": round(passed / len(rows), 3),
        "rows": rows,
    }
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Compatibility score: {passed}/{len(rows)} ({result['pass_rate']:.0%}); "
          f"results: {target}")
    return 0 if passed == len(rows) else 1


def _cases(selection: str) -> list[dict]:
    cases = core.load().get("cases") or []
    if not selection.strip():
        return cases
    requested = [one.strip() for one in selection.split(",") if one.strip()]
    if not requested:
        raise ValueError("select at least one case")
    by_id = {str(one.get("id") or ""): one for one in cases}
    missing = [one for one in requested if one not in by_id]
    if missing:
        raise ValueError(f"unknown case(s): {', '.join(missing)}")
    return [by_id[one] for one in requested]


def _int_or_none(value):
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _delta(after, before, *, first: bool):
    if after is None:
        return None
    if before is None:
        return after if first else None
    return after - before


class _SocketAsker:
    """The local socket's completion plus the small ask interface used by this CLI."""

    def __init__(self, socket):
        self.socket = socket

    def ask(self, prompt: str) -> str:
        answer = self.socket.complete(prompt)
        if not answer.strip():
            raise RuntimeError("local server returned an empty completion")
        return answer

    @property
    def tokens_in(self):
        return self.socket.tokens_in

    @property
    def tokens_out(self):
        return self.socket.tokens_out


if __name__ == "__main__":
    raise SystemExit(main())
