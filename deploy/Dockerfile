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
COPY knowledge/domains.py ./knowledge/domains.py
COPY knowledge/stoplists.py ./knowledge/stoplists.py
COPY knowledge/parts/__init__.py ./knowledge/parts/__init__.py
COPY knowledge/parts/validate_part_yaml.py ./knowledge/parts/validate_part_yaml.py

# Sync YAML catalog to DB on each start (idempotent), then launch the API.
CMD ["sh", "-c", "python -m backend.sync && uvicorn backend.api.main:app --host 0.0.0.0 --port 8000"]
