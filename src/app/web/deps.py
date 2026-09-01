"""Request-scoped access to the store.

One connection per request, always closed. The store is a local SQLite file in
WAL mode, so concurrent readers are free and a writer does not block them.
"""

from fastapi import Request

from app.web import state
from kriko.store.db import connect


def get_store(request: Request):
    conn = connect(request.app.state.settings.store_path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def get_app_state(request: Request):
    """Request-scoped access to the UI's own SQLite file.

    Separate from `get_store` on purpose: this connection never sees pack data
    and pack data never sees history. See app/web/state.py.
    """
    conn = state.connect(request.app.state.settings.app_state_path)
    try:
        yield conn
    finally:
        conn.close()


def get_jobs(request: Request):
    """The app's single job runner.

    On `app.state` rather than constructed per request: the thread pool and the
    work in it must outlive the request that started it, which is the whole
    point of a job.
    """
    return request.app.state.jobs
