# Turnstile demo service — one free-tier container (PRD 01).
#
# Runtime needs ONLY: the service package + the pure engine (schema, pricing,
# verdict, detectors, replay, ingest), the committed dashboard (HTML + sample
# JSON, served statically from the same origin), pricing/rates.yaml, and
# fixtures/sample/baselines.json. No models, no keys, no GPU.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv
WORKDIR /app

# Workspace metadata first (layer cache): dependency resolution reruns only
# when a manifest or the lockfile changes.
COPY pyproject.toml uv.lock ./
COPY packages/agent/pyproject.toml packages/agent/
COPY packages/corpus/pyproject.toml packages/corpus/
COPY packages/dashboard/pyproject.toml packages/dashboard/
COPY packages/detectors/pyproject.toml packages/detectors/
COPY packages/experiments/pyproject.toml packages/experiments/
COPY packages/ingest/pyproject.toml packages/ingest/
COPY packages/live/pyproject.toml packages/live/
COPY packages/pricing/pyproject.toml packages/pricing/
COPY packages/quality/pyproject.toml packages/quality/
COPY packages/replay/pyproject.toml packages/replay/
COPY packages/schema/pyproject.toml packages/schema/
COPY packages/service/pyproject.toml packages/service/
COPY packages/verdict/pyproject.toml packages/verdict/

# Sources + the committed data the service serves and reads.
COPY packages/ packages/
COPY pricing/ pricing/
COPY fixtures/sample/baselines.json fixtures/sample/baselines.json

# Commit SHA for GET /health. Default EMPTY, not "unknown": a literal "unknown"
# is truthy and short-circuits commit_sha() before it can read Render's runtime
# RENDER_GIT_COMMIT. Empty lets the runtime env win; and if Render passes
# RENDER_GIT_COMMIT as a build arg, we bake it at build time too.
ARG RENDER_GIT_COMMIT=
ARG TURNSTILE_COMMIT=
ENV TURNSTILE_COMMIT=${TURNSTILE_COMMIT:-${RENDER_GIT_COMMIT}}

RUN uv sync --frozen --no-dev --package turnstile-service
ENV PATH="/app/.venv/bin:$PATH"

# Day-5 Part E (additive OCI labels only -- no base-image change, no layer
# reshuffle; placed AFTER the dependency layer so the layer-cache comment
# above stays valid: label changes never invalidate the uv-sync layer).
ARG VERSION=0.1.0-dev
ARG GITHUB_SHA=
LABEL org.opencontainers.image.title="turnstile-demo" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${GITHUB_SHA}"

EXPOSE 8000

# $PORT is set by the host (Render); default keeps `docker run -p` working.
# --limit-concurrency bounds simultaneous engine runs on a small container.
CMD ["sh", "-c", "uvicorn turnstile_service.app:app --host 0.0.0.0 --port ${PORT:-8000} --limit-concurrency 20"]
