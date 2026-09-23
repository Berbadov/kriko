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


def brief(conn, subject_id: str, pack_id: str) -> dict:
    """What to research about this subject, in this pack's own terms."""
    task = plan_task(conn, subject_id, pack_id)
    return {
        "subject": task.subject_label,
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
