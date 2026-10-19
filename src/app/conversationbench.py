"""Conversation acceptance scenarios for any configured answering provider.

Default invocation only prints the plan. --run explicitly sends requests to the
selected accounts. Search/page inputs are fixed; agent availability is reported
separately from a measured failure. No result is written to the reader's history.
"""

import argparse
import json
import sqlite3
import tempfile
import time
from pathlib import Path
from typing import cast

from app import chat, chatdata
from app.turnusage import TurnUsage
from app.web import state, tasks
from app.web.jobs import Progress
from app.web.settings import Settings
from app.workcontract import empty_offer

PAGES = {
    "https://fixtures.example/a": "Product A: 199 EUR, weight 2 kg. Sold in Germany. Manufacturer specification.",
    "https://fixtures.example/b": "Product B: 249 EUR, weight 3 kg. Sold in Germany. Manufacturer specification.",
}
SCENARIOS = (
    {"id": "ownership", "message": "Explain how induction charging works.", "expected": ["magnetic"]},
    {"id": "two-links", "message": "Compare https://fixtures.example/a and https://fixtures.example/b, with sources and prices.", "expected": ["199", "249"], "pages": 2},
    {"id": "remember-budget", "message": "Which one meets my budget?", "expected": ["199", "220"], "history": True},
    {"id": "latest-correction", "message": "Correction: my budget is now 180 EUR. Which one can I afford?", "expected": ["180", "199", "249"], "history": True},
)


class Quiet:
    job_id = "conversation-benchmark"

    def set(self, *args): pass
    def log(self, *args): pass
    def check(self): pass
    def partial(self, *args): pass


def run(agent: str, scenario: dict, reader: Settings) -> dict:
    from app.providers import agent_ready
    from app import localplane

    if agent != "local" and not agent_ready(reader.app_state_path, agent):
        return {"agent": agent, "scenario": scenario["id"], "status": "unavailable", "reason": "Agent or credentials are not available."}
    if agent == "local" and not localplane.is_ready(reader.app_state_path):
        return {"agent": agent, "scenario": scenario["id"], "status": "unavailable", "reason": "The local model is not ready."}
    with tempfile.TemporaryDirectory(prefix="kriko-conversation-bench-") as directory:
        root = Path(directory)
        copied = root / "app.sqlite"
        if reader.app_state_path.exists():
            source, target = sqlite3.connect(str(reader.app_state_path)), sqlite3.connect(str(copied))
            try: source.backup(target)
            finally: source.close(); target.close()
        conn = state.connect(copied)
        conn.close()
        settings = Settings(app_state_path=copied, store_path=root / "knowledge.sqlite", analysis_log_path=root / "analysis.jsonl")
        meter = TurnUsage()
        params = {"harness": agent, "backend": "local" if agent == "local" else "harness", "max_tokens": 2400}
        quiet = cast(Progress, Quiet())
        identity: dict = {}

        def ask(prompt):
            answer, _ = tasks._ask_about_checks(settings, meter.parameters(params), quiet,
                prompt + "\nThis is a fixed-corpus benchmark. Use the provided pages only; do not browse outside them.",
                timeout=60.0, on_usage=meter.record, on_agent=identity.update)
            return answer

        history = ([{"role": "reader", "text": "I live in Germany. My budget is 220 EUR."}]
                   + [{"role": "agent", "text": "We discussed another detail."}] * 10
                   + [{"role": "agent", "text": "Product A costs 199 EUR, B costs 249 EUR.", "sources": ["web_search"]}]
                   if scenario.get("history") else [])
        opened = []
        def read(url):
            opened.append(url)
            return PAGES.get(url, "")
        ctx = chatdata.Context(web_search=lambda q, n: [{"url": url, "title": url} for url in PAGES], web_read=read)
        began = time.monotonic()
        try:
            out = chat.run_turn(scenario["message"], ask=ask, ctx=ctx, history=history)
            answer = out["answer"]
            checks = {"delivered_work": not empty_offer(answer) and len(answer.split()) >= 8,
                      "expected_facts": all(word.casefold() in answer.casefold() for word in scenario["expected"]),
                      "all_links_read": len(set(opened)) >= scenario.get("pages", 0),
                      "no_protocol_reply": not chat.search_request(answer),
                      "no_unverified_reference": out.get("verification", {}).get("status") != "unverified"}
            return {"agent": agent, "resolved_agent": identity, "scenario": scenario["id"], "status": "passed" if all(checks.values()) else "failed",
                    "checks": checks, "answer": answer, "ms": round((time.monotonic() - began) * 1000), **meter.snapshot()}
        except Exception as error:
            return {"agent": agent, "scenario": scenario["id"], "status": "failed", "reason": str(error), **meter.snapshot()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", action="append", required=True, help="local, a CLI ID, or an API agent ID; repeat for multiple providers")
    parser.add_argument("--run", action="store_true", help="Send requests using the selected accounts; provider charges can apply")
    parser.add_argument("--out", type=Path, help="Write the JSON report here")
    args = parser.parse_args()
    rows = ([run(agent, scenario, Settings.from_env()) for agent in args.agent for scenario in SCENARIOS]
            if args.run else [{"agent": agent, **scenario, "status": "planned"} for agent in args.agent for scenario in SCENARIOS])
    report = {"suite": "conversation-readiness", "grading": "Deterministic completion, fact, source and continuity checks; semantic review is still required.", "trials": rows}
    encoded = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        args.out.write_text(encoded + "\n", encoding="utf-8")
    else:
        print(encoded)
    return int(any(row["status"] in {"failed", "unavailable"} for row in rows))


if __name__ == "__main__":
    raise SystemExit(main())
