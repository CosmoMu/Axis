FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN addgroup --system axis && adduser --system --ingroup axis axis

COPY pyproject.toml README.md ./
COPY app ./app
COPY config ./config
COPY migrations ./migrations
COPY scripts ./scripts
COPY alembic.ini ./

RUN pip install --no-cache-dir . && \
    mkdir -p /app/var/attachments && \
    chown -R axis:axis /app

USER axis

CMD ["python", "scripts/run_bot.py"]
