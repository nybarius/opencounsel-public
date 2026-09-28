FROM ghcr.io/astral-sh/uv:0.11.29-python3.12-trixie-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy
WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.12-slim-trixie

ENV DEBIAN_FRONTEND=noninteractive \
    HOME=/tmp/opencounsel-home \
    PATH=/app/.venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    XDG_CACHE_HOME=/tmp/opencounsel-cache

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        fontconfig \
        fonts-liberation2 \
        libreoffice-writer \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin opencounsel \
    && mkdir -p /home/opencounsel/data \
    && chown -R opencounsel:opencounsel /home/opencounsel

WORKDIR /app
COPY --from=builder /app/.venv /app/.venv

USER 10001:10001
EXPOSE 8765
VOLUME ["/home/opencounsel/data"]

HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=5 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/healthz', timeout=2)"]

CMD ["opencounsel", "ui", "--host", "0.0.0.0", "--port", "8765", "--work-root", "/home/opencounsel/data"]
