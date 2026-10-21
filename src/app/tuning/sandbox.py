"""A throwaway app state that carries the reader's settings and nothing else.

A tuning run drives the real chat turn, which writes threads, messages and
agent ledger rows. Those must not land in the reader's history, and the
reader's preferences must still apply: *"set of real cases answered by
preferred llm and search provider"* means the run has to see what Settings
holds. So each run gets its own `app.sqlite` with the settings copied in
(`bench._copy_settings`, the one place that copy is done) and any override the
command line names written on top. The reader's knowledge store is only read.
"""

import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path

from app import prefs
from app.web import state
from app.web.settings import Settings


@contextmanager
def sandbox(reader_app_state: Path, *, store_path: Path | None = None,
            overrides: dict | None = None):
    """`Settings` for a scratch state seeded from the reader's `app.sqlite`.

    `overrides` are settings keys written over the copy (the agent pick, the
    search provider). The directory is removed on exit, even on an error.
    """
    from app import bench

    root = Path(tempfile.mkdtemp(prefix="kriko-tuning-"))
    try:
        settings = Settings(
            store_path=store_path or (Path(reader_app_state).parent / "knowledge.sqlite"),
            app_state_path=root / "app.sqlite",
            analysis_log_path=root / "analyses.jsonl")
        state.connect(settings.app_state_path).close()
        bench._copy_settings(reader_app_state, settings.app_state_path)
        if overrides:
            conn = state.connect(settings.app_state_path)
            try:
                prefs.write(conn, {key: str(value) for key, value in overrides.items()})
            finally:
                conn.close()
        yield settings
    finally:
        shutil.rmtree(root, ignore_errors=True)
