"""B178: a short skill, tied to no one product, harness or model.

*"Make skills.md model, harness and product agnostic (important)"* and
*"Shorten skills.md, it is bloated, make it efficient"* (the reader,
2026-09-29). The generated skill was 4,944 words: about 3,300 from the installed
packs' own sections and 1,900 generic, with screen names, a repo path, a dated
history note and a worked example from one category in the generic part.

Three things are asserted here, each about the document an agent is handed:

* its length does not depend on what is installed (a pack can ship a long
  principle, a long identification method, and there can be many packs);
* it names nothing that belongs to a screen, a product, a harness or a model;
* each of the five steps names one input and one output.

The fourth half of the request, that a pack's own bar still reaches the agent,
is asserted on `research_brief`, the document that carries it.
"""

import re

import pytest

from app import agentconfig, agentskill
from kriko.research import plan_task
from kriko.research.agent import AgentResearcher
from kriko.store.db import connect

LIMIT = 1500

#: Nouns of the reader's screens. Not derived: the screens live in `ui/`, which
#: `app/` may not read, and the point is that none of them is spoken here.
SCREENS = (
    "Activity", "Sites", "Knowledge", "Overview", "Browse", "Settings",
    "Verify", "extension", "dashboard", "Connect",
)
#: Model families. A closed list of names that change every quarter would be
#: the thing this item removes, so the test names the families, not versions.
MODELS = ("opus", "sonnet", "haiku", "gpt", "gemini", "mistral", "llama", "qwen")


def _words(text: str) -> int:
    return len(re.findall(r"\S+", text))


def _install(conn, pack_id: str, *, principle: str = "", identify: str = "") -> None:
    conn.execute(
        "INSERT INTO packs (pack_id, name, version, schema_version, built_at,"
        " content_digest, enabled, installed_at)"
        " VALUES (?, ?, '1', 1, '2026-09-01', 'd', 1, '2026-09-01')",
        (pack_id, f"Pack {pack_id}"),
    )
    for path, role, text in (
        ("research/principle.md", "principle", principle),
        ("research/skill.md", "skill", identify),
    ):
        if text:
            conn.execute(
                "INSERT INTO pack_assets VALUES (?,?,?,?)",
                (pack_id, path, role, text),
            )
    conn.execute(
        "INSERT INTO subjects (subject_id, pack_id, kind, label)"
        " VALUES (?, ?, 'unit', 'A unit')",
        (f"{pack_id}-s", pack_id),
    )
    conn.commit()


@pytest.fixture
def store(tmp_path):
    conn = connect(tmp_path / "k.sqlite")
    yield conn
    conn.close()


def test_the_skill_stays_under_1500_words_whatever_packs_are_installed(store):
    # Reproduces the report: the pack sections alone were about 3,300 words.
    long_text = " ".join(f"word{i}" for i in range(2000))
    for n in range(25):
        _install(store, f"p{n:02d}", principle=long_text, identify=long_text)
    body = agentskill.render(store) or ""
    assert _words(body) < LIMIT, _words(body)


def test_the_skill_with_one_heavy_pack_and_a_full_agenda_is_short(store):
    long_text = " ".join(f"word{i}" for i in range(5000))
    _install(store, "heavy", principle=long_text, identify=long_text)
    rows = [
        {"kind": "empty_subject", "label": f"Subject {i} " + "long " * 30,
         "subject_id": f"s{i}", "asked": 3, "why": "nothing known. " * 10}
        for i in range(9)
    ]
    assert _words(agentskill.render(store, rows) or "") < LIMIT


def test_the_empty_installation_skill_is_short_too(store):
    assert _words(agentskill.render(store) or "") < LIMIT


def test_the_skill_names_no_screen_product_harness_or_model(store):
    _install(store, "probe", principle="Keep what the inspection misses.")
    body = agentskill.render(store, [
        {"kind": "empty_subject", "label": "A unit", "subject_id": "probe-s",
         "asked": 2, "why": "nothing known"},
    ]) or ""
    # Frontmatter and the stamp carry the skill's own name; the rest is prose.
    prose = body.split("---", 2)[2]
    lowered = prose.lower()
    harnesses = {
        word.lower()
        for target in agentconfig.targets()
        for word in (*re.split(r"[\s-]+", target.label), *target.id.split("-"))
        if len(word) > 2
    }
    banned = {w.lower() for w in SCREENS} | set(MODELS) | harnesses
    # Whole words: "sites" must not be found inside "websites" being legal, but
    # a screen called Sites must not appear at all.
    found = sorted(w for w in banned if re.search(rf"\b{re.escape(w)}\b", lowered))
    assert not found, found
    # No repo path, no dated history, no other category's example.
    assert "docs/" not in prose and "src/" not in prose and "packs/" not in prose
    assert not re.search(r"\b20\d\d-\d\d-\d\d\b", prose)
    for product in ("car", "drill", "golf", "timing belt", "sahibinden"):
        assert not re.search(rf"\b{product}\b", lowered), product


def test_each_of_the_five_steps_names_one_input_and_one_output(store):
    _install(store, "probe", principle="A bar.")
    assert len(agentskill.STEPS) == 5
    for step in agentskill.STEPS:
        assert len(step) == 3, step
    body = agentskill.render(store) or ""
    for tool, _input, _output in agentskill.STEPS:
        (line,) = [ln for ln in body.splitlines() if f"`{tool}`" in ln and ln[:2].strip().rstrip(".").isdigit()]
        assert line.count("Input:") == 1, line
        assert line.count("Output:") == 1, line


def test_the_brief_carries_the_bar_the_method_and_the_rationale_rule(store):
    # What left the skill must arrive through research_brief.
    _install(
        store, "probe",
        principle="Keep what the routine inspection cannot catch.",
        identify="Search the discriminating attribute, not the label.",
    )
    brief = AgentResearcher().brief(plan_task(store, "probe-s", "probe"))
    assert "Keep what the routine inspection cannot catch." in brief
    assert "Search the discriminating attribute, not the label." in brief
    assert "`rationale`" in brief
