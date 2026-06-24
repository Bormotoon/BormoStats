# Stage 1: Build frontend
FROM node:22-alpine@sha256:16e22a550f3863206a3f701448c45f7912c6896a62de43add43bb9c86130c3e2 AS frontend-builder

WORKDIR /build

COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

# Stage 2: Python runtime
FROM python:3.14.3-slim-trixie@sha256:6a27522252aef8432841f224d9baaa6e9fce07b07584154fa0b9a96603af7456

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --home-dir /home/app --create-home app

WORKDIR /app

COPY requirements.txt pyproject.toml ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY --chown=app:app common/ ./common/
COPY --chown=app:app backend/ ./backend/
COPY --chown=app:app workers/ ./workers/
COPY --chown=app:app collectors/ ./collectors/
COPY --chown=app:app warehouse/ ./warehouse/
COPY --chown=app:app automation/ ./automation/
# scripts/ excluded via .dockerignore (operational tools only)

# Copy built frontend from stage 1
COPY --from=frontend-builder --chown=app:app /build/dist ./backend/app/ui/dist

WORKDIR /app/backend
ENV PYTHONPATH=/app/backend:/app \
    HOME=/tmp \
    XDG_CACHE_HOME=/tmp/.cache

USER app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
