"""The benchmark: start one, read the results.

B111. `app/bench.py` explains what is measured and why the cases are derived
rather than enumerated; this is the door.

A `POST` starts a job, because measuring three cases across two planes is
minutes of work and, on the paid plane, real money — both of which are reasons
long work is a row here rather than a request that hangs.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import AliasChoices, BaseModel, Field

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
    #: Comma-separated model ids to sweep, or empty for "whichever this
    #: installation would pick". The axis §2.6 names first, and swept on the
    #: same terms as the others: only when asked for. Sweeping the whole
    #: catalogue by default would multiply the bill by however many models the
    #: reader happens to have priced.
    models: str = Field("", validation_alias=AliasChoices("models", "llms"))
    #: Comma-separated search providers to sweep. Already honoured by the job;
    #: it was simply not reachable from here, so "which providers" could not
    #: be scoped from the screen that runs the benchmark.
    searches: str = ""


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
    summary = state.bench_summary(conn)
    return {
        "runs": [_served(row) for row in rows],
        # How each plane failed, not only how often (B124). "Four of five
        # harness runs failed, all of them `auth`" is actionable; "four of five
        # failed" is not.
        "verdict": bench.verdict(rows),
        # Recall, precision and hallucination with Wilson intervals, for the
        # rows whose cases carried ground truth (B126).
        "scored": {
            "groups": [
                _served(group) for group in bench.scored(rows).get("groups", [])
            ]
        },
        "summary": [_served(row) for row in summary],
        "cases": bench.cases(store),
        # What the measurements currently *decide*, which is the point of
        # having them: a table nobody reads back is folklore with a schema.
        "protocols": [
            {
                "name": one.name,
                "context_chars": one.context_chars,
                "batch_size": one.batch_size,
                "preamble": one.preamble,
            }
            for one in protocols.CATALOGUE
        ],
        "chosen": {
            row["model"]: protocols.choose(summary, row["model"]).name
            for row in summary
            if row.get("model")
        },
        # `readout` is the reader-facing table, so it crosses the boundary
        # below like everything else here.
        # The reader's actual ask (B126 §7): per model, the batch size,
        # context budget, preamble, search provider, measured cost per
        # accepted claim and hallucination rate with its interval — and
        # whether there was even enough measured to say so.
        "readout": [_served(row) for row in protocols.readout(rows, summary)],
    }


SERVED_AS = {"model": "llm"}


def _served(row: dict) -> dict:
    """One row, spelled the way the interface is allowed to spell it.

    `ui/` may not contain a pack's vocabulary, and the gate that enforces it
    bans this particular word outright -- it means an LLM here and a car's
    model in every pack about vehicles, and the interface cannot tell which
    from a payload key. So the boundary renames, rather than the store: the
    column keeps the name its own callers use, and nothing downstream has to
    know two words for one thing. The last time a producer and its reader
    disagreed about a string across this kind of boundary, an entire class of
    pack silently never reached the reader.
    """
    return {SERVED_AS.get(key, key): value for key, value in row.items()}


@router.post("/bench/estimate")
def estimate_bench(
    body: BenchRequest, conn=Depends(get_app_state), store=Depends(get_store),
) -> dict:
    """What this grid would run and roughly what it would cost. Runs nothing.

    "Benchmarking everything costs a lot. I need to scope it." Scoping without
    a number is still guessing: every axis multiplies, so three cases, two
    planes and three protocols at two reps is thirty-six runs — and nothing
    said so before pressing.

    A separate endpoint rather than a flag on the POST, so that asking what
    something costs can never start it.
    """
    from app import bench

    params = body.model_dump()
    try:
        bench.validate(params)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    found = bench.cases(store, pack_id=params.get("pack_id") or "",
                        limit=int(params.get("cases") or bench.DEFAULT_CASES))
    return bench.estimate(conn, params, len(found))


#: Where saved grids live. One settings key holding a JSON object rather than a
#: table: these are a handful of named requests, they are interface state like
#: every other preference, and a table would be a migration for something a
#: reader will have three of.
SAVED_KEY = "bench_configs"
MAX_SAVED = 20


@router.get("/bench/configs")
def read_configs(conn=Depends(get_app_state)) -> dict:
    """Grids the reader named, so a comparison can be repeated.

    Results are only comparable across runs if the *config* was the same, and
    a config reconstructed from memory next month is a different experiment
    wearing the same name.
    """
    import json

    raw = state.all_settings(conn).get(SAVED_KEY) or "{}"
    try:
        saved = json.loads(raw)
    except ValueError:
        saved = {}
    return {"configs": {
        name: {("llms" if key == "models" else key): value for key, value in config.items()}
        for name, config in saved.items() if isinstance(config, dict)
    } if isinstance(saved, dict) else {}}


class SaveConfig(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    config: BenchRequest


@router.put("/bench/configs")
def save_config(body: SaveConfig, conn=Depends(get_app_state)) -> dict:
    import json

    saved = read_configs(conn)["configs"]
    if body.name not in saved and len(saved) >= MAX_SAVED:
        raise HTTPException(
            400, f"{MAX_SAVED} saved grids is the limit — delete one first")
    saved[body.name] = body.config.model_dump()
    state.put_settings(conn, {SAVED_KEY: json.dumps(saved)})
    return read_configs(conn)


@router.delete("/bench/configs/{name}")
def forget_config(name: str, conn=Depends(get_app_state)) -> dict:
    import json

    saved = read_configs(conn)["configs"]
    saved.pop(name, None)
    state.put_settings(conn, {SAVED_KEY: json.dumps(saved)})
    return read_configs(conn)


@router.post("/bench")
def start_bench(body: BenchRequest, runner=Depends(get_jobs)) -> dict:
    from app import bench

    try:
        bench.validate(body.model_dump())
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    job_id = runner.submit("bench", body.model_dump())
    return {"job_id": job_id, "kind": "bench"}
