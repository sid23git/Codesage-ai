# syntax=docker/dockerfile:1
#
# Production image for the CodeSage API (FastAPI + Uvicorn).
#
# Two stages: `builder` installs the project (and anything that needs a
# compiler to build its wheel) into an isolated virtualenv; `runtime` is a
# clean slim image that only ever receives that finished virtualenv plus
# the application source -- no compiler, no pip cache, no dev/test tooling.
#
# All configuration is via environment variables (see .env.example and
# docker-compose.yml) -- nothing here bakes in a secret, a database
# credential, or an API key.

FROM python:3.12.7-slim AS builder

# build-essential is only needed here, in the discarded builder stage, in
# case a dependency (or a future one) doesn't ship a prebuilt wheel for
# this exact platform and falls back to a source build.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

# Copied separately from the rest of the source so this (slow) install
# layer is only invalidated when dependencies actually change, not on
# every application-code edit.
COPY pyproject.toml ./
COPY app ./app

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir .


FROM python:3.12.7-slim AS runtime

RUN groupadd --system app && useradd --system --gid app --home /app app

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY --chown=app:app app ./app
COPY --chown=app:app alembic ./alembic
COPY --chown=app:app alembic.ini ./alembic.ini
COPY --chown=app:app pyproject.toml ./pyproject.toml

ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER app

# 8000 is only the *default* -- see CMD below. Render (and most PaaS
# platforms) assign their own port at runtime via the PORT env var and
# route health checks and all traffic to it; EXPOSE is purely metadata
# for humans/tooling (e.g. `docker run -P`) and has no effect on which
# port the process actually binds to.
EXPOSE 8000

# Shell form (not exec-form JSON) so $PORT is expanded by the shell at
# container start, not baked in at build time -- `${PORT:-8000}` falls
# back to 8000 when PORT is unset (docker-compose.yml, local `docker run`),
# and honours whatever port Render (or any other platform) actually
# assigns. `exec` replaces the shell with python itself so this stays a
# faithful proxy for what the app will actually be doing.
HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=5 \
    CMD exec python -c "import urllib.request; urllib.request.urlopen('http://localhost:${PORT:-8000}/health', timeout=3)"

# 1 Uvicorn worker process. Phase 0's original production default was 2
# (see backend/.env.example / app/db/session.py's DB_POOL_SIZE comment),
# but the M8 Phase 3 Render deployment runs on a 512 MB free-tier
# instance: 2 worker *processes* each carry a full separate Python heap
# (FastAPI/SQLAlchemy/anthropic/openai/tiktoken, ~100-180MB idle apiece),
# and INGESTION_MAX_CONCURRENT's semaphore is a per-process singleton, so
# 2 workers meant a worst case of 4 simultaneous in-memory ingestions --
# real OOM-kill risk on that instance size. 1 worker keeps this
# comfortably within budget; revisit alongside a larger instance if
# throughput ever actually requires more than one process. Migrations
# are never run here -- see app/main.py's lifespan and the deployment
# docs; apply them explicitly with `alembic upgrade head` as a release
# step.
#
# Shell form (see HEALTHCHECK above for why): Render injects its own
# PORT env var and routes health checks/traffic to it -- a hardcoded
# `--port 8000` here means uvicorn never listens where Render is
# actually checking, which is the exact cause of a deploy that builds
# fine but then times out waiting for a health check that can never
# succeed (reproduced locally: with PORT=10000 injected, the container
# only ever answers on 8000). `exec` makes uvicorn PID 1's replacement
# so SIGTERM (deploy/restart/shutdown) reaches it directly instead of
# being swallowed by an un-exec'd shell -- important for in-flight
# requests and background ingestion tasks to shut down cleanly.
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1
