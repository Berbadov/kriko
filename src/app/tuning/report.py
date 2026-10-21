"""The tuning report: plain static HTML, sortable by links, nothing to execute.

The same look and the same mechanism as the benchmark's `listing`: no script,
every sortable column has a low-to-high and a high-to-low link that opens a
pre-sorted page, and everything long (the answer, the grader's reasoning, the
evidence, the trace) sits in a native `<details>` that expands in place. Copy
the folder to share it.

Each row says which agent answered (and with which search provider) and which
graded, because that is what makes a number interpretable. The grader's
reasoning is the grader's own summary and the verdicts it gave per fact and per
claim, with the deterministic downgrades listed beside them.
"""

import html
from collections.abc import Callable
from pathlib import Path

from app.searchbench.listing import PAGE_STYLE
from app.tuning import failures

EXTRA_STYLE = (
    ".ok{color:#146c2e;font-weight:600}.bad{color:#a4262c;font-weight:600}.warn{color:#8a5a00;font-weight:600}"
    ".chips span{display:inline-block;margin:2px 4px 2px 0;padding:1px 8px;border:1px solid #ccd;"
    "border-radius:10px;font-size:12px;white-space:nowrap}"
    ".who{color:#444;font-size:13px}.kv td:first-child{width:11em;color:#555}"
    "table.inner{margin:6px 0}table.inner td,table.inner th{padding:5px 8px;font-size:13px}"
    ".quote{color:#444;font-style:italic}")

#: Sortable columns: key, label, how a row is valued for sorting (None sorts last).
COLUMNS: tuple[tuple[str, str, Callable[[dict], float | None]], ...] = (
    ("verdict", "Verdict", lambda r: None if r["accepted"] is None else int(r["accepted"])),
    ("facts", "Required facts", lambda r: r["grading"].get("fact_credit")),
    ("claims", "Claims supported", lambda r: (r["grading"].get("claims_supported", 0) / r["grading"]["claims_total"]
                                              if r["grading"].get("claims_total") else None)),
    ("links", "Links open", lambda r: ((r["grading"].get("links") or {}).get("open", 0)
                                       / (r["grading"].get("links") or {}).get("total", 1)
                                       if (r["grading"].get("links") or {}).get("total") else None)),
    ("seconds", "Seconds", lambda r: r.get("seconds")),
    ("cost", "USD", lambda r: r.get("usd")),
)


def _order(value: float | None, direction: str, case: str) -> tuple:
    """Rows with no value last, whichever way the column is sorted."""
    return value is None, (-(value or 0) if direction == "desc" else (value or 0)), case


def esc(value) -> str:
    return html.escape(str(value), quote=True)


def _pct(value, digits: int = 0) -> str:
    return "—" if value is None else f"{value * 100:.{digits}f}%"


def _who(entry: dict) -> str:
    name = entry.get("label") or entry.get("id") or "unknown"
    bits = [bit for bit in (entry.get("id"), entry.get("model")) if bit]
    return f"{name} ({', '.join(bits)})" if bits else name


def _page(title: str, body: str) -> str:
    return ("<!doctype html><html lang='en'><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{esc(title)}</title><style>{PAGE_STYLE}{EXTRA_STYLE}</style>{body}</html>")


def _chips(classes: list[str]) -> str:
    return "".join(f"<span title='{esc(failures.CLASSES.get(name, ''))}'>{esc(name)}</span>" for name in classes)


def _verdict(row: dict) -> str:
    if row["accepted"] is True:
        return "<span class='ok'>PASS</span>"
    if row["accepted"] is False:
        return "<span class='bad'>FAIL</span>"
    return "<span class='warn'>UNGRADED</span>" if row["status"] == "ungraded" else "<span class='bad'>ERROR</span>"


