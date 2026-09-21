"""A category named in plain words becomes a draft. (D4)

The reader asked for this three times, the last time as

    package bulding still expects user raw input to create which i said many
    times, its gotta be automated with agents man

so the assertions here are in two groups, and the second group is the reason
the feature is allowed to exist at all:

* **The reader types one thing.** A category. Everything else — the pack id,
  the identity keys, the bar, the searches, the first rows — comes back from an
  agent that read the category, and a draft appears with nothing installed.
* **The agent's reach did not widen.** It prints JSON; Kriko writes the files
  through `app/packdraft.py`. No Python reaches disk, no path escapes the
  draft, nothing is installed without the reader's press, and a malformed reply
  costs a run rather than a store row.
"""

import contextlib
import json

import pytest
import yaml

from app import packauthor, packdraft

PACK = {
    "pack_id": "org.example.drills",
    "name": "Cordless drills",
    "languages": ["en"],
    "markets": ["EU"],
    "identity": {"product": ["brand", "series"]},
    "principle": "Surface what an owner cannot find out by holding one.",
    "templates": ["{label} common problems", "{label} chuck wobble forum"],
    "domains": [{"id": "mechanical", "label": "Mechanical"}],
    "attributes": [{"id": "voltage_v", "label": "Voltage", "datatype": "number"}],
    "lineup": ["Makita DHP484", "Bosch GSB 18V-55"],
    "subjects": [
        {"kind": "product", "label": "Makita DHP484",
         "identity": {"brand": "makita", "series": "DHP484"},
         "aliases": ["DHP484Z"], "attributes": {"voltage_v": 18}},
        {"kind": "product", "label": "Bosch GSB 18V-55",
         "identity": {"brand": "bosch", "series": "GSB18V55"}},
    ],
    "claims": [
        {"subject": {"kind": "product",
                     "identity": {"brand": "makita", "series": "DHP484"}},
         "domain": "mechanical", "severity": "high",
         "title": "Chuck jaws lose grip after heavy hammer use",
         "body": "Bits slip under load once the jaws wear.",
         "advice": "Check for runout before buying used."},
    ],
    "notes": "Two models read; nothing solid on the Bosch yet.",
}


def _reply(pack: dict) -> str:
    """What the CLI prints: prose, then the object in a fence."""
    return ("I read a dozen threads and the owner's manuals.\n\n"
            "```json\n" + json.dumps(pack) + "\n```\n")


def _store(tmp_path):
    """A store path, so drafts land beside it rather than in `~/.kriko`."""
    return tmp_path / "knowledge.sqlite"


# ── the reader types one thing ───────────────────────────────────────────


def test_one_category_becomes_a_draft_the_reader_never_described(tmp_path):
    """The whole of D4 in one assertion.

    Nothing in the input names a directory, a pack id, a subject kind or an
    identity key — the four fields the screen this replaces demanded.
    """
    written = packauthor.author(_store(tmp_path), _reply(PACK),
                                category="cordless drills")

    assert written["pack_id"] == "org.example.drills"
    assert written["subjects"] == 2
    assert written["claims"] == 1
    assert written["installed"] is False

    draft = packdraft.open_draft(_store(tmp_path), written["slug"])
    files = draft.files()
    for name in ("pack.toml", "README.md", "research/principle.md",
                 "research/templates.yaml", "vocabulary/terms.yaml",
                 "data/subjects.yaml", "data/claims.yaml"):
        assert name in files, files


def test_the_identity_table_is_the_agents_and_reaches_pack_toml(tmp_path):
    """The decision the reader was being asked to make blind.

    Too few keys and unrelated rows collide into one subject; too many and one
    thing splits across subjects that never see each other's claims. Neither
    raises. An agent that has read the category can make it; a reader who has
    not cannot.
    """
    written = packauthor.author(_store(tmp_path), _reply(PACK), category="drills")
    draft = packdraft.open_draft(_store(tmp_path), written["slug"])
    toml = (draft.root / "pack.toml").read_text(encoding="utf-8")

    assert 'product = ["brand", "series"]' in toml
    assert written["identity"] == {"product": ["brand", "series"]}


def test_the_manifest_says_which_language_the_queries_are_in(tmp_path):
    """A pack whose searches are Turkish and whose manifest claims English is
    the defect the reader already reported as "turkish-english queries"."""
    pack = dict(PACK, languages=["tr", "en"], markets=["TR"],
                templates=["{label} arıza şikayet"])
    written = packauthor.author(_store(tmp_path), _reply(pack), category="drills")
    draft = packdraft.open_draft(_store(tmp_path), written["slug"])
    toml = (draft.root / "pack.toml").read_text(encoding="utf-8")

    assert 'languages = ["tr", "en"]' in toml
    assert 'markets = ["TR"]' in toml


