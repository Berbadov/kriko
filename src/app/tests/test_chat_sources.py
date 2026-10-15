"""The records a chat agent may ask for: capped, read-only, never raising, never secret.

The fixture is a neutral two-product pack built from the data model (its own
pack.toml, terms, subjects and claims), not from a shipped category.
"""

import dataclasses
import textwrap

import pytest

from app import chatdata, keys
from app.web import state
from kriko.pack import build
from kriko.store import packstore
from kriko.store.db import connect

TOML = """
[pack]
id = "gears"
name = "Gears"
version = "0.1.0"
[identity]
product = ["brand", "model"]
"""

TERMS = """
- {term_id: product, role: subject_kind}
- {term_id: brand, role: attribute, datatype: text, match: {required: true}}
- {term_id: model, role: attribute, datatype: text, match: {required: true}}
- {term_id: colour, role: attribute, datatype: text}
- {term_id: power_w, role: attribute, datatype: number, unit: w}
- {term_id: mech, role: domain}
"""

SUBJECTS = """
- kind: product
  label: Alpha Unit 200
  identity: {brand: acme, model: alpha200}
  attributes: {colour: red, power_w: 200}
  aliases: ["Alpha compact"]
- kind: product
  label: Beta Unit 300
  identity: {brand: acme, model: beta300}
  attributes: {colour: blue, power_w: 300}
"""

CLAIMS = """
- subject: {kind: product, identity: {brand: acme, model: alpha200}}
  kind: known_issue
  domain: mech
  severity: high
  text: {en: {title: Overheats under load, body: The housing gets hot after long runs., advice: a}}
  evidence:
    - {url: "https://maker.example.test/alpha", quote: The housing gets hot after long runs.}
- subject: {kind: product, identity: {brand: acme, model: beta300}}
  kind: known_issue
  domain: mech
  severity: low
  text: {en: {title: Cable is short, body: b, advice: a}}
  evidence:
    - {url: "https://maker.example.test/beta", quote: The cable is short.}
"""

SECRET = "sk-test-SECRET-value-123"


@pytest.fixture
def store(tmp_path):
    root = tmp_path / "gears"
    (root / "vocabulary").mkdir(parents=True)
    (root / "data").mkdir()
    (root / "pack.toml").write_text(textwrap.dedent(TOML), encoding="utf-8")
    (root / "vocabulary" / "terms.yaml").write_text(TERMS, encoding="utf-8")
    (root / "data" / "subjects.yaml").write_text(SUBJECTS, encoding="utf-8")
    (root / "data" / "claims.yaml").write_text(CLAIMS, encoding="utf-8")
    conn = connect(tmp_path / "knowledge.sqlite")
    packstore.install(conn, build.build(root, tmp_path / "gears.kpack"))
    yield conn
    conn.close()


@pytest.fixture
def app_state(tmp_path):
    conn = state.connect(tmp_path / "app.sqlite")
    yield conn
    conn.close()


@pytest.fixture
def ctx(store, app_state):
    return chatdata.Context(store=store, app=app_state)


def _subject(store, label):
    return store.execute("SELECT subject_id, pack_id FROM subjects WHERE label = ?",
                         (label,)).fetchone()


# ── the agent's view before it asks ─────────────────────────────────────


def test_the_sources_are_described_by_name_and_meaning_only(ctx, store):
    described = chatdata.describe_sources()
    names = {item["name"] for item in described}
    assert {"product_match", "catalogue_search", "subject_detail", "saved_checks",
            "quick_looks", "compare_drafts", "activity", "research_runs", "packs",
            "sites", "coverage_gaps"} <= names
    for item in described:
        assert set(item) == {"name", "description", "args"}
        assert isinstance(item["description"], str) and item["description"]
        assert all(isinstance(meaning, str) for meaning in item["args"].values())
    # No record of the store appears in the description the agent reads first.
    text = repr(described)
    assert "Alpha Unit 200" not in text and "Overheats" not in text


# ── every source: capped, never raising, empty stores answer with a note ─


@pytest.mark.parametrize("name", sorted(chatdata.SOURCES))
def test_a_source_with_nothing_to_read_answers_with_a_note(name):
    empty = chatdata.Context(store=None, app=None)
    out = chatdata.run(name, empty, {})
    assert out["source"] == name
    assert out["rows"] == []
    assert isinstance(out["note"], str) and out["note"]
    assert out.get("error") is False


