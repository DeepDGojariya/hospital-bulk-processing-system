# Stage 1: build the React front end.
FROM node:24-slim AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend ./
RUN npm run build -- --outDir dist

# Stage 2: the Python service, which also serves the built front end.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.14 /uv /bin/uv

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Dependencies first, so this layer is cached until the lockfile changes.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY app ./app
COPY --from=frontend /frontend/dist ./app/static

RUN useradd --create-home appuser
USER appuser

EXPOSE 8000

# A single worker on purpose: batch state lives in this process's memory.
# exec makes uvicorn PID 1, so it receives the stop signal directly.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