def test_a_domain_a_claim_used_and_forgot_to_declare_is_declared_anyway(tmp_path):
    """The builder refuses a row naming an undeclared term.

    Left alone, that failure arrives as an error about a claim when the fault
    is in the vocabulary — and the reader reads it as the draft being broken.
    """
    pack = dict(PACK, domains=[])
    written = packauthor.author(_store(tmp_path), _reply(pack), category="drills")
    draft = packdraft.open_draft(_store(tmp_path), written["slug"])
    terms = yaml.safe_load((draft.root / "vocabulary" / "terms.yaml").read_text(encoding="utf-8"))

    declared = {row["term_id"] for row in terms if row["role"] == "domain"}
    assert "mechanical" in declared
    # And every identity key, which is what makes the subject rows loadable.
    attributes = {row["term_id"] for row in terms if row["role"] == "attribute"}
    assert {"brand", "series", "voltage_v"} <= attributes


def test_the_draft_the_agent_wrote_actually_builds(tmp_path):
    """The gate that matters: a draft that does not build is a directory.

    Everything above asserts a file exists. This one runs the real builder over
    what the agent proposed, which is the only assertion that can fail for the
    reason a reader would notice.
    """
    written = packauthor.author(_store(tmp_path), _reply(PACK), category="drills")
    artifact = packdraft.build_artifact(_store(tmp_path), written["slug"])
    assert artifact.exists()
    assert artifact.suffix == ".kpack"


def test_a_claim_is_ranked_as_proposed_rather_than_evidenced(tmp_path):
    """An agent's reading is not a source row.

    A pack that shipped agent-proposed claims at the confidence of evidenced
    ones would launder a guess into the store, and the research plane's whole
    acceptance path exists to stop exactly that.
    """
    written = packauthor.author(_store(tmp_path), _reply(PACK), category="drills")
    draft = packdraft.open_draft(_store(tmp_path), written["slug"])
    claims = yaml.safe_load((draft.root / "data" / "claims.yaml").read_text(encoding="utf-8"))

    assert claims[0]["detection"] == "reported"
    assert claims[0]["confidence"] == 0.5
    assert claims[0]["subject"] == {
        "kind": "product", "identity": {"brand": "makita", "series": "DHP484"}}


# ── and the agent's reach did not widen ──────────────────────────────────


def test_nothing_the_agent_names_can_become_a_file_name(tmp_path):
    """The draft's file set is fixed, so an agent cannot add to it.

    `packdraft.WRITABLE_FILES` is the list, and `build.py` is absent from it on
    purpose: a pack may ship Python and a pack an *agent* wrote may not,
    because installing it would run code the reader never read.
    """
    pack = dict(PACK, name="Drills")
    written = packauthor.author(_store(tmp_path), _reply(pack), category="drills")
    draft = packdraft.open_draft(_store(tmp_path), written["slug"])

    assert not any(name.endswith(".py") for name in draft.files())
    with pytest.raises(packdraft.DraftRefused):
        packdraft.write(_store(tmp_path), slug=written["slug"],
                        path="build.py", text="import os")


def test_a_pack_id_that_looks_like_a_path_does_not_become_one(tmp_path):
    """The directory is derived from the id, never accepted as one."""
    pack = dict(PACK, pack_id="../../.claude/settings")
    written = packauthor.author(_store(tmp_path), _reply(pack), category="drills")
    root = packdraft.drafts_root(_store(tmp_path)).resolve()

    draft = packdraft.open_draft(_store(tmp_path), written["slug"])
    assert root in draft.root.resolve().parents
    assert ".." not in written["slug"]


def test_a_reply_with_no_json_is_refused_and_writes_nothing(tmp_path):
    with pytest.raises(packauthor.PackRefused, match="no JSON"):
        packauthor.author(_store(tmp_path), "I could not find much, sorry.",
                          category="drills")
    assert not packdraft.drafts_root(_store(tmp_path)).exists()


def test_a_pack_with_no_identity_table_is_refused_rather_than_defaulted(tmp_path):
    """A default identity table would be this module having an opinion about
    what things are like — the exact thing the engine's scaffold refuses to."""
    pack = dict(PACK)
    pack.pop("identity")
    with pytest.raises(packauthor.PackRefused, match="identity"):
        packauthor.author(_store(tmp_path), _reply(pack), category="drills")


def test_a_pack_with_no_searches_is_refused(tmp_path):
    """A pack with no templates renders zero queries, so its Research button
    says what to keep and never says what to look for."""
    with pytest.raises(packauthor.PackRefused, match="templates"):
        packauthor.author(_store(tmp_path), _reply(dict(PACK, templates=[])),
                          category="drills")


