FROM python:3.12

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev

ENV PATH="/app/.venv/bin:$PATH"

COPY cinema ./cinema
COPY migrations ./migrations
