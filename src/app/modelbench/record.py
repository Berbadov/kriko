"""Writing a sweep into the app's own history, so the interface can show it.

The report files are the deliverable; this is how the same measurements reach
the screen the Tauri interface will build. It is a **projection**, not a second
measurement: one `Measurement` becomes one `bench_runs` row, and nothing is
recomputed on the way.

`bench_runs` was designed around *planes* and *protocols*, so a model-centric
row has to be spelled in its vocabulary. The mapping is deliberate and worth
reading before trusting a column:

* `plane` ← the candidate's kind (`local` | `harness` | `api`). That is what the
  kind is: how the model was reached.
* `model` ← the model, and `harness` is folded into it when a CLI drove it, so
  the row a reader sees is the thing they would type.
* `protocol` ← `modelbench-v1`, a name that is deliberately **not** in
  `app.protocols.CATALOGUE`. A protocol is a context/batch choice, and this
  sweep did not sweep one; naming it something the catalogue knows would make
  `protocols.readout` report a batch size that was never used.
* `accepted` / `refused` ← expected facts found / items the key could not
  support. These are the closest honest reading of the two columns: what came
  back and stood up, and what came back and did not.
* `gold` ← the score itself, in the shape `protocols.readout` already reads, so
  the existing readout shows the new numbers without a second code path.
* `tokens` ← the metered total, and `None` when nobody counted. Never 0.

**Opt-in, never automatic.** `record_bench` is the reader's history. A benchmark
that wrote to it without being asked would be the same class of mistake as one
that grew the pack it measured — so this runs only behind `--record`.
"""

#: The `protocol` value every projected row carries. See the module docstring.
PROTOCOL = "modelbench-v1"


def legacy_row(measurement, case: dict) -> dict:
    """One `Measurement` as one `bench_runs` row."""
    score = dict(measurement.score or {})
    found = list(score.get("found") or [])
    fabricated = int(score.get("fabricated") or 0)
    missed = list(score.get("missed") or [])
    model = measurement.model or measurement.candidate_id
    if measurement.harness and measurement.harness not in model:
        model = f"{measurement.harness}/{model}"
    row = {
        "batch_id": "",
        "subject_id": measurement.case_id,
        "subject": str(case.get("product") or measurement.case_id),
        "pack_id": "",
        "plane": measurement.kind,
        "model": model,
        "protocol": PROTOCOL,
        "context_chars": None,
        "batch_size": None,
        "kind": "fixed",
        "set_id": measurement.set_id,
        "set_version": measurement.set_version,
        "rep": measurement.rep,
        "ms": measurement.ms,
        "tokens": measurement.reply.tokens_total,
        "usd": measurement.reply.usd,
        "documents": len(case.get("documents") or []),
        # The two columns `readout` divides to get an acceptance rate. See the
        # module docstring for why these are the honest reading.
        "accepted": len(found),
        "refused": fabricated,
        "findings": len(found) + len(missed),
        "reasons": [
            str(one.get("reason") or "")[:200]
            for one in (score.get("errors") or [])[:5] if isinstance(one, dict)
        ],
        "error": measurement.error,
        "note": _note(measurement),
        "search_provider": "supplied-corpus",
        "detail": {
            "candidate": measurement.candidate_id,
            "candidate_label": measurement.candidate_label,
            "dimension": measurement.dimension,
            "prompt_fingerprint": measurement.prompt_fingerprint,
            "prompt_chars": measurement.prompt_chars,
            "answer_key": measurement.answer_key,
        },
    }
    if score:
        # `abstention_expected` is the one field `readout` wants that the
        # verdict does not carry on its own: the verdict says whether the model
        # abstained, not whether abstaining was the right answer.
        row["gold"] = {
            **score,
            "case": measurement.case_id,
            "abstention_expected": bool(measurement.answer_key.get("expect_abstention")),
            # `readout` computes a hallucination rate as
            # `hallucinated / raw_produced`, falling back to `findings` when the
            # key is absent — and `findings` here is facts *expected*, not items
            # the model put forward. Without this line the app's screen and this
            # benchmark's report would divide the same numerator by two
            # different denominators and publish two different rates for one
            # fact, which is the exact failure this module exists to avoid.
            "raw_produced": int(score.get("produced") or 0),
            "measurement": {
                "tokens_in": measurement.reply.tokens_in,
                "tokens_out": measurement.reply.tokens_out,
                "stages": [],
                "finish_reason": measurement.reply.finish_reason,
                "verification": None,
                "cost_basis": "per_token" if measurement.reply.usd is not None
                              else "unknown",
                # Strictly: `reported` or `reported_total` is a count somebody
                # made; `estimated` and `none` are not, and saying they were
                # complete is what would let a guess into a mean.
                "usage_complete": measurement.reply.metered,
                "usage": measurement.reply.usage,
            },
        }
    return row


def _note(measurement) -> str:
    if measurement.error:
        return f"model benchmark: failed — {measurement.error[:160]}"
    return (f"model benchmark ({measurement.dimension or 'case'}), "
            f"tokens {measurement.reply.usage}")


def record(app_state_path, measurements: list, cases_by_id: dict) -> int:
    """Write every successful projection into `bench_runs`. Returns the count.

    A row with no case to describe is skipped rather than written half-empty: a
    history row that cannot say what was measured is worse than a missing one.
    """
    from app.web import state

    conn = state.connect(app_state_path)
    written = 0
    try:
        for measurement in measurements:
            case = cases_by_id.get(measurement.case_id)
            if case is None:
                continue
            state.record_bench(conn, legacy_row(measurement, case))
            written += 1
    finally:
        conn.close()
    return written
