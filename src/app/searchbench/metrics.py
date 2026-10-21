"""Token ledger, Wilson intervals and task-clustered bootstrap comparisons."""

import math
import random
import statistics
from collections import defaultdict


TOKEN_FIELDS = ("input", "cached_input", "output", "reasoning", "total")


def normalized_usage(usage):
    def count(value):
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None
    incoming, outgoing = count(usage.get("prompt_tokens")), count(usage.get("completion_tokens"))
    details = usage.get("prompt_tokens_details") or {}
    completed = usage.get("completion_tokens_details") or {}
    cached = details.get("cached_tokens", usage.get("cached_input_tokens", usage.get("prompt_cache_hit_tokens")))
    total = count(usage.get("total_tokens"))
    return {"input": incoming, "cached_input": count(cached), "output": outgoing,
            "reasoning": count(completed.get("reasoning_tokens", usage.get("reasoning_tokens"))),
            "total": total if total is not None else incoming + outgoing if incoming is not None and outgoing is not None else None}


def ledger(row):
    events = row["events"]
    models = [e for e in events if e["kind"] == "model"]
    usages = [normalized_usage(e.get("usage") or {}) for e in models]
    for event, usage in zip(models, usages):
        event["tokens"] = usage
    row["tokens"] = {field: sum(u[field] for u in usages) if usages and all(u[field] is not None for u in usages) else None for field in TOKEN_FIELDS}
    row["known_tokens"] = {field: sum(u[field] or 0 for u in usages) for field in TOKEN_FIELDS}
    row["usage_complete"] = bool(models) and all(row["tokens"][field] is not None for field in ("input", "output", "total"))
    row["model_calls"] = len(models)
    row["http_requests"] = len(events)
    row["search_requests"] = sum(e["kind"].endswith("search") for e in events)
    row["fetch_requests"] = sum(e["kind"].endswith(("fetch", "contents", "extract")) for e in events)
    row["provider_credits"] = sum(e.get("credits") or 0 for e in events)
    row["credits_reported"] = any(e.get("credits") is not None for e in events)
    costs = [e.get("cost_usd") for e in events]
    row["known_cost_usd"] = sum(c for c in costs if c is not None)
    row["cost_complete"] = bool(costs) and all(c is not None for c in costs)
    row["cost_usd"] = row["known_cost_usd"] if row["cost_complete"] else None
    for label, subset in (("model", models), ("retrieval", [e for e in events if e["kind"] != "model"])):
        amounts = [e.get("cost_usd") for e in subset]
        row[label + "_cost_usd"] = sum(amounts) if all(c is not None for c in amounts) else None
    return row


def wilson(successes, n):
    if not n:
        return None
    z = 1.959963984540054
    proportion = successes / n
    denominator = 1 + z * z / n
    center = (proportion + z * z / (2 * n)) / denominator
    half = z * math.sqrt(proportion * (1 - proportion) / n + z * z / (4 * n * n)) / denominator
    return [max(0, center - half), min(1, center + half)]


def cluster_interval(rows, field, *, samples=2000, seed=42):
    """Bootstrap whole tasks, retaining repetitions; no interval for one task."""
    from app.searchbench.report import percentile

    clusters = defaultdict(list)
    for row in rows:
        if row.get(field) is not None:
            clusters[row["case"]].append(row[field])
    if len(clusters) < 2:
        return None
    rng = random.Random(seed)
    groups = list(clusters.values())
    means = []
    for _ in range(samples):
        draw = [value for group in rng.choices(groups, k=len(groups)) for value in group]
        means.append(statistics.mean(draw))
    return [percentile(means, .025), percentile(means, .975)]


def paired_comparisons(rows, baseline):
    """Pair by task and repetition; report complete successful pairs only."""
    groups = defaultdict(dict)
    for row in rows:
        key = (row.get("candidate", row.get("model", "retrieval-only")), row["search"], row["strategy"])
        groups[key][(row["case"], row["repetition"])] = row
    reference = groups.get(tuple(baseline), {})
    comparisons = []
    for key, group in groups.items():
        if key == tuple(baseline):
            continue
        differences = []
        for pair in reference.keys() & group.keys():
            a, b = reference[pair], group[pair]
            if a["status"] == b["status"] == "ok":
                differences.append({"case": pair[0], "delta_s": b["total_s"] - a["total_s"],
                                    "delta_cost_usd": b["cost_usd"] - a["cost_usd"] if a.get("cost_usd") is not None and b.get("cost_usd") is not None else None,
                                    "delta_tokens": b["tokens"]["total"] - a["tokens"]["total"] if a["tokens"]["total"] is not None and b["tokens"]["total"] is not None else None})
        comparisons.append({"candidate": key, "baseline": baseline, "successful_pairs": len(differences),
                            "unpaired_or_failed": len(reference.keys() | group.keys()) - len(differences),
                            "mean_latency_delta_s": statistics.mean(d["delta_s"] for d in differences) if differences else None,
                            "cost_pairs": sum(d["delta_cost_usd"] is not None for d in differences),
                            "token_pairs": sum(d["delta_tokens"] is not None for d in differences),
                            "mean_cost_delta_usd": statistics.mean(d["delta_cost_usd"] for d in differences if d["delta_cost_usd"] is not None) if any(d["delta_cost_usd"] is not None for d in differences) else None,
                            "mean_tokens_delta": statistics.mean(d["delta_tokens"] for d in differences if d["delta_tokens"] is not None) if any(d["delta_tokens"] is not None for d in differences) else None,
                            "latency_delta_ci95": cluster_interval(differences, "delta_s"),
                            "cost_delta_ci95": cluster_interval(differences, "delta_cost_usd"),
                            "tokens_delta_ci95": cluster_interval(differences, "delta_tokens")})
    return comparisons
