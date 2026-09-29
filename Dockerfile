FROM python:3.12-slim AS base

COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /usr/local/bin/uv

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"
WORKDIR /srv

COPY pyproject.toml uv.lock ./


# Dev (сервис tests): prod-зависимости + группа dev (pytest)
FROM base AS dev
RUN uv sync --frozen --no-cache
COPY . .


# Prod: только зависимости из [project.dependencies]
FROM base AS prod
RUN uv sync --frozen --no-cache --no-dev
COPY . .

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
