"""A part is not the product it fits (the local agent's failed Quick Look).

The reader's words: "it seems that agent couldnt differentiate between the
1.5dci the engine and the specific filter and somewhat failed", after a run
that read 24 pages and reported "No usable pages could be read. Check OpenSERP
and the connection". The listing was a Turkish marketplace title for an air
filter that fits an engine. Every page was rejected because the whole title had
to appear on a French forum, and the error then blamed the connection.
"""
import json

import pytest

from app import localplane
from app.providers import local_pipeline
from app.providers.local_identity import (
    clean_product_name, fold, parse_identity, relevant_source, scope_note, source_scope,
)
from app.providers.local_inference import LocalInferenceError
from app.providers.local_search_plan import nothing_read, part_queries

TITLE = "Mann Hava Filtresi Renault Megane Iv K9K 1.5 Dcı 2015 ->"
REPLY = {
    "canonical_name": "Mann Hava Filtresi Renault Megane Iv K9K 1.5 Dcı 2015",
    "aliases": [], "variant": "", "identifiers": [], "unknowns": [], "evidence": [],
    "brand": "Mann", "item": "Hava Filtresi",
    "item_terms": ["filtre à air", "air filter"],
    "fits": "Renault Megane IV K9K 1.5 dCi 2015",
}


def part(**changes):
    return parse_identity(json.dumps({**REPLY, **changes}), clean_product_name(TITLE))


# ---- the title -------------------------------------------------------------


def test_a_titles_trailing_arrow_is_not_part_of_the_name():
    assert clean_product_name(TITLE) == TITLE.removesuffix(" ->")
    assert clean_product_name("  » Lamp X1 | ") == "Lamp X1"


def test_the_dotless_i_and_accents_are_one_word():
    assert fold("Dcı") == fold("dCi") == "dci"
    assert fold("filtre à air") == "filtre a air"


# ---- identity: what is sold, what it fits ----------------------------------


def test_the_part_and_the_product_it_fits_are_two_subjects():
    identity = part()
    assert identity.dependent
    assert identity.brand == "Mann"
    assert identity.item_terms[0] == "filtre à air"
    assert identity.fits == "Renault Megane IV K9K 1.5 dCi 2015"


def test_a_product_that_stands_alone_has_no_host():
    identity = part(item="", item_terms=[], fits="")
    assert not identity.dependent and scope_note(identity) == ""


def test_a_host_the_text_never_names_is_not_invented():
    identity = part(fits="Peugeot 308 HDi 2019")
    assert not identity.dependent and identity.fits == ""


def test_a_name_the_model_rewrote_still_keeps_what_it_got_right():
    identity = part(canonical_name="Mann Air Filter for a Megane")
    assert identity.dependent and identity.canonical_name == clean_product_name(TITLE)


def test_an_older_reply_without_the_new_fields_still_parses():
    old = {key: REPLY[key] for key in
           ("canonical_name", "aliases", "variant", "identifiers", "unknowns", "evidence")}
    identity = parse_identity(json.dumps(old), clean_product_name(TITLE))
    assert not identity.dependent and identity.canonical_name == clean_product_name(TITLE)


# ---- pages: the engine's page is not the filter's page ---------------------

PAGES = {
    "filter thread": ("Filtre à air Mann sur Megane 4 1.5 dCi K9K",
                      "Mon filtre à air Mann s'est colmaté, Renault Megane K9K."),
    "engine page": ("Moteur 1.5 dCi K9K fiabilité",
                    "Injecteurs et vanne EGR du K9K, Renault Megane."),
    "any filter": ("Filtre à air encrassé", "Un filtre à air sale réduit la puissance."),
    "filter and engine": ("Moteur 1.5 dCi K9K", "Renault Megane K9K: changez le filtre à air."),
}


@pytest.mark.parametrize("page, scope", [
    ("filter thread", "item"), ("engine page", "host_only"),
    ("any filter", "other"), ("filter and engine", "item")])
def test_a_page_is_judged_by_the_part_not_by_its_host(page, scope):
    title, text = PAGES[page]
    assert source_scope(part(), title, text) == scope
    assert relevant_source(part(), title, text) is (scope == "item")


def test_a_translated_name_matches_a_page_that_words_it_differently():
    # Found live: the model named the part "Filtre d'air"; the forums say "filtre à air".
    identity = part(item_terms=["Filtre d'air", "Air filter"])
    title, text = PAGES["filter thread"]
    assert source_scope(identity, title, text) == "item"
    assert source_scope(identity, *PAGES["engine page"]) == "host_only"


def test_the_prompt_identity_leaves_out_empty_fields_and_quotes():
    shown = part().prompt_dict()
    assert "evidence" not in shown and "source" not in shown and "aliases" not in shown
    assert shown["fits"] and shown["item_terms"]


def test_the_whole_listing_title_is_no_longer_required_on_a_page():
    title, text = PAGES["filter thread"]
    assert TITLE.casefold() not in (title + text).casefold()
    assert relevant_source(part(), title, text)


def test_the_models_are_told_the_host_is_context_only():
    note = scope_note(part())
    assert "context only" in note and "NOT a finding" in note and "Mann" in note


# ---- searches --------------------------------------------------------------


def test_searches_name_the_part_in_the_search_language_not_the_title():
    queries = part_queries(part(), "fr")
    assert 3 <= len(queries) <= 4
    for query in queries:
        assert "filtre à air" in query
        assert "Hava" not in query and "->" not in query and "2015" not in query
    assert any("K9K" in query for query in queries)
    assert any("Mann" in query and "Megane" not in query for query in queries)


def test_a_product_that_stands_alone_keeps_its_own_planner():
    assert part_queries(part(item="", item_terms=[], fits=""), "fr") == []


