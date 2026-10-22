"""python -m app.searchbench: preflight, retrieval measurements, full agent sweeps."""

import argparse
import asyncio
import hashlib
import itertools
import json
import os
import platform
import random
import sys
import uuid
import zipfile
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from app.redaction import redact_json
from app.searchbench.agent import research, evidence_metrics
from app.searchbench.config import MODELS, SEARCHES, load_keys
from app.searchbench.report import aggregate, write_report, write_csvs
from app.searchbench.retrieval import Retrieval
from app.searchbench.transport import Wire
from app.searchbench.metrics import ledger, paired_comparisons


def selection(value, choices):
    selected = list(choices) if value == "all" else [item.strip() for item in value.split(",")]
    unknown = set(selected) - set(choices)
    if unknown:
        raise ValueError("Unknown selection: " + ", ".join(sorted(unknown)))
    if len(set(selected)) != len(selected):
        raise ValueError("Selections must not contain duplicates")
    return selected


def redact(value):
    """The trace with this sweep's provider keys taken out (shared helper, `app.redaction`)."""
    return redact_json(value, {m.key_env for m in MODELS.values()} | {s[1] for s in SEARCHES.values()})


async def retrieval_run(wire, variant, case, timeout, results=5, page_chars=6000):
    retrieval = Retrieval(wire, variant, count=results, page_chars=page_chars)
    row = {"case": case["id"], "question": case["question"], "search": variant, "strategy": "retrieval", "status": "error"}
    try:
        async with asyncio.timeout(timeout):
            hits = await retrieval.search(case["question"])
            row["status"] = "ok" if hits else "empty"
    except TimeoutError:
        row["status"] = "timeout"
    except Exception as error:
        row["error"] = type(error).__name__
    row.update(total_s=wire.now(), first_result_s=retrieval.first_result_s, sources=list(retrieval.sources.values()),
               events=wire.events, http_requests=len(wire.events))
    row["quality"] = evidence_metrics("", row["sources"], case)
    return ledger(row)


