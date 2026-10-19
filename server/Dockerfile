# Build from the repository root:  docker build -f server/Dockerfile -t kriko-relay .
FROM python:3.13-slim
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY server ./server
RUN pip install --no-cache-dir . \
 && useradd --system --no-create-home relay \
 && mkdir /data && chown relay /data
ENV PYTHONPATH=/app/server KRIKO_CLOUD_DB=/data/relay.sqlite HOST=0.0.0.0 PORT=8080
USER relay
EXPOSE 8080
VOLUME /data
CMD ["python", "-m", "kriko_cloud"]
