"""B127 and B128 — the two verbs the authoring loop was missing.

*"This pack seems very solid but it includes 19 products and lacks the 20th. I
don't want to rebuild the whole thing."* and *"as well as the button: verify the
knowledge here."*

Authoring was all-or-nothing: the only way to change a draft was to author the
category again, which re-spends the run and can come back **worse** — the
reader's second attempt returned nothing at all. A generator you cannot correct
is a slot machine. And verifying existed for one claim, on a press, and not for
the screenful a reader is actually looking at.

The property that makes amending safe is the one most of these tests are about:
nothing existing is rewritten, and a refused amendment leaves the draft exactly
as it was.
"""

import json

import pytest
import yaml
from fastapi.testclient import TestClient

from app import packauthor, packdraft
from app.web import state
from app.web.app import create_app
from app.web.settings import Settings
from kriko.store.db import connect


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        store_path=tmp_path / "k.sqlite",
        app_state_path=tmp_path / "app.sqlite",
        analysis_log_path=tmp_path / "a.jsonl",
    )


def _pack(**over) -> dict:
    base = {
        "pack_id": "samsung.earbuds",
        "name": "Samsung earbuds",
        "lineup": [
            "Galaxy Buds Pro", "Galaxy Buds2 Pro", "Galaxy Buds Live",
            "Galaxy Buds3", "Galaxy Buds3 Pro", "Galaxy Buds FE",
        ],
        "coverage": {"note": "ran out of sources for the 2024 models",
                     "out_of_scope": ["Galaxy Watch6"]},
        "identity": {"product": ["brand", "series"]},
        "principle": "What owners report going wrong, not spec opinions.",
        "templates": ["{label} battery drain", "{label} case not charging"],
        "domains": [{"id": "battery", "label": "Battery"}],
        "subjects": [
            {"kind": "product", "label": "Galaxy Buds Pro",
             "identity": {"brand": "samsung", "series": "galaxy buds pro"}},
            {"kind": "product", "label": "Galaxy Buds2 Pro",
             "identity": {"brand": "samsung", "series": "galaxy buds2 pro"}},
        ],
        "claims": [
            {"subject": {"kind": "product",
                         "identity": {"brand": "samsung",
                                      "series": "galaxy buds pro"}},
             "domain": "battery", "severity": "high",
             "title": "One earbud stops holding charge after 12-18 months",
             "body": "Widely reported.", "advice": "Check per-bud percentage."},
        ],
    }
    return {**base, **over}


def _reply(payload: dict) -> str:
    return "Here it is.\n\n```json\n" + json.dumps(payload) + "\n```"


# ── the line-up, which is what stops an agent quietly covering a corner ──────


def test_what_the_agent_did_not_cover_is_written_down(settings):
    """The reader's failure: three of twenty, reported as success.

    An author that stops early is not wrong on its own terms — it found what it
    found. A pack covering a fraction of a category is *confidently* incomplete:
    the reader who looks up the fourth product gets "nothing known" and
    concludes there is nothing to know. So the gap is data."""
    written = packauthor.author(settings.store_path, _reply(_pack()),
                                category="samsung headphones")
    assert written["lineup"] == 6
    assert set(written["uncovered"]) == {
        "Galaxy Buds Live", "Galaxy Buds3", "Galaxy Buds3 Pro", "Galaxy Buds FE"
    }
    coverage = yaml.safe_load(
        (packdraft.open_draft(settings.store_path, written["slug"]).root
         / "research" / "coverage.yaml").read_text(encoding="utf-8")
    )
    assert coverage["out_of_scope"] == ["Galaxy Watch6"]
    assert "ran out of sources" in coverage["note"]


def test_a_pack_named_with_a_sentence_is_refused(settings):
    """"Samsung Galaxy Buds and wireless headphones common problems" is a
    sentence about a pack, and in a list of packs it is the line nobody can
    scan. Every pack here is about what goes wrong with something."""
    with pytest.raises(packauthor.PackRefused) as raised:
        packauthor.author(
            settings.store_path,
            _reply(_pack(name="Samsung Galaxy Buds and wireless headphones "
                              "common problems")),
        )
    assert "common problems" in str(raised.value)


def test_a_name_that_is_merely_long_is_refused_too(settings):
    with pytest.raises(packauthor.PackRefused) as raised:
        packauthor.author(
            settings.store_path,
            _reply(_pack(name="Samsung wireless in ear audio devices sold since 2019")),
        )
    assert "words" in str(raised.value)


def test_a_good_name_survives(settings):
    written = packauthor.author(settings.store_path, _reply(_pack()))
    assert written["name"] == "Samsung earbuds"


# ── amending ────────────────────────────────────────────────────────────────


