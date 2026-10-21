"""Accuracy-qualified product comparisons. Never pool incompatible experiments."""

import csv
import html
import json
import statistics
from collections import defaultdict

from app.searchbench.accuracy import primary_citations
from app.searchbench.metrics import TOKEN_FIELDS, cluster_interval, ledger
from app.searchbench.report import aggregate, percentile


def mean(values):
    return statistics.mean(values) if values else None


def summarize(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[row["profile"]].append(row)
    summaries = []
    for name, group in groups.items():
        known = [r for r in group if r.get("accuracy", {}).get("complete")]
        passed = [r for r in known if r["accuracy"]["accepted"]]
        complete_cost = all(r.get("cost_complete") for r in group)
        annotated = [{**r, "quality_pass": int(r["accuracy"]["accepted"])} for r in known]
        summary = {"profile": name, "n": len(group), "graded": len(known), "accepted": len(passed),
                   "execution_ok": sum(r["status"] == "ok" for r in group),
                   "pass_rate": len(passed) / len(group) if len(known) == len(group) else None,
                   "pass_rate_lower": len(passed) / len(group),
                   "pass_rate_upper": (len(passed) + len(group) - len(known)) / len(group),
                   "pass_ci95": cluster_interval(annotated, "quality_pass") if len(known) == len(group) else None,
                   "mean_attempt_s": mean([r["total_s"] for r in group]),
                   "attempt_s_ci95": cluster_interval(group, "total_s"),
                   "completion_median_s": statistics.median([r["total_s"] for r in group if r["status"] == "ok"]) if any(r["status"] == "ok" for r in group) else None,
                   "accepted_median_s": statistics.median([r["total_s"] for r in passed]) if passed else None,
                   "accepted_p95_s": percentile([r["total_s"] for r in passed], .95) if len(passed) >= 20 else None,
                   "known_cost_usd": sum(r["known_cost_usd"] for r in group),
                   "cost_complete": complete_cost,
                   "mean_cost_usd": mean([r["cost_usd"] for r in group]) if complete_cost else None,
                   "known_cost_per_attempt": sum(r["known_cost_usd"] for r in group) / len(group),
                   "known_cost_per_accepted": sum(r["known_cost_usd"] for r in group) / len(passed) if passed else None,
                   "fact_recall": mean([r["accuracy"]["fact_recall"] for r in known]),
                   "fact_f1": mean([r["accuracy"]["fact_f1"] for r in known if r["accuracy"].get("fact_f1") is not None]),
                   "fact_f1_ci95": cluster_interval([{"case": r["case"], "fact_f1": r["accuracy"].get("fact_f1")} for r in known if r["accuracy"].get("fact_f1") is not None], "fact_f1"),
                   "judge_agreement": mean([int(r["accuracy"]["judge_agreement"]) for r in known]),
                   "scope_violations": sum(r["accuracy"]["scope_violation"] for r in known),
                   "critical_fact_passes": sum(all(a.get("critical_ok", False) for a in r.get("audits", {}).values()) for r in known),
                   "false_claim_answers": sum(any(a.get("false_claims", 0) for a in r.get("audits", {}).values()) for r in known),
                   "grounding_failures": sum(any(a.get("citation_support_rate") is not None and a["citation_support_rate"] < .8 for a in r.get("audits", {}).values()) for r in known),
                   "search_requests": sum(r["search_requests"] for r in group),
                   "fetch_requests": sum(r["fetch_requests"] for r in group)}
        for field in TOKEN_FIELDS:
            summary["known_" + field + "_tokens"] = sum(r["known_tokens"][field] for r in group)
            summary[field + "_tokens_complete"] = all(r["tokens"][field] is not None for r in group)
        summary["known_tokens_per_attempt"] = summary["known_total_tokens"] / len(group)
        summary["pareto"] = False
        summaries.append(summary)
    # A lower-bound bill cannot dominate a fully priced alternative.
    eligible = [s for s in summaries if s["pass_rate"] is not None and s["cost_complete"]]
    for item in eligible:
        item["pareto"] = not any(
            other is not item and other["pass_rate"] >= item["pass_rate"]
            and other["mean_attempt_s"] <= item["mean_attempt_s"]
            and other["mean_cost_usd"] <= item["mean_cost_usd"]
            and (other["pass_rate"] > item["pass_rate"] or other["mean_attempt_s"] < item["mean_attempt_s"] or other["mean_cost_usd"] < item["mean_cost_usd"])
            for other in eligible)
    return sorted(summaries, key=lambda s: (-s["pass_rate_lower"], s["mean_attempt_s"]))


def paired(rows, baseline="m25-deepseek"):
    reference = {(r["case"], r["repetition"]): r for r in rows if r["profile"] == baseline}
    groups = defaultdict(list)
    for row in rows:
        a = reference.get((row["case"], row["repetition"]))
        if a and row["profile"] != baseline:
            both_graded = row.get("accuracy", {}).get("complete") and a.get("accuracy", {}).get("complete")
            groups[row["profile"]].append({"case": row["case"], "time_delta_s": row["total_s"] - a["total_s"],
                "quality_delta": int(row["accuracy"]["accepted"]) - int(a["accuracy"]["accepted"]) if both_graded else None,
                "f1_delta": row["accuracy"].get("fact_f1") - a["accuracy"].get("fact_f1") if both_graded and row["accuracy"].get("fact_f1") is not None and a["accuracy"].get("fact_f1") is not None else None,
                "cost_delta_usd": row["cost_usd"] - a["cost_usd"] if row.get("cost_complete") and a.get("cost_complete") else None,
                "token_delta": row["tokens"]["total"] - a["tokens"]["total"] if row["tokens"]["total"] is not None and a["tokens"]["total"] is not None else None})
    result = []
    for profile, differences in groups.items():
        item = {"profile": profile, "baseline": baseline, "pairs": len(differences)}
        for field in ("time_delta_s", "quality_delta", "f1_delta", "cost_delta_usd", "token_delta"):
            item[field + "_n"] = sum(r[field] is not None for r in differences)
            item[field + "_mean"] = mean([r[field] for r in differences if r[field] is not None])
            item[field + "_ci95"] = cluster_interval(differences, field)
        result.append(item)
    return result


def csv_file(path, rows):
    columns = list(dict.fromkeys(k for row in rows for k in row))
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        writer.writerows({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list, tuple)) else v for k, v in row.items()} for row in rows)


