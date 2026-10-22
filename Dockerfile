# Where smartva-rs comes from: "release" (default) downloads the pinned GitHub
# release asset of drguptavivek/SmartVA-Analyze-rust and verifies its SHA-256,
# so hosts never compile Rust; "source" builds vendor/smartva-analyze/rust with
# cargo (developers only). The pins are build args from x-release-pins in
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
FROM python:3.13-slim AS smartva_rs_release
ARG TARGETARCH
ARG SMARTVA_RS_VERSION
ARG SMARTVA_RS_SHA256_ARM64
ARG SMARTVA_RS_SHA256_AMD64
# Python (already the base) downloads and verifies: no apt-get, no curl.
RUN TARGETARCH="$TARGETARCH" SMARTVA_RS_VERSION="$SMARTVA_RS_VERSION" \
    SHA_ARM64="$SMARTVA_RS_SHA256_ARM64" SHA_AMD64="$SMARTVA_RS_SHA256_AMD64" \
    python - <<'PY'
import hashlib, os, shutil, sys, tarfile, urllib.request

arch = os.environ["TARGETARCH"]
version = os.environ.get("SMARTVA_RS_VERSION", "")
sha = {"arm64": os.environ.get("SHA_ARM64", ""), "amd64": os.environ.get("SHA_AMD64", "")}.get(arch, "")
if not version or not sha:
    sys.exit(f"ERROR: no smartva-rs pin for linux/{arch}: pass SMARTVA_RS_VERSION and "
             "SMARTVA_RS_SHA256_* (x-release-pins in docker-compose.yml) or build with "
             "SMARTVA_RS_SOURCE=source")
asset = "smartva-rs-linux-" + ("x86_64" if arch == "amd64" else arch)
url = f"https://github.com/drguptavivek/SmartVA-Analyze-rust/releases/download/{version}/{asset}.tar.gz"
path = f"/tmp/{asset}.tar.gz"
for attempt in range(3):
    try:
        urllib.request.urlretrieve(url, path)
        break
    except OSError:
        if attempt == 2:
            raise
digest = hashlib.sha256(open(path, "rb").read()).hexdigest()
if digest != sha:
    sys.exit(f"ERROR: {asset}.tar.gz SHA-256 {digest} does not match the pin {sha}")
print(f"{asset}.tar.gz: OK")
with tarfile.open(path) as tar:
    member = tar.getmember(f"{asset}/smartva-rs")
    with tar.extractfile(member) as src, open("/usr/local/bin/smartva-rs", "wb") as dst:
        shutil.copyfileobj(src, dst)
os.chmod("/usr/local/bin/smartva-rs", 0o755)
os.remove(path)
PY

# Developer option (SMARTVA_RS_SOURCE=source): compile here. Never on a host.
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

# ---- Expo web export: pinned DigitVA release, never built on the host ----
FROM python:3.13-slim AS expo_web
ARG EXPO_WEB_TAG
ARG EXPO_WEB_SHA256
RUN EXPO_WEB_TAG="$EXPO_WEB_TAG" EXPO_WEB_SHA256="$EXPO_WEB_SHA256" python - <<'PY'
import hashlib, os, sys, tarfile, urllib.request

tag = os.environ.get("EXPO_WEB_TAG", "")
sha = os.environ.get("EXPO_WEB_SHA256", "")
if not tag or not sha:
    sys.exit("ERROR: no Expo web export pin: pass EXPO_WEB_TAG and EXPO_WEB_SHA256 "
             "(x-release-pins in docker-compose.yml)")
url = f"https://github.com/drguptavivek/DigitVA/releases/download/{tag}/{tag}.tar.gz"
path = f"/tmp/{tag}.tar.gz"
for attempt in range(3):
    try:
        urllib.request.urlretrieve(url, path)
        break
    except OSError:
        if attempt == 2:
            raise
digest = hashlib.sha256(open(path, "rb").read()).hexdigest()
if digest != sha:
    sys.exit(f"ERROR: {tag}.tar.gz SHA-256 {digest} does not match the pin {sha}")
print(f"{tag}.tar.gz: OK")
target = "/opt/digitva/expo-client"
os.makedirs(target)
with tarfile.open(path) as tar:
    tar.extractall(target, filter="data")
if not os.path.isfile(os.path.join(target, "index.html")):
    sys.exit(f"ERROR: {tag}.tar.gz has no index.html")
os.remove(path)
PY

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
# The Expo web export, also outside /app; EXPO_CLIENT_DIST points here.
COPY --from=expo_web /opt/digitva/expo-client /opt/digitva/expo-client

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
