FROM astral/uv:python3.13-trixie

RUN apt-get update && \
    apt-get install -y --no-install-recommends postgresql-client ffmpeg && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies first for better caching
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Copy application code
COPY . .

# Install SmartVA-Analyze from vendored source (--no-deps: CLI deps are in pyproject.toml)
RUN uv pip install --python /app/.venv/bin/python --no-deps /app/vendor/smartva-analyze

RUN chmod +x boot.sh scripts/wait-for-celery-beat-db.sh

ENV FLASK_APP=run.py
ENV UV_SYSTEM_PYTHON=1

ENTRYPOINT ["./boot.sh"]
EXPOSE 5000
