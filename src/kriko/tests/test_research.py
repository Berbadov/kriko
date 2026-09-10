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
        subject_id="s1", subject_label="Makita DHP484", subject_kind="product",
        pack_id="drill", identity={"brand": "makita", "model": "DHP484"},
        attribution_aliases=("DHP484Z",), search_aliases=("DHP 484",),
        queries=("{alias} common problems", "{label} failure symptoms"),
        value_principle="Keep only what an inspection would not catch.",
        domains=("mechanical", "battery"), max_documents=3,
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
    assert "Makita DHP484 common problems" in brief
    assert "Makita DHP484 failure symptoms" in brief


def test_a_search_name_becomes_the_query_and_the_display_label_steps_aside():
    """The third alias tier, and the reason it is a tier of its own.

    A display label carries whatever tells two rows apart in a list. Fed to a
    search engine, `packs/cars`' produced `Volkswagen Golf 1.5_TSI 150 hp
    common problems` — seven queries a reader watched find nothing, twice. A
    pack that knows what people type says so in `search_name` rows, and those
    win.
    """
    task = _task(search_names=("Makita 18V hammer drill",))
    assert task.query_names == ("Makita 18V hammer drill",)
    queries = task.rendered_queries()
    assert "Makita 18V hammer drill common problems" in queries
    assert not any("Makita DHP484" in query for query in queries)


def test_a_widening_fragment_never_becomes_a_query_on_its_own():
    """Why `search_only` could not just be reused for the above.

    `packs/drill` ships `LXT` and `DHP 484` — fragments whose job is to widen a
    search that already names the thing. Promoting one to the subject of a
    query turns `Makita DHP484 common problems` into `DHP 484 common problems`,
    which is a worse search than the label it replaced.
    """
    task = _task()
    assert task.search_aliases == ("DHP 484",)
    assert task.query_names == ("Makita DHP484",)
    assert all("DHP 484 " not in query for query in task.rendered_queries())


def test_a_query_never_carries_a_catalog_spelling_through_to_a_search_box():
    """The safety net under the tier, for a pack that ships no search names.

    An identifier's punctuation is a storage detail. This is deliberately the
    only rewriting the engine does — a category's own conventions are pack
    data, and a `_MAKE_MAP` one layer further in is still a `_MAKE_MAP`.
    """
    task = _task(subject_label="Makita DHP_484_Z", search_aliases=())
    assert "Makita DHP 484 Z common problems" in task.rendered_queries()


def test_the_brief_names_the_packs_domain_vocabulary():
    assert "mechanical, battery" in AgentResearcher().brief(_task())


def test_search_only_aliases_are_marked_as_unusable_for_attribution():
    """Design-flaw 3: a search alias shared with siblings attributed a claim."""
    brief = AgentResearcher().brief(_task())
    assert "never be used to attribute" in brief
    assert "DHP 484" in brief.split("never be used to attribute")[1]


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
    document = Document(url="https://e.example",
                        text="The chuck bearing wears at high charge cycles.")
    researcher = ApiResearcher(
        search=lambda *_: [], fetch=lambda _: "",
        complete=lambda _: '[{"title":"Chuck bearing wear","domain":"mechanical",'
                           '"severity":"high","quote":"The battery pack catches fire weekly."}]')
    assert researcher.extract(_task(), document) == []


def test_a_grounded_quote_survives():
    document = Document(url="https://e.example",
                        text="The chuck bearing wears at high charge cycles.")
    researcher = ApiResearcher(
        search=lambda *_: [], fetch=lambda _: "",
        complete=lambda _: '[{"title":"Chuck bearing wear","domain":"mechanical",'
                           '"severity":"high","quote":"The chuck bearing wears at high charge cycles."}]')
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


def test_the_brief_says_whose_bar_it_is_quoting():
    """The claim bar is the pack's taste, and the brief must say so. (D5)

    The reader read the cars pack's four bullets — engine code, gearbox type,
    cam belt — as Kriko's own opinion about what is worth surfacing, and
    reported it as the engine being "still car fixated". It is not: the text is
    `research/principle.md`, pack data, quoted verbatim, and that is the design
    (`docs/PACK_CONTRACT.md`) precisely so that what counts as worth surfacing
    stays a property of the category rather than of the engine.

    Nothing needed fixing in the layering. What needed fixing was a heading
    that named no owner, because a reader who cannot see whose bar it is has
    only one candidate to blame.
    """
    task = _task()
    brief = AgentResearcher().brief(task)

    assert task.pack_id in brief
    assert f"the `{task.pack_id}` pack's bar" in brief
    # And the sentence, not only the heading: a heading is skimmed past.
    assert "not by Kriko" in brief


def test_the_narrowest_search_name_leads_and_the_broadest_is_dropped():
    """Order and count, both of which the store cannot express.

    An alias table has no ordinal, so `plan_task` reads names back
    alphabetically — which put `Volkswagen Golf` ahead of `Volkswagen Golf
    EA211` and made the broadest search the first thing in the brief. And the
    render is a cross product: three names against `packs/cars`' seven
    templates is 21 searches where the reader had been shown 7, most of them
    near-duplicates of each other.

    Both are shape rules, so both live in the engine: a name containing another
    name is the narrower of the two in any category, and the one dropped by the
    cap is always the broadest — the direction an agent widens toward on its
    own when a narrow search finds nothing.
    """
    task = _task(search_names=(
        "Volkswagen Golf", "Volkswagen Golf VII", "Volkswagen Golf EA211"))
    assert task.query_names == ("Volkswagen Golf EA211", "Volkswagen Golf VII")
    queries = task.rendered_queries()
    assert len(queries) == len(task.queries) * 2
    assert not any(query.startswith("Volkswagen Golf common") for query in queries)


def test_the_order_of_a_briefs_searches_does_not_move_between_runs():
    """A brief that reshuffles itself is a brief nobody can diff.

    Two names of equal length are ordered alphabetically rather than by
    whatever order the rows came back in, so the same subject researched twice
    produces the same brief.
    """
    names = ("Bosch GSB 18", "Bosch GSR 18")
    assert _task(search_names=names).query_names == names
    assert _task(search_names=tuple(reversed(names))).query_names == names
