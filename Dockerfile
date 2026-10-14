# ---- Builder: install Python dependencies ----
FROM python:3.13-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY scripts/sync_smartva_package_data.py scripts/
COPY vendor/smartva-analyze vendor/smartva-analyze
RUN uv sync --frozen --no-dev && \
    uv run python scripts/sync_smartva_package_data.py

# ---- Runtime: minimal image ----
FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

# PostgreSQL 18 client from PGDG: pg_dump refuses a server newer than itself,
# and the split production database runs 18 (it still dumps the bundled 17).
RUN apt-get update && \
    apt-get install -y --no-install-recommends postgresql-common sox libsox-fmt-all && \
    /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh -y && \
    apt-get install -y --no-install-recommends postgresql-client-18 && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy venv from builder
COPY --from=builder /app/.venv /app/.venv

# Copy application code
COPY . .

RUN chmod +x boot.sh boot-public-doris.sh scripts/wait-for-celery-beat-db.sh

ENV FLASK_APP=run.py
ENV PATH="/app/.venv/bin:${PATH}"

# SmartVA charts are debug-only (SMARTVA_CHARTS); when on, matplotlib's font
# cache is already built into the image, never rebuilt per run.
ENV MPLCONFIGDIR=/opt/matplotlib
RUN mkdir -p /opt/matplotlib && python -c "import matplotlib.font_manager"

ENTRYPOINT ["./boot.sh"]
EXPOSE 5000
