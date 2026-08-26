"""The two research planes, and the line between free and paid.

The important assertions here are about money and about grounding. Everything
else is plumbing.
"""

import pytest

from kriko.research import (ApiResearcher, BudgetExceeded, Document, Finding,
                            ResearchTask, get_researcher, plan_task)
from kriko.research.agent import AgentResearcher


def _task(**kw):
    base = dict(
        subject_id="s1", subject_label="Renault K9K", subject_kind="product",
        pack_id="cars", identity={"make": "renault", "engine_code": "K9K"},
        attribution_aliases=("1.5 dCi",), search_aliases=("dCi",),
        queries=("{alias} common problems", "{label} failure symptoms"),
        value_principle="Keep only what an inspection would not catch.",
        domains=("engine", "transmission"), max_documents=3,
    )
    base.update(kw)
    return ResearchTask(**base)


# ── choosing a plane ─────────────────────────────────────────────────────

def test_the_default_plane_costs_nothing():
    """A tool that starts spending because a key was in the environment is a
    tool people stop trusting."""
    researcher = get_researcher()
    assert researcher.name == "agent"
    assert researcher.cost_basis == "subscription"


def test_the_paid_plane_is_opt_in_and_explicit():
    researcher = get_researcher({"backend": "api"},
                                search=lambda *_: [], fetch=lambda _: "",
                                complete=lambda _: "[]")
    assert researcher.cost_basis == "per_token"


def test_an_unknown_backend_is_rejected():
    with pytest.raises(ValueError, match="agent|api"):
        get_researcher({"backend": "telepathy"})


# ── the brief ────────────────────────────────────────────────────────────

def test_the_brief_carries_the_packs_own_value_principle():
    """What is worth keeping belongs to the category, not to the engine."""
    brief = AgentResearcher().brief(_task())
    assert "Keep only what an inspection would not catch." in brief


def test_the_brief_renders_the_packs_query_templates():
    brief = AgentResearcher().brief(_task())
    assert "Renault K9K common problems" in brief
    assert "Renault K9K failure symptoms" in brief


def test_the_brief_names_the_packs_domain_vocabulary():
    assert "engine, transmission" in AgentResearcher().brief(_task())


def test_search_only_aliases_are_marked_as_unusable_for_attribution():
    """Design-flaw 3: a search alias shared with siblings attributed a claim."""
    brief = AgentResearcher().brief(_task())
    assert "never be used to attribute" in brief
    assert "dCi" in brief.split("never be used to attribute")[1]


def test_the_brief_demands_verbatim_quotes():
    brief = AgentResearcher().brief(_task())
    assert "VERBATIM" in brief
    assert "invented" in brief


def test_a_pack_with_no_principle_still_produces_a_usable_brief():
    brief = AgentResearcher().brief(_task(value_principle=""))
    assert "ships no value principle" in brief


def test_the_agent_plane_never_fetches_or_calls_a_model():
    """Silently falling back to a paid path would turn free into a surprise bill."""
    researcher = AgentResearcher()
    assert researcher.gather(_task()) == []
    assert researcher.extract(_task(), Document(url="u", text="t")) == []


# ── the paid plane ───────────────────────────────────────────────────────

def test_the_budget_is_a_hard_stop_not_a_warning():
    calls = []

    def search(query, limit):
        calls.append(query)
        return [{"url": f"https://e.example/{len(calls)}"}]

    researcher = ApiResearcher(search=search, fetch=lambda _: "text",
                               complete=lambda _: "[]", price_per_call=1.0)
    with pytest.raises(BudgetExceeded):
        researcher.gather(_task(budget_usd=1.5))
    assert len(calls) <= 2, "spending must stop at the ceiling, not after it"


def test_gather_skips_sources_it_cannot_read():
    researcher = ApiResearcher(
        search=lambda q, n: [{"url": "https://a.example"}, {"url": "https://b.example"}],
        fetch=lambda url: "" if "a.example" in url else "real text",
        complete=lambda _: "[]")
    docs = researcher.gather(_task(queries=("{label}",)))
    assert [d.url for d in docs] == ["https://b.example"]


