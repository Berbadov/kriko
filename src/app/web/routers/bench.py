"""The benchmark: start one, read the results.

B111. `app/bench.py` explains what is measured and why the cases are derived
rather than enumerated; this is the door.

A `POST` starts a job, because measuring three cases across two planes is
minutes of work and, on the paid plane, real money — both of which are reasons
long work is a row here rather than a request that hangs.
"""

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.web import state
from app.web.deps import get_app_state, get_jobs, get_store

router = APIRouter(prefix="/api", tags=["bench"])


class BenchRequest(BaseModel):
    #: Comma-separated, or empty for "whatever this machine can run". Named
    #: rather than discovered when a reader wants one plane measured again —
    #: re-running the whole grid to re-measure one of them is how a benchmark
    #: becomes something nobody presses.
    planes: str = ""
    pack_id: str = ""
    cases: int = Field(3, ge=1, le=50)
    max_documents: int = Field(3, ge=1, le=20)
    #: Per case. The paid plane's ceiling, and the reason this endpoint does
    #: not default to "every plane, unbounded".
    budget_usd: float = Field(0.20, ge=0.0, le=20.0)
    #: Comma-separated protocol names to sweep (B123), or empty for "whatever
    #: the plane would choose". Sweeping every protocol by default would
    #: multiply the bill by three to answer a question nobody asked.
    protocols: str = ""
    #: How many times each measurement is repeated (B126). One run of a case
    #: is a sample reported as a constant, and two protocols cannot be compared
    #: from one observation each.
    reps: int = Field(1, ge=1, le=10)


@router.get("/bench")
def read_bench(
    limit: int = Query(100, ge=1, le=1000),
    conn=Depends(get_app_state),
    store=Depends(get_store),
) -> dict:
    """Every measurement, the per-plane summary, and what would be measured next.

    `cases` is in the same payload deliberately: a reader looking at an empty
    benchmark needs to know what pressing the button would actually run, and a
    second request to find out is a second thing to forget.
    """
    from app import bench

    from app import protocols

    rows = state.bench_runs(conn, limit=limit)
    return {
        "runs": rows,
        # How each plane failed, not only how often (B124). "Four of five
        # harness runs failed, all of them `auth`" is actionable; "four of five
        # failed" is not.
        "verdict": bench.verdict(rows),
        # Recall, precision and hallucination with Wilson intervals, for the
        # rows whose cases carried ground truth (B126).
        "scored": bench.scored(rows),
        "summary": state.bench_summary(conn),
        "cases": bench.cases(store),
        # What the measurements currently *decide*, which is the point of
        # having them: a table nobody reads back is folklore with a schema.
        "protocols": [
            {
                "name": one.name,
                "context_chars": one.context_chars,
                "batch_size": one.batch_size,
            }
            for one in protocols.CATALOGUE
        ],
        "chosen": {
            row["model"]: protocols.choose(
                state.bench_summary(conn), row["model"]
            ).name
            for row in state.bench_summary(conn)
            if row.get("model")
        },
    }


@router.post("/bench")
def start_bench(body: BenchRequest, runner=Depends(get_jobs)) -> dict:
    job_id = runner.submit("bench", body.model_dump())
    return {"job_id": job_id, "kind": "bench"}
