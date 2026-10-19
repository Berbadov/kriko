"""`python -m kriko_cloud`: run the relay and its sweeps."""

import os

import uvicorn

from .app import create_app

if __name__ == "__main__":
    uvicorn.run(create_app(sweeper=True), host=os.environ.get("HOST", "127.0.0.1"),
                port=int(os.environ.get("PORT", "8080")), log_level="info", proxy_headers=True)
