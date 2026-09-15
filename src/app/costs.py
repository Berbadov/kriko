"""What this installation has spent, and what pressing a button would cost.

Two questions, one file, and they are not the same question:

* **What did it cost?** Measured. `research_runs` and `bench_runs` carry
  dollars and tokens per run, and neither is estimated — where nobody counted,
  the column is NULL and stays NULL. A measurement presented where none exists
  is the `raised: true` mistake, and it is worse here than anywhere else
  because the reader's next decision is whether to spend more.
* **What will it cost?** An *estimate*, labelled as one, from what this
  installation has actually spent per run on this plane. Not a vendor price
  list: a price list goes stale, cannot know the reader's model, and would
  quietly become the number everybody trusts.

**There is no credit balance here, and that is deliberate.** No completion or
search vendor exposes a remaining balance an API key may read — and a number
this app invented for that would be the most dangerous number on the screen.
What it can honestly show is: which keys are set, what the last runs cost, and
what the next one is likely to. The reader's balance lives where they topped it
up, and the screen says so with a link rather than guessing.
"""

from datetime import UTC, datetime, timedelta

#: How far back "recently" reaches for the per-run estimate. Long enough to
#: include a handful of runs, short enough that a price change six months ago
#: does not anchor today's estimate.
WINDOW_DAYS = 30

#: How many runs it takes before an average is offered at all. One run is an
#: anecdote, and an estimate from an anecdote is a guess wearing a decimal
#: point — the same rule `app/protocols.py` applies to protocols.
MIN_RUNS = 2


def spent(conn, *, days: int = WINDOW_DAYS) -> dict:
    """What has actually been spent, by plane, in the window.

    Runs that counted nothing are counted as runs and not as zeros: "six runs,
    two of which reported a cost" is the truth, and averaging the other four in
    as free would understate every estimate built on it.
    """
    since = (datetime.now(UTC) - timedelta(days=max(1, days))).isoformat()
    rows = conn.execute(
        # `AS llm`, not `model`: the client may not contain a pack's identity
        # key, and `/api/research-planes` already answers in this spelling for
        # the same reason.
        "SELECT plane, model AS llm, COUNT(*) AS runs,"
        " SUM(CASE WHEN spent_usd IS NOT NULL THEN 1 ELSE 0 END) AS priced,"
        " SUM(COALESCE(spent_usd, 0)) AS usd,"
        " SUM(COALESCE(tokens_used, 0)) AS tokens"
        " FROM research_runs WHERE started_at >= ?"
        " GROUP BY plane, model ORDER BY usd DESC",
        (since,),
    ).fetchall()
    planes = []
    for row in rows:
        one = dict(row)
        one["usd_per_run"] = (
            round(one["usd"] / one["priced"], 4) if one["priced"] else None
        )
        planes.append(one)
    total = conn.execute(
        "SELECT SUM(COALESCE(spent_usd, 0)) AS usd,"
        " SUM(COALESCE(tokens_used, 0)) AS tokens, COUNT(*) AS runs"
        " FROM research_runs WHERE started_at >= ?",
        (since,),
    ).fetchone()
    return {
        "days": days,
        "planes": planes,
        "usd": round(float(total["usd"] or 0), 4),
        "tokens": int(total["tokens"] or 0),
        "runs": int(total["runs"] or 0),
    }


def estimate(conn, *, plane: str, subjects: int = 1, days: int = WINDOW_DAYS) -> dict:
    """What `subjects` runs on this plane are likely to cost here.

    From this installation's own history, and `None` when there is not enough
    of it. A missing estimate is an honest screen — "nothing has been measured
    yet" — and an invented one is a promise the app cannot keep.
    """
    since = (datetime.now(UTC) - timedelta(days=max(1, days))).isoformat()
    row = conn.execute(
        "SELECT COUNT(*) AS runs, AVG(spent_usd) AS usd, AVG(tokens_used) AS tokens"
        " FROM research_runs"
        " WHERE plane = ? AND started_at >= ? AND spent_usd IS NOT NULL",
        (plane, since),
    ).fetchone()
    runs = int(row["runs"] or 0)
    if runs < MIN_RUNS:
        return {
            "plane": plane,
            "subjects": subjects,
            "usd": None,
            "tokens": None,
            "basis": runs,
            "note": (
                "nothing measured yet on this plane — run one subject and the "
                "estimate becomes this installation's own"
            ),
        }
    per_run = float(row["usd"] or 0)
    return {
        "plane": plane,
        "subjects": subjects,
        "usd": round(per_run * max(1, subjects), 4),
        "tokens": int((row["tokens"] or 0) * max(1, subjects)),
        "basis": runs,
        "note": f"estimated from {runs} measured run(s) here, not a price list",
    }


def overview(conn, *, planes=("api", "harness")) -> dict:
    """The whole answer for a screen: spend, per-plane estimates, key status.

    Keys are in the same payload because "what will this cost" and "can this
    run at all" are the same decision at the moment of pressing, and two
    requests to answer one question is two things to keep in sync.
    """
    from app import keys

    return {
        "spent": spent(conn),
        "estimates": {one: estimate(conn, plane=one) for one in planes},
        "keys": [
            {
                "id": item["id"],
                "label": item["label"],
                "present": item["present"],
                "purpose": item["purpose"],
            }
            for item in keys.status()
        ],
        # Said rather than guessed: no vendor exposes a balance to an API key,
        # and a number invented for it would be the most dangerous one here.
        "balance": {
            "known": False,
            "note": "Kriko cannot read a provider's remaining credit — no key "
                    "can. Check your balance with the provider; what is shown "
                    "here is what this installation has actually spent.",
        },
    }
