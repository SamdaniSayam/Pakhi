# ── Stage 1: builder ──────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /app

# Install system deps for building wheels
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc g++ gfortran libopenblas-dev && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md LICENSE ./
COPY pakhi/ pakhi/

# Build wheel
RUN pip install --no-cache-dir build && \
    python -m build --wheel --outdir /wheels

# ── Stage 2: runtime ─────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

LABEL maintainer="TripleS Studio"
LABEL description="Pakhi — Weather intelligence for quantitative trading"
LABEL org.opencontainers.image.source="https://github.com/SamdaniSayam/pakhi"

# Runtime system deps
RUN apt-get update && \
    apt-get install -y --no-install-recommends libopenblas0 libgomp1 curl && \
    rm -rf /var/lib/apt/lists/* && \
    groupadd -r pakhi && useradd -r -g pakhi -d /home/pakhi -s /sbin/nologin pakhi

WORKDIR /home/pakhi

# Install pakhi from built wheel (no build tools in runtime). Postgres and API extras are
# required here so both CLI workers and WS-3 uvicorn API can run.
COPY --from=builder /wheels/*.whl /tmp/wheels/
RUN pip install --no-cache-dir "$(ls /tmp/wheels/*.whl)[all,api,postgres]" && \
    rm -rf /tmp/wheels

# Pre-fetch Open-Meteo timezone data so first run is fast
RUN python -c "import zoneinfo; zoneinfo.ZoneInfo('UTC')" 2>/dev/null || true

# Copy example scripts for quick start
COPY examples/ /home/pakhi/examples/
COPY data/README.md /home/pakhi/data/README.md

# Health check — verify CLI or API endpoint is functional
HEALTHCHECK --interval=60s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/v1/health || pakhi --version

# Run as non-root
USER pakhi
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PAKHI_HOME=/home/pakhi

ENTRYPOINT ["pakhi"]
CMD ["--help"]
