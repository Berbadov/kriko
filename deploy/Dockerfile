FROM python:3.11-slim

WORKDIR /app

# Install dependencies first (layer caches unless requirements.txt changes)
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY backend/ ./backend/

# Sync YAML catalog to DB on each start (idempotent), then launch the API.
CMD ["sh", "-c", "python -m backend.sync && uvicorn backend.api.main:app --host 0.0.0.0 --port 8000"]
