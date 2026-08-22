FROM python:3.11-slim

WORKDIR /app

# Install dependencies first (layer caches unless requirements.txt changes)
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY backend/ ./backend/

# sync.py's CI validation gate (docs/design_flaws.md Flaw 1) imports
# knowledge.parts.validate_part_yaml. Bring in only that slice, not the full
# knowledge plane (mistralai/langchain/exa-py stay off this image — see
# knowledge/requirements.txt) — these files only need stdlib + pyyaml, already
# installed above.
COPY knowledge/__init__.py ./knowledge/__init__.py
COPY knowledge/yamlutil.py ./knowledge/yamlutil.py
# Title similarity — backend/core/resolver.py and backend/sync.py both import
# it, and knowledge/dedup.py shares it. Pure stdlib.
COPY knowledge/title_sim.py ./knowledge/title_sim.py
COPY knowledge/consequence_tier.py ./knowledge/consequence_tier.py
COPY knowledge/domains.py ./knowledge/domains.py
COPY knowledge/stoplists.py ./knowledge/stoplists.py
COPY knowledge/parts/__init__.py ./knowledge/parts/__init__.py
COPY knowledge/parts/validate_part_yaml.py ./knowledge/parts/validate_part_yaml.py
# Serving payload v2 / source quality: sync.py resolves each claim's
# component (registry lookup + subsystem/detection) and best source tier
# against these registries. Still stdlib + pyyaml only.
COPY knowledge/sources/__init__.py ./knowledge/sources/__init__.py
COPY knowledge/sources/tiers.py ./knowledge/sources/tiers.py
COPY knowledge/catalog/__init__.py ./knowledge/catalog/__init__.py
COPY knowledge/catalog/registry.py ./knowledge/catalog/registry.py
COPY knowledge/catalog/emissions.py ./knowledge/catalog/emissions.py
COPY knowledge/catalog/components.yaml ./knowledge/catalog/components.yaml
COPY knowledge/catalog/source_tiers.yaml ./knowledge/catalog/source_tiers.yaml

# Deploy-staleness stamp (backlog B15): the app reports these via /health and
# every /analyze response, so a stale image is visible instead of silently
# serving pre-fix behaviour. Values come from build args (wired in
# deploy/docker-compose.yml); a build that passes neither stamps "unknown" —
# which is itself the tell that the image was never stamped.
ARG GIT_COMMIT=unknown
ARG GIT_BUILD_TIME=unknown
ENV GIT_COMMIT=$GIT_COMMIT \
    GIT_BUILD_TIME=$GIT_BUILD_TIME

# Sync YAML catalog to DB on each start (idempotent), then launch the API.
CMD ["sh", "-c", "python -m backend.sync && uvicorn backend.api.main:app --host 0.0.0.0 --port 8000"]