def legacy_manifest(folder):
    result = []
    for path in sorted(folder.parent.glob("searchbench-*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        rows = [ledger(row) for row in document["runs"]]
        settings = document.get("config", {})
        result.append({"file": path.name, "n": len(rows), "ok": sum(r["status"] == "ok" for r in rows),
                       "source_sha256": document.get("source_sha256"), "command": settings.get("command"),
                       "known_cost_usd": sum(r["known_cost_usd"] for r in rows),
                       "cost_complete": all(r["cost_complete"] for r in rows),
                       "included_in_product_ranking": False,
                       "reason": "Documentation/retrieval development cohort; different tasks, protocol or budgets."})
    return result


def generate(folder):
    document = json.loads((folder / "results.json").read_text(encoding="utf-8"))
    rows, cases = document["runs"], document["cases"]
    summary = summarize(rows)
    comparisons = paired(rows)
    strata = []
    for category in sorted({c["category"] for c in cases}):
        for complexity in sorted({c["complexity"] for c in cases}):
            strata.extend({**s, "category": category, "complexity": complexity}
                          for s in summarize([r for r in rows if r["category"] == category and r["complexity"] == complexity]))
    def fmt(value, digits=2):
        return "—" if value is None else f"{value:.{digits}f}"
    def interval(value):
        return "—" if value is None else f"[{value[0]:.2f}, {value[1]:.2f}]"
    accepted = sum(r.get("accuracy", {}).get("accepted") is True for r in rows)
    graded = sum(r.get("accuracy", {}).get("complete", False) for r in rows)
    audits = [entry["audit"] for r in rows for entry in r.get("audit_history", [])]
    grading_cost = sum(a.get("meter", {}).get("known_cost_usd", 0) for a in audits)
    grading_tokens = sum(a.get("meter", {}).get("known_tokens", {}).get("total", 0) for a in audits)
    dataset = document.get("dataset") or {}
    categories = ", ".join(dataset.get("categories", [])) or "shoes, computers and cars"
    cohort = (f"Dataset {dataset.get('name', 'product benchmark')} v{dataset.get('version', '?')} ({dataset.get('split', 'unspecified')}), checked {dataset.get('checked_on', 'date not recorded')}. "
              f"The cohort covers {categories}, balanced across easy, heavy and missing-identity jobs. "
              "Prompts are original; older benchmark results are retained separately.")
    design_links = ", ".join(f"[{index + 1}]({url})" for index, url in enumerate(dataset.get("design_references", [])))
    price_links = ", ".join(f"[{name}]({url})" for name, url in (document.get("price_sources") or {}).items())
    lines = ["# Product search: accuracy, speed, cost and tokens", "",
             f"Measured {document['created_at']}. Phase: **{document['phase']}**. {len(rows)} research attempts across {len(cases)} product prompts; {graded} fully graded; {accepted} accepted by both evaluators.", "",
             cohort, "",
             ("Benchmark design references: " + design_links + ". Their evaluation design informed the task mix; question text was written for this corpus." if design_links else "Original question text and answer keys are stored with the run."), "",
             f"Research load: {document['config']['workers']} concurrent runs, shared account pacing. Each easy/heavy/identity trial has the same predeclared 20/45/12-second ceiling across profiles. There were {document['config'].get('reps', 1)} repetitions per question; confidence intervals cluster repetitions by prompt.", "",
             "Acceptance requires ≥80% required-fact coverage, every critical fact fully correct, no audited false claim or scope violation, and adequate supported primary citations. A targeted clarification can pass an incomplete-identity task without citations. Both blinded evaluators must agree to pass; evaluator agreement is not proof of truth.", "",
             "Rubric fact F1 is shown beside acceptance: criterion credit contributes true positives, omitted/partial criterion credit contributes false negatives, and judge-confirmed false claims among up to 12 audited material claims contribute false positives. F1 is model-judged answer coverage, not an information-retrieval ranking score; citation and scope gates remain separate.", "",
             "Latency includes timed-out attempts in the mean. Cost per accepted answer includes the cost of failed and rejected attempts. Unknown usage remains a lower bound. Confidence intervals bootstrap whole product prompts (2,000 draws); p95 needs 20 accepted answers per profile.",
             "Estimated spend uses the recorded public-rate basis (" + document.get("price_date", "unknown") + "): " + document.get("price_basis", "rate details unavailable") + "", "",
             ("Rate cards: " + price_links + "." if price_links else "Rate sources are recorded in results.json."), "",
             "## Combined results", "",
             "| Profile | Accepted / n | Graded | Pass 95% CI | Fact F1 [95% CI] | Mean wait / attempt (s) | Accepted median (s) | Mean $ / attempt | $ / accepted answer | Known tokens / attempt | Pareto |",
             "|---|---:|---:|---|---|---:|---:|---:|---:|---:|---|"]
    for s in summary:
        lower = "" if s["cost_complete"] else "≥ "
        token_lower = "" if s["total_tokens_complete"] else "≥ "
        lines.append("| " + " | ".join([s["profile"], f"{s['accepted']}/{s['n']}", str(s["graded"]), interval(s["pass_ci95"]),
                     fmt(s["fact_f1"], 3) + " " + interval(s["fact_f1_ci95"]),
                     fmt(s["mean_attempt_s"]), fmt(s["accepted_median_s"]), lower + fmt(s["known_cost_per_attempt"], 5),
                     lower + fmt(s["known_cost_per_accepted"], 5) if s["known_cost_per_accepted"] is not None else "—", token_lower + fmt(s["known_tokens_per_attempt"], 0), "yes" if s["pareto"] else "—"]) + " |")
    lines += ["", "## Quality failure diagnostics", "", "Counts below can overlap. A correct core specification is distinct from an answer that meets all publication/evidence gates.", "",
              "| Profile | Runtime OK / n | Both judges: critical facts correct | Audited false-claim answers | Citation-support failures | Scope flags | Judge agreement |", "|---|---:|---:|---:|---:|---:|---:|"]
    for s in summary:
        lines.append("| " + " | ".join([s["profile"], f"{s['execution_ok']}/{s['n']}", str(s["critical_fact_passes"]), str(s["false_claim_answers"]), str(s["grounding_failures"]), str(s["scope_violations"]), fmt(s["judge_agreement"])]) + " |")
    category_order = dataset.get("categories", sorted({case["category"] for case in cases}))
    complexity_order = dataset.get("complexities", ["easy", "heavy", "identity"])
    workload_columns = [f"{category.title()} {complexity}" for category in category_order for complexity in complexity_order]
    lines += ["", "![Product quality and latency](quality-speed.png)", "", "![Product accuracy by workload](workloads.png)", "",
              "## Workload results", "", "Each cell shows accepted/attempted. A dash marks a cell whose grading is incomplete; sample counts stay visible.", "",
              "| Profile | " + " | ".join(workload_columns) + " |",
              "|---|" + "|".join("---" for _ in workload_columns) + "|"]
    for s in summary:
        cells = []
        for category in category_order:
            for complexity in complexity_order:
                found = next((a for a in strata if a["profile"] == s["profile"] and a["category"] == category and a["complexity"] == complexity), None)
                cells.append("—" if not found else f"{found['accepted']}/{found['n']}" + (" (pending)" if found["graded"] < found["n"] else ""))
        lines.append("| " + " | ".join([s["profile"], *cells]) + " |")
    lines += ["", "## Paired differences from m25-deepseek", "", "Positive acceptance/F1 deltas favor the candidate; negative wait/cost/token deltas favor it. Failed runtime attempts remain in time comparisons. Intervals bootstrap whole prompts; missing bills are excluded from dollar deltas, with pair counts exported.", "",
              "| Profile | Pairs | Acceptance delta | Acceptance 95% CI | F1 delta | F1 95% CI | Wait delta (s) | Wait 95% CI | Mean $ delta | Mean token delta |", "|---|---:|---:|---|---:|---|---:|---|---:|---:|"]
    for p in comparisons:
        lines.append("| " + " | ".join([p["profile"], str(p["pairs"]), fmt(p["quality_delta_mean"]), interval(p["quality_delta_ci95"]), fmt(p["f1_delta_mean"], 3), interval(p["f1_delta_ci95"]), fmt(p["time_delta_s_mean"]), interval(p["time_delta_s_ci95"]), fmt(p["cost_delta_usd_mean"], 5), fmt(p["token_delta_mean"], 0)]) + " |")
    lines += ["", "## Search-only comparison", "", document.get("retrieval_query_policy", "Serial retrieval measurements use the same product questions."), "Returned results are not automatically relevant or correct.", "",
              "| Search | n | OK | Median (s) | Mean (s) | Mean 95% CI | Known $ / request |", "|---|---:|---:|---:|---:|---|---:|"]
    for s in aggregate(document["retrieval_runs"]):
        lines.append("| " + " | ".join([s["search"], str(s["n"]), str(s["ok"]), fmt(s["median_s"]), fmt(s["mean_s"]), interval(s["mean_s_ci95_task_bootstrap"]), fmt(s["known_cost_usd"] / s["n"], 5)]) + " |")
    case_map = {case["id"]: case for case in cases}
    retrieval_quality = []
    for row in document["retrieval_runs"]:
        case = case_map[row["case"]]
        if case["complexity"] == "identity":
            continue
        identifiers = " ".join("[" + source["id"] + "]" for source in row["sources"])
        primaries = primary_citations(identifiers, row["sources"], case["primary_domains"])
        retrieval_quality.append({"search": row["search"], "case": row["case"], "repetition": row["repetition"],
                                  "publisher_hit": bool(primaries), "distinct_publisher_documents": len(primaries), "results": len(row["sources"])})
    lines += ["", "### Publisher-source retrieval coverage", "", "For easy and heavy prompts with an identified product. This asks whether results included a manufacturer/regulator document. It excludes hosted community posts and duplicate translations; it does not establish relevance, entailment or answer accuracy.", "",
              "| Search | Trials | With publisher evidence | Mean distinct publisher documents |", "|---|---:|---:|---:|"]
    for search in sorted({r["search"] for r in retrieval_quality}):
        group = [r for r in retrieval_quality if r["search"] == search]
        lines.append(f"| {search} | {len(group)} | {sum(r['publisher_hit'] for r in group)}/{len(group)} | {statistics.mean(r['distinct_publisher_documents'] for r in group):.2f} |")
    occurrence_rows, observed = [], defaultdict(int)
    for row in document["retrieval_runs"]:
        key = row["search"], row["case"]
        observed[key] += 1
        occurrence_rows.append({**row, "observed_occurrence": observed[key]})
    lines += ["", "### First versus repeated queries", "", "These are first and second **observed** identical requests in this experiment, not guaranteed cold/warm provider caches. Providers may cache responses outside this process. Repetition labels were shuffled, so chronology determines the grouping.", "",
              "| Search | First-observed n | First median (s) | Repeat n | Repeat median (s) |", "|---|---:|---:|---:|---:|"]
    for search in sorted({r["search"] for r in occurrence_rows}):
        first = [r["total_s"] for r in occurrence_rows if r["search"] == search and r["observed_occurrence"] == 1 and r["status"] == "ok"]
        repeated = [r["total_s"] for r in occurrence_rows if r["search"] == search and r["observed_occurrence"] > 1 and r["status"] == "ok"]
        lines.append("| " + " | ".join([search, str(len(first)), fmt(statistics.median(first) if first else None), str(len(repeated)), fmt(statistics.median(repeated) if repeated else None)]) + " |")
    lines += ["", "## Metering and evaluation limits", "",
              f"Known research spend: **${sum(r['known_cost_usd'] for r in rows):.5f}**. Known retrieval-screen spend: **${sum(r['known_cost_usd'] for r in document['retrieval_runs']):.5f}**. Known grading spend (separate): **${grading_cost:.5f}**. Totals can be lower bounds when requests time out.",
              f"Known grading tokens (not charged to candidate runtimes): **{grading_tokens:,}**. All grading attempts, including retries and failures, are retained in audit_history and separate grading CSVs.",
              f"Tavily comparison rate: ${document['tavily_comparison_usd_per_credit']:g}/credit (published pay-as-you-go), not the account's actual plan invoice. Exa uses reported costDollars; DeepSeek uses its per-successful-request rate; model prices are frozen in results.json.",
              "Input includes cached input; output includes reasoning. Never add these subsets twice. All per-call raw usage, credits, statuses and timing remain in the JSON and request CSV.",
              "Evaluators: Mistral Large 4 and Mercury 3, blinded to candidate identity and timing/cost. They see only the frozen fact rubric and evidence actually passed to the researcher. Short/truncated evidence can make citation support indeterminate. Judgement errors and disagreements remain visible; these are model-assisted accuracy estimates, not a human-adjudicated benchmark.",
              f"No product-family traffic mix or universal winner is assumed. The corpus has {len(cases) // max(1, len(dataset.get('categories', [])))} prompts per category; larger held-out sets and repeated runs are needed before selecting a production route. No Google AI baseline was measured."]
    if document.get("postprocessor_notes"):
        lines += ["", "Deterministic scoring correction: " + document["postprocessor_notes"]]
    calibration_path = folder / "calibration.json"
    if calibration_path.exists():
        calibration = json.loads(calibration_path.read_text(encoding="utf-8"))
        lines += ["", "## Evaluator calibration", "", calibration["note"], "", "| Judge | Correct controlled decisions / scored | Unscored | Known evaluation cost ($) |", "|---|---:|---:|---:|"]
        for judge in sorted({r["judge"] for r in calibration["audits"]}):
            group = [r for r in calibration["audits"] if r["judge"] == judge]
            scored = [r for r in group if r["audit"]["status"] == "scored"]
            correct = sum(r["audit"]["accepted"] == r["expected"] for r in scored)
            cost = sum(r["audit"].get("meter", {}).get("known_cost_usd", 0) for r in group)
            lines.append(f"| {judge} | {correct}/{len(scored)} | {len(group) - len(scored)} | {cost:.5f} |")
    manifest = legacy_manifest(folder)
    lines += ["", "## Earlier experiments: history only", "", "| Experiment | Attempts | Runtime OK | Known cost ($) | Pooled into product ranking |", "|---|---:|---:|---:|---|"]
    for entry in manifest:
        lines.append(f"| {entry['file']} | {entry['n']} | {entry['ok']} | {entry['known_cost_usd']:.5f} | no |")
    # One transparent example of why the earlier keyword score was insufficient.
    pilot = folder.parent / "searchbench-20261020-141614-77fdaf.json"
    if pilot.exists():
        old = json.loads(pilot.read_text(encoding="utf-8"))
        candidate = next((r for r in old["runs"] if r.get("candidate") == "mercury-2.5" and r["strategy"] == "eager" and r["case"] == "mercury-generations"), None)
        if candidate:
            official = primary_citations(candidate["answer"], candidate["sources"], ["inceptionlabs.ai"])
            lines += ["", f"Earlier 2.92-second Mercury 2.5/Mercury comparison: keyword coverage was {candidate['quality']['answer_term_coverage']:.0%}, but it cited {len(official)} official Inception sources. It left Mercury 2.5 tool support unresolved despite official support. The original 'fastest' observation was a runtime result, not an accuracy-qualified winner."]
    lines += ["", "## Rejected, failed or disputed answers", ""]
    for row in rows:
        if row.get("accuracy", {}).get("accepted") is True:
            continue
        lines += [f"### {row['profile']} — {row['case']}", "", f"Runtime: {row['status']}; wait {row['total_s']:.2f}s. Consensus: {row.get('accuracy', {}).get('accepted', 'pending')}."]
        for model, audit in row.get("audits", {}).items():
            lines += [f"- {model}: {audit['status']}; " + audit.get("detail", {}).get("summary", audit.get("error", "no final answer"))]
            for criterion in audit.get("detail", {}).get("criteria", []):
                if criterion["credit"] < 1:
                    lines.append(f"  - {criterion['id']}: {criterion['credit']:g} — {criterion.get('reason', '')}")
        lines.append("")
    (folder / "analysis.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    csv_file(folder / "profiles.csv", summary)
    csv_file(folder / "workloads.csv", strata)
    csv_file(folder / "paired.csv", comparisons)
    csv_file(folder / "history.csv", manifest)
    flat = []
    requests = []
    for row in rows:
        shared = {k: row.get(k) for k in ("profile", "case", "category", "complexity", "repetition", "status", "total_s", "deadline_s")}
        flat.append({**shared, **{k: row.get(k) for k in ("first_answer_text_s", "first_draft_text_s", "answer_type", "known_cost_usd", "cost_usd", "cost_complete", "search_requests", "fetch_requests")},
                     **{"tokens_" + k: row["tokens"][k] for k in TOKEN_FIELDS}, **row.get("accuracy", {}), "answer": row["answer"]})
        for index, event in enumerate(row["events"]):
            request = event.get("request") or {}
            requests.append({**shared, "request_index": index, **{k: event.get(k) for k in ("kind", "provider", "model", "status", "duration_s", "cost_usd", "credits", "http_version")},
                             "query": request.get("query"), "request_target": request.get("url") or request.get("urls") or request.get("ids"),
                             **{"tokens_" + k: event.get("tokens", {}).get(k) for k in TOKEN_FIELDS}})
    csv_file(folder / "trials.csv", flat)
    csv_file(folder / "requests.csv", requests)
    grading, grading_requests = [], []
    for row in rows:
        for index, entry in enumerate(row.get("audit_history", [])):
            audit = entry["audit"]
            meter = audit.get("meter", {})
            shared = {"profile": row["profile"], "case": row["case"], "judge": entry["model"], "audit_attempt": index}
            grading.append({**shared, "status": audit["status"], "accepted": audit.get("accepted"), "fact_recall": audit.get("fact_recall"), "fact_f1": audit.get("fact_f1"), "fact_precision": audit.get("fact_precision"),
                            "known_cost_usd": meter.get("known_cost_usd", 0), "cost_complete": meter.get("cost_complete", True),
                            **{"known_tokens_" + k: meter.get("known_tokens", {}).get(k, 0) for k in TOKEN_FIELDS}})
            for event in meter.get("events", []):
                grading_requests.append({**shared, **{k: event.get(k) for k in ("provider", "model", "status", "duration_s", "cost_usd")},
                                         **{"tokens_" + k: event.get("tokens", {}).get(k) for k in TOKEN_FIELDS}})
    csv_file(folder / "grading.csv", grading)
    csv_file(folder / "grading-requests.csv", grading_requests)
    csv_file(folder / "retrieval.csv", [{k: r.get(k) for k in ("search", "case", "category", "complexity", "repetition", "observed_occurrence", "search_query", "query_chars", "query_compacted", "status", "total_s", "known_cost_usd", "cost_complete", "provider_credits")} for r in occurrence_rows])
    csv_file(folder / "retrieval-publishers.csv", retrieval_quality)
    (folder / "analysis.json").write_text(json.dumps({"profiles": summary, "workloads": strata, "paired": comparisons, "history": manifest}, indent=2), encoding="utf-8")
    plot(folder, document, summary, strata)
    # Static HTML only: linked ranking views and native expandable trial logs, no JavaScript.
    def esc(value):
        return html.escape("—" if value is None else str(value), quote=True)

    def ranking_table(anchor, title, metric, *, reverse, display):
        ranked = sorted(summary, key=lambda row: (row[metric] is None, -(row[metric] or 0) if reverse else (row[metric] if row[metric] is not None else 0)))
        result = [f"<section id='{anchor}'><h2>{title}</h2><div class='scroll'><table><thead><tr><th>#</th><th>Profile</th><th>Accepted / n</th><th>Fact F1 [95% CI]</th><th>Mean wait (s)</th><th>Known $ / attempt</th><th>$ / accepted</th><th>Known tokens / attempt</th></tr></thead><tbody>"]
        for rank, item in enumerate(ranked, 1):
            cost_prefix = "" if item["cost_complete"] else "≥ "
            result.append("<tr>" + "".join(f"<td>{esc(value)}</td>" for value in (
                rank, item["profile"], f"{item['accepted']}/{item['n']}",
                f"{fmt(item['fact_f1'], 3)} {interval(item['fact_f1_ci95'])}", fmt(item["mean_attempt_s"]),
                cost_prefix + fmt(item["known_cost_per_attempt"], 5),
                (cost_prefix + fmt(item["known_cost_per_accepted"], 5)) if item["known_cost_per_accepted"] is not None else "—",
                ("≥ " if not item["total_tokens_complete"] else "") + fmt(item["known_tokens_per_attempt"], 0))) + "</tr>")
        result.append("</tbody></table></div></section>")
        return "".join(result)

    page = "<!doctype html><meta charset='utf-8'><title>Product search analysis</title><style>body{font:16px system-ui;max-width:1450px;margin:32px auto;padding:0 22px;color:#182235}h1{font-size:30px}h2{font-size:21px;margin-top:28px}.scroll{overflow-x:auto}table{border-collapse:collapse;width:100%;min-width:900px}td,th{text-align:left;padding:8px;border-bottom:1px solid #ddd;vertical-align:top}th{background:#f3f6fb}img{width:100%;height:auto}a{color:#1659bf}details{margin:8px 0;border:1px solid #d7deea;border-radius:6px;padding:8px}summary{cursor:pointer;font-weight:600}pre{white-space:pre-wrap;overflow-wrap:anywhere}.answer{max-height:380px;overflow:auto}.nav a{margin-right:14px}</style><h1>Product research: accuracy × speed × cost</h1>"
    page += f"<p>{len(rows)} attempts across {len(cases)} original product prompts; {graded} fully graded; {accepted} accepted by both evaluators. Two repetitions per question. Model-assisted screening results.</p>"
    page += "<p><a href='analysis.md'>Full analysis</a> · <a href='trials.csv'>Trials</a> · <a href='requests.csv'>Request log</a> · <a href='grading.csv'>Grading log</a> · <a href='retrieval.csv'>Search log</a> · <a href='workloads.csv'>Workload breakdown</a></p>"
    page += "<p class='nav'>Rankings: <a href='#ranking-accepted'>Accepted high→low</a> · <a href='#ranking-f1'>Fact F1 high→low</a> · <a href='#ranking-speed'>Speed low→high</a> · <a href='#ranking-cost'>Cost low→high</a></p>"
    page += ranking_table("ranking-accepted", "Accepted answers · high to low", "accepted", reverse=True, display="accepted")
    page += ranking_table("ranking-f1", "Rubric fact F1 · high to low", "fact_f1", reverse=True, display="fact_f1")
    page += ranking_table("ranking-speed", "Mean response time · low to high", "mean_attempt_s", reverse=False, display="mean_attempt_s")
    page += ranking_table("ranking-cost", "Known cost per attempt · low to high", "known_cost_per_attempt", reverse=False, display="known_cost_per_attempt")
    page += "<h2>Speed and accuracy</h2><img src='quality-speed.png' alt='Fact F1, speed and cost'><img src='workloads.png' alt='Accepted answers by category and job type'>"
    page += "<h2>Expandable trial logs</h2><p>Each row opens the answer, cited sources and both graders’ short notes. Citation support and scope violations remain separate acceptance checks.</p>"
    case_order = {case["id"]: case for case in cases}
    for profile in sorted({row["profile"] for row in rows}):
        group = sorted([row for row in rows if row["profile"] == profile], key=lambda row: (row["case"], row["repetition"]))
        stats = next(item for item in summary if item["profile"] == profile)
        page += f"<details><summary>{esc(profile)} — {stats['accepted']}/{stats['n']} accepted; F1 {fmt(stats['fact_f1'], 3)}; mean {fmt(stats['mean_attempt_s'])}s</summary><div class='scroll'><table><thead><tr><th>Case</th><th>Job</th><th>Rep</th><th>Status</th><th>Accepted</th><th>F1</th><th>Seconds</th><th>Known $</th><th>Tokens</th><th>Answer and evidence</th></tr></thead><tbody>"
        for row in group:
            case = case_order[row["case"]]
            citations = " ".join(f"<a href='{esc(source['url'])}' rel='noopener'>{esc(source['id'])}: {esc(source.get('title') or source['url'])}</a>" for source in row.get("sources", [])) or "No sources returned"
            audit_notes = "<br>".join(f"<b>{esc(model)}</b>: {esc(audit.get('detail', {}).get('summary') or audit.get('error') or audit['status'])}" for model, audit in row.get("audits", {}).items()) or "Pending grading"
            f1s = "—" if row.get("accuracy", {}).get("fact_f1") is None else f"{row['accuracy']['fact_f1']:.3f}"
            answer = row.get("answer") or "No answer returned."
            evidence = f"<details><summary>Open answer and evidence</summary><div class='answer'><pre>{esc(answer)}</pre><p>{citations}</p><p>{audit_notes}</p></div></details>"
            page += "<tr>" + "".join(f"<td>{value}</td>" for value in (
                esc(row["case"]), esc(f"{case['category']} · {case['complexity']}"), esc(row["repetition"]), esc(row["status"]),
                esc(row.get("accuracy", {}).get("accepted")), esc(f1s), esc(fmt(row["total_s"])),
                esc(("≥ " if not row.get("cost_complete") else "") + fmt(row.get("known_cost_usd"), 5)),
                esc(("≥ " if not row.get("usage_complete") else "") + fmt(row.get("known_tokens", {}).get("total"), 0)), evidence)) + "</tr>"
        page += "</tbody></table></div></details>"
    page += "<p>Rubric fact F1 counts credited required criteria as true positives, omissions/partial credits as false negatives, and judge-confirmed false claims among up to 12 audited material claims as false positives. It is not search-ranking F1. Costs include failed and rejected attempts; ≥ marks a lower bound. Tavily uses the declared $0.008/credit comparison rate. No Google baseline was measured.</p>"
    (folder / "analysis.html").write_text(page, encoding="utf-8")
    (folder / "index.html").write_text(page, encoding="utf-8")
    print(folder / "analysis.html")


def plot(folder, document, summary, strata):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figure, axis = plt.subplots(figsize=(12, 7))
    for index, s in enumerate(summary):
        if s["fact_f1"] is None:
            continue
        axis.scatter(s["mean_attempt_s"], s["fact_f1"], s=70 + 9000 * s["known_cost_per_attempt"],
                     color="#2563eb" if s["pareto"] else "#64748b", alpha=.8)
        axis.annotate(str(index + 1), (s["mean_attempt_s"], s["fact_f1"]), xytext=(5, 8 if index % 2 == 0 else -14), textcoords="offset points", fontsize=9)
    for index, s in enumerate(summary):
        figure.text(.73, .88 - index * .045, f"{index + 1}. {s['profile']}", fontsize=9)
    axis.set(xlabel="Mean time per attempt, including failures (seconds)", ylabel="Rubric fact F1 (mean of both judges)", ylim=(-.07, 1.08))
    axis.set_title("Product fact F1 versus speed; bubble area reflects known cost", loc="left", fontsize=15, pad=18)
    axis.spines[["top", "right"]].set_visible(False)
    axis.grid(alpha=.15)
    figure.text(.02, .02, "Blue: non-dominated on accepted-answer rate, speed and fully priced cost. Grey: otherwise. F1 is model-judged; rubric, citation and scope gates remain separate.", fontsize=9)
    figure.tight_layout(rect=(0, .06, .72, 1))
    figure.savefig(folder / "quality-speed.png", dpi=180)
    figure.savefig(folder / "quality-speed.svg")
    plt.close(figure)

    dataset = document.get("dataset") or {}
    categories = dataset.get("categories", sorted({row["category"] for row in strata}))
    complexities = dataset.get("complexities", ["easy", "heavy", "identity"])
    columns = [(category, workload) for category in categories for workload in complexities]
    matrix = []
    labels = []
    for s in summary:
        values, texts = [], []
        for category, workload in columns:
            value = next((x for x in strata if x["profile"] == s["profile"] and x["category"] == category and x["complexity"] == workload), None)
            values.append(value["pass_rate"] if value and value["pass_rate"] is not None else float("nan"))
            texts.append(f"{value['accepted']}/{value['n']}" if value and value["graded"] == value["n"] else "pending")
        matrix.append(values)
        labels.append(texts)
    figure, axis = plt.subplots(figsize=(max(14, .9 * len(columns) + 5), max(5, .5 * len(summary) + 2)))
    axis.imshow(matrix, cmap="Blues", vmin=0, vmax=1, aspect="auto")
    for i, row in enumerate(labels):
        for j, text in enumerate(row):
            axis.text(j, i, text, ha="center", va="center", color="white" if matrix[i][j] > .6 else "#172b4d", fontsize=10)
    axis.set_xticks(range(len(columns)), [c + "\n" + w for c, w in columns])
    axis.set_yticks(range(len(summary)), [s["profile"] for s in summary])
    axis.set_title("Accepted / attempted, by product category and job type", loc="left", fontsize=15, pad=18)
    figure.text(.02, .02, "Missing-identity tasks reward targeted clarification. Every critical rubric fact must pass; runtime success alone is insufficient.", fontsize=9)
    figure.tight_layout(rect=(0, .06, 1, 1))
    figure.savefig(folder / "workloads.png", dpi=180)
    figure.savefig(folder / "workloads.svg")
    plt.close(figure)


def generate_master(folders):
    """Combine views while retaining experimental blocks and grading provenance."""
    documents = [json.loads((folder / "results.json").read_text(encoding="utf-8")) for folder in folders]
    root = folders[0].parent
    lines = ["# Product web search: combined analysis", "",
             "This combines the experiment records and views, not their incompatible samples. Block 1 is the original product screen; block 2 is a later randomized comparison of the combined stack with contemporary controls. The later block reuses the same nine prompts and is not a held-out confirmation set.", "",
             "## What counts as success", "",
             "A final answer must meet the frozen fact, critical-scope and evidence gates under both blinded evaluators. Targeted clarification is a valid outcome for an unidentified product. A fast, fluent, cited-looking answer is not automatically accepted. These are model-assisted acceptance estimates; factual truth has not been exhaustively human-adjudicated.", ""]
    totals = {"research": 0, "retrieval": 0, "grading": 0, "research_cost": 0., "retrieval_cost": 0., "grading_cost": 0., "calibration_cost": 0., "tokens": 0}
    flat = []
    for block, (folder, document) in enumerate(zip(folders, documents), 1):
        rows = document["runs"]
        summaries = summarize(rows)
        totals["research"] += len(rows)
        totals["retrieval"] += len(document["retrieval_runs"])
        totals["research_cost"] += sum(r["known_cost_usd"] for r in rows)
        totals["retrieval_cost"] += sum(r["known_cost_usd"] for r in document["retrieval_runs"])
        totals["tokens"] += sum(r["known_tokens"]["total"] for r in rows)
        audits = [e["audit"] for r in rows for e in r.get("audit_history", [])]
        totals["grading"] += len(audits)
        totals["grading_cost"] += sum(a.get("meter", {}).get("known_cost_usd", 0) for a in audits)
        calibration_path = folder / "calibration.json"
        if calibration_path.exists():
            calibration = json.loads(calibration_path.read_text(encoding="utf-8"))
            controls = calibration["audits"]
            totals["calibration_cost"] += sum(c["audit"].get("meter", {}).get("known_cost_usd", 0) for c in controls)
            scored_controls = [c for c in controls if c["audit"]["status"] == "scored"]
            correct_controls = sum(c["audit"]["accepted"] == c["expected"] for c in scored_controls)
            lines += [f"Evaluator controls: {correct_controls}/{len(scored_controls)} correct scored decisions; {len(controls) - len(scored_controls)} unscored. These simple curated controls do not establish open-web grading reliability.", ""]
        lines += [f"## Block {block}: {folder.name}", "",
                  f"{len(rows)} attempts, {len(document['cases'])} prompts, {document['config']['workers']} concurrent research workers. [Full analysis]({folder.name}/analysis.md) · [Trial CSV]({folder.name}/trials.csv) · [Paired statistics]({folder.name}/paired.csv)", "",
                  "| Profile | Accepted / n | Mean wait per attempt (s) | Accepted median (s) | Known $ / attempt | Known $ / accepted | Known tokens / attempt |", "|---|---:|---:|---:|---:|---:|---:|"]
        for s in summaries:
            flat.append({"block": block, "folder": folder.name, **s})
            lower = "" if s["cost_complete"] else "≥ "
            cost_accepted = "—" if s["known_cost_per_accepted"] is None else lower + f"{s['known_cost_per_accepted']:.5f}"
            latency = "—" if s["accepted_median_s"] is None else f"{s['accepted_median_s']:.2f}"
            tokens = ("" if s["total_tokens_complete"] else "≥ ") + f"{s['known_tokens_per_attempt']:.0f}"
            lines.append(f"| {s['profile']} | {s['accepted']}/{s['n']} | {s['mean_attempt_s']:.2f} | {latency} | {lower}{s['known_cost_per_attempt']:.5f} | {cost_accepted} | {tokens} |")
        lines += ["", "### Job difficulty", "", "| Job type | Runtime completions / n | Fully graded | Both-judge accepted / n | Mean wait (s) |", "|---|---:|---:|---:|---:|"]
        for kind in ("easy", "heavy", "identity"):
            group = [r for r in rows if r["complexity"] == kind]
            complete = sum(r.get("accuracy", {}).get("complete", False) for r in group)
            passed = sum(r.get("accuracy", {}).get("accepted") is True for r in group)
            lines.append(f"| {kind} | {sum(r['status'] == 'ok' for r in group)}/{len(group)} | {complete} | {passed}/{len(group)} | {statistics.mean(r['total_s'] for r in group):.2f} |")
        judged = [r for r in rows if all(r.get("audits", {}).get(m, {}).get("status") in ("scored", "no_answer") for m in ("mistral-large-4", "mercury-3"))]
        if judged:
            a = [int(r["audits"]["mistral-large-4"]["accepted"]) for r in judged]
            b = [int(r["audits"]["mercury-3"]["accepted"]) for r in judged]
            agreement = sum(x == y for x, y in zip(a, b)) / len(a)
            chance = statistics.mean(a) * statistics.mean(b) + (1 - statistics.mean(a)) * (1 - statistics.mean(b))
            kappa = (agreement - chance) / (1 - chance) if chance < 1 else None
            lines += ["", f"Evaluator agreement: {agreement:.1%} across {len(a)} graded answers; Cohen's κ = {kappa:.3f}." if kappa is not None else "", "Agreement measures consistency, not truth. Repeated prompts and model families limit independence; these are descriptive diagnostics."]
        lines += ["", f"![Block {block} workload breakdown]({folder.name}/workloads.png)", ""]
    combined_rows = next((d["runs"] for d in reversed(documents) if any(r["profile"] == "m25-federated-verify-m3" for r in d["runs"])), [])
    if combined_rows:
        lookup = {s["profile"]: s for s in summarize(combined_rows)}
        candidate = lookup["m25-federated-verify-m3"]
        lines += ["## What the combined stack bought", "",
                  "The combined profile is Mercury 2.5 drafting and Mercury 3 verification over concurrent DeepSeek, Exa and Tavily retrieval. It does not invoke every model for every question; the Ministral and Large 4 alternatives are compared in block 1.", ""]
        for baseline in ("m25-deepseek", "m25-federated"):
            control = lookup.get(baseline)
            if control is None:
                continue
            comparison = next(p for p in paired(combined_rows, baseline) if p["profile"] == candidate["profile"])
            interval = comparison["quality_delta_ci95"]
            lines += [f"Against **{baseline}** in the same block: {candidate['accepted']}/{candidate['n']} versus {control['accepted']}/{control['n']} accepted; mean wait {candidate['mean_attempt_s']:.2f}s versus {control['mean_attempt_s']:.2f}s; estimated cost/attempt ${candidate['known_cost_per_attempt']:.5f} versus ${control['known_cost_per_attempt']:.5f}."]
            if interval is not None:
                lines += [f"Paired acceptance improvement {comparison['quality_delta_mean']:+.1%}; exploratory 95% question-bootstrap interval [{interval[0]:+.1%}, {interval[1]:+.1%}]. An interval crossing zero does not establish a reliable quality gain."]
        heavy = [r for r in combined_rows if r["profile"] == candidate["profile"] and r["complexity"] == "heavy"]
        lines += ["", f"Combined-stack heavy jobs: {sum(r.get('accuracy', {}).get('accepted') is True for r in heavy)}/{len(heavy)} accepted. There is only one heavy prompt per product category, so this is a useful failure-finding screen, not a category reliability estimate.",
                  "The saved answers reveal a verifier-output problem: it sometimes writes a review of its draft instead of a concise answer to the user. The computer identity response failed to ask the actual user for identification. On the easy MacBook prompt, the verifier corrected the draft's display-count mistake but added extraneous assertions and the judges disagreed. More verification can create new failure surfaces.",
                  "Passing means correctness plus the declared evidence/completeness gates. Some rejections have correct core facts but too few distinct primary documents, unsupported extra detail or a missing requested clarification. The rejection audits preserve that distinction.", ""]
    lines += ["## Interpretation", "",
              "- Read easy lookups, heavy jobs and missing-identity cases separately. A profile's overall score depends on the deliberately equal workload mix used here.",
              "- Compare the combined three-provider/two-model workflow with controls in block 2. Its additional providers and verification calls are all metered, including rejected attempts.",
              "- The next routing hypothesis is DeepSeek + Mercury 2.5 for identified easy lookups, targeted clarification for missing identity, and added primary-source retrieval plus verification for difficult/conflicting evidence. This adaptive route has not been measured end to end; do not assign it the combined profile's observed score or latency.",
              "- Before the next held-out run, make verifier output directly answer the user's question, preserve necessary clarification, and suppress unsupported peripheral claims. Fix these as a new version and retain these frozen results.",
              "- A timeout or exhausted tool budget is a failure of this bounded workflow, not a claim that a model cannot solve the task with a different budget or harness.",
              "- Exa/Tavily repeated-query speed differs substantially from first-observed speed. Their per-block tables retain both; no cold-cache or Google-parity claim is made.",
              "- Community posts hosted on a manufacturer's domain are not manufacturer-authored documentation. Translations and tracked duplicates cannot manufacture independent source counts.",
              "- Publishing a route requires a larger held-out product corpus, repeated runs, manual adjudication of disputed cases, and explicit acceptable-error thresholds for high-consequence jobs. No single scalar score or universal winner is imposed.", "",
              "## Metering across these blocks", "",
              f"Research attempts: **{totals['research']}**. Retrieval-screen calls: **{totals['retrieval']}**. Grading attempts (including retries): **{totals['grading']}**.",
              f"Known research cost **${totals['research_cost']:.5f}**; known retrieval-screen cost **${totals['retrieval_cost']:.5f}**; known grading cost **${totals['grading_cost']:.5f}**. Known research model tokens: **{totals['tokens']:,}**. Incomplete bills remain lower bounds.",
              f"Evaluator-control calibration is separate again: **${totals['calibration_cost']:.5f}**. Costs are estimates from reported usage and frozen rates, not provider invoices; missing cache detail is priced as uncached input. Timing and token measurements remain independently available.",
              "Grading and retrieval-screen spending are benchmark-development costs; they are not added to the deployed candidate's per-answer cost. Tavily is compared at the explicitly declared $0.008/credit pay-as-you-go rate; actual plan/free-tier billing may differ.", "",
              "Earlier documentation sweeps remain linked in each block's history table. They are not pooled into product accuracy or cost-per-accepted-answer statistics."]
    markdown = root / "mega-analysis-20261020.md"
    markdown.write_text("\n".join(lines) + "\n", encoding="utf-8")
    csv_file(root / "mega-analysis-20261020.csv", flat)
    page = "<!doctype html><meta charset='utf-8'><title>Combined product benchmark</title><style>body{font:16px system-ui;max-width:1400px;margin:40px auto;padding:0 24px;color:#182235}table{border-collapse:collapse;width:100%}td,th{text-align:left;padding:9px;border-bottom:1px solid #ddd}img{width:100%;height:auto}a{color:#1659bf}h1{font-size:32px}</style><h1>Product research: combined analysis</h1>"
    page += f"<p>{totals['research']} research attempts · {totals['retrieval']} retrieval trials · separate experimental blocks. Accuracy is assessed by two blinded models, not keyword matching.</p><p><a href='{markdown.name}'>Full analysis and methodology</a> · <a href='mega-analysis-20261020.csv'>Combined CSV, with block IDs</a></p>"
    if "## What the combined stack bought" in lines:
        start = lines.index("## What the combined stack bought") + 1
        stop = lines.index("## Interpretation")
        page += "<h2>What the combined stack bought</h2>"
        page += "".join("<p>" + html.escape(line.replace("**", "")) + "</p>" for line in lines[start:stop] if line)
    for block, folder in enumerate(folders, 1):
        group = [s for s in flat if s["block"] == block]
        page += f"<h2>Block {block}: {folder.name}</h2><p><a href='{folder.name}/analysis.html'>Detailed report, paired intervals, audits and CSVs</a></p><table><tr><th>Profile</th><th>Accepted / n</th><th>Mean wait (s)</th><th>Known $ / accepted</th></tr>"
        for s in group:
            cost = "—" if s["known_cost_per_accepted"] is None else ("" if s["cost_complete"] else "≥ ") + f"${s['known_cost_per_accepted']:.5f}"
            page += "<tr>" + "".join("<td>" + html.escape(str(v)) + "</td>" for v in (s["profile"], f"{s['accepted']}/{s['n']}", f"{s['mean_attempt_s']:.2f}", cost)) + "</tr>"
        page += f"</table><img src='{folder.name}/workloads.png' alt='Product workload acceptance breakdown for block {block}'>"
    page += "<p>Counts are small and the second block is exploratory follow-up. Costs include rejected attempts; unknown bills are lower bounds. No universal production winner or Google baseline is claimed. The full analysis explains the combined stack's gains, regressions, paired uncertainty and proposed next routing experiment.</p>"
    path = root / "mega-analysis-20261020.html"
    path.write_text(page, encoding="utf-8")
    print(path)
