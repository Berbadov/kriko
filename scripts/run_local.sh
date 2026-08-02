#!/usr/bin/env bash
# Run the API with no Docker and no Postgres — a file-backed SQLite DB seeded
# from the real catalog via the real backend.sync functions.
#
# The normal path is `docker compose -f deploy/docker-compose.yml up` (Postgres
# + API on :8000). Use this when Docker isn't available (e.g. Docker Desktop's
# WSL integration is off) or :8000 is taken.
#
#   ./scripts/run_local.sh            # seed + serve on :8077
#   PORT=9001 ./scripts/run_local.sh  # pick another port
#
# analysis_log is intentionally not created: it uses Postgres ARRAY columns and
# is not on the serve path (backend/api/main.py logs it best-effort and only
# warns if the table is missing).
set -euo pipefail

cd "$(dirname "$0")/.."

PORT="${PORT:-8077}"
DB_PATH="${DB_PATH:-$PWD/local.db}"

export DATABASE_URL="sqlite:///$DB_PATH"
export PYTHONPATH="$PWD"

# Deploy-staleness stamp (B15): the API reports these in /health and /analyze,
# same as the Docker build args. Pre-set env vars win; otherwise read the
# checkout; "unknown" outside one — a missing stamp must never break the run.
export GIT_COMMIT="${GIT_COMMIT:-$(git rev-parse --short HEAD 2>/dev/null || echo unknown)}"
export GIT_BUILD_TIME="${GIT_BUILD_TIME:-$(git log -1 --format=%cI 2>/dev/null || echo unknown)}"

echo "Seeding $DB_PATH from backend/data/ …"
python3 - <<'PY'
from sqlalchemy.orm import Session

from backend.db.session import engine
from backend.db.models import Variant, Claim, ClaimVariant, ClaimSource
from backend.sync import (
    sync_variants, sync_claims, sync_parts, prune_removed_claims,
    _validate_part_yaml_or_raise,
)

for t in (Variant.__table__, Claim.__table__, ClaimVariant.__table__, ClaimSource.__table__):
    t.create(engine, checkfirst=True)

_validate_part_yaml_or_raise()

with Session(engine) as db:
    n_variants = sync_variants(db)
    _, legacy_ids = sync_claims(db)
    n_links, parts_ids = sync_parts(db)
    prune_removed_claims(db, legacy_ids | parts_ids)
    db.commit()
    print(f"  {n_variants} variants, {db.query(Claim).count()} claims, {n_links} claim-variant links")
PY

echo "Serving on http://localhost:$PORT  (health: /health, analyze: POST /analyze)"
exec python3 -m uvicorn backend.api.main:app --port "$PORT"
