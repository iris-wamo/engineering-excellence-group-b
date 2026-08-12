FROM python:3.12-slim

WORKDIR /app

RUN pip install uv

# Copy dependencies first so this layer is cached and only
# re-runs when dependencies actually change (not on every source edit).
COPY pyproject.toml uv.lock ./

# Install only the locked dependencies, without installing the project itself yet.
RUN uv sync --frozen --no-install-project

COPY . .

# Now install the project itself against the already cached dependencies.
RUN uv sync --frozen

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
