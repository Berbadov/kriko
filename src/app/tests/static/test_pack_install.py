"""Browser-plane pack artifact installation tests."""

import textwrap

import pytest
from fastapi.testclient import TestClient

from app.web.app import create_app
from app.web.routers import packs as packs_router
from app.web.settings import Settings
from kriko.pack import build


@pytest.fixture
def artifact(tmp_path):
    root = tmp_path / "source"
    (root / "vocabulary").mkdir(parents=True)
    (root / "data").mkdir()
    (root / "research").mkdir()
    (root / "pack.toml").write_text(
        textwrap.dedent(
            """
            [pack]
            id = "uploaded"
            name = "Uploaded pack"
            version = "1.0.0"
            license = "CC0-1.0"
            [identity]
            product = ["brand", "model"]
            """
        ),
        encoding="utf-8",
    )
    (root / "vocabulary" / "terms.yaml").write_text(
        "- {term_id: product, role: subject_kind}\n"
        "- {term_id: brand, role: attribute, datatype: text}\n"
        "- {term_id: model, role: attribute, datatype: text}\n",
        encoding="utf-8",
    )
    (root / "data" / "subjects.yaml").write_text(
        "- kind: product\n  label: Test product\n"
        "  identity: {brand: acme, model: one}\n",
        encoding="utf-8",
    )
    (root / "data" / "claims.yaml").write_text("[]\n", encoding="utf-8")
    (root / "research" / "principle.md").write_text("Useful facts.", encoding="utf-8")
    (root / "research" / "templates.yaml").write_text("[]\n", encoding="utf-8")
    return build.build(root, tmp_path / "uploaded.kpack").read_bytes()


@pytest.fixture
def client(tmp_path):
    store_path = tmp_path / "store.sqlite"
    return TestClient(
        create_app(
            Settings(
                store_path=store_path,
                analysis_log_path=tmp_path / "analyses.jsonl",
            )
        )
    )


def test_install_upload_returns_pack_revision_and_counts(client, artifact):
    response = client.post(
        "/api/packs/install?filename=uploaded.kpack",
        content=artifact,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["pack"] == {
        "pack_id": "uploaded",
        "name": "Uploaded pack",
        "version": "1.0.0",
        "enabled": True,
    }
    assert body["revision"]["revision_id"].startswith("uploaded@")
    assert body["counts"] == {"subjects": 1, "claims": 0, "evidence": 0}


def test_invalid_upload_reports_error_and_removes_staged_file(client, monkeypatch):
    staged = []
    real_installer = packs_router.packstore.install

    def fail_install(store, path):
        staged.append(path)
        raise ValueError("not a valid pack")

    monkeypatch.setattr(packs_router.packstore, "install", fail_install)
    response = client.post(
        "/api/packs/install",
        headers={"X-Filename": "broken.kpack"},
        content=b"invalid artifact",
    )
    monkeypatch.setattr(packs_router.packstore, "install", real_installer)

    assert response.status_code == 400
    assert response.json()["detail"] == "invalid pack artifact: not a valid pack"
    assert staged and not staged[0].exists()


def test_path_like_filename_is_rejected(client, artifact):
    response = client.post(
        "/api/packs/install?filename=..%2Fuploaded.kpack",
        content=artifact,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "filename must be a plain file name"