# ---- the verdict when nothing was found ------------------------------------


def test_nothing_read_names_the_real_cause():
    assert "did not answer" in nothing_read({"queries_searched": 0, "search_errors": 4})
    assert "no results" in nothing_read(
        {"queries_searched": 4, "search_errors": 0, "unique_hits": 0})
    assert "none could be read" in nothing_read(
        {"queries_searched": 4, "unique_hits": 9, "pages_unreadable": 9})


class Socket:
    max_tokens = 512
    last_finish_reason = "stop"

    def json(self, prompt, schema):
        return json.dumps(REPLY)

    def prompt_chars_allowed(self):
        return 12000


class Agent:
    output_language = "fr"
    search_language = "fr"
    given_queries: list = []
    given_sources = None
    requested_specs = None
    source_instructions = ""
    page_titles: dict = {}
    sources: dict = {}

    def __init__(self, coverage):
        self._complete = Socket()
        self.read_coverage = coverage
        self.search_coverage: dict = {}
        self.searched: list = []
        self.read_options: dict = {}
        self.said: list = []

    def _check(self):
        pass

    def _say(self, line):
        self.said.append(line)

    def _read(self, queries, *, identity=None, prefer_issues=False, quick=False):
        self.searched = queries
        self.read_options = {"identity": identity, "prefer_issues": prefer_issues,
                             "quick": quick}
        self.search_coverage = dict(self.read_coverage)
        return []


def run(coverage):
    agent = Agent(coverage)
    pipeline = local_pipeline.QuickLookPipeline(agent)
    return agent, pipeline, lambda: pipeline.run("# Quick look\n", TITLE, None)


def test_pages_read_but_none_about_the_part_is_an_empty_result_not_a_connection_error():
    agent, pipeline, go = run({"queries_searched": 4, "unique_hits": 24, "pages_read": 24,
                               "pages_irrelevant": 24, "pages_host_only": 20})
    result = json.loads(go())
    assert result["risks"] == [] and result["specs"] == []
    assert pipeline.coverage["status"] == "no_matching_product_evidence"
    assert pipeline.coverage["pages_read"] == 24
    assert any("none was about this product" in line for line in agent.said)
    assert agent.read_options["quick"] is True
    assert all("Hava" not in query and "->" not in query for query in agent.searched)
    assert any("filtre à air" in query for query in agent.searched)


def test_a_search_that_never_answered_still_says_so():
    _, _, go = run({"queries_searched": 0, "search_errors": 4})
    with pytest.raises(LocalInferenceError, match="did not answer"):
        go()


# ---- the recommended model -------------------------------------------------


def test_the_recommended_model_is_the_default_when_the_server_has_it():
    models = ["qwen3.5:4b", "llama3.2:3b", "gemma4:e2b", "nomic-embed-text"]
    assert localplane._pick(models, "") == "gemma4:e2b"


def test_a_quantisation_of_the_recommended_model_counts():
    assert localplane._pick(["qwen3.5:9b", "gemma4:e2b-it-q4_K_M"], "") == "gemma4:e2b-it-q4_K_M"


def test_the_readers_own_choice_still_wins():
    assert localplane._pick(["gemma4:e2b", "qwen3.5:4b"], "qwen3.5:4b") == "qwen3.5:4b"


def test_without_it_the_old_rule_applies():
    assert localplane._pick(["qwen3.5:9b", "qwen3.5:4b", "llama3.2:1b"], "") == "qwen3.5:4b"
    assert localplane._pick(["llama3.2:1b"], "") == ""


def test_the_plane_reports_the_recommendation(monkeypatch):
    from app.providers import local_discovery

    server = {"url": "http://127.0.0.1:11434", "name": "Ollama", "up": True,
              "models": ["gemma4:e2b"]}
    monkeypatch.setattr(local_discovery, "discover", lambda url="": [server])
    monkeypatch.setattr(local_discovery, "search_answers", lambda url="": True)
    plane = localplane.resolve()
    assert plane["model"] == plane["recommended_model"] == "gemma4:e2b"
    assert plane["recommended_installed"] is True


# ---- the size floor ---------------------------------------------------------
#
# The reader, on a 0.8B model: "guy is literally making shit up". A model under
# the floor is refused by its size tag, picked or not, offered or not.


def test_a_model_under_the_floor_is_never_run_even_when_picked():
    assert localplane.too_small("qwen3.5:0.8b")
    assert localplane.too_small("gemma3:270m")
    assert not localplane.too_small("gemma4:e2b")
    assert not localplane.too_small("llama3:latest")  # unknown is not small
    assert localplane._pick(["qwen3.5:0.8b", "qwen3.5:4b"], "qwen3.5:0.8b") == "qwen3.5:4b"


def test_a_picked_tiny_model_leaves_the_plane_not_ready_and_says_why(monkeypatch):
    from app.providers import local_discovery

    server = {"url": "http://127.0.0.1:11434", "name": "Ollama", "up": True,
              "models": ["qwen3.5:0.8b"]}
    monkeypatch.setattr(local_discovery, "discover", lambda url="": [server])
    monkeypatch.setattr(local_discovery, "search_answers", lambda url="": True)
    plane = localplane.resolve(model="qwen3.5:0.8b")
    assert plane["ready"] is False and plane["model"] == ""
    assert "0.8B" in plane["reason"] and "gemma4:e2b" in plane["reason"]


def test_a_tiny_size_is_not_offered_for_download():
    from app import modelpull

    html = ('<a href="/library/qwen3.5"><span>0.8b</span><span>4b</span></a>'
            '<a href="/library/gemma3"><span>270m</span><span>4b</span></a>')
    assert [row["sizes"] for row in modelpull._library_rows(html)] == [["4b"], ["4b"]]
