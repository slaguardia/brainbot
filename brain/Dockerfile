# Brain service image. A Postgres + pgvector document store (asyncpg
# in-process; no graph DB) serving ingest + recall/profile/map over HTTP +
# MCP. Runs on the brainnet alongside postgres.
FROM python:3.11-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install deps first (cached layer), then the package.
COPY pyproject.toml ./
COPY brain ./brain
RUN pip install --no-cache-dir .

EXPOSE 8100

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8100/health || exit 1

CMD ["uvicorn", "brain.api:app", "--host", "0.0.0.0", "--port", "8100"]
