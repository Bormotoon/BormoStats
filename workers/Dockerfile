FROM python:3.15.0-slim-trixie@sha256:f5b92f2a669a4c347044f29367f31983280b648250ca94dea66f98c53bc87e58

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
