"""What a tuning run would spend, said before anyone presses the button.

*"The run's cost is shown up front and needs the reader's press."* Spending an
agent is the reader's decision, so the plan is printed first and nothing runs
until `--yes`. The figures are upper bounds worked out from the run's shape
(cases, repetitions, the chat turn's own call ceilings), never a promise:

* calls are counted exactly as bounds (a chat turn is at most
  `chat.MAX_AGENT_CALLS` agent calls and `MAX_SEARCH_ROUNDS` searches; the
  grader is one call, twice if its reply must be re-asked);
* dollars appear only for an agent that bills per token, from the reader's own
  price list (`models.toml`), with deliberately generous token ceilings, and
  say "unknown" where the list has no row. A coding-agent CLI on a
  subscription has no per-token price and is shown as calls against the plan;
* nothing here invents a measurement. The run itself records what was spent
  where the agent reports it.
"""

from app.tuning import evidence

#: Generous per-call token ceilings for the upper bound, input and output.
ANSWER_CALL = (9000, 1500)
GRADE_CALL = (24000, 1800)


def _dollars(ref, calls: int, per_call: tuple[int, int]) -> dict:
    from app import modelcatalogue
    from app.web.settings import KRIKO_HOME

    if ref.kind != "api":
        basis = ("a local model: no charge, but slow" if ref.kind == "local"
                 else "a coding-agent CLI: no per-token charge; each call counts against your plan")
        return {"usd": 0.0 if ref.kind == "local" else None, "basis": basis}
    price = modelcatalogue.price(ref.model, per_call[0] * calls, per_call[1] * calls, KRIKO_HOME) if ref.model else None
    return {"usd": price, "basis": ("at most, from your price list" if price is not None
                                    else "per-token price unknown for this model")}


def plan(cases: list[dict], answerer, grader, search_provider: str, *, reps: int = 1) -> dict:
    """The shape and upper-bound cost of a run, as plain data for the CLI."""
    from app import chat

    attempts = len(cases) * max(1, reps)
    answer_calls = attempts * chat.MAX_AGENT_CALLS
    grade_calls = attempts * 2
    searches = attempts * (chat.MAX_SEARCH_ROUNDS + 1)
    return {
        "attempts": attempts, "cases": len(cases), "reps": max(1, reps),
        "answerer": answerer.public(), "grader": grader.public(),
        "search_provider": search_provider,
        "answer_calls_at_most": answer_calls, "grade_calls_at_most": grade_calls,
        "searches_at_most": searches,
        "page_fetches_at_most": attempts * evidence.MAX_PAGES,
        "answerer_cost": {"calls": answer_calls, **_dollars(answerer, answer_calls, ANSWER_CALL)},
        "grader_cost": {"calls": grade_calls, **_dollars(grader, grade_calls, GRADE_CALL)},
    }


def describe(shape: dict) -> str:
    """The plan as the paragraph the reader reads before pressing."""
    def line(label, who, cost):
        usd = cost["usd"]
        money = (f"up to ${usd:.2f}" if isinstance(usd, (int, float)) and usd
                 else "no charge" if usd == 0 else "price not known")
        return (f"  {label:<9}{who['label']} ({who['id']}"
                + (f", {who['model']}" if who.get("model") else "")
                + f"): at most {cost['calls']} call(s); {money}; {cost['basis']}.")

    return "\n".join([
        f"{shape['attempts']} attempt(s): {shape['cases']} case(s) x {shape['reps']} run(s).",
        line("answers", shape["answerer"], shape["answerer_cost"]),
        line("grades", shape["grader"], shape["grader_cost"]),
        f"  search   {shape['search_provider']}: at most {shape['searches_at_most']} search(es) "
        f"and {shape['page_fetches_at_most']} page fetch(es).",
        "These are upper bounds, not a quote. The grader is not the agent that answers, and it is "
        "never told which one did."])