def _details(row: dict) -> str:
    grading = row["grading"]
    out = [f"<p>{esc(row['question'])}</p>",
           "<p class='who'>Answered by " + esc(_who(row["answered_by"])) + " · search: "
           + esc(row["answered_by"].get("search_provider", "")) + "<br>Graded by "
           + esc(_who(row["graded_by"])) + " (a different agent; it saw the final answer and the "
           "fetched pages, never the answerer's reasoning or identity)</p>",
           "<p><b>Answer</b></p><pre>" + esc(row["answer"]["text"] or row["answer"]["error"] or "No answer.") + "</pre>"]
    if row["answer"].get("error"):
        out.append(f"<p class='bad'>Run error: {esc(row['answer']['error'])}</p>")
    reasons = grading.get("failed_because") or []
    if reasons:
        out.append("<p><b>Why it did not pass</b></p><ul>" + "".join(f"<li>{esc(one)}</li>" for one in reasons) + "</ul>")
    out.append("<details><summary>Grader's reasoning</summary>")
    if grading.get("status") == "grader_error":
        out.append(f"<p class='warn'>The grader could not be read: {esc(grading.get('error', ''))}</p>")
    out.append(f"<pre>{esc(grading.get('summary') or 'The grader gave no summary.')}</pre>")
    if grading.get("facts"):
        out.append("<table class='inner'><tr><th>Required fact</th><th>Verdict</th><th>Evidence quotation</th>"
                   "<th>Reason</th></tr>")
        for fact in grading["facts"]:
            out.append("<tr><td>" + esc(fact["id"]) + ("<br><small>critical</small>" if fact["critical"] else "")
                       + "</td><td>" + esc(fact["status"]) + (" (unverified)" if not fact["verified"] else "")
                       + "</td><td class='quote'>" + esc(fact["quote"]) + "<br><small>" + esc(fact["url"])
                       + "</small></td><td>" + esc(fact["reason"]) + "</td></tr>")
        out.append("</table>")
    elif not grading.get("rubric_scored"):
        out.append("<p class='note'>No rubric for this case, so required facts were not scored.</p>")
    if grading.get("claims"):
        out.append("<table class='inner'><tr><th>Claim in the answer</th><th>Supported by the page it cites</th>"
                   "<th>Quotation</th></tr>")
        for claim in grading["claims"]:
            out.append("<tr><td>" + esc(claim["text"]) + "</td><td>" + esc(claim["supported"])
                       + "</td><td class='quote'>" + esc(claim["quote"]) + "<br><small>" + esc(claim["url"])
                       + "</small></td></tr>")
        out.append("</table>")
    identity = grading.get("identity") or {}
    if identity:
        out.append(f"<p>Product identity: <b>{esc({True: 'matches', False: 'does not match', None: 'not judged'}[identity.get('matches')])}"
                   f"</b>. {esc(identity.get('reason', ''))}</p>")
    if grading.get("normalisations"):
        out.append("<p><b>Checked against the evidence, not taken on trust</b></p><ul>"
                   + "".join(f"<li>{esc(one)}</li>" for one in grading["normalisations"]) + "</ul>")
    out.append("</details>")
    links = grading.get("links") or {}
    out.append(f"<details><summary>Links and evidence · {links.get('open', 0)}/{links.get('total', 0)} of the "
               f"answer's links open · {len(row['evidence'])} page(s) fetched</summary>"
               "<table class='inner'><tr><th>Page</th><th>Opens</th><th>In the answer</th><th>Read by the answerer</th></tr>")
    for page in row["evidence"]:
        out.append("<tr><td><a href='" + esc(page["url"]) + "' target='_blank' rel='noopener noreferrer'>"
                   + esc(page["url"]) + "</a>"
                   + (f"<details><summary>excerpt</summary><pre>{esc(page['excerpt'])}</pre></details>"
                      if page["excerpt"] else "") + "</td><td>" + ("yes" if page["opens"] else "<span class='bad'>no</span>")
                   + "</td><td>" + ("yes" if page["in_answer"] else "no") + "</td><td>"
                   + ("yes" if page["read_by_answerer"] else "no") + "</td></tr>")
    out.append("</table></details>")
    if row.get("trace"):
        out.append("<details><summary>The answerer's run log</summary><pre>" + esc("\n".join(row["trace"]))
                   + "</pre></details>")
    return "".join(out)


def _classes_table(summary: dict) -> str:
    counts = summary.get("failure_classes") or {}
    if not counts:
        return "<p>No failed attempt, so no failure class.</p>"
    top = summary.get("commonest_failure")
    rows = "".join(
        f"<tr><td>{esc(name)}{' <b>(commonest)</b>' if name == top else ''}</td><td>{esc(failures.CLASSES[name])}"
        f"</td><td>{counts[name]}</td></tr>" for name in failures.CLASSES if name in counts)
    return ("<table class='inner'><tr><th>Failure class</th><th>Meaning</th><th>Attempts</th></tr>" + rows
            + "</table><p class='note'>Classes are derived automatically from the run, the grader's checked "
            "findings and the links; an attempt with two classes counts in both. The commonest class is the "
            "next mechanism to build, not the next prompt to tweak.</p>")