async def sweep(args):
    import httpx

    searches = selection(args.searches, SEARCHES)
    models = selection(args.models, MODELS) if args.command == "run" else [""]
    strategies = selection(args.strategies, ("sequential", "parallel", "eager")) if args.command == "run" else ["retrieval"]
    case_path = Path(args.cases)
    cases = json.loads(case_path.read_text(encoding="utf-8-sig"))
    if args.limit:
        cases = cases[:args.limit]
    if not cases or len({c["id"] for c in cases}) != len(cases):
        raise ValueError("Cases must be nonempty and have unique IDs")
    for case in cases:
        if not isinstance(case.get("question"), str) or not case["question"].strip():
            raise ValueError("Every case requires a question")
    needed = {SEARCHES[s][1] for s in searches} | {MODELS[m].key_env for m in models if m}
    missing = sorted(name for name in needed if not os.environ.get(name))
    if missing:
        raise ValueError("Missing keys: " + ", ".join(missing))
    jobs = list(itertools.product(models, searches, strategies, cases, range(args.reps)))
    random.Random(args.seed).shuffle(jobs)
    baseline = (models[0] or "retrieval-only", searches[0], strategies[0])
    now = datetime.now(timezone.utc)
    code_hash = hashlib.sha256()
    for source_file in sorted(Path(__file__).parent.glob("*.py")):
        code_hash.update(source_file.name.encode())
        code_hash.update(source_file.read_bytes())
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stem = out / ("searchbench-" + now.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6])
    with zipfile.ZipFile(stem.with_suffix(".source.zip"), "x", compression=zipfile.ZIP_DEFLATED) as snapshot:
        for source_file in sorted(Path(__file__).parent.iterdir()):
            if source_file.suffix in (".py", ".json"):
                snapshot.write(source_file, "app/searchbench/" + source_file.name)
    document = {"schema_version": 1, "created_at": now.isoformat(), "python": sys.version, "platform": platform.platform(),
                "config": vars(args), "case_sha256": hashlib.sha256(case_path.read_bytes()).hexdigest(),
                "models": {m: asdict(MODELS[m]) for m in models if m}, "searches": {s: SEARCHES[s] for s in searches},
                "price_date": "2026-10-20", "source_sha256": code_hash.hexdigest(),
                "httpx_version": httpx.__version__, "baseline": baseline, "source_snapshot": stem.with_suffix(".source.zip").name, "runs": []}
    print(f"{len(jobs)} runs; report {stem}.md", flush=True)
    async with httpx.AsyncClient(http2=args.http2, timeout=httpx.Timeout(20, connect=5), limits=httpx.Limits(max_connections=12, max_keepalive_connections=12)) as client:
        with stem.with_suffix(".jsonl").open("x", encoding="utf-8") as journal:
            # Share quota clocks across runs; each run gets isolated evidence and memoization.
            locks, next_at = {}, {}
            for index, (model, search, strategy, case, repetition) in enumerate(jobs, 1):
                wire = Wire(client)
                wire.locks, wire.next_at = locks, next_at
                run_started_at = datetime.now(timezone.utc).isoformat()
                if model:
                    row = await research(wire, MODELS[model], search, case, strategy=strategy, rounds=args.rounds,
                                         calls=args.calls, timeout=args.timeout, max_tokens=args.max_tokens,
                                         results=args.results, page_chars=args.page_chars)
                else:
                    row = await retrieval_run(wire, search, case, args.timeout, args.results, args.page_chars)
                row.update(repetition=repetition, candidate=model or "retrieval-only", started_at=run_started_at)
                row = json.loads(redact(row))
                document["runs"].append(row)
                document["summary"] = aggregate(document["runs"])
                document["paired_comparisons"] = paired_comparisons(document["runs"], baseline)
                journal.write(json.dumps(row, ensure_ascii=False) + "\n")
                journal.flush()
                stem.with_suffix(".json").write_text(redact(document), encoding="utf-8")
                write_report(document, stem.with_suffix(".md"))
                write_csvs(document, stem)
                print(f"[{index}/{len(jobs)}] {model or 'retrieval'} {search} {strategy} {case['id']}: {row['status']} {row['total_s']:.2f}s", flush=True)
    print(json.dumps(aggregate(document["runs"]), indent=2))
    return int(any(r["status"] != "ok" for r in document["runs"]))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    arguments = sys.argv[1:] if argv is None else list(argv)
    if arguments[:1] == ["tune"]:
        # Engine tuning: the reader's own agent and search provider answer real
        # cases and another agent grades them. Its own commands; it spends
        # nothing without --yes (see app.tuning.cli).
        from app.tuning.cli import main as tune

        return tune(arguments[1:])
    parser = argparse.ArgumentParser(description=__doc__ + " `tune` runs engine tuning.")
    parser.add_argument("--env-file", default=".env", help="load only the five named provider keys; existing environment wins")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="key presence and configured candidates; no API calls")
    report = commands.add_parser("report", help="rebuild Markdown without API calls")
    report.add_argument("source")
    for command in ("retrieval", "run"):
        sub = commands.add_parser(command)
        sub.add_argument("--searches", default="deepseek-content,deepseek-snippets")
        sub.add_argument("--models", default="mercury-3,mercury-2.5,ministral-14b,ministral-8b", help="Large 4 and DeepSeek control are explicit opt-ins; all includes both")
        sub.add_argument("--strategies", default="parallel,eager")
        sub.add_argument("--cases", default=str(Path(__file__).with_name("cases.json")))
        sub.add_argument("--limit", type=int, default=0)
        sub.add_argument("--reps", type=int, default=1)
        sub.add_argument("--rounds", type=int, default=4)
        sub.add_argument("--calls", type=int, default=12)
        sub.add_argument("--timeout", type=float, default=60)
        sub.add_argument("--max-tokens", type=int, default=3000)
        sub.add_argument("--results", type=int, default=5, help="search results per query (1–20)")
        sub.add_argument("--page-chars", type=int, default=6000, help="page text characters per source passed to the model")
        sub.add_argument("--seed", type=int, default=42)
        sub.add_argument("--http2", action="store_true", help="enable HTTP/2 multiplexing (requires h2); negotiated version is recorded")
        sub.add_argument("--out", default=".local-evaluation/searchbench")
    args = parser.parse_args(argv)
    load_keys(Path(args.env_file))
    try:
        if args.command == "list":
            print(json.dumps({"models": {name: {"model": m.model, "key_env": m.key_env, "ready": bool(os.environ.get(m.key_env))} for name, m in MODELS.items()},
                              "searches": {name: {"key_env": s[1], "ready": bool(os.environ.get(s[1]))} for name, s in SEARCHES.items()}}, indent=2))
            return 0
        if args.command == "report":
            path = Path(args.source)
            write_report(json.loads(path.read_text(encoding="utf-8")), path.with_suffix(".md"))
            write_csvs(json.loads(path.read_text(encoding="utf-8")), path.with_suffix(""))
            return 0
        if min(args.reps, args.rounds, args.calls, args.max_tokens) < 1 or args.timeout <= 0 or args.limit < 0:
            raise ValueError("Budgets and repetitions must be positive; limit must be nonnegative")
        if not 1 <= args.results <= 20 or args.page_chars < 100:
            raise ValueError("Results must be 1–20 and page-chars at least 100")
        return asyncio.run(sweep(args))
    except ValueError as error:
        parser.error(str(error))


if __name__ == "__main__":
    raise SystemExit(main())
