"""The plane that spends money, and every stop between it and a bill.

`kriko/research/api.py` could always run a per-token research plane. Nothing
could ever *start* one, because it takes search, fetch and completion as
injected callables and no caller supplied them — `get_researcher({"backend":
"api"})` raised `TypeError`. `app/providers/` supplies them, and these tests
hold the four things that make that safe rather than reckless:

* **The ceiling is not optional.** `ApiResearcher._charge` treats a budget of
  zero as *unlimited* — right for the agent plane, whose marginal cost really
  is zero, exactly wrong for this one. `app/web/tasks.py::_budget` applies a
  floor, so a paid run that nobody gave a budget still has one.
* **Nothing catches the stop and carries on.** A `BudgetExceeded` caught and
  logged would be a hard stop turned into a warning, which is the whole
  failure this mechanism exists to prevent. Asserted against the source.
* **The adapters translate, they do not account.** Cost is charged in exactly
  one place; an adapter with its own running total would be a second answer to
  "what did this cost".
* **No test needs an API key.** The injected-callable seam is what makes that
  true, and it is the rule that keeps this suite runnable. Every test here
  either fakes the transport or fakes the callable.
"""

import ast
import inspect
import re
from pathlib import Path

import pytest

from app import keys
from app.providers import MissingKey, exa, fetch, llm
from app.web import tasks
from kriko.research import ApiResearcher, BudgetExceeded, ResearchTask


@pytest.fixture(autouse=True)
def no_real_keys(monkeypatch, tmp_path):
    """Neither the developer's shell nor their `~/.kriko/env` reaches a test."""
    for provider in keys.PROVIDERS:
        monkeypatch.delenv(provider.env, raising=False)
    monkeypatch.setattr(keys, "env_path", lambda home=None: tmp_path / "env")
    yield


