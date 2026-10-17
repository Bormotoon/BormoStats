FROM python:3.14.8-slim-trixie@sha256:a2b82f3c48559aa0a8446d9af49826b6e2b2016f4cd2afabfe6013ec53729170

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --home-dir /home/app --create-home app \
    && mkdir -p /exports && chown app:app /exports

WORKDIR /app

COPY requirements.txt pyproject.toml ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir --require-hashes -r requirements.txt

COPY --chown=app:app . .

WORKDIR /app/workers
ENV PYTHONPATH=/app/workers:/app \
    HOME=/tmp \
    XDG_CACHE_HOME=/tmp/.cache

USER app

EXPOSE 9101 9102

CMD ["celery", "-A", "app.celery_app:celery_app", "worker", "--loglevel=INFO", "--concurrency=4", "--queues=etl,wb,ozon,competitor,automation,marketplace_actions,webhooks"]
