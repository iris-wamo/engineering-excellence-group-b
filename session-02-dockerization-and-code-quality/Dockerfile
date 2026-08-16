# syntax=docker/dockerfile:1
# Base 
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy
    
WORKDIR /app

# Builder
FROM base AS builder

COPY --from=ghcr.io/astral-sh/uv:0.11.32 /uv /uvx /bin/

COPY pyproject.toml uv.lock ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-install-project --no-dev

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
COPY README.md ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev

# Runtime
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

RUN groupadd --system app \
    && useradd --system --gid app app

COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/app ./app
COPY --from=builder /app/alembic ./alembic
COPY --from=builder /app/alembic.ini ./

COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/docs')"

ENTRYPOINT ["/entrypoint.sh"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]