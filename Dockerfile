# ---- Builder: install Python dependencies ----
FROM python:3.13-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY scripts/sync_smartva_package_data.py scripts/
COPY vendor/smartva-analyze vendor/smartva-analyze
RUN uv sync --frozen --no-dev && \
    uv run python scripts/sync_smartva_package_data.py

# ---- SmartVA engine: pure-Rust smartva-rs (SMARTVA_ENGINE=rust) ----
# Toolchain stays in this stage; the runtime gets only the binary.
FROM rust:1.90-slim-trixie AS smartva_rs
RUN apt-get update && \
    apt-get install -y --no-install-recommends pkg-config libfontconfig1-dev && \
    rm -rf /var/lib/apt/lists/*
WORKDIR /build
COPY vendor/smartva-analyze/rust/Cargo.toml vendor/smartva-analyze/rust/Cargo.lock ./
COPY vendor/smartva-analyze/rust/src src
RUN CARGO_PROFILE_RELEASE_STRIP=true cargo build --release --locked --bin smartva-rs

# ---- Runtime: minimal image ----
FROM python:3.13-slim AS runtime

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

# libfontconfig1 (with libfreetype6): shared libraries smartva-rs links.
# PostgreSQL 18 client from PGDG: pg_dump refuses a server newer than itself,
# and the split production database runs 18 (it still dumps the bundled 17).
RUN apt-get update && \
    apt-get install -y --no-install-recommends postgresql-common sox libsox-fmt-all libfontconfig1 && \
    /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh -y && \
    apt-get install -y --no-install-recommends postgresql-client-18 && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy venv from builder
COPY --from=builder /app/.venv /app/.venv

# Outside /app, so the dev compose bind mount (.:/app) does not hide it.
COPY --from=smartva_rs /build/target/release/smartva-rs /usr/local/bin/smartva-rs

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
