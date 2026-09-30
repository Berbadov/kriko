"""B173: a product's specifications, each with its page, from the pack's own attributes.

*"Support detailed product info fetching for Compare (more detail is fine, see
Compare)"*. Specs already fit as subject attributes; what was missing is the
ask (the author brief and the quick look never requested them), a source on
each, and a way for a screen to name them without knowing the category.
"""

import json

import pytest
import yaml
from fastapi.testclient import TestClient

from app import packauthor, packdraft, quicklook
from app.web.app import create_app
from app.web.settings import Settings
from kriko.store import packstore
from kriko.store.db import connect

PAGE = "https://example.org/phone-15"


def _pack(attributes) -> dict:
    return {
        "pack_id": "org.example.phones",
        "name": "Phones",
        "lineup": ["Phone 15", "Phone 15 Pro"],
        "identity": {"product": ["brand", "series"]},
        "principle": "What owners report going wrong.",
        "templates": ["{label} common problems"],
        "domains": [{"id": "battery", "label": "Battery"}],
        "attributes": [
            {"id": "chipset", "label": "Chipset", "datatype": "text"},
            {"id": "battery_mah", "label": "Battery capacity", "datatype": "number"},
        ],
        "subjects": [
            {"kind": "product", "label": "Phone 15",
             "identity": {"brand": "acme", "series": "phone 15"},
             "attributes": attributes},
            {"kind": "product", "label": "Phone 15 Pro",
             "identity": {"brand": "acme", "series": "phone 15 pro"}},
        ],
        "claims": [],
    }


def _reply(payload: dict) -> str:
    return "Done.\n\n```json\n" + json.dumps(payload) + "\n```"


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        store_path=tmp_path / "k.sqlite",
        app_state_path=tmp_path / "app.sqlite",
        analysis_log_path=tmp_path / "a.jsonl",
    )


# ── the ask ──────────────────────────────────────────────────────────────


def test_the_author_brief_asks_for_specifications_with_a_source_each():
    text = packauthor.brief("phones")
    assert "specifications" in text.lower()
    assert '"source"' in text


def test_the_quick_look_asks_for_specifications_and_names_the_packs_own(tmp_path):
    text = quicklook.brief("Phone 15", attributes="* Chipset\n* Battery capacity")
    assert '"specs"' in text
    assert "* Chipset" in text and "* Battery capacity" in text
    assert '"specs"' in quicklook.brief("Phone 15")


def test_a_quick_look_keeps_only_specifications_that_name_a_page():
    found = quicklook.parse(_reply({"specs": [
        {"name": "Chipset", "value": "A16", "url": PAGE},
        {"name": "Battery", "value": "3349 mAh"},
        {"name": "", "value": "x", "url": PAGE},
        {"name": "Display", "value": "6.1 in", "url": "file:///etc/passwd"},
    ]}))
    assert found["specs"] == [
        {"name": "Chipset", "value": "A16", "url": PAGE, "domain": "example.org"}]


# ── the record ───────────────────────────────────────────────────────────


def test_an_authored_specification_without_a_page_is_dropped(settings):
    written = packauthor.author(
        settings.store_path,
        _reply(_pack({
            "chipset": {"value": "A16", "source": PAGE},
            "battery_mah": 3349,
        })),
        category="phones",
    )
    root = packdraft.open_draft(settings.store_path, written["slug"]).root
    rows = yaml.safe_load((root / "data" / "subjects.yaml").read_text(encoding="utf-8"))
    assert rows[0]["attributes"] == {"chipset": {"value": "A16", "source": PAGE}}


def test_an_amendment_adds_sourced_specifications_to_a_subject_already_there(settings):
    written = packauthor.author(
        settings.store_path, _reply(_pack({})), category="phones")
    before = yaml.safe_load((packdraft.open_draft(settings.store_path, written["slug"])
                             .root / "data" / "subjects.yaml").read_text(encoding="utf-8"))
    assert "attributes" not in before[0]

    packauthor.amend(settings.store_path, written["slug"], _reply({
        "attributes": [{"id": "weight_g", "label": "Weight", "datatype": "number"}],
        "subjects": [{
            "kind": "product", "label": "Phone 15",
            "identity": {"brand": "acme", "series": "phone 15"},
            "attributes": {
                "chipset": {"value": "A16", "source": PAGE},
                "weight_g": {"value": "171", "source": PAGE},
                "undeclared": {"value": "x", "source": PAGE},
                "battery_mah": {"value": "3349"},
            },
        }],
    }))
    root = packdraft.open_draft(settings.store_path, written["slug"]).root
    rows = yaml.safe_load((root / "data" / "subjects.yaml").read_text(encoding="utf-8"))
    assert rows[0]["attributes"] == {
        "chipset": {"value": "A16", "source": PAGE},
        "weight_g": {"value": "171", "source": PAGE},
    }
    # It builds: the new attribute is declared, the stray key never reached it.
    assert packdraft.build_artifact(settings.store_path, written["slug"]).exists()


def test_the_amend_brief_lists_the_specifications_the_pack_declares(settings):
    written = packauthor.author(
        settings.store_path, _reply(_pack({})), category="phones")
    state = packauthor.draft_state(settings.store_path, written["slug"])
    text = packauthor.amend_brief(state)
    assert "`chipset`: Chipset" in text
    assert "`brand`" not in text.split("## Specifications")[1].split("##")[0]


# ── what a screen reads ──────────────────────────────────────────────────


def _installed(settings) -> tuple[TestClient, str]:
    written = packauthor.author(
        settings.store_path,
        _reply(_pack({"chipset": {"value": "A16", "source": PAGE},
                      "battery_mah": {"value": "3349", "source": PAGE}})),
        category="phones")
    artifact = packdraft.build_artifact(settings.store_path, written["slug"])
    conn = connect(settings.store_path)
    packstore.install(conn, artifact)
    subject = conn.execute(
        "SELECT subject_id FROM subjects WHERE label = 'Phone 15'").fetchone()[0]
    conn.close()
    return TestClient(create_app(settings)), subject


def test_a_subject_lists_its_specifications_with_the_packs_label_and_source(settings):
    client, subject = _installed(settings)
    attributes = client.get(f"/api/subjects/{subject}").json()["attributes"]
    by_key = {a["key"]: a for a in attributes}
    assert by_key["chipset"]["label"] == "Chipset"
    assert by_key["chipset"]["value_text"] == "A16"
    assert by_key["chipset"]["source_url"] == PAGE
    assert by_key["battery_mah"]["datatype"] == "number"
    # An identity key carries no source.
    assert by_key["brand"]["is_identity"] == 1
    assert by_key["brand"]["source_url"] == ""


def test_a_store_made_before_the_source_column_gains_it(tmp_path):
    import sqlite3

    path = tmp_path / "old.sqlite"
    old = sqlite3.connect(path)
    old.execute(
        "CREATE TABLE attributes (attribute_id TEXT NOT NULL, pack_id TEXT NOT NULL,"
        " subject_id TEXT NOT NULL, key TEXT NOT NULL, value_text TEXT NOT NULL,"
        " value_num REAL, unit TEXT NOT NULL DEFAULT '',"
        " valid_from TEXT NOT NULL DEFAULT '', valid_to TEXT NOT NULL DEFAULT '',"
        " is_identity INTEGER NOT NULL DEFAULT 0, confidence REAL,"
        " PRIMARY KEY (attribute_id, pack_id))")
    old.commit()
    old.close()
    conn = connect(path)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(attributes)")}
    conn.close()
    assert "source_url" in columns
