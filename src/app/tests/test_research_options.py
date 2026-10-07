"""The reader's source options reach every agent's brief.

"options for research: forum/review/and such sources for options and source
counts for agents". Stored once on the Agents tab, read by each agent run.
"""
from app import prefs
from app.web import state
from app.web.tasks import _source_ceiling


def _stored(tmp_path, **values):
    path = tmp_path / "app.sqlite"
    conn = state.connect(path)
    try:
        prefs.write(conn, values)
    finally:
        conn.close()
    return path


def test_nothing_chosen_adds_nothing(tmp_path):
    assert _source_ceiling({}, _stored(tmp_path)) == ""


def test_stored_kinds_and_count_reach_the_brief(tmp_path):
    path = _stored(tmp_path, **{prefs.RESEARCH_SOURCES: "8",
                                prefs.RESEARCH_KINDS: "reviews,forums,nonsense"})
    said = _source_ceiling({}, path)
    # In the vocabulary's own order, and an unknown kind is dropped.
    assert "owner forums and discussion threads; professional reviews" in said
    assert "nonsense" not in said
    assert "Read at most 8 sources" in said


def test_a_runs_own_choice_wins(tmp_path):
    path = _stored(tmp_path, **{prefs.RESEARCH_SOURCES: "8", prefs.RESEARCH_KINDS: "forums"})
    said = _source_ceiling({"max_documents": 1, "source_kinds": ["recalls"]}, path)
    assert "Read at most 1 source in total" in said
    assert "recalls" in said and "forums" not in said


def test_the_choices_list_the_kinds_and_the_stored_options(tmp_path):
    path = _stored(tmp_path, **{prefs.RESEARCH_SOURCES: "500"})
    conn = state.connect(path)
    try:
        out = prefs.research_options(conn)
    finally:
        conn.close()
    assert out == {"sources": prefs.MAX_RESEARCH_SOURCES, "kinds": []}
