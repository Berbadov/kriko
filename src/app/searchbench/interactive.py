"""Pack frozen product results into a compact, offline-data interactive view."""

import argparse
import json
from pathlib import Path

from app.searchbench.accuracy import citation_ids


LABELS = {
    "m25-deepseek": "Mercury 2.5 · DeepSeek",
    "m3-deepseek": "Mercury 3 · DeepSeek",
    "m8-deepseek": "Ministral 8B · DeepSeek",
    "m14-deepseek": "Ministral 14B · DeepSeek",
    "large4-deepseek": "Large 4 · DeepSeek",
    "m25-exa": "Mercury 2.5 · Exa",
    "m25-tavily": "Mercury 2.5 · Tavily",
    "m25-federated": "Mercury 2.5 · all searches",
    "m25-verify-m3": "DeepSeek · 2.5 → 3",
    "m25-federated-verify-m3": "All searches · 2.5 → 3",
    "m25-parallel": "Mercury 2.5 · parallel",
}


def build(folders, output):
    blocks = []
    for index, folder in enumerate(folders, 1):
        document = json.loads((folder / "results.json").read_text(encoding="utf-8"))
        rows = []
        for trial, row in enumerate(document["runs"]):
            cited = citation_ids(row["answer"])
            rows.append({
                "id": f"{index}-{trial}", "profile": row["profile"], "case": row["case"],
                "question": row["question"], "category": row["category"], "job": row["complexity"],
                "seconds": round(row["total_s"], 4), "status": row["status"],
                "accepted": row.get("accuracy", {}).get("accepted"),
                "cost": row["known_cost_usd"], "costComplete": row["cost_complete"],
                "tokens": row["known_tokens"], "reportedTokens": row["tokens"],
                "tokensComplete": row["tokens"]["total"] is not None,
                "searches": row["search_requests"], "fetches": row["fetch_requests"],
                "answer": row["answer"],
                "sources": [{"id": s["id"], "url": s["url"]} for s in row["sources"] if s["id"] in cited],
                "audits": [{"judge": model, "accepted": audit.get("accepted"),
                            "summary": audit.get("detail", {}).get("summary", audit.get("error", "No final answer")),
                            "recall": audit.get("fact_recall"), "support": audit.get("citation_support_rate"),
                            "primaries": audit.get("primary_citations"),
                            "gaps": [{"id": c["id"], "credit": c["credit"], "reason": c.get("reason", "")}
                                     for c in audit.get("detail", {}).get("criteria", []) if c["credit"] < 1]}
                           for model, audit in row.get("audits", {}).items()],
            })
        blocks.append({"id": str(index), "label": f"Block {index} · {len(rows)} attempts", "rows": rows})
    data = json.dumps({"blocks": blocks, "labels": LABELS}, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    fragment = Path(__file__).with_name("interactive.html").read_text(encoding="utf-8").replace("__BENCHMARK_DATA__", data)
    if len(fragment.encode("utf-8")) >= 1_000_000:
        raise ValueError("Interactive view exceeds the 1 MB inline limit")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(fragment, encoding="utf-8")
    print(f"{output}: {sum(len(b['rows']) for b in blocks)} original answers; {len(fragment.encode('utf-8')):,} bytes")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folders", nargs="+", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    build(args.folders, args.out)


if __name__ == "__main__":
    main()
