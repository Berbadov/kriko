"""A harvest or an update installs a catalog without asking; the reader can go back."""

import textwrap

from fastapi.testclient import TestClient

from app.web.app import create_app
from app.web.settings import Settings
from kriko.pack import build
from kriko.store import packstore
from kriko.store.db import connect


def _pack(tmp_path, version, title):
    root = tmp_path / f"src-{version}"
    for d in ("vocabulary", "data"):
        (root / d).mkdir(parents=True)
    (root / "pack.toml").write_text(textwrap.dedent(f"""
        [pack]
        id = "widgets"
        name = "Widgets"
        version = "{version}"
        [identity]
        product = ["brand", "model"]
    """), encoding="utf-8")
    (root / "vocabulary" / "terms.yaml").write_text(
        "- {term_id: product, role: subject_kind}\n"
        "- {term_id: brand, role: attribute, datatype: text}\n"
        "- {term_id: model, role: attribute, datatype: text}\n", encoding="utf-8")
    (root / "data" / "subjects.yaml").write_text(
        "- {kind: product, label: Widget, identity: {brand: acme, model: w1}}\n", encoding="utf-8")
    (root / "data" / "claims.yaml").write_text(textwrap.dedent(f"""
        - subject: {{kind: product, identity: {{brand: acme, model: w1}}}}
          kind: known_issue
          domain: general
          severity: low
          text: {{en: {{title: {title}, body: b, advice: a}}}}
          evidence:
            - {{url: "https://example.org/{version}", quote: It happened.}}
    """), encoding="utf-8")
    return build.build(root, tmp_path / f"w-{version}.kpack")


def test_going_back_restores_the_version_before(tmp_path):
    store = connect(tmp_path / "knowledge.sqlite")
    packstore.install(store, _pack(tmp_path, "1.0.0", "First"))
    packstore.install(store, _pack(tmp_path, "1.1.0", "Second"))
    store.commit()
    store.close()
    client = TestClient(create_app(Settings(
        store_path=tmp_path / "knowledge.sqlite", app_state_path=tmp_path / "app.sqlite",
        analysis_log_path=tmp_path / "a.jsonl")))

    [pack] = client.get("/api/packs").json()
    assert (pack["version"], pack["previous_version"]) == ("1.1.0", "1.0.0")
    assert client.post("/api/packs/widgets/rollback").json()["version"] == "1.0.0"
    [pack] = client.get("/api/packs").json()
    assert pack["version"] == "1.0.0"
    assert client.post("/api/packs/nothing/rollback").status_code == 404
