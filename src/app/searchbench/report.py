"""Rebuildable reports: retain failures and distinguish structural quality from truth."""

import math
import csv
import json
import statistics
from collections import defaultdict
from pathlib import Path

from app.searchbench.metrics import TOKEN_FIELDS, cluster_interval, wilson, paired_comparisons


def percentile(values, p):
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * p
    low, high = math.floor(position), math.ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def aggregate(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[(row.get("model", "retrieval-only"), row["search"], row.get("strategy", "retrieval"))].append(row)
    summaries = []
    for (model, search, strategy), group in groups.items():
        ok = [r for r in group if r["status"] == "ok"]
        times = [r["total_s"] for r in ok]
        first = [r["first_answer_text_s"] for r in ok if r.get("first_answer_text_s") is not None]
        summary = {"model": model, "search": search, "strategy": strategy, "n": len(group),
                          "ok": len(ok), "failures": len(group) - len(ok),
                          "success_rate_ci95_wilson": wilson(len(ok), len(group)),
                          "mean_s": statistics.mean(times) if times else None,
                          "mean_s_ci95_task_bootstrap": cluster_interval(ok, "total_s"),
                          "stddev_s": statistics.stdev(times) if len(times) >= 2 else None,
                          "median_s": statistics.median(times) if times else None,
                          "p95_s": percentile(times, .95) if len(times) >= 20 else None,
                          "max_s": max(times) if times else None,
                          "first_answer_median_s": statistics.median(first) if first else None,
                          "known_cost_usd": sum(r.get("known_cost_usd", 0) for r in group),
                          "cost_complete": all(r.get("cost_complete", False) for r in group),
                          "mean_cost_usd": statistics.mean(r["cost_usd"] for r in group) if all(r.get("cost_usd") is not None for r in group) else None,
                          "cost_usd_ci95_task_bootstrap": cluster_interval(group, "cost_usd") if all(r.get("cost_usd") is not None for r in group) else None,
                          "search_requests": sum(r.get("search_requests", 0) for r in group),
                          "fetch_requests": sum(r.get("fetch_requests", 0) for r in group),
                          "provider_credits": sum(r.get("provider_credits", 0) for r in group),
                          "mean_pages_read": statistics.mean(r.get("quality", {}).get("pages_read", 0) for r in group),
                          "citation_errors": sum(len(r.get("quality", {}).get("unknown_citations", [])) for r in group)}
        for field in TOKEN_FIELDS:
            values = [r.get("tokens", {}).get(field) for r in group]
            summary[field + "_tokens"] = sum(values) if all(v is not None for v in values) else None
            summary["known_" + field + "_tokens"] = sum(r.get("known_tokens", {}).get(field, 0) for r in group)
        summary["mean_total_tokens"] = summary["total_tokens"] / len(group) if summary["total_tokens"] is not None else None
        summaries.append(summary)
    return summaries


def write_report(document, path: Path):
    rows = document["runs"]
    summaries = aggregate(rows)
    def number(value):
        return "—" if value is None else f"{value:.2f}"
    lines = ["# Web research experiments", "", f"Measured: {document['created_at']}", "",
             "Exploratory measurements, not a Google parity claim. No local response cache survives a run; provider caches may apply.",
             "Latency statistics include successful runs only; failure counts include every attempted run. p95 requires 20 successes per group.",
             "Connection pools are reused across runs. Run order is seeded and shuffled; the first request can include connection setup.",
             "Costs are dated estimates from reported usage, not invoices. A ≥ means some cost is unknown. Tavily credits are retained separately.",
             "Citation IDs and keyword coverage are structural diagnostics; factual correctness and citation entailment are unscored.", "",
             "| Model | Search | Strategy | OK / n | Answer first text (s) | Median (s) | p95 (s) | Max (s) | Read pages/run | Known cost ($) |",
             "|---|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    for summary in summaries:
        lines.append("| " + " | ".join([summary["model"], summary["search"], summary["strategy"],
            f"{summary['ok']}/{summary['n']}", number(summary["first_answer_median_s"]), number(summary["median_s"]),
            number(summary["p95_s"]), number(summary["max_s"]), number(summary["mean_pages_read"]),
            ("" if summary["cost_complete"] else "≥ ") + f"{summary['known_cost_usd']:.6f}"]) + " |")
    if document.get("config"):
        settings = document["config"]
        lines.extend(["", "Experiment settings: " + "; ".join(f"`{key}={settings[key]}`" for key in ("reps", "rounds", "calls", "timeout", "max_tokens", "results", "page_chars", "http2", "seed") if key in settings) + ".",
                      "", "Harness source SHA-256: `" + document.get("source_sha256", "unrecorded") + "`."])
    if document.get("models"):
        lines.extend(["", "## Price assumptions", "", "USD per million tokens; estimated, not an invoice. Price date: " + document.get("price_date", "unknown") + ". Mercury 3 and Large 4 include the documented launch discount.", "",
                      "| Model | Input | Cached input | Output | Reasoning effort |", "|---|---:|---:|---:|---|"])
        for model in document["models"].values():
            rates = ["—" if model[key] is None else f"{model[key]:g}" for key in ("input_usd", "cached_usd", "output_usd")]
            lines.append("| " + " | ".join([model["model"], *rates, model.get("effort") or "provider default"]) + " |")
    lines.extend(["", "## Tokens and cost", "", "All attempts, including failed generations. Cached input is a subset of input; reasoning is a subset of output. Never add either twice.",
                  "A dash means the provider did not report every component. Raw per-call usage is retained in JSON.", "",
                  "| Model | Search | Strategy | Input | Cached input | Output | Reasoning | Total | Mean total/run | Mean $/attempt | Searches | Fetches | Credits |",
                  "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"])
    for summary in summaries:
        cells = [summary["model"], summary["search"], summary["strategy"]]
        cells += [str(summary[f + "_tokens"]) if summary[f + "_tokens"] is not None else "—" for f in TOKEN_FIELDS]
        cells += [number(summary["mean_total_tokens"]), f"{summary['mean_cost_usd']:.6f}" if summary["mean_cost_usd"] is not None else "—",
                  str(summary["search_requests"]), str(summary["fetch_requests"]), str(summary["provider_credits"])]
        lines.append("| " + " | ".join(cells) + " |")
    lines.extend(["", "## Statistical measures", "", "95% mean-latency intervals bootstrap whole questions (2,000 draws, seed 42); repetitions remain in their task cluster. At least two distinct questions are required.",
                  "Wilson success intervals are nominal binomial diagnostics; repeated questions can violate the independence assumption. Small sweeps are screening experiments.", "",
                  "| Model | Search | Strategy | Mean (s) | SD (s) | Mean latency 95% CI | Success 95% Wilson CI |", "|---|---|---|---:|---:|---|---|"])
    for summary in summaries:
        def interval(value):
            return "—" if value is None else f"[{value[0]:.2f}, {value[1]:.2f}]"
        lines.append("| " + " | ".join([summary["model"], summary["search"], summary["strategy"], number(summary["mean_s"]), number(summary["stddev_s"]),
                     interval(summary["mean_s_ci95_task_bootstrap"]), interval(summary["success_rate_ci95_wilson"])]) + " |")
    if document.get("baseline"):
        lines.extend(["", "Paired baseline: `" + " / ".join(document["baseline"]) + "`. Negative deltas favor the candidate. Only successful matched question/repetition pairs enter these differences; exclusions are shown.", "",
                      "| Candidate | Successful pairs | Unpaired or failed | Mean delta (s) | Delta 95% task-bootstrap CI |", "|---|---:|---:|---:|---|"])
        for comparison in paired_comparisons(rows, document["baseline"]):
            lines.append("| " + " | ".join([" / ".join(comparison["candidate"]), str(comparison["successful_pairs"]), str(comparison["unpaired_or_failed"]),
                         number(comparison["mean_latency_delta_s"]), interval(comparison["latency_delta_ci95"])]) + " |")
    lines.extend(["", "## Individual runs", "", "| Case | Model | Search | Strategy | Status | Total (s) | First result (s) | Calls |", "|---|---|---|---|---|---:|---:|---:|"])
    for row in rows:
        lines.append("| " + " | ".join([row["case"], row.get("model", "retrieval-only"), row["search"], row.get("strategy", "retrieval"),
            row["status"], number(row["total_s"]), number(row.get("first_result_s")), str(row.get("http_requests", 0))]) + " |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_csvs(document, stem: Path):
    """Flat trial and request tables for R, scipy, pandas or spreadsheets."""
    trials, requests = [], []
    for index, row in enumerate(document["runs"], 1):
        shared = {key: row.get(key) for key in ("case", "repetition", "candidate", "model", "search", "strategy")}
        shared.update(experiment=stem.name, trial=index)
        shared.update({"setting_" + key: document.get("config", {}).get(key) for key in ("results", "page_chars", "max_tokens", "http2", "rounds", "calls", "timeout")})
        trial = {**shared, **{k: row.get(k) for k in ("started_at", "status", "total_s", "first_result_s", "first_answer_text_s", "model_calls", "search_requests", "fetch_requests", "http_requests", "cache_hits", "known_cost_usd", "cost_usd", "cost_complete", "usage_complete", "model_cost_usd", "retrieval_cost_usd", "provider_credits", "credits_reported")}}
        trial.update({"tokens_" + k: row.get("tokens", {}).get(k) for k in TOKEN_FIELDS})
        trial.update({"quality_" + k: v for k, v in row.get("quality", {}).items() if not isinstance(v, (list, dict))})
        trials.append(trial)
        for event_index, event in enumerate(row["events"], 1):
            request = {**shared, "request_index": event_index,
                       **{k: event.get(k) for k in ("kind", "provider", "resolved_model", "start_s", "duration_s", "first_text_s", "first_tool_s", "status", "error", "finish_reason", "http_version", "cost_usd", "credits")}}
            request.update({"tokens_" + k: event.get("tokens", {}).get(k) for k in TOKEN_FIELDS})
            requests.append(request)
    comparisons = paired_comparisons(document["runs"], document["baseline"]) if document.get("baseline") else []
    for suffix, records in (("trials", trials), ("requests", requests), ("summary", aggregate(document["runs"])), ("comparisons", comparisons)):
        columns = list(dict.fromkeys(key for record in records for key in record))
        with stem.with_suffix("." + suffix + ".csv").open("w", encoding="utf-8", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=columns)
            writer.writeheader()
            writer.writerows({k: json.dumps(v) if isinstance(v, (list, dict, tuple)) else v for k, v in r.items()} for r in records)
