# ---- Builder: install Python dependencies ----
FROM python:3.13-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY vendor/smartva-analyze vendor/smartva-analyze
RUN uv sync --frozen --no-dev

# ---- Runtime: minimal image ----
FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

RUN apt-get update && \
    apt-get install -y --no-install-recommends postgresql-client sox libsox-fmt-all && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy venv from builder
COPY --from=builder /app/.venv /app/.venv

# Copy application code
COPY . .

RUN chmod +x boot.sh scripts/wait-for-celery-beat-db.sh

ENV FLASK_APP=run.py
ENV PATH="/app/.venv/bin:${PATH}"

ENTRYPOINT ["./boot.sh"]
EXPOSE 5000