def _drafted(settings):
    return packauthor.author(settings.store_path, _reply(_pack()),
                             category="samsung headphones")


def _addition(**over) -> dict:
    base = {
        "subjects": [
            {"kind": "product", "label": "Galaxy Buds3 Pro",
             "identity": {"brand": "samsung", "series": "galaxy buds3 pro"}},
        ],
        "claims": [
            {"subject": {"kind": "product",
                         "identity": {"brand": "samsung",
                                      "series": "galaxy buds3 pro"}},
             "domain": "battery", "severity": "medium",
             "title": "Case drains when stored", "body": "Reported.",
             "advice": "Charge before storing."},
        ],
        "coverage": {"note": "still nothing solid on the FE"},
    }
    return {**base, **over}


def test_an_amendment_adds_without_touching_what_was_there(settings):
    """The property that makes this safe to press on a pack you already like."""
    drafted = _drafted(settings)
    before = (packdraft.open_draft(settings.store_path, drafted["slug"]).root
              / "data" / "subjects.yaml").read_text(encoding="utf-8")
    result = packauthor.amend(settings.store_path, drafted["slug"],
                              _reply(_addition()))
    assert result["subjects_added"] == 1 and result["claims_added"] == 1
    after = (packdraft.open_draft(settings.store_path, drafted["slug"]).root
             / "data" / "subjects.yaml").read_text(encoding="utf-8")
    # Everything that was there is still there, unchanged, and in order —
    # including the header comment that says what the file is.
    assert after.startswith(before.splitlines()[0])
    for row in yaml.safe_load(before):
        assert row in yaml.safe_load(after)


def test_an_amendment_that_echoes_the_draft_changes_nothing(settings):
    """The brief hands the agent the existing list, and a model reading a list
    will sometimes echo it. That has to cost nothing rather than duplicate
    everything."""
    drafted = _drafted(settings)
    echo = {"subjects": _pack()["subjects"], "claims": _pack()["claims"]}
    with pytest.raises(packauthor.PackRefused) as raised:
        packauthor.amend(settings.store_path, drafted["slug"], _reply(echo))
    assert "already in this draft" in str(raised.value)


def test_a_refused_amendment_leaves_the_draft_exactly_as_it_was(settings):
    drafted = _drafted(settings)
    root = packdraft.open_draft(settings.store_path, drafted["slug"]).root
    before = {
        path.name: path.read_text(encoding="utf-8")
        for path in (root / "data").iterdir()
    }
    with pytest.raises(packauthor.PackRefused):
        packauthor.amend(settings.store_path, drafted["slug"], "no json here")
    after = {
        path.name: path.read_text(encoding="utf-8")
        for path in (root / "data").iterdir()
    }
    assert after == before


def test_the_gap_shrinks_as_it_is_covered(settings):
    """A second amend asks for what is still missing, not for what was just
    done — which is only true if the coverage file is rewritten as it goes."""
    drafted = _drafted(settings)
    assert "Galaxy Buds3 Pro" in drafted["uncovered"]
    result = packauthor.amend(settings.store_path, drafted["slug"],
                              _reply(_addition()))
    assert "Galaxy Buds3 Pro" not in result["uncovered"]
    assert "Galaxy Buds FE" in result["uncovered"]


def test_the_amend_brief_shows_what_exists_and_what_is_missing(settings):
    drafted = _drafted(settings)
    brief = packauthor.amend_brief(
        packauthor.draft_state(settings.store_path, drafted["slug"]),
        "the 2024 models",
    )
    assert "the 2024 models" in brief
    assert "Galaxy Buds Pro" in brief          # already covered — do not repeat
    assert "Galaxy Buds FE" in brief           # the gap
    assert "adding to it" in brief
    # The pack's own bar travels with the request: an addition that does not
    # clear it is the same mistake as a bad original.
    assert "spec opinions" in brief


def test_an_amendment_cannot_invent_an_identity_key(settings):
    """You are adding rows to a table whose columns are fixed."""
    drafted = _drafted(settings)
    with pytest.raises(packauthor.PackRefused):
        packauthor.amend(
            settings.store_path, drafted["slug"],
            _reply({"subjects": [
                {"kind": "product", "label": "Odd one",
                 "identity": {"brand": "samsung", "colour": "black"}}
            ]}),
        )


def test_amending_is_a_job_and_a_tool(settings, monkeypatch):
    """Both doors, like everything else that grows knowledge."""
    from app import mcp_server

    drafted = _drafted(settings)
    client = TestClient(create_app(settings))
    started = client.post(
        f"/api/packs/drafts/{drafted['slug']}/amend", json={"note": "the FE"}
    )
    assert started.status_code == 200 and started.json()["kind"] == "pack_amend"

    monkeypatch.setattr(mcp_server, "STORE_PATH", settings.store_path)
    monkeypatch.setattr(mcp_server, "_app_state_path",
                        lambda: settings.app_state_path)
    answer = mcp_server.amend_draft(drafted["slug"], "the FE")
    assert "the FE" in answer["brief"]
    assert "Galaxy Buds FE" in answer["uncovered"]


