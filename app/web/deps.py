"""Request-scoped access to the store.

One connection per request, always closed. The store is a local SQLite file in
WAL mode, so concurrent readers are free and a writer does not block them.
"""

from fastapi import Request

from kriko.store.db import connect


def get_store(request: Request):
    conn = connect(request.app.state.settings.store_path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
