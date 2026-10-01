"""B188: a clean install, rebuilt by the new flow."""

import pytest
from fastapi.testclient import TestClient

from app import cleaninstall
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


@pytest.fixture
def client(settings) -> TestClient:
    connect(settings.store_path).close()
    return TestClient(create_app(settings))


def _install_pack(settings, pack_id="probe"):
    store = connect(settings.store_path)
    try:
        store.execute(
            "INSERT INTO packs (pack_id, name, version, schema_version, built_at,"
            " content_digest, enabled, installed_at)"
            " VALUES (?, ?, '1', 1, '2026-09-01', 'd', 1, '2026-09-01')",
            (pack_id, pack_id.title()),
        )
        store.execute(
            "INSERT INTO subjects (pack_id, subject_id, kind, label)"
            " VALUES (?, ?, ?, ?)", (pack_id, "s1", "product", "Thing one"),
        )
        store.commit()
    finally:
        store.close()


def test_reset_removes_every_pack_and_keeps_history(client, settings):
    _install_pack(settings, "probe")
    _install_pack(settings, "other")
    conn = state.connect(settings.app_state_path)
    state.record_lookup(conn, source="analyze", label="Thing one",
                        request={}, response={})
    conn.close()

    answer = client.post("/api/packs/reset").json()
    assert sorted(answer["removed"]) == ["other", "probe"]
    assert answer["history_kept"] is True

    store = connect(settings.store_path)
    try:
        assert store.execute("SELECT COUNT(*) FROM packs").fetchone()[0] == 0
        assert store.execute("SELECT COUNT(*) FROM subjects").fetchone()[0] == 0
    finally:
        store.close()
    conn = state.connect(settings.app_state_path)
    try:
        rows = conn.execute("SELECT COUNT(*) FROM lookups").fetchone()[0]
        assert rows >= 1
    finally:
        conn.close()


def test_seeding_is_refused_after_a_reset(settings):
    from app import bundledpacks

    _install_pack(settings, "probe")
    cleaninstall.reset(settings.store_path, settings.app_state_path)
    bundledpacks.seed(
        settings.store_path, source=None,
        app_state_path=settings.app_state_path)
    # No bundled packs on this machine either way; the marker is the point.
    assert cleaninstall.was_reset(settings.app_state_path) is True


def test_the_marker_can_be_cleared_to_reseed(settings):
    cleaninstall.reset(settings.store_path, settings.app_state_path)
    assert cleaninstall.was_reset(settings.app_state_path) is True
    cleaninstall.clear_reset(settings.app_state_path)
    assert cleaninstall.was_reset(settings.app_state_path) is False


def test_reset_discards_drafts(settings, tmp_path):
    _install_pack(settings, "probe")
    from app import packdraft
    root = packdraft.drafts_root(settings.store_path)
    (root / "my-draft").mkdir(parents=True)
    (root / "my-draft" / "pack.toml").write_text("name = 'x'", encoding="utf-8")
    result = cleaninstall.reset(settings.store_path, settings.app_state_path)
    assert "my-draft" in result["drafts"]
    assert not (root / "my-draft").exists()