@pytest.mark.parametrize("name", sorted(chatdata.SOURCES))
def test_a_source_over_an_empty_store_never_raises(name, tmp_path):
    fresh_store = connect(tmp_path / "empty.sqlite")
    fresh_app = state.connect(tmp_path / "empty-app.sqlite")
    try:
        out = chatdata.run(name, chatdata.Context(store=fresh_store, app=fresh_app), {})
    finally:
        fresh_store.close()
        fresh_app.close()
    assert out["rows"] == [] or isinstance(out["rows"], list)
    assert isinstance(out["note"], str)


def test_an_unknown_source_is_an_error_not_an_exception(ctx):
    out = chatdata.run("no_such_source", ctx, {})
    assert out["error"] is True
    assert out["rows"] == []
    assert "no_such_source" in out["note"]


def test_an_argument_the_source_does_not_declare_is_dropped_and_named(ctx):
    out = chatdata.run("catalogue_search", ctx, {"query": "alpha", "drop_table": "x"})
    assert [row["label"] for row in out["rows"]] == ["Alpha Unit 200"]
    assert "drop_table" in out["note"]


def test_rows_and_text_are_capped_whatever_the_source_returns(ctx, store):
    long = "word " * 200
    for index in range(30):
        store.execute("INSERT INTO subjects VALUES (?,?,?,?)",
                      (f"bulk{index:03d}", "gears", "product", f"Alpha bulk {index} {long}"))
    store.commit()
    out = chatdata.run("catalogue_search", ctx, {"query": "alpha"})
    assert len(out["rows"]) <= chatdata.ROWS_CAP
    assert out["truncated"] is True
    for row in out["rows"]:
        assert len(row["label"]) <= chatdata.TEXT_CAP


def test_a_source_that_raises_is_reported_as_a_note(ctx, monkeypatch):
    def broken(ctx, **kwargs):
        raise RuntimeError("the disk moved")

    original = chatdata.SOURCES["packs"]
    monkeypatch.setitem(chatdata.SOURCES, "packs",
                        dataclasses.replace(original, run=broken))
    out = chatdata.run("packs", ctx, {})
    assert out["rows"] == []
    assert "RuntimeError" in out["note"]


# ── the searching skill ─────────────────────────────────────────────────


def _row(out, label):
    return next(row for row in out["rows"] if row["label"] == label)


def _status(row, phrase, role="must"):
    return next(one["status"] for one in row[role] if one["text"] == phrase)


def test_a_partial_word_finds_the_product(ctx):
    out = chatdata.run("product_match", ctx, {"query": "alp"})
    assert out["rows"][0]["label"] == "Alpha Unit 200"


def test_a_widened_search_finds_a_product_the_full_phrase_missed(ctx):
    """`red` names a colour, which no search box reaches; the whole phrase finds
    nothing, the single word `alpha` finds the product."""
    out = chatdata.run("product_match", ctx, {"query": "red alpha"})
    assert out["rows"] and out["rows"][0]["label"] == "Alpha Unit 200"
    assert "search(es)" in out["note"]


def test_a_must_is_met_only_by_a_recorded_fact(ctx):
    row = _row(chatdata.run("product_match", ctx,
                            {"query": "alpha", "must": ["red"], "prefer": ["light"]}),
               "Alpha Unit 200")
    assert _status(row, "red") == "met"
    assert "colour red" in next(one for one in row["must"] if one["text"] == "red")["evidence"]
    assert _status(row, "light", role="prefer") == "unknown"


def test_a_constraint_with_no_text_hit_is_unknown_never_met(ctx):
    row = _row(chatdata.run("product_match", ctx,
                            {"query": "alpha", "must": ["waterproof"]}), "Alpha Unit 200")
    assert _status(row, "waterproof") == "unknown"
    assert row["all_musts_met"] is False


def test_a_serious_recorded_risk_contradicts_a_constraint(ctx):
    row = _row(chatdata.run("product_match", ctx,
                            {"query": "alpha", "must": ["overheats"]}), "Alpha Unit 200")
    found = row["must"][0]
    assert found["status"] == "contradicted"
    assert found["evidence"] == "Overheats under load"
    assert found["source"] == "https://maker.example.test/alpha"


def test_a_low_severity_risk_does_not_contradict(ctx):
    row = _row(chatdata.run("product_match", ctx,
                            {"query": "beta", "must": ["short"]}), "Beta Unit 300")
    assert row["must"][0]["status"] == "unknown"