# ── B129: a draft that has been installed says so ───────────────────────────


def test_an_installed_draft_stops_claiming_it_is_waiting(settings):
    """The reader installed the draft, saw the pack in Knowledge, and the
    "…was drafted for you" card stayed — which reads as an install that did not
    take. Marked rather than deleted: the directory is the only copy of what the
    agent proposed, and covering its gaps has to keep working afterwards."""
    drafted = _drafted(settings)
    client = TestClient(create_app(settings))
    assert client.get("/api/packs/drafts").json()["items"][0]["installed_as"] == ""
    installed = client.post(f"/api/packs/drafts/{drafted['slug']}/install")
    assert installed.status_code == 200, installed.text
    row = client.get("/api/packs/drafts").json()["items"][0]
    assert row["installed_as"] == "samsung.earbuds"
    # And it is still a draft: amend, rebuild, install again.
    assert packdraft.open_draft(settings.store_path, drafted["slug"]).root.is_dir()


# ── B128: verify ────────────────────────────────────────────────────────────


def _installed_claim(settings):
    conn = connect(settings.store_path)
    conn.execute(
        "INSERT INTO packs (pack_id, name, version, schema_version, built_at,"
        " content_digest, enabled, installed_at)"
        " VALUES ('probe', 'Probe', '1', 1, '2026-09-01', 'd', 1, '2026-09-01')"
    )
    conn.execute(
        "INSERT INTO subjects (subject_id, pack_id, kind, label)"
        " VALUES ('s1', 'probe', 'product', 'Thing')"
    )
    conn.execute(
        "INSERT INTO claims (claim_id, pack_id, subject_id, kind, domain,"
        " severity, author_confidence, created_at)"
        " VALUES ('c1', 'probe', 's1', 'known_issue', 'engine', 'high', 0.6,"
        " datetime('now'))"
    )
    conn.execute(
        "INSERT INTO claim_text VALUES ('c1', 'probe', 'en', 'A known thing',"
        " 'body', 'advice')"
    )
    conn.execute(
        "INSERT INTO sources (source_id, pack_id, url, domain, site_or_channel,"
        " title, lang, source_type, published_at, retrieved_at)"
        " VALUES ('src1', 'probe', 'https://example.test/t', 'example.test',"
        " '', '', 'en', 'page', '', '2026-09-01')"
    )
    conn.execute(
        "INSERT INTO evidence (evidence_id, pack_id, claim_id, source_id,"
        " quote, locator, stance, independent)"
        " VALUES ('e1', 'probe', 'c1', 'src1', 'the thing fails', '',"
        " 'supports', 1)"
    )
    conn.commit()
    conn.close()


def test_verifying_a_pack_is_a_job_that_records_a_verdict_per_claim(
    settings, monkeypatch
):
    """One claim was a press; a screenful is minutes, and minutes belong in a
    row that outlives the request."""
    from app import factcheck
    from app.web import tasks

    _installed_claim(settings)
    monkeypatch.setattr(
        factcheck, "check_claim",
        lambda sources, **kw: {"verdict": factcheck.MISSING,
                               "detail": "the page no longer says it",
                               "sources": list(sources)},
    )
    result = tasks.verify(settings, {"pack_id": "probe"}, _Progress())
    assert result["checked"] == 1
    assert result["verdicts"] == {factcheck.MISSING: 1}
    conn = state.connect(settings.app_state_path)
    (row,) = state.fact_checks(conn)
    assert row["claim_id"] == "c1" and row["verdict"] == factcheck.MISSING
    # Reported, never retracted: the claim is still in the store.
    store = connect(settings.store_path)
    assert store.execute("SELECT COUNT(*) FROM claims").fetchone()[0] == 1


def test_verifying_nothing_says_so_rather_than_succeeding_emptily(settings):
    from app.web import tasks

    with pytest.raises(ValueError) as raised:
        tasks.verify(settings, {"pack_id": "nope"}, _Progress())
    assert "no installed claims" in str(raised.value)


def test_verify_is_reachable_as_an_operation(settings):
    _installed_claim(settings)
    client = TestClient(create_app(settings))
    started = client.post("/api/verify", json={"pack_id": "probe"})
    assert started.status_code == 200 and started.json()["kind"] == "verify"


class _Progress:
    def log(self, line: str) -> None:
        pass

    def set(self, progress: float, message: str = "") -> None:
        pass

    def check(self) -> None:
        pass
