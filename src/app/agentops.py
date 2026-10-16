"""The research operations an agent performs, with no door attached.

`research_brief`, `research_agenda` and `submit_findings` used to exist only as
MCP tools, which made MCP the one door a harness had to walk through to do
research at all — and MCP is the door that was failing to connect while the
CLI next to it worked. So the bodies live here and every door is a wrapper:

    kriko agenda --pack org.kriko.cars
    kriko brief  <subject_id> --pack org.kriko.cars
    kriko submit <subject_id> --pack org.kriko.cars findings.json

`app/mcp_server.py` calls the same three functions. **The acceptance path does
not move**: `submit` goes through `accept_findings` and `log_submission`
exactly as the MCP tool always did, so a claim's provenance still does not
depend on which door it came in — the door is only the label on the
submissions row and the operations feed.

Everything prints and takes JSON, because the caller is an agent that reads
`--help`, not a person reading a table.
"""

from collections.abc import Sequence
from pathlib import Path

from app import agenda as _agenda
from app.findings import accept_findings, log_submission
from kriko.research import get_researcher, plan_task


def prior_runs(app_state_path, subject_id: str, pack_id: str,
               limit: int = 20) -> list:
    """One subject's earlier submissions, oldest first. `[]` when there is none.

    The memory half of the loop: `brief` renders these, so a run starts from
    what earlier runs learned instead of re-running their dead ends. Read
    from the interface's own log (`submissions`), which every door writes
    through `log_submission` — so a run's memory does not depend on which
    door the runs before it came in through.

    A missing or unreadable log is `[]`, never an error: a researcher with
    no history is the ordinary first-run case, and the brief simply renders
    no memory section.
    """
    if not app_state_path:
        return []
    try:
        from app.web import state

        conn = state.connect(Path(app_state_path))
    except Exception:  # noqa: BLE001 — see the docstring
        return []
    try:
        return state.submissions_for(conn, subject_id, pack_id, limit)
    except Exception:  # noqa: BLE001
        return []
    finally:
        conn.close()


def _digest(runs: Sequence) -> list:
    """Raw submissions as the brief remembers them: counts, queries, refusal heads.

    The reasons are grouped on their first clause exactly as the author's
    own refusal tally groups them (`state.refusal_reasons`), so the same
    sentence the author tunes against is the one a next run writes past.
    """
    out = []
    for row in runs:
        verdicts = (row or {}).get("verdicts") or {}
        heads: dict[str, int] = {}
        for one in verdicts.get("rejected") or []:
            reason = str(one.get("reason") or "unstated")
            head = reason.split("—")[0].split(";")[0].strip() or reason
            heads[head] = heads.get(head, 0) + 1
        out.append({
            "kept": len(verdicts.get("accepted") or []),
            "refused": len(verdicts.get("rejected") or []),
            "queries": [str(q) for q in row.get("queries") or []],
            "refusal_heads": [
                head for head, _ in
                sorted(heads.items(), key=lambda kv: (-kv[1], kv[0]))[:3]
            ],
        })
    return out


def brief(conn, subject_id: str, pack_id: str, *, effort: str = "fast",
          app_state_path=None) -> dict:
    """What to research about this subject, in this pack's own terms.

    `effort` is how much run the caller is buying — `fast` or `deep`; the
    brief states its budget either way. `app_state_path` is where the
    submission log lives: with it, the brief remembers what earlier runs on
    this subject did; without it, it remembers nothing and is still a brief.
    """
    task = plan_task(
        conn, subject_id, pack_id, effort=effort,
        prior_runs=tuple(_digest(prior_runs(app_state_path, subject_id, pack_id))),
    )
    return {
        "subject": task.subject_label,
        "mode": task.effort,
        "queries": list(task.rendered_queries()),
        "brief": get_researcher().brief(task),
    }


def agenda(conn, *, app_state_path, log_path, pack_id: str = "", limit: int = 20) -> dict:
    """What to research next, in the order it is worth it (`app/agenda.py`).

    The app's own database is optional here: without it the agenda still
    ranks, it only cannot see stale re-checks. A missing interface file is
    never why an agent is told there is nothing to do.
    """
    app_state = None
    try:
        from app.web import state as _state

        app_state = _state.connect(Path(app_state_path))
    except Exception:  # noqa: BLE001 — see the docstring
        app_state = None
    try:
        return _agenda.compute(
            conn, app_state=app_state, log_path=log_path,
            pack_id=pack_id, limit=limit,
        )
    finally:
        if app_state is not None:
            app_state.close()


def submit(
    conn,
    *,
    app_state_path,
    door: str,
    subject_id: str,
    pack_id: str,
    findings: list[dict],
    queries: Sequence[str] | None = None,
) -> dict:
    """Store what the agent read; ungrounded and low-value findings are refused.

    The per-finding verdicts come back to the caller, and the batch is logged
    to `app.sqlite` under `door` after acceptance has decided — the log is
    bookkeeping, never a condition of a finding being kept. The store is
    committed first, so the log can never describe a batch the store lost.
    """
    kept: list[dict] = []
    verdicts = accept_findings(conn, subject_id, pack_id, findings, retain=kept)
    conn.commit()
    log_submission(
        app_state_path,
        door=door,
        subject_id=subject_id,
        pack_id=pack_id,
        verdicts=verdicts,
        queries=queries,
        documents=kept,
    )
    return verdicts