def test_a_pack_with_no_bar_for_a_claim_is_refused(tmp_path):
    """The engine ranks; it does not decide taste. A pack that ships no
    principle has handed the one category-specific judgement back to nobody."""
    with pytest.raises(packauthor.PackRefused, match="principle"):
        packauthor.author(_store(tmp_path), _reply(dict(PACK, principle="")),
                          category="drills")


def test_a_subject_missing_an_identity_key_is_refused_with_the_key_named(tmp_path):
    """A missing key hashes to a different thing rather than failing, which is
    why this is the one shape error worth stopping the whole draft for."""
    pack = dict(PACK, subjects=[
        {"kind": "product", "label": "Makita DHP484",
         "identity": {"brand": "makita"}}])
    with pytest.raises(packauthor.PackRefused, match="series"):
        packauthor.author(_store(tmp_path), _reply(pack), category="drills")


def test_a_claim_about_a_subject_nobody_declared_is_dropped_not_fatal(tmp_path):
    """Dropped rather than refused: an agent that researched three things and
    wrote two subjects has produced a usable pack with one loose claim, and
    failing the draft for it throws away the work."""
    pack = dict(PACK, claims=PACK["claims"] + [
        {"subject": {"kind": "product",
                     "identity": {"brand": "hilti", "series": "SF6H"}},
         "domain": "mechanical", "title": "Something about a drill nobody listed"}])
    written = packauthor.author(_store(tmp_path), _reply(pack), category="drills")
    assert written["claims"] == 1


def test_authoring_installs_nothing(tmp_path):
    """Three steps, three authorities: the agent proposes, Kriko writes, the
    reader installs. This asserts the third one is still separate."""
    from kriko.store.db import connect

    written = packauthor.author(_store(tmp_path), _reply(PACK), category="drills")
    assert written["installed"] is False

    conn = connect(_store(tmp_path))
    rows = list(conn.execute("SELECT pack_id FROM packs"))
    conn.close()
    assert [row["pack_id"] for row in rows] == []


# ── the brief the agent is handed ────────────────────────────────────────


def test_the_brief_names_the_silent_failure_the_reader_could_not_have_known():
    """An instruction that says "choose identity keys" without saying what a
    wrong choice does silently is an instruction that gets obeyed carelessly."""
    brief = packauthor.brief("espresso machines")
    assert "espresso machines" in brief
    assert "the same thing" in brief
    assert "Neither failure raises" in brief
    # And the one rule that outranks completeness.
    assert "Never invent a claim" in brief


def test_the_brief_tells_the_agent_it_has_no_tools_and_prints_json():
    """B92's constraint, restated for this job: the spawned agent gets no
    `--mcp-config`, so an instruction to call a Kriko tool would be an
    instruction to call nothing."""
    brief = packauthor.brief("e-bikes")
    assert "no Kriko tools" in brief
    assert "```json" in brief


def test_the_brief_warns_against_the_query_shape_the_reader_reported():
    """`Volkswagen Golf 1.5_TSI 150 hp common problems` — seven queries a
    reader watched find nothing, twice. A new pack should not repeat it."""
    brief = packauthor.brief("drills")
    assert "catalog identifier" in brief


# ── through the job runner, which is the door the reader presses ─────────


def _fake_cli(tmp_path, reply_text: str):
    """A CLI that prints what a real one would, as a real subprocess.

    Borrowed shape from `test_the_harness_research_plane.py`: the thing most
    likely to be wrong is the spawn, and a monkeypatched `subprocess.run`
    tests neither the vector nor the envelope.
    """
    import json as _json
    import sys

    from app.providers import harness as harness_mod

    envelope = tmp_path / "author-reply.json"
    envelope.write_text(
        _json.dumps({"type": "result", "result": reply_text}), encoding="utf-8")
    script = tmp_path / "fake_author_cli.py"
    script.write_text(
        "import pathlib, sys\n"
        f"sys.stdin.read()\n"
        f"sys.stdout.write(pathlib.Path({str(envelope)!r}).read_text(encoding='utf-8'))\n",
        encoding="utf-8")
    return harness_mod.Harness(
        "fake", "Fake CLI", sys.executable, (str(script), "-p"), structured=True)


class _Recorder:
    def __init__(self):
        self.lines: list[str] = []
        self.partials: list[dict] = []

    def set(self, fraction, message=""):
        if message:
            self.lines.append(message)

    def log(self, line):
        self.lines.append(line)

    @property
    def cancelled(self):
        return False

    def check(self):
        pass

    def partial(self, result):
        # Real `Progress` writes this to the job row so a cancel keeps what was
        # finished. Held here so a test can assert on the checkpoints too.
        self.partials.append(result)


