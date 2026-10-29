# Stage 1: Build frontend
FROM node:26-alpine@sha256:6f08a523443ddedf52941874c203475b0ad503e859ad70cb26ab8be9a517dbd5 AS frontend-builder

WORKDIR /build

COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

# Stage 2: Python runtime
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

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*", "--timeout-graceful-shutdown", "20"]