def _header(document: dict) -> str:
    summary = document["summary"]
    answered = document.get("answered_by") or {}
    engine = document["engine"]
    interval = summary.get("pass_ci95")
    rate = ("—" if summary["pass_rate"] is None else
            f"{summary['accepted']}/{summary['graded']} = {_pct(summary['pass_rate'])}"
            + (f" (95% interval {_pct(interval[0])} to {_pct(interval[1])})" if interval else ""))
    spend = "unknown" if not summary["spend_complete"] and not summary["spent_usd"] else (
        ("at least " if not summary["spend_complete"] else "") + f"${summary['spent_usd']:.4f}")
    return (
        f"<h1>Engine tuning{(': ' + esc(document['label'])) if document.get('label') else ''}</h1>"
        "<table class='kv'>"
        f"<tr><td>Answered by</td><td>{esc(_who(answered.get('agent') or {}))}</td></tr>"
        f"<tr><td>Search provider</td><td>{esc(answered.get('search_provider', ''))}</td></tr>"
        f"<tr><td>Graded by</td><td>{esc(_who(document['graded_by']))} <span class='note'>never the agent "
        "that answered</span></td></tr>"
        f"<tr><td>Engine</td><td>{esc(engine.get('version', ''))} {esc((engine.get('git_sha') or '')[:10])}"
        f"{' (uncommitted changes)' if engine.get('dirty') else ''}</td></tr>"
        f"<tr><td>Cases</td><td>{document['case_set']['count']} "
        f"({esc(', '.join(f'{k}: {v}' for k, v in document['case_set']['sources'].items()))}), "
        f"{document['config']['reps']} run(s) each · set {esc(document['case_set']['sha256'][:12])} · "
        f"grading protocol {esc(document['protocol']['hash'])}</td></tr>"
        f"<tr><td>Accepted</td><td>{rate}</td></tr>"
        f"<tr><td>Required facts</td><td>{_pct(summary['fact_credit'])} mean credit "
        "<span class='note'>(rubric cases only)</span></td></tr>"
        f"<tr><td>Claims supported</td><td>{_pct(summary['claims_supported_share'])} by the page each cites</td></tr>"
        f"<tr><td>Links</td><td>{summary['links_open']}/{summary['links_total']} open · "
        f"{summary['links_invented']} invented</td></tr>"
        f"<tr><td>Mean seconds</td><td>{'—' if summary['mean_seconds'] is None else f'{summary['mean_seconds']:.1f}'}"
        f" · spend {spend}</td></tr></table>"
        "<h2>Why attempts failed</h2>" + _classes_table(summary))


