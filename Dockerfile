FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl build-essential && \
    rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

COPY backend/pyproject.toml backend/uv.lock* ./backend/
WORKDIR /app/backend
RUN uv venv .venv && \
    . .venv/bin/activate && \
    uv pip install -e . && \
    uv pip install surrealdb

COPY backend/ ./
COPY locales/ /app/locales/

ENV PATH="/app/backend/.venv/bin:$PATH"
EXPOSE 5001

CMD ["python", "run.py"]
