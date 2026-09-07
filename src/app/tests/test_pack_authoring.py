"""Starting a pack from inside the app.

The app could build a pack directory and install the artifact, but not create
the directory — authoring began outside it, in a document. This is that door,
and the two things it must not do: install anything, or overwrite an author's
rows.
"""

import pytest
from fastapi.testclient import TestClient

from app.web.app import create_app
from app.web.settings import Settings


@pytest.fixture
def client(tmp_path):
    app = create_app(
        Settings(
            store_path=tmp_path / "k.sqlite",
            app_state_path=tmp_path / "app.sqlite",
            analysis_log_path=tmp_path / "a.jsonl",
        )
    )
    with TestClient(app) as client:
        yield client


def _new(client, root, **over):
    body = {
        "root": str(root),
        "pack_id": "org.example.thing",
        "name": "Things",
        "identity": {"product": ["brand", "series"]},
    }
    return client.post("/api/packs/scaffold", json={**body, **over})


def test_it_writes_a_pack_that_the_build_job_can_then_take(client, tmp_path):
    response = _new(client, tmp_path / "newpack")
    assert response.status_code == 200
    files = response.json()["files"]
    assert any(name.endswith("pack.toml") for name in files)
    assert any(name.endswith("claims.yaml") for name in files)

    # Nothing installed: writing files and installing knowledge are separate
    # steps on purpose, so a mistake here costs a directory rather than a
    # store row.
    assert client.get("/api/packs").json() == []


def test_a_second_scaffold_over_the_same_directory_is_a_conflict(client, tmp_path):
    root = tmp_path / "newpack"
    assert _new(client, root).status_code == 200
    again = _new(client, root)
    # 409 rather than 400: the request was fine, the filesystem was not, and
    # the fix is a different directory rather than a corrected field.
    assert again.status_code == 409
    assert "pack.toml" in again.json()["detail"]


def test_an_identity_table_the_contract_would_reject_is_refused_here(client, tmp_path):
    response = _new(client, tmp_path / "p", identity={})
    assert response.status_code == 400
    # And it says why, in the same words the manifest loader would have used
    # much later: an author who has not chosen identity keys has not yet made
    # the pack's most consequential decision.
    assert "hash to the same id" in response.json()["detail"]


def test_an_unwritable_directory_is_a_message_rather_than_a_traceback(client, tmp_path):
    blocked = tmp_path / "afile"
    blocked.write_text("not a directory", encoding="utf-8")
    response = _new(client, blocked / "under" / "it")
    assert response.status_code == 400
    assert "could not write" in response.json()["detail"]
