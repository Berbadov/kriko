import os
from pathlib import Path

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg://postgres:postgres@localhost:5432/kriko",
)

# Full-payload analysis log (JSONL, append-only). Path is repo-root-relative
# by default so it resolves the same way on a host checkout (cwd = repo root)
# and inside the API container (WORKDIR /app, backend/ copied to /app/backend)
# — see deploy/docker-compose.yml's `../logs:/app/logs` mount.
REPO_ROOT = Path(__file__).parent.parent
ANALYSES_LOG_PATH = Path(os.environ.get(
    "ANALYSES_LOG_PATH",
    str(REPO_ROOT / "logs" / "analyses.jsonl"),
))

# Deploy-staleness stamp (backlog B15): which commit this artifact was built
# from, and when. Set at image-build time (deploy/Dockerfile ARGs → ENV, wired
# in deploy/docker-compose.yml) or exported by scripts/run_local.sh. Falls back
# to "unknown" when absent — never crash on a missing stamp; "unknown" is
# itself the tell that the deploy was never stamped.
GIT_COMMIT = os.environ.get("GIT_COMMIT") or "unknown"
GIT_BUILD_TIME = os.environ.get("GIT_BUILD_TIME") or "unknown"

# GET /debug/analyses is off (404) unless explicitly enabled — it reads back
# full request/response payloads, so it must not be exposed by default on an
# internet-facing deployment. The CLI (ops/reports/analyses.py) reads the
# same file directly and needs no such gate.
ENABLE_DEBUG_ENDPOINT = os.environ.get("ENABLE_DEBUG_ENDPOINT", "").lower() in ("1", "true", "yes")

# CORS: allow the Chrome extension origin. The extension ID must be set in env
# for production; localhost is allowed for local dev.
ALLOWED_ORIGINS = [
    o.strip()
    for o in os.environ.get(
        "ALLOWED_ORIGINS",
        "chrome-extension://localhost,http://localhost:3000,http://127.0.0.1:3000",
    ).split(",")
    if o.strip()
]

# Disclaimer text — always appended to every response.
# HUMAN DECISION #4: final legal wording should be reviewed by counsel.
STANDARD_DISCLAIMER = (
    "Known reliability risks from public sources for this specific variant. "
    "Absence of a listed issue does not mean the car is fault-free — "
    "always get an independent pre-purchase inspection before buying."
)