def test_musts_rank_first_then_contradictions_then_unknowns(ctx):
    out = chatdata.run("product_match", ctx, {
        "query": "unit", "must": ["blue"], "prefer": ["red"],
    })
    assert [row["label"] for row in out["rows"]][0] == "Beta Unit 300"
    assert out["rows"][0]["all_musts_met"] is True
    assert [row["rank"] for row in out["rows"]] == [1, 2]

    contradicted = chatdata.run("product_match", ctx, {
        "query": "unit", "must": ["overheats"],
    })
    labels = [row["label"] for row in contradicted["rows"]]
    assert labels.index("Alpha Unit 200") > labels.index("Beta Unit 300")


def test_product_match_says_what_it_could_not_find(ctx):
    out = chatdata.run("product_match", ctx, {"query": "zzzz qqqq"})
    assert out["rows"] == []
    assert "no candidate" in out["note"]


def test_subject_detail_gives_attributes_and_each_risk_with_its_page(ctx, store):
    subject = _subject(store, "Alpha Unit 200")
    out = chatdata.run("subject_detail", ctx, {"subject_id": subject["subject_id"]})
    detail = out["rows"][0]
    assert detail["label"] == "Alpha Unit 200"
    assert {"key": "colour", "value": "red", "unit": ""} in detail["attributes"]
    risk = detail["risks"][0]
    assert risk["title"] == "Overheats under load"
    assert risk["sources"][0]["url"] == "https://maker.example.test/alpha"
    assert "hot after long runs" in risk["sources"][0]["quote"]
    assert chatdata.run("subject_detail", ctx, {"subject_id": "nope"})["rows"] == []


def test_packs_reports_what_is_installed_and_how_much(ctx):
    row = chatdata.run("packs", ctx, {})["rows"][0]
    assert row == {"pack_id": "gears", "name": "Gears", "version": "0.1.0",
                   "enabled": True, "subjects": 2, "claims": 2}


# ── the reader's own records, read only when asked ──────────────────────


def test_saved_checks_are_found_by_the_words_inside_them(ctx, app_state):
    state.record_lookup(app_state, source="extension", label="Alpha Unit 200",
                        request={}, response={"claims": [
                            {"title": "Overheats under load", "severity": "high"}]})
    state.record_lookup(app_state, source="extension", label="Beta Unit 300",
                        request={}, response={"claims": []})
    found = chatdata.run("saved_checks", ctx, {"text": "overheats"})
    assert [row["label"] for row in found["rows"]] == ["Alpha Unit 200"]
    assert found["rows"][0]["risk_titles"] == ["Overheats under load"]
    assert len(chatdata.run("saved_checks", ctx, {})["rows"]) == 2


def test_the_text_filter_is_every_word_not_any(ctx, app_state):
    state.record_lookup(app_state, source="extension", label="Alpha Unit 200",
                        request={}, response={"claims": []})
    assert chatdata.run("saved_checks", ctx, {"text": "alpha blue"})["rows"] == []


# ── no source may read a secret ─────────────────────────────────────────


def test_no_source_returns_a_key_or_a_settings_value(ctx, app_state, tmp_path, monkeypatch):
    env = tmp_path / ".env"
    assert keys.save({"exa": SECRET}, path=env) == ["exa"]
    state.put_settings(app_state, {"compare.token": SECRET})
    assert SECRET in env.read_text(encoding="utf-8")
    assert SECRET in repr(state.all_settings(app_state))
    for name in chatdata.SOURCES:
        out = chatdata.run(name, ctx, {"query": "alpha", "text": "", "pack_id": ""})
        assert SECRET not in repr(out), name


# ── the matcher's own words ─────────────────────────────────────────────


def _fact(text, identity=False):
    return {"text": text, "key": "k", "value": text, "unit": "", "identity": identity, "source": ""}


def test_a_unit_beside_a_number_is_part_of_the_constraint():
    """`18V` must not be met by a model code that happens to contain `18`."""
    assert chatdata._content("18V") == ["18", "v"]
    assert chatdata._content("a drill x wheel") == ["drill", "wheel"]
    model_code = [_fact("model TC-CD-18-2", identity=True)]
    assert chatdata._judge("18V", model_code, [])["status"] == "unknown"
    with_unit = [_fact("voltage_v 18 v")]
    assert chatdata._judge("18V", with_unit, [])["status"] == "met"