def build(document: dict, out: Path) -> Path:
    """Write the report and its sorted pages into `out`; returns `index.html`."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)

    def name(key: str, direction: str) -> str:
        return f"sorted-{key}-{direction}.html"

    rows = document["rows"]
    for key, direction in [("", "")] + [(k, d) for k, _, _ in COLUMNS for d in ("asc", "desc")]:
        ordered = list(rows)
        if key:
            pick = next(value for k, _, value in COLUMNS if k == key)
            ordered.sort(key=lambda row: _order(pick(row), direction, row["case"]))
        header = "".join(
            f"<th>{esc(label)}<br><small><a href='{name(k, 'asc')}' aria-label='{esc(label)} low to high'>↑ low</a>"
            f" / <a href='{name(k, 'desc')}' aria-label='{esc(label)} high to low'>↓ high</a></small></th>"
            for k, label, _ in COLUMNS)
        lines = []
        for row in ordered:
            grading = row["grading"]
            links = grading.get("links") or {}
            lines.append(
                f"<tr><td>{esc(row['case'])}<br><small>{esc(row['source'])}"
                f"{' · run ' + str(row['rep']) if document['config']['reps'] > 1 else ''}</small></td>"
                f"<td>{_verdict(row)}</td><td>{_pct(grading.get('fact_credit'))}</td>"
                f"<td>{_pct((grading.get('claims_supported', 0) / grading['claims_total']) if grading.get('claims_total') else None)}"
                f"</td><td>{links.get('open', 0)}/{links.get('total', 0)}</td><td>{row['seconds']:.1f}</td>"
                f"<td>{'—' if row['usd'] is None else f'{row['usd']:.4f}'}</td>"
                f"<td class='chips'>{_chips(row['failures'])}</td></tr>"
                f"<tr class='logs'><td colspan='8'><details><summary>Question, answer, grader's reasoning, evidence"
                f"</summary>{_details(row)}</details></td></tr>")
        page = (_header(document)
                + "<h2>Cases</h2>"
                + (f"<p>Sorted by {esc(next(label for k, label, _ in COLUMNS if k == key))}: "
                   f"{'low → high' if direction == 'asc' else 'high → low'} · <a href='index.html'>original order</a></p>"
                   if key else "")
                + "<div class='scroll'><table><tr><th>Case</th>" + header + "<th>Failure classes</th></tr>"
                + "".join(lines) + "</table></div>"
                + "<p class='note'>The grader is a different agent from the answerer, but it is still a model: "
                "this is a model-assisted measurement, not human-adjudicated truth, on a small case set. "
                "Required facts are scored only for cases with a rubric. Missing grades stay visible as "
                "UNGRADED and are not counted as passes.</p>")
        (out / (name(key, direction) if key else "index.html")).write_text(
            _page("Engine tuning", page), encoding="utf-8")
    return out / "index.html"


def _delta(entry: dict, scale: float = 1.0, unit: str = "", digits: int = 1) -> str:
    if entry["mean"] is None:
        return "—"
    text = f"{entry['mean'] * scale:+.{digits}f}{unit}"
    if entry["ci95"]:
        text += f" (95% interval {entry['ci95'][0] * scale:+.{digits}f} to {entry['ci95'][1] * scale:+.{digits}f})"
    return text + f" over {entry['pairs']} pair(s)"


def build_comparison(result: dict, out: Path) -> Path:
    """Write `compare.html`: the paired before/after comparison."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    rate = result["pass_rate"]
    flags = "".join(f"<li class='warn'>{esc(note)}</li>" for note in result["notes"])
    first, second = result["before"], result["after"]

    def side(one: dict) -> str:
        engine = one["engine"]
        return (f"{esc(one['label'] or 'run')} · engine {esc(engine.get('version', ''))} "
                f"{esc((engine.get('git_sha') or '')[:10])}{' (uncommitted)' if engine.get('dirty') else ''}"
                f" · answered by {esc(_who((one['answered_by'] or {}).get('agent') or {}))}"
                f" · graded by {esc(_who(one['graded_by']))}")

    counts = result["failure_classes"]
    class_rows = "".join(
        f"<tr><td>{esc(name)}</td><td>{counts['before'].get(name, 0)}</td><td>{counts['after'].get(name, 0)}</td></tr>"
        for name in failures.CLASSES if name in counts["before"] or name in counts["after"])
    case_rows = "".join(
        f"<tr><td>{esc(row['case'])}</td><td>{esc(row['before'])}</td><td>{esc(row['after'])}</td>"
        f"<td class='{'ok' if row['change'] == 'improved' else 'bad' if row['change'] == 'regressed' else ''}'>"
        f"{esc(row['change'])}</td><td class='chips'>{_chips(row['failures_before'])}</td>"
        f"<td class='chips'>{_chips(row['failures_after'])}</td></tr>"
        for row in sorted(result["rows"], key=lambda r: ({"regressed": 0, "improved": 1}.get(r["change"], 2), r["case"])))
    p = result["sign_test_p"]
    body = (
        "<h1>Before and after</h1>"
        f"<p class='who'>Before: {side(first)}<br>After: {side(second)}</p>"
        + (f"<ul>{flags}</ul>" if flags else "")
        + f"<h2>{esc(result['verdict'])}</h2>"
        "<table class='kv'>"
        f"<tr><td>Pairs</td><td>{result['paired']} graded in both runs over {result['cases_compared']} case(s); "
        f"{result['left_out']} left out (unpaired or ungraded)</td></tr>"
        f"<tr><td>Pass rate</td><td>{_pct(rate['before'])} → {_pct(rate['after'])}; difference "
        f"{'—' if rate['delta'] is None else f'{rate['delta'] * 100:+.1f} points'}"
        f"{'' if not rate['ci95'] else f' (95% interval {rate['ci95'][0] * 100:+.1f} to {rate['ci95'][1] * 100:+.1f})'}</td></tr>"
        f"<tr><td>Changed verdict</td><td>{len(result['improved'])} improved, {len(result['regressed'])} regressed; "
        f"{len(result['still_passing'])} passed both, {len(result['still_failing'])} failed both"
        f"{'' if p is None else f'; exact sign test p = {p:.3f}'}</td></tr>"
        f"<tr><td>Required facts</td><td>{esc(_delta(result['fact_credit'], 100, ' points'))}</td></tr>"
        f"<tr><td>Claims supported</td><td>{esc(_delta(result['claims_supported'], 100, ' points'))}</td></tr>"
        f"<tr><td>Seconds</td><td>{esc(_delta(result['seconds']))}</td></tr>"
        f"<tr><td>USD</td><td>{esc(_delta(result['usd'], 1, '', 4))}</td></tr>"
        f"<tr><td>Tokens</td><td>{esc(_delta(result['tokens'], 1, '', 0))}</td></tr></table>"
        "<h2>Failure classes</h2><table class='inner'><tr><th>Class</th><th>Before</th><th>After</th></tr>"
        + (class_rows or "<tr><td colspan='3'>No failed attempt in either run.</td></tr>") + "</table>"
        "<h2>Cases</h2><div class='scroll'><table><tr><th>Case</th><th>Before</th><th>After</th><th>Change</th>"
        "<th>Failure classes before</th><th>after</th></tr>" + case_rows + "</table></div>"
        "<p class='note'>Differences are paired by case and repetition; the interval resamples whole cases, "
        "because repetitions of one case are not independent. A small case set gives a wide interval, and an "
        "interval that includes zero does not distinguish the runs. Both runs are graded by a model.</p>")
    path = out / "compare.html"
    path.write_text(_page("Before and after", body), encoding="utf-8")
    return path
