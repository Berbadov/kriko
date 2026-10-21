"""Plain HTML benchmark tables: static sort links and native expandable logs."""

import argparse
import html
import json
import statistics
from pathlib import Path

from app.searchbench.accuracy import citation_ids


def fact_f1_proxy(audit):
    """A descriptive composite, not classification F1 over matched propositions."""
    if audit.get("status") == "no_answer":
        return 0.0, 0.0, 0.0
    if audit.get("status") != "scored":
        return None
    claims = audit.get("detail", {}).get("claims", [])
    precision = sum(c.get("correct") is True for c in claims) / len(claims) if claims else 0.0
    recall = audit["fact_recall"]
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return f1, precision, recall


def summarize(rows):
    summaries = []
    for profile in sorted({r["profile"] for r in rows}):
        group = [r for r in rows if r["profile"] == profile]
        factual = [r for r in group if r["complexity"] != "identity"]
        scores = []
        for row in factual:
            audits = list(row.get("audits", {}).values())
            results = [fact_f1_proxy(a) for a in audits]
            if len(results) == 2 and all(s is not None for s in results):
                scores.append(tuple(statistics.mean(s[i] for s in results) for i in range(3)))
        summaries.append({
            "profile": profile, "rows": group, "f1": statistics.mean(s[0] for s in scores) if scores else None,
            "precision": statistics.mean(s[1] for s in scores) if scores else None,
            "recall": statistics.mean(s[2] for s in scores) if scores else None,
            "f1_n": len(scores), "factual_n": len(factual),
            "accepted": sum(r.get("accuracy", {}).get("accepted") is True for r in group), "n": len(group),
            "seconds": statistics.mean(r["total_s"] for r in group),
            "cost": statistics.mean(r["known_cost_usd"] for r in group),
            "cost_complete": all(r["cost_complete"] for r in group),
            "tokens": statistics.mean(r["known_tokens"]["total"] for r in group),
            "tokens_complete": all(r["tokens"]["total"] is not None for r in group),
        })
    return summaries


