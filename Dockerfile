FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
RUN pip install --no-cache-dir uv
COPY pyproject.toml uv.lock README.md ./
COPY alembic.ini ./
COPY alembic ./alembic
COPY src ./src
COPY data ./data
COPY config ./config
COPY scripts ./scripts
COPY docker-entrypoint.sh ./docker-entrypoint.sh
RUN uv sync --frozen --no-dev
RUN chmod +x ./docker-entrypoint.sh

EXPOSE 21235

ENTRYPOINT ["./docker-entrypoint.sh"]
