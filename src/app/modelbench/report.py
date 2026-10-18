"""The artifact: one sweep, in three shapes for three readers.

* **JSON** — everything, including the per-case evidence, for a script or the
  next version of the interface.
* **CSV** — the aggregate table and the per-case rows, for a spreadsheet, which
  is where a model choice actually gets argued about.
* **Markdown** — the readable report, with the caveats *in* it.

The Markdown is not a decoration on the JSON. It carries three things a bare
table cannot, and each one exists because its absence is how a benchmark starts
lying:

**Comparability first.** The report opens by naming the corpus version and the
prompt fingerprints actually used. Two runs that disagree on a fingerprint did
not measure the same task, and their numbers should never be put in one table.

**Token honesty.** Every candidate states whether its counts were reported by
the endpoint, reported as a whole-session total by a CLI, estimated, or not
available at all. "9,000 tokens" from a coding-agent CLI and "900 tokens" from a
local model are both true and mean different things; a report that printed them
side by side without saying so would invite exactly the wrong conclusion.

**Where it fails, not only how much.** The per-dimension section is the part a
reader acts on: a model that is sound everywhere except under distractor load
has a context problem, and a model that fabricates on the exclusion cases has a
reasoning problem.
"""

import csv
import json
from pathlib import Path

#: Printed for a number that does not exist. A dash, never a zero: the whole
#: point of several columns is that "not measured" and "measured as nothing"
#: are different answers.
NONE = "—"


def _pct(value, interval=None) -> str:
    if value is None:
        return NONE
    text = f"{value * 100:.0f}%"
    if interval:
        low, high = interval
        text += f" ({low * 100:.0f}–{high * 100:.0f}%)"
    return text


def _num(value, suffix: str = "") -> str:
    if value is None:
        return NONE
    if isinstance(value, float):
        text = f"{value:,.1f}"
    else:
        text = f"{value:,}"
    return text + suffix


def _ms(value) -> str:
    if value is None:
        return NONE
    return f"{value / 1000:.1f}s"


def _figure(value) -> str:
    """A count or a ratio, without trailing noise: `1,439.5`, not `1439.500`."""
    if isinstance(value, float):
        text = f"{value:,.3f}".rstrip("0").rstrip(".")
        return text or "0"
    return f"{value:,}"


def _bare(value) -> str:
    return "" if value is None else str(value)


def _chart(name: str, stem: str, alt: str) -> list[str]:
    """An embedded chart, as the two lines of Markdown that carry it.

    The image sits *before* the table it summarises, because a reader who
    understands the picture can then read the table as detail rather than
    having to reconstruct the picture from it. The alt text repeats the finding
    for a reader who cannot see it and for the plain-text view on a phone.
    """
    if not stem:
        return []
    return [f"![{alt}]({stem}-{name}.svg)", ""]