def build(folders, output):
    from app.searchbench.interactive import LABELS

    output.mkdir(parents=True, exist_ok=True)
    def esc(value):
        return html.escape(str(value))
    def percent(value):
        return "—" if value is None else f"{value:.1%}"
    def name(block, metric="f1", direction="desc"):
        return f"block-{block}-{metric}-{direction}.html"
    metrics = {"f1": "F1 proxy", "accepted": "Accepted", "seconds": "Mean seconds", "cost": "$/attempt", "tokens": "Tokens/attempt"}
    summaries = []
    documents = [json.loads((p / "results.json").read_text(encoding="utf-8")) for p in folders]
    for block, document in enumerate(documents, 1):
        summary = summarize(document["runs"])
        summaries.append(summary)
        logs = {}
        for group in summary:
            entries = []
            for row in group["rows"]:
                accepted = row.get("accuracy", {}).get("accepted")
                verdict = "PASS" if accepted is True else "FAIL" if accepted is False else "UNSCORED"
                amount = ("" if row["cost_complete"] else "≥ ") + f"${row['known_cost_usd']:.5f}"
                entry = f"<details><summary>{esc(row['case'])} · {verdict} · {row['total_s']:.2f}s · {amount}</summary>"
                entry += f"<p>{esc(row['question'])}</p><pre>{esc(row['answer'] or 'No final answer returned.')}</pre>"
                entry += "<details><summary>Request log</summary><table><tr><th>Provider / model</th><th>Kind</th><th>Status</th><th>Seconds</th><th>USD</th><th>Input / output tokens</th></tr>"
                for event in row["events"]:
                    tokens = event.get("tokens", {})
                    duration = event.get("duration_s")
                    cost = event.get("cost_usd")
                    values = [event.get("model") or event.get("provider"), event.get("kind"), event.get("status"),
                              "—" if duration is None else f"{duration:.3f}", "—" if cost is None else f"{cost:.6f}",
                              f"{tokens.get('input', '—')} / {tokens.get('output', '—')}"]
                    entry += "<tr>" + "".join(f"<td>{esc(v)}</td>" for v in values) + "</tr>"
                entry += "</table></details><details><summary>Judge log + citations</summary>"
                for model, audit in row.get("audits", {}).items():
                    score = fact_f1_proxy(audit) if row["complexity"] != "identity" else None
                    numbers = "" if score is None else f" · F1 proxy {score[0]:.1%} · P {score[1]:.1%} · R {score[2]:.1%}"
                    entry += f"<p><b>{esc(model)}{numbers}</b><br>{esc(audit.get('detail', {}).get('summary', audit.get('status')))}</p>"
                cited = citation_ids(row["answer"])
                for source in row["sources"]:
                    if source["id"] in cited and source["url"].startswith(("https://", "http://")):
                        entry += f"<p><a href='{esc(source['url'])}' target='_blank' rel='noopener noreferrer'>{esc(source['id'])} · {esc(source['url'])}</a></p>"
                entries.append(entry + "</details></details>")
            logs[group["profile"]] = "".join(entries)
        for metric in metrics:
            for direction in ("asc", "desc"):
                ordered = sorted(summary, key=lambda r: (r[metric] is None, -(r[metric] or 0) if direction == "desc" else (r[metric] or 0), r["profile"]))
                page = "<!doctype html><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Benchmark results</title><style>body{font:15px system-ui;max-width:1150px;margin:28px auto;padding:0 16px;color:#202124;background:#fff}table{border-collapse:collapse;width:100%}td,th{text-align:left;border-bottom:1px solid #ddd;padding:10px}th small{white-space:nowrap}a{color:#1755a5}details{margin:8px 0}summary{cursor:pointer}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit}p{overflow-wrap:anywhere}.scroll{overflow-x:auto}.note{color:#555;font-size:13px}.logs>td{padding-top:0}h1{font-size:23px}nav{margin:16px 0}</style><h1>Benchmark results</h1>"
                page += "<nav>" + " · ".join(f"<a href='{name(i)}'>{'● ' if i == block else ''}Block {i} ({len(d['runs'])} attempts)</a>" for i, d in enumerate(documents, 1)) + "</nav>"
                page += f"<p>{esc(metrics[metric])}: {'low → high' if direction == 'asc' else 'high → low'}</p><div class='scroll'><table><tr><th>Stack</th>"
                for key, label in metrics.items():
                    page += f"<th>{label}<br><small><a href='{name(block,key,'asc')}' aria-label='{label} low to high'>↑ low</a> / <a href='{name(block,key,'desc')}' aria-label='{label} high to low'>↓ high</a></small></th>"
                page += "</tr>"
                for row in ordered:
                    values = [LABELS.get(row["profile"], row["profile"]), percent(row["f1"]), f"{row['accepted']}/{row['n']}",
                              f"{row['seconds']:.2f}", ("" if row["cost_complete"] else "≥ ") + f"{row['cost']:.5f}",
                              ("" if row["tokens_complete"] else "≥ ") + f"{row['tokens']:,.0f}"]
                    page += "<tr>" + "".join(f"<td>{esc(v)}</td>" for v in values) + "</tr>"
                    page += f"<tr class='logs'><td colspan='6'><details><summary>Logs · {len(row['rows'])} outputs · P {percent(row['precision'])} / R {percent(row['recall'])}</summary>{logs[row['profile']]}</details></td></tr>"
                page += "</table></div><p class='note'>F1 proxy: harmonic mean of audited-claim precision and required-fact recall, averaged over both judges and factual research attempts. Unknown claims count against precision; runtime failures score zero. Clarification tasks use the Accepted column. This composite is not standard classification F1. Costs include rejected attempts; ≥ means incomplete metering.</p>"
                (output / name(block, metric, direction)).write_text(page, encoding="utf-8")
    latest = name(len(documents))
    (output / "index.html").write_text((output / latest).read_text(encoding="utf-8"), encoding="utf-8")
    print(output / "index.html")
    for row in summaries[-1]:
        print(f"{row['profile']}: F1 proxy {percent(row['f1'])}, P {percent(row['precision'])}, R {percent(row['recall'])}, accepted {row['accepted']}/{row['n']}, {row['seconds']:.2f}s, ${row['cost']:.5f}/attempt")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folders", nargs="+", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    build(args.folders, args.out)


if __name__ == "__main__":
    main()