def test_a_quote_absent_from_the_document_is_discarded():
    """Grounding, enforced rather than requested.

    The entire value of the evidence chain is that a fabricated quote cannot
    pass quietly. An LLM asked for verbatim text will sometimes produce
    something plausible instead, so the check is mechanical.
    """
    document = Document(url="https://e.example", text="The injectors foul at high mileage.")
    researcher = ApiResearcher(
        search=lambda *_: [], fetch=lambda _: "",
        complete=lambda _: '[{"title":"Injector fouling","domain":"engine",'
                           '"severity":"high","quote":"The turbo explodes weekly."}]')
    assert researcher.extract(_task(), document) == []


def test_a_grounded_quote_survives():
    document = Document(url="https://e.example", text="The injectors foul at high mileage.")
    researcher = ApiResearcher(
        search=lambda *_: [], fetch=lambda _: "",
        complete=lambda _: '[{"title":"Injector fouling","domain":"engine",'
                           '"severity":"high","quote":"The injectors foul at high mileage."}]')
    (finding,) = researcher.extract(_task(), document)
    assert isinstance(finding, Finding)
    assert finding.source_url == "https://e.example"


def test_a_malformed_model_reply_yields_nothing_rather_than_crashing():
    """Unattended runs must survive a model having a bad day."""
    researcher = ApiResearcher(search=lambda *_: [], fetch=lambda _: "",
                              complete=lambda _: "I'm afraid I can't do that")
    assert researcher.extract(_task(), Document(url="u", text="t")) == []


# ── building a task from a pack ──────────────────────────────────────────

def test_plan_task_reads_everything_from_pack_rows(tmp_path):
    import textwrap
    from kriko.pack import build
    from kriko.store import packstore
    from kriko.store.db import connect

    root = tmp_path / "p"
    (root / "vocabulary").mkdir(parents=True)
    (root / "data").mkdir(parents=True)
    (root / "research").mkdir(parents=True)
    (root / "pack.toml").write_text(textwrap.dedent("""
        [pack]
        id = "p"
        name = "P"
        version = "0.1.0"
        [identity]
        product = ["brand", "model"]
    """), encoding="utf-8")
    (root / "vocabulary" / "terms.yaml").write_text(
        "- {term_id: product, role: subject_kind}\n"
        "- {term_id: brand, role: attribute, datatype: text}\n"
        "- {term_id: model, role: attribute, datatype: text}\n"
        "- {term_id: mech, role: domain}\n", encoding="utf-8")
    (root / "data" / "subjects.yaml").write_text(
        "- kind: product\n  label: Thing One\n"
        "  identity: {brand: acme, model: one}\n"
        "  aliases: [Thing-1]\n", encoding="utf-8")
    (root / "data" / "claims.yaml").write_text("[]\n", encoding="utf-8")
    (root / "research" / "principle.md").write_text("Only the expensive.", encoding="utf-8")
    (root / "research" / "templates.yaml").write_text('- "{alias} faults"\n', encoding="utf-8")

    store = connect(tmp_path / "store.sqlite")
    packstore.install(store, build.build(root, tmp_path / "p.kpack"))
    subject_id = store.execute("SELECT subject_id FROM subjects").fetchone()[0]

    task = plan_task(store, subject_id, "p", budget_usd=2.0)
    assert task.subject_label == "Thing One"
    assert task.identity == {"brand": "acme", "model": "one"}
    assert task.attribution_aliases == ("Thing-1",)
    assert task.value_principle == "Only the expensive."
    assert task.queries == ("{alias} faults",)
    assert task.domains == ("mech",)
    assert task.budget_usd == 2.0
    store.close()


def test_plan_task_rejects_an_unknown_subject(tmp_path):
    from kriko.store.db import connect
    store = connect(tmp_path / "store.sqlite")
    with pytest.raises(KeyError):
        plan_task(store, "nope", "nope")
    store.close()