def _executable(source: str) -> str:
    """The module with its comments and docstrings gone.

    The gates below read source, and a rule about what the code *does* must not
    be satisfiable — or breakable — by prose. `ast.unparse` of the parsed tree
    drops comments outright; the docstring nodes are removed by hand, because
    unparse keeps those.
    """
    import ast

    tree = ast.parse(source)
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if (
            isinstance(body, list)
            and body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            body.pop(0)
    return ast.unparse(tree)


def _task(**over) -> ResearchTask:
    return ResearchTask(
        subject_id="s1",
        subject_label="A Thing",
        subject_kind="product",
        pack_id="probe",
        **{"budget_usd": 0.0, "max_documents": 3, **over},
    )


# ── the adapters ─────────────────────────────────────────────────────────


def test_search_returns_the_engine_s_shape_not_the_vendor_s(monkeypatch):
    """`{"url", "title", "site"}`, translated here and nowhere else.

    The engine must not learn a vendor's response schema — that is the whole
    reason the callable is injected. A result with no URL is dropped rather
    than passed on as a document nothing can fetch.
    """
    monkeypatch.setattr(
        exa,
        "post_json",
        lambda url, payload, headers, **kw: {
            "results": [
                {"url": "https://forum.example/t/1", "title": "Thread", "extra": 1},
                {"title": "no url at all"},
                "not a dict",
            ]
        },
    )
    hits = exa.searcher(api_key="not-a-real-key")("some query", 5)
    assert hits == [
        {"url": "https://forum.example/t/1", "title": "Thread", "site": "forum.example"}
    ]


def test_a_search_provider_that_is_down_costs_a_query_not_the_run(monkeypatch):
    """`{}` in, `[]` out. `gather` already treats an empty result as a miss."""
    monkeypatch.setattr(exa, "post_json", lambda *a, **k: {})
    assert exa.searcher(api_key="x")("q", 5) == []


def test_a_completion_survives_the_json_fence_every_model_adds(monkeypatch):
    """`extract` calls `json.loads` on this and returns nothing when it fails.

    A fence is therefore the difference between a document's findings and
    silence, and it is not worth losing them to a formatting habit.
    """
    monkeypatch.setattr(
        llm,
        "post_json",
        lambda *a, **k: {
            "choices": [{"message": {"content": '```json\n[{"title": "x"}]\n```'}}]
        },
    )
    assert llm.completer(api_key="x")("prompt") == '[{"title": "x"}]'


def test_a_completion_provider_that_is_down_returns_nothing_rather_than_raising(
    monkeypatch,
):
    monkeypatch.setattr(llm, "post_json", lambda *a, **k: {})
    assert llm.completer(api_key="x")("prompt") == ""


def test_reading_a_page_keeps_the_prose_and_drops_the_furniture():
    """Grounding is only as good as this. `extract` refuses a quote it cannot
    find in `document.text`, so an honest quote lost to mangled extraction
    reads as a hallucination."""
    text = fetch.to_text(
        "<html><head><style>p{color:red}</style></head><body>"
        "<nav>Home | Login</nav>"
        "<p>The pump fails at around 150&nbsp;000 km.</p>"
        "<script>track()</script>"
        "<footer>© Example</footer></body></html>"
    )
    assert "The pump fails at around 150" in text
    assert "track()" not in text
    assert "color:red" not in text


def test_a_non_http_url_is_never_fetched():
    """`fetch` is handed URLs a search provider returned. urllib is perfectly
    happy to read `file:///etc/passwd`, which makes the scheme check a
    boundary rather than a nicety."""
    assert fetch.reader()("file:///etc/passwd") == ""
    assert fetch.reader()("ftp://example.com/x") == ""


def test_the_adapters_keep_no_running_total():
    """Cost is charged in one place: `ApiResearcher._charge`.

    An adapter that counted would be a second answer to "what did this cost",
    and the two would eventually disagree — at which point neither is usable
    as the thing that stops a bill.
    """
    for module in (exa, llm, fetch):
        code = _executable(Path(inspect.getfile(module)).read_text(encoding="utf-8"))
        assert "spent" not in code, f"{module.__name__} is accounting"
        assert "budget" not in code.lower(), f"{module.__name__} is accounting"


def test_the_paid_plane_refuses_to_exist_without_a_key():
    """A screen the reader can act on, not a vendor's 401 five seconds in."""
    from app.providers import api_researcher

    with pytest.raises(MissingKey):
        api_researcher()


# ── the ceiling ──────────────────────────────────────────────────────────


def test_a_paid_run_that_names_no_budget_still_gets_one():
    """Zero means unlimited to `_charge`. On this plane that is the $40 bill."""
    assert tasks._budget({"backend": "api"}) == tasks.DEFAULT_AGENDA_BUDGET_USD / 2
    assert tasks._budget({"backend": "api", "budget_usd": 0.05}) == 0.05
    # And the free plane keeps its zero, because there its zero is true.
    assert tasks._budget({"backend": "agent"}) == 0.0


def test_the_budget_stops_the_run_rather_than_warning_about_it():
    """Overshoot it and the plane raises, mid-gather, with money left unspent.

    Three queries at ten cents against a fifteen-cent ceiling: the second
    charge is what trips it, and nothing after it runs.
    """
    calls = []

    def search(query, limit):
        calls.append(query)
        return [{"url": f"https://example/{len(calls)}", "title": "t", "site": "e"}]

    researcher = ApiResearcher(
        search, lambda url: "a page", lambda prompt: "[]", price_per_call=0.10
    )
    task = _task(
        budget_usd=0.15,
        queries=("{label} one", "{label} two", "{label} three"),
    )
    with pytest.raises(BudgetExceeded):
        researcher.gather(task)
    assert len(calls) == 1, "it charged for a query it should never have run"


def _stops(handler: ast.ExceptHandler) -> bool:
    """Whether an `except` body can fall out of its own bottom.

    Walked as a tree rather than matched as text, because the sibling clause
    is the trap: `agenda_run`'s handler is followed by `except Cancelled:
    raise`, and any regex whose body-end guess is one indent level off finds
    that `raise` and passes a handler that does nothing of the kind. It is
    also what caught the first version of this gate — a `continue` mutation
    went through it green.

    A `raise` or `return` anywhere in the body stops. A `break` counts only
    when it belongs to this handler rather than to a loop written inside it.
    """
    for node in handler.body:
        for inner in ast.walk(node):
            if isinstance(inner, (ast.Raise, ast.Return)):
                return True
            if isinstance(inner, ast.Break) and not _inside_a_loop(node, inner):
                return True
    return False


def _inside_a_loop(root: ast.AST, target: ast.AST) -> bool:
    """A `break` in a loop of the handler's own making breaks that loop."""
    for node in ast.walk(root):
        if isinstance(node, (ast.For, ast.While)):
            if any(child is target for child in ast.walk(node)):
                return True
    return False


def test_no_caller_catches_the_budget_stop_and_carries_on():
    """The one gate that cannot be written as a behaviour test.

    Every `except BudgetExceeded` in `app/` must reach a `raise`, a `break`
    or a `return` — reported and stopped. A caller that logged it and carried
    on would turn a hard stop into a warning, and the mutation that proves
    this gate is to replace one of those with `continue`.

    Deliberately not narrowed to `kriko.research`'s `BudgetExceeded`.
    `kriko/ledger/costs.py` defines a second class of the same name for the
    pack pipeline, and the rule is identical for both: a ceiling that can be
    caught and stepped over is not a ceiling. `app/pipeline/ledger_run.py` is
    the pipeline's own compliance — it prints the abort and returns exit 2.
    """
    def named(handler):
        node = handler.type
        names = [node] if not isinstance(node, ast.Tuple) else list(node.elts)
        return any(
            getattr(n, "id", "") == "BudgetExceeded"
            or getattr(n, "attr", "") == "BudgetExceeded"
            for n in names
            if n is not None
        )

    offenders, checked = [], 0
    for path in Path("src/app").rglob("*.py"):
        if "/tests/" in str(path):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler) or not named(node):
                continue
            checked += 1
            if not _stops(node):
                offenders.append(f"{path}:{node.lineno}")

    assert not offenders, (
        f"{offenders} catch BudgetExceeded without stopping. The ceiling is a "
        "hard stop; a caught-and-logged stop is a warning."
    )
    # A gate that found nothing to check is a gate that has stopped working.
    assert checked >= 2, f"only {checked} handler(s) found — is the rglob right?"


def test_the_research_stages_themselves_never_mention_the_budget_stop():
    """`_research` has no `except BudgetExceeded` at all.

    The stages are where the spending happens, so a handler *inside* them
    could resume a run the ceiling had already stopped. The catch belongs at
    the run's boundary, where the only thing left to do is write the outcome
    down and re-raise.
    """
    source = inspect.getsource(tasks._research)
    assert "BudgetExceeded" not in source