def markdown(rows: list, aggregate: list[dict], dimensions: list[dict],
             cases: list[dict], *, title: str, when: str, machine: str = "",
             notes: list[str] | None = None, stem: str = "") -> str:
    """The readable report: comparability, the table, honesty, then the detail."""
    from app.modelbench import aggregate as agg

    shape = agg.summary(rows)
    lines: list[str] = []
    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"Measured {when}." + (f" On {machine}." if machine else ""))
    lines.append("")
    lines.append("## What was measured")
    lines.append("")
    for one in shape["sets"]:
        lines.append(f"- Corpus **{one['set_id']}** version **{one['set_version']}**")
    lines.append(f"- {shape['case_count']} case(s), {shape['runs']} run(s), "
                 f"{shape['graded_runs']} scored, {shape['failed_runs']} failed")
    lines.append(f"- Candidates: {', '.join('`' + one + '`' for one in shape['candidates'])}")
    split = shape["cases_with_split_briefs"]
    if shape["fingerprints_agree"]:
        lines.append(
            f"- Comparability check passed: every candidate received a "
            f"byte-identical brief for each of the {shape['case_count']} case(s). "
            "The comparison is fair."
        )
    else:
        lines.append(
            f"- **Comparability check FAILED** on {len(split)} case(s): "
            + ", ".join(f"`{one}`" for one in split)
            + ". Two candidates were given different text for the same case, so "
            "these rows are not comparable and the table below is not a ranking."
        )
    lines.append("")
    if notes:
        for note in notes:
            lines.append(f"> {note}")
        lines.append("")

    lines.append("## The comparison")
    lines.append("")
    lines.extend(_chart(
        "tradeoff", stem,
        "Scatter of tokens per run against fabrication rate; bubble area is "
        "expected facts found, bars are 95% intervals. Cheapest and cleanest is "
        "the bottom left."))
    lines.append("| Model | Reached by | Runs | Failed | Answered in shape | Claimed | "
                 "Correct facts | Hallucinated | Specs found | Wrong specs | Abstained | "
                 "Tokens/run | Tokens/fact | Median time |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for one in aggregate:
        lines.append("| " + " | ".join([
            f"`{one['candidate']}`",
            one["kind"],
            _num(one["runs"]),
            _pct(one["failure_rate"]),
            _pct(one["valid_shape_rate"]),
            _num(one["produced"]),
            _pct(one["recall"], one.get("recall_interval")),
            _pct(one["hallucination_rate"], one.get("hallucination_interval")),
            _pct(one["spec_recall"]),
            _pct(one["spec_error_rate"], one.get("spec_error_interval")),
            _pct(one["abstention_accuracy"]),
            _num(one["tokens_total_mean"]),
            _num(one["tokens_per_fact"]),
            _ms(one["latency_p50_ms"]),
        ]) + " |")
    lines.append("")
    lines.append("**Answered in shape** is how often the reply was even the requested "
                 "JSON object, and **Claimed** is how many items it put forward in "
                 "total. Both are here because the hallucination column needs a "
                 "visible denominator: a model that produced nothing has *no* "
                 "hallucination rate, and a dash in that column means \"nothing was "
                 "claimed\", never \"nothing was wrong\".")
    lines.append("")
    lines.append("**Specs found** is the share of requested specifications answered "
                 "with the key's exact name, value and URL, and **Wrong specs** is the "
                 "share of the ones it *did* return that were wrong. They are a pair "
                 "on purpose: a model that returns no figures scores no wrong specs, "
                 "and only the first column shows that it found nothing.")
    lines.append("")
    lines.append("**Correct facts** and **hallucinated** are pooled over every item "
                 "produced, with their 95% Wilson intervals in brackets; the interval "
                 "is the honest part, because a rate from five items is an anecdote. "
                 "**Tokens/fact** divides counted tokens by expected facts found, so a "
                 "cheap model that found nothing does not win it.")
    lines.append("")
    lines.extend(_chart(
        "quality", stem,
        "Horizontal bars of the five pooled rates per model: correct facts, "
        "hallucinated, specs found, wrong specs and abstention. Green bars mean "
        "a higher number is better; red bars mean a higher number is worse."))
    lines.extend(_chart(
        "tokens", stem,
        "Mean tokens per run per model, split into sent and returned where the "
        "transport reported a split. A dashed outline marks a whole-session "
        "figure from a coding-agent CLI, which is a different kind of number."))

    lines.append("## What the token numbers mean")
    lines.append("")
    lines.append("| Model | Counted | What the counter saw | In | Out | Total | Notes |")
    lines.append("|---|---|---|---|---|---|---|")
    for one in aggregate:
        lines.append("| " + " | ".join([
            f"`{one['candidate']}`",
            f"{one['metered_runs']}/{one['runs']}",
            _usage_words(one),
            _num(one["tokens_in_mean"]),
            _num(one["tokens_out_mean"]),
            _num(one["tokens_total_mean"]),
            _usage_note(one),
        ]) + " |")
    lines.append("")
    lines.append("- **reported** — the endpoint sent a usage block, so the split is real.")
    lines.append("- **reported total** — a coding-agent CLI metered its whole session "
                 "(its own system prompt, its tools, every turn). A large number here "
                 "is the harness's cost, not the brief's.")
    lines.append("- **estimated** — nobody counted; in and out were approximated from "
                 "characters. Never used by the means above.")
    lines.append("- **not counted** — nobody counted and no estimate was safe.")
    lines.append("")

    if len(aggregate) > 1:
        lines.append("## Who leads, and on what")
        lines.append("")
        lines.extend(_leaders(aggregate))
        lines.append("")

    lines.append("## What kind of fabrication")
    lines.append("")
    lines.extend(_chart(
        "fabrication", stem,
        "Counts per model of claims the documents did not support, the subset "
        "whose quotation is not in the page it names, and specifications "
        "returned under the wrong name, value or URL."))
    lines.append("| Model | Items claimed | Not supported | of which a bad quote | "
                 "Specs returned | Specs wrong |")
    lines.append("|---|---|---|---|---|---|")
    for one in aggregate:
        lines.append("| " + " | ".join([
            f"`{one['candidate']}`",
            _num(one["produced"]),
            _num(one["fabricated"]),
            _num(one["unsupported_quotes"]),
            _num(one["specs_produced"]),
            _num(one["specs_wrong"]),
        ]) + " |")
    lines.append("")
    lines.append("Counts, not rates, because the three failures have different "
                 "remedies and only the counts show which one a model suffers from. "
                 "**Not supported** is a claim the documents do not make or a quote "
                 "that is not in the page it names; **a bad quote** is the subset "
                 "where the quotation itself does not appear; **specs wrong** is a "
                 "figure returned under the wrong name, value or URL. A model with "
                 "many claims and few bad quotes is over-reaching; one with many bad "
                 "quotes is not reading.")
    lines.append("")

    if dimensions:
        lines.append("## Where each model fails")
        lines.append("")
        lines.extend(_chart(
            "dimensions", stem,
            "Grid of models against the case dimension each case was built to "
            "test, shaded by the share of claimed items the documents did not "
            "support. A dash means nothing was claimed for that case."))
        lines.append("| Model | Case dimension | Correct facts | Hallucinated | Runs |")
        lines.append("|---|---|---|---|---|")
        for one in dimensions:
            lines.append("| " + " | ".join([
                f"`{one['candidate']}`",
                one["dimension"],
                _pct(one["recall"], one.get("recall_interval")),
                _pct(one["hallucination_rate"], one.get("hallucination_interval")),
                _num(one["runs"]),
            ]) + " |")
        lines.append("")

    failures = _all_failures(aggregate)
    if failures:
        lines.append("## Failures, by cause")
        lines.append("")
        lines.append("| Model | Failure | Count |")
        lines.append("|---|---|---|")
        for line in failures:
            lines.append("| " + " | ".join(line) + " |")
        lines.append("")

    lines.append("## Run by run")
    lines.append("")
    lines.append("| Model | Case | Dimension | Correct | Missed | Invented | "
                 "Tokens | Usage | Time | Error |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for one in cases:
        lines.append("| " + " | ".join([
            f"`{one['candidate']}`",
            one["case"],
            one["dimension"] or NONE,
            _num(len(one["found"])),
            _num(len(one["missed"])),
            _num(len(one["hallucinated"])),
            _num(one["tokens_total"]),
            one["usage"],
            _ms(one["ms"]),
            (one["error"][:60] + "…") if len(one["error"]) > 60 else (one["error"] or ""),
        ]) + " |")
    lines.append("")
    return "\n".join(lines) + "\n"


def _usage_words(one: dict) -> str:
    """What the counter was, in a phrase, for the token table.

    "reported total" is decided by the *absence* of a split, not by a flag on the
    row: a CLI that meters a whole session and an endpoint that returns only a
    grand total are the same fact to a reader, and `tokens_in_runs == 0` is
    exactly that fact. Getting this wrong is not cosmetic — it would label an
    8,000-token session total as an endpoint-reported split, which is the one
    reading the notes below tell a reader to trust.
    """
    if one["metered_runs"] and not one.get("tokens_in_runs"):
        return "reported total"
    if one["metered_runs"]:
        return "reported"
    if one["estimated_runs"]:
        return "estimated"
    return "not counted"


def _usage_note(one: dict) -> str:
    parts = []
    if one["metered_runs"]:
        parts.append(f"{one['metered_runs']}/{one['runs']} metered")
    if one["estimated_runs"]:
        parts.append(f"{one['estimated_runs']} estimated (excluded from means)")
    if one["unmetered_runs"]:
        parts.append(f"{one['unmetered_runs']} not counted")
    return "; ".join(parts) or NONE


def _leaders(aggregate: list[dict]) -> list[str]:
    """One line per metric, naming the leader — and refusing when it is a tie.

    A winner with a 0.2% margin and an overlapping interval is noise, and a
    report that anoints one is how a benchmark becomes folklore. Where two
    intervals overlap the line says so instead of choosing.
    """
    out: list[str] = []

    def _best(label: str, key: str, *, higher: bool, rate_key: str = "") -> None:
        scored = [one for one in aggregate if one.get(key) is not None]
        if len(scored) < 2:
            out.append(f"- **{label}**: not enough measured to compare.")
            return
        ordered = sorted(scored, key=lambda one: one[key], reverse=higher)
        top, second = ordered[0], ordered[1]
        if rate_key:
            first_interval = top.get(rate_key) or (0, 1)
            second_interval = second.get(rate_key) or (0, 1)
            overlaps = (first_interval[0] <= second_interval[1]
                        and second_interval[0] <= first_interval[1])
            if overlaps:
                out.append(
                    f"- **{label}**: `{top['candidate']}` leads on the point "
                    f"estimate but its interval overlaps `{second['candidate']}`'s. "
                    "Not yet separable — run more repetitions."
                )
                return
        out.append(f"- **{label}**: `{top['candidate']}` ({_figure(top[key])})")

    _best("Most expected facts found", "recall", higher=True, rate_key="recall_interval")
    _best("Fewest invented claims", "hallucination_rate", higher=False,
          rate_key="hallucination_interval")
    _best("Most accurate specifications", "spec_error_rate", higher=False,
          rate_key="spec_error_interval")
    _best("Cheapest per expected fact", "tokens_per_fact", higher=False)
    _best("Fastest median answer", "latency_p50_ms", higher=False)
    return out


def _all_failures(aggregate: list[dict]) -> list[list[str]]:
    out: list[list[str]] = []
    for one in aggregate:
        for failure in one.get("failures") or []:
            out.append([f"`{one['candidate']}`", failure["error"],
                        str(failure["count"])])
    return out


def candidate_csv(aggregate: list[dict]) -> str:
    """The aggregate table as CSV text."""
    columns = [
        "candidate", "candidate_label", "kind", "runs", "graded", "failed",
        "failure_rate", "valid_shape_rate", "recall", "recall_interval",
        "hallucination_rate", "hallucination_interval", "spec_recall",
        "spec_error_rate", "spec_error_interval", "abstention_accuracy",
        "pass_rate", "wanted", "found", "accepted", "produced", "fabricated",
        "unsupported_quotes", "specs_wanted", "specs_found", "specs_produced",
        "specs_wrong", "tokens_total_mean", "tokens_total_median",
        "tokens_in_mean", "tokens_out_mean", "tokens_per_fact",
        "tokens_per_accepted", "tokens_per_claim", "usd_total", "usd_per_fact",
        "usd_per_accepted", "metered_runs", "estimated_runs", "unmetered_runs",
        "latency_p50_ms", "latency_p95_ms",
    ]
    return _csv(columns, aggregate)


def case_csv(cases: list[dict]) -> str:
    """The per-case rows as CSV text."""
    columns = [
        "candidate", "candidate_label", "kind", "case", "dimension", "rep",
        "ms", "error", "tokens_in", "tokens_out", "tokens_total", "usage",
        "usd", "finish_reason", "brief_chars", "reply_chars",
        "prompt_fingerprint", "set_id", "set_version",
    ]
    return _csv(columns, cases)


def _csv(columns: list[str], rows: list[dict]) -> str:
    import io

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(columns)
    for row in rows:
        writer.writerow([_cell(row.get(column)) for column in columns])
    return buffer.getvalue()


def _cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return "–".join(str(one) for one in value)
    if isinstance(value, dict):
        return json.dumps(value, sort_keys=True)
    return str(value)


def build(rows: list, *, title: str, when: str, machine: str = "",
          notes: list[str] | None = None) -> dict:
    """The whole document, computed from rows and nothing else.

    One builder for both a fresh sweep and a re-render, so a report is always
    cut with the *current* formulas. The alternative — re-rendering from the
    aggregate stored in an old JSON — means a fix to a rate never reaches a
    report that was already paid for, and a stale number in a file is exactly
    the folklore this benchmark exists to avoid.
    """
    from app.modelbench import aggregate as agg

    return {
        "title": title,
        "measured_at": when,
        "machine": machine,
        "set": agg.summary(rows),
        "candidates": agg.by_candidate(rows),
        "by_dimension": agg.by_dimension(rows),
        "runs": agg.by_case(rows),
        "notes": list(notes if notes is not None else caveats(rows)),
    }


def caveats(rows: list) -> list[str]:
    """The sentences a reader must not be able to miss, derived from the rows.

    In the document rather than only in a terminal, because a report is the
    thing that gets pasted somewhere: a caveat that stayed in the console is a
    caveat the next reader never saw.
    """
    from app.modelbench import aggregate as agg

    out: list[str] = []
    shape = agg.summary(rows)
    counted = agg.by_candidate(rows)
    unmetered = [one["candidate"] for one in counted
                 if one["unmetered_runs"] or one["estimated_runs"]]
    if unmetered:
        out.append(
            "Token counts are not available for every run of: "
            + ", ".join(f"`{one}`" for one in unmetered)
            + ". Those runs are excluded from the token means rather than counted as zero."
        )
    # A candidate that never produced the requested shape has no recall and no
    # hallucination rate — two dashes that could be misread as "nothing wrong".
    # Naming it is the difference between a report and a trap.
    shapeless = [one["candidate"] for one in counted
                 if one["valid_shape_rate"] == 0 and one["graded"]]
    if shapeless:
        out.append(
            "These candidates never returned the requested JSON shape, so they "
            "produced no claims to score: "
            + ", ".join(f"`{one}`" for one in shapeless)
            + ". Their dashes mean *nothing was claimed*, not *nothing was wrong*."
        )
    if shape["failed_runs"]:
        out.append(
            f"{shape['failed_runs']} of {shape['runs']} runs failed. A failure is a "
            "result: those runs are in the failure rate and are not scored."
        )
    if shape["case_count"] and shape["case_count"] < 4:
        out.append(
            "Fewer than four cases were run, so every interval in this report is wide. "
            "Treat the ranking as a direction, not a decision."
        )
    return out


def write(directory, rows: list, *, stem: str = "modelbench", title: str,
          when: str, machine: str = "", notes: list[str] | None = None) -> dict:
    """Write all four shapes beside each other. Returns the paths written."""
    out = Path(directory)
    out.mkdir(parents=True, exist_ok=True)
    document = build(rows, title=title, when=when, machine=machine, notes=notes)
    return {name: str(path)
            for name, path in _write_all(out, stem, document, rows).items()}


def rerender(source, *, directory="", stem: str = "", title: str = "",
             when: str = "") -> dict:
    """Rebuild every shape from a saved JSON, without spending anything.

    A report is a *view* of measurements, and a view should not cost a sweep to
    correct. This is how a formatting or a labelling fix reaches a report that
    was already paid for — and, more usefully, how the same measurements can be
    re-cut for a different question later.
    """
    document = json.loads(Path(source).read_text(encoding="utf-8"))
    rows = rows_from_document(document)
    fresh = build(
        rows,
        title=title or str(document.get("title") or "Model benchmark"),
        when=when or str(document.get("measured_at") or ""),
        machine=str(document.get("machine") or ""),
    )
    out = Path(directory) if directory else Path(source).parent
    target = stem or Path(source).stem
    return {name: str(path)
            for name, path in _write_all(out, target, fresh, rows).items()}


def rows_from_document(document: dict) -> list:
    """`Measurement`s back out of a saved report.

    Rebuilt rather than re-derived from anything — a saved run must never need
    the model to be reachable, or a report could not be read on a machine that
    no longer has the model. What is not in the JSON (`answer_key`) comes back
    empty, which is correct: the report does not print it.
    """
    from app.modelbench.runner import Measurement
    from app.modelbench.sockets import Reply

    rows = []
    for one in document.get("runs") or []:
        score = dict(one.get("score") or {})
        if score and "specs_produced" not in score:
            # A report written before this field existed still knows which
            # specifications were right and which were wrong, so the denominator
            # is derivable. Printing a dash instead would read as "no wrong
            # specs", which is the one thing this column exists to distinguish.
            score["specs_produced"] = (len(score.get("spec_found") or [])
                                       + len(score.get("spec_errors") or []))
        row = Measurement(
            candidate_id=str(one.get("candidate") or ""),
            candidate_label=str(one.get("candidate_label") or ""),
            kind=str(one.get("kind") or ""),
            model=str(one.get("model") or ""),
            harness=str(one.get("harness") or ""),
            case_id=str(one.get("case") or ""),
            dimension=str(one.get("dimension") or ""),
            set_id=str(one.get("set_id") or ""),
            set_version=str(one.get("set_version") or ""),
            prompt_fingerprint=str(one.get("prompt_fingerprint") or ""),
            prompt_chars=int(one.get("prompt_chars") or 0),
            rep=int(one.get("rep") or 1),
            ms=one.get("ms"),
            error=str(one.get("error") or ""),
            score=score,
        )
        row.reply = Reply(
            model=row.model,
            tokens_in=one.get("tokens_in"),
            tokens_out=one.get("tokens_out"),
            tokens_total=one.get("tokens_total"),
            usage=str(one.get("usage") or "none"),
            finish_reason=str(one.get("finish_reason") or ""),
            usd=one.get("usd"),
            brief_chars=int(one.get("brief_chars") or 0),
            reply_chars=int(one.get("reply_chars") or 0),
        )
        rows.append(row)
    return rows


def _write_all(out: Path, stem: str, document: dict, rows: list) -> dict:
    """Every file, from one document. The only place a path is named."""
    from app.modelbench import charts

    paths = {
        "json": out / f"{stem}.json",
        "candidates_csv": out / f"{stem}-candidates.csv",
        "cases_csv": out / f"{stem}-cases.csv",
        "markdown": out / f"{stem}.md",
    }
    paths["json"].write_text(json.dumps(document, indent=2, sort_keys=False),
                             encoding="utf-8")
    paths["candidates_csv"].write_text(
        candidate_csv(document.get("candidates") or []), encoding="utf-8")
    paths["cases_csv"].write_text(case_csv(document.get("runs") or []),
                                  encoding="utf-8")
    paths["markdown"].write_text(
        markdown(rows, document.get("candidates") or [],
                 document.get("by_dimension") or [], document.get("runs") or [],
                 title=str(document.get("title") or "Model benchmark"),
                 when=str(document.get("measured_at") or ""),
                 machine=str(document.get("machine") or ""),
                 notes=list(document.get("notes") or []),
                 stem=stem),
        encoding="utf-8",
    )
    # The charts are part of the report and are rebuilt with it, so a corrected
    # rate cannot leave a stale graph standing beside it.
    for name, path in charts.write(out, stem, document).items():
        paths[f"chart_{name}"] = Path(path)
    return paths