def test_authoring_a_pack_is_given_longer_than_one_subjects_research(
    tmp_path, monkeypatch
):
    """The ceilings are different because the jobs are. (B105)

    `TIMEOUT_SECONDS` is sized for three searches and four pages. Authoring a
    pack is a category read from scratch, four decisions made from what was
    read, and two or three subjects researched before the first character is
    printed -- measured past ten minutes against the real CLI. Handing that
    the research ceiling kills healthy runs and reports them as hangs, which
    is the least debuggable failure this feature could have.
    """
    from app.providers import harness as harness_mod
    from app.web import tasks

    fake = _fake_cli(tmp_path, _reply(PACK))
    asked = {}
    monkeypatch.setattr(harness_mod, "available", lambda: [fake])

    def factory(**kwargs):
        asked.update(kwargs)
        return harness_mod.HarnessResearcher(fake, timeout=60)

    monkeypatch.setattr("app.providers.harness_researcher", factory)
    settings = type(
        "S", (), {"store_path": _store(tmp_path),
                  "app_state_path": tmp_path / "app.sqlite"}
    )()
    tasks.pack_author(settings, {"category": "cordless drills"}, _Recorder())

    assert asked["timeout"] == harness_mod.AUTHOR_TIMEOUT_SECONDS
    assert harness_mod.AUTHOR_TIMEOUT_SECONDS > harness_mod.TIMEOUT_SECONDS
    # And a reader who names one still gets theirs. Suppressed because the
    # draft this fake writes already exists by now, which happens after the
    # researcher has been asked for -- and the ask is the whole assertion.
    with contextlib.suppress(Exception):
        tasks.pack_author(
            settings, {"category": "espresso machines", "timeout_seconds": 90},
            _Recorder())
    assert asked["timeout"] == 90.0


def test_one_press_ends_with_a_draft_and_a_message_naming_it(tmp_path, monkeypatch):
    """The reader's whole experience of D4, through the real job handler."""
    from app.providers import harness as harness_mod
    from app.web import tasks

    fake = _fake_cli(tmp_path, _reply(PACK))
    monkeypatch.setattr(harness_mod, "available", lambda: [fake])
    monkeypatch.setattr(
        "app.providers.harness_researcher",
        lambda **kw: harness_mod.HarnessResearcher(fake, timeout=60))

    settings = type("S", (), {"store_path": _store(tmp_path),
                                  "app_state_path": tmp_path / "app.sqlite"})()
    progress = _Recorder()
    result = tasks.pack_author(settings, {"category": "cordless drills"}, progress)

    assert result["pack_id"] == "org.example.drills"
    assert result["installed"] is False
    last = progress.lines[-1]
    # A run that ends without saying what it did is the defect B92 was about.
    assert "org.example.drills" in last
    assert "Install" in last


def test_no_coding_agent_says_what_to_do_instead_rather_than_failing_blankly(
        tmp_path, monkeypatch):
    """A dead end is worse than a refusal. The other door is the MCP server,
    and a reader who cannot find it will read this as the button being broken.
    """
    from app.providers import harness as harness_mod
    from app.web import tasks

    monkeypatch.setattr(harness_mod, "available", lambda: [])
    monkeypatch.setattr(harness_mod, "found_but_unusable", lambda: [])
    settings = type("S", (), {"store_path": _store(tmp_path),
                                  "app_state_path": tmp_path / "app.sqlite"})()

    with pytest.raises(ValueError, match="MCP server"):
        tasks.pack_author(settings, {"category": "drills"}, _Recorder())


def test_an_empty_category_is_refused_before_an_agent_is_started(tmp_path):
    """The one thing the reader does have to type."""
    from app.web import tasks

    settings = type("S", (), {"store_path": _store(tmp_path),
                                  "app_state_path": tmp_path / "app.sqlite"})()
    with pytest.raises(ValueError, match="category"):
        tasks.pack_author(settings, {"category": "  "}, _Recorder())


def test_what_the_agent_said_survives_a_reply_that_was_not_a_pack(
        tmp_path, monkeypatch):
    """An agent that read the category well and printed a malformed object has
    produced work worth seeing. A refusal that throws the text away is a
    refusal nobody can act on."""
    from app.providers import harness as harness_mod
    from app.web import tasks

    fake = _fake_cli(tmp_path, "I read a lot and then forgot to print JSON.")
    monkeypatch.setattr(harness_mod, "available", lambda: [fake])
    monkeypatch.setattr(
        "app.providers.harness_researcher",
        lambda **kw: harness_mod.HarnessResearcher(fake, timeout=60))

    settings = type("S", (), {"store_path": _store(tmp_path),
                                  "app_state_path": tmp_path / "app.sqlite"})()
    progress = _Recorder()
    with pytest.raises(ValueError, match="did not produce a usable pack"):
        tasks.pack_author(settings, {"category": "drills"}, progress)
    assert any("forgot to print JSON" in line for line in progress.lines)
