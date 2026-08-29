"""Verdict-quality eval over packs/cars/pipeline/gold/gold.yaml (11 hand-judged entries).

Acceptance bar before judge.py's gates may be retired: every gold entry with
verdict: incorrect must NOT come back supported + product_value=high. Prints
per-entry outcomes; exit 1 on any must-catch failure. Costs ~11 sync
deepseek-v4-flash calls."""

import sys
from pathlib import Path

import yaml

from packs.cars.pipeline.ledger import verdict
from kriko.ledger.costs import Budget

GOLD = Path(__file__).parent.parent / "gold" / "gold.yaml"


def main() -> int:
    entries = yaml.safe_load(GOLD.read_text()) or []
    budget = Budget()
    client = verdict._client()
    failures = 0
    for e in entries:
        payload = {
            "component_id": e.get("claim_key", "unknown"),
            "domain": e.get("domain", "general"),
            "sibling_codes": [],
            "evidence": [{
                "title": e["title"], "rationale": e.get("rationale", ""),
                "inspection_advice": "", "severity": e.get("severity", "medium"),
                "quote": e.get("quote", ""), "component_hint": None,
                "url": "gold", "site_or_channel": "gold", "source_type": "page",
                "target_hint": e.get("claim_key", ""),
            }],
        }
        m = client.chat.completions.create(
            model=verdict.VERDICT_MODEL, max_tokens=1200,
            response_format={"type": "json_object"},
            messages=[{"role": "user", "content": verdict.build_prompt(payload)}])
        budget.charge(verdict.VERDICT_MODEL,
                      m.usage.prompt_tokens, m.usage.completion_tokens)
        try:
            v = verdict.parse_verdict(m.choices[0].message.content)
            # Gate the model's product_value on the deterministic pre-check the
            # pipeline applies at export — measure what actually ships, not the
            # raw (unreliable) LLM self-report.
            pv = verdict.gate_product_value([e["title"]], v)
            kept = v["supported"] and pv == "high"
        except ValueError:
            kept = False
        want_kept = e.get("verdict") == "correct"
        ok = kept == want_kept
        if not ok and not want_kept:
            failures += 1        # must-catch: a known-bad claim survived
        print(f"{'OK ' if ok else 'MISS'} kept={kept} want={want_kept}  {e['title'][:60]}")
    print(budget.report())
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
