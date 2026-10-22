# Where smartva-rs comes from: "release" (default) downloads the pinned GitHub
# release asset of drguptavivek/SmartVA-Analyze-rust and verifies its SHA-256,
# so hosts never compile Rust; "source" builds vendor/smartva-analyze/rust with
# cargo (developers only). The pins are build args from x-smartva-rs in
# docker-compose.yml.
ARG SMARTVA_RS_SOURCE=release

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
# An unset or wrong pin fails the build; verification is never skipped.
FROM debian:bookworm-slim AS smartva_rs_release
ARG TARGETARCH
ARG SMARTVA_RS_VERSION
ARG SMARTVA_RS_SHA256_ARM64
ARG SMARTVA_RS_SHA256_AMD64
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*
RUN set -eu; \
    case "$TARGETARCH" in \
      arm64) sha="$SMARTVA_RS_SHA256_ARM64" ;; \
      amd64) sha="$SMARTVA_RS_SHA256_AMD64" ;; \
      *) sha="" ;; \
    esac; \
    if [ -z "$SMARTVA_RS_VERSION" ] || [ -z "$sha" ]; then \
      echo "ERROR: no smartva-rs pin for linux/$TARGETARCH: pass SMARTVA_RS_VERSION and SMARTVA_RS_SHA256_* (x-smartva-rs in docker-compose.yml) or build with SMARTVA_RS_SOURCE=source" >&2; \
      exit 1; \
    fi; \
    case "$TARGETARCH" in amd64) arch=x86_64 ;; *) arch="$TARGETARCH" ;; esac; \
    asset="smartva-rs-linux-${arch}"; \
    curl -fsSL --retry 3 -o "/tmp/$asset.tar.gz" \
      "https://github.com/drguptavivek/SmartVA-Analyze-rust/releases/download/${SMARTVA_RS_VERSION}/$asset.tar.gz"; \
    echo "$sha  /tmp/$asset.tar.gz" | sha256sum -c -; \
    tar -xzf "/tmp/$asset.tar.gz" -C /tmp "$asset/smartva-rs"; \
    install -m 0755 "/tmp/$asset/smartva-rs" /usr/local/bin/smartva-rs; \
    rm -rf "/tmp/$asset" "/tmp/$asset.tar.gz"

# Developer option (RUST_BINARIES=source): compile here. Never on a host.
FROM rust:1.90-slim-trixie AS smartva_rs_source
RUN apt-get update && \
    apt-get install -y --no-install-recommends pkg-config libfontconfig1-dev && \
    rm -rf /var/lib/apt/lists/*
WORKDIR /build
COPY vendor/smartva-analyze/rust/Cargo.toml vendor/smartva-analyze/rust/Cargo.lock ./
COPY vendor/smartva-analyze/rust/src src
RUN CARGO_PROFILE_RELEASE_STRIP=true cargo build --release --locked --bin smartva-rs && \
    cp target/release/smartva-rs /usr/local/bin/smartva-rs

FROM smartva_rs_${SMARTVA_RS_SOURCE} AS smartva_rs

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
COPY --from=smartva_rs /usr/local/bin/smartva-rs /usr/local/bin/smartva-rs

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
