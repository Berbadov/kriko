"""Measure one local quick look, stage by stage, on this machine.

The console's local tab answers "what is it doing right now". This answers
"what did each leg cost, and did changing it help" — the same rows, on the same
clock, written down so two runs can be compared.

    .venv/Scripts/python.exe tools/measure_local.py --product "Aster One"
    .venv/Scripts/python.exe tools/measure_local.py --product "Aster One" \
        --model gemma4:e2b --repeat 3 --output .local-evaluation/stages.jsonl

Every stage is timed where it happens (`providers/local_agent._measured` and
`_phase`), so the table's `in`/`out` are the model's own usage for that stage
and `t/s` is output tokens over that stage's milliseconds. Nothing is inferred
after the fact.

The stages are the ones this pipeline actually runs, which is worth saying
plainly: **there is no embedding stage**. The retrieval leg is a public search
engine (OpenSERP), the context is whole pages fitted to the model's window, and
selection is extractive evidence IDs — search-grounded generation, not vector
RAG. `fetch` is per page, because one slow host hidden inside an average is the
usual reason a "slow" run is slow.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from app import localplane, quicklook  # noqa: E402
from app.providers import local_asker  # noqa: E402
from app.tui import local  # noqa: E402

HEADER = f"{'stage':<10} {'calls':>5} {'fail':>4} {'secs':>7} {'in':>7} {'out':>7} {'t/s':>6} {'worst':>6}"


def run_one(product: str, plan: dict, args) -> dict:
    asker = local_asker(
        base_url=plan["url"], serving_name=plan["model"],
        search_base_url=plan["search_url"], search_kind=plan["search_kind"],
        timeout=plan["timeout"], runtime_options=plan.get("runtime_options"),
        context_tokens=plan.get("context_tokens"),
        output_language=plan.get("output_language", "auto"),
        search_language=plan.get("search_language", "en"),
        max_tokens=args.max_tokens,
    )
    asker.runtime = plan.get("runtime", {})
    said: list[str] = []

    def say(line: str) -> None:
        said.append(line)
        if args.verbose:
            print(f"  · {line}", file=sys.stderr)

    asker.on_action = say
    record = {
        "product": product, "model": plan["model"], "runtime_name": plan["name"],
        "runtime": {key: plan.get("runtime", {}).get(key) for key in
                    ("runtime", "device", "memory_bytes", "vram_bytes",
                     "context_tokens", "reason")},
        "search": plan.get("search_label", ""), "search_url": plan.get("search_url", ""),
        "context_tokens": plan.get("context_tokens"),
        "host": {"platform": platform.platform(), "machine": platform.machine(),
                 "logical_cpus": os.cpu_count()},
    }
    started = time.monotonic()
    try:
        reply = asker.ask_quick(product)
        found = quicklook.parse(reply, asker.sources)
        record.update(
            risks=found.get("risks") or [], specs=found.get("specs") or [],
            dropped=found.get("dropped", 0),
        )
        record["error"] = ""
    except Exception as error:  # noqa: BLE001 - a failed run is a measurement too
        record["error"] = f"{type(error).__name__}: {error}"
        record["risks"], record["specs"], record["dropped"] = [], [], 0
    record["wall_seconds"] = round(time.monotonic() - started, 3)
    # After the run, not before it: Ollama only reports where the model was
    # placed once it is loaded, and a probe taken before the first token says
    # `unknown` on a machine that is in fact using its GPU.
    if getattr(asker, "runtime", None):
        record["runtime"] = {key: asker.runtime.get(key) for key in
                             ("runtime", "device", "memory_bytes", "vram_bytes",
                              "context_tokens", "reason")}
    record["stages"] = asker.metrics
    record["coverage"] = asker.coverage
    record["identity"] = asker.identity
    record["actions"] = said
    return record


def show(record: dict) -> None:
    print(f"\nlocal quick look · {record['product']}")
    runtime = record.get("runtime") or {}
    where = " · ".join(str(one) for one in (
        record.get("model"), record.get("runtime_name"),
        runtime.get("device"), f"ctx {record.get('context_tokens')}",
        record.get("search")) if one)
    print(f"  {where}")
    if record.get("error"):
        print(f"  FAILED: {record['error']}")
    print("\n" + HEADER)
    for row in local.fold(record.get("stages") or []):
        tps = f"{row['tps']:.1f}" if row.get("tps") else "—"
        print(f"{row['stage']:<10} {row['calls']:>5} {row['failed']:>4} "
              f"{row['seconds']:>7.1f} {row['tokens_in']:>7} {row['tokens_out']:>7} "
              f"{tps:>6} {row['longest'] / 1000:>6.1f}")
    health = local.health(record.get("stages") or [], record.get("coverage"))
    print(f"\n  wall {record['wall_seconds']:.1f}s · {health['calls']} calls · "
          f"{health['failed']} failed · {health['tokens_out']} out tokens"
          + (f" · {health['tps']:.1f} tok/s" if health.get("tps") else ""))
    print(f"  kept {len(record.get('risks') or [])} risk(s), "
          f"{len(record.get('specs') or [])} spec(s), "
          f"{record.get('dropped', 0)} unsourced dropped")
    coverage = record.get("coverage") or {}
    if coverage:
        print(f"  coverage {coverage.get('status', '?')}: "
              f"{coverage.get('pages_read', 0)} pages read, "
              f"{coverage.get('pages_relevant', 0)} relevant, "
              f"{coverage.get('pages_extracted', 0)} evidence passes, "
              f"{coverage.get('accepted_candidates', 0)} accepted / "
              f"{coverage.get('rejected_candidates', 0)} rejected")
        for reason, count in sorted((coverage.get("rejection_reasons") or {}).items(),
                                    key=lambda item: -item[1])[:5]:
            print(f"    refused {count}× {reason}")
        for failure in coverage.get("errors") or []:
            print(f"    error at {failure.get('stage')}: {failure.get('reason')}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--product", required=True,
                        help="the product a quick look would be asked about")
    parser.add_argument("--url", default="", help="model server (default: discover)")
    parser.add_argument("--model", default="", help="model name (default: the recommended one)")
    parser.add_argument("--search-url", default="", help="OpenSERP base (default: 127.0.0.1:7000)")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--max-tokens", type=int, default=1024)
    parser.add_argument("--output", type=Path, default=None,
                        help="JSONL file; default .local-evaluation/local-stages/<stamp>.jsonl")
    parser.add_argument("--verbose", action="store_true",
                        help="also print every stage line as it happens")
    args = parser.parse_args()

    plan = localplane.resolve(None, url=args.url, model=args.model,
                              search_url=args.search_url)
    if not plan["ready"]:
        print(f"the local plane is not ready: {plan['reason']}")
        print("  start the model server and OpenSERP, or pass --url / --search-url")
        return 1
    output = args.output or (Path(".local-evaluation") / "local-stages"
                             / f"{time.strftime('%Y%m%d-%H%M%S')}.jsonl")
    output.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(1, max(1, args.repeat) + 1):
        print(f"\n=== run {attempt}/{args.repeat} ===")
        record = run_one(args.product, plan, args)
        record["attempt"] = attempt
        show(record)
        with output.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    print(f"\nwrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
