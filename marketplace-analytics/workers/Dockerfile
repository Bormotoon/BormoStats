FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt requirements-dev.txt pyproject.toml ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY . .

WORKDIR /app/workers
ENV PYTHONPATH=/app/workers:/app

CMD ["celery", "-A", "app.celery_app:celery_app", "worker", "--loglevel=INFO", "--concurrency=4"]
