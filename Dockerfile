# Copyright (c) Selqor Labs.
# Multi-stage build: Node (frontend) + Python (backend)

# ---- Stage 1: Build React frontend ----
FROM node:20-alpine AS frontend
WORKDIR /app/frontend
COPY src/dashboard/frontend/package*.json ./
RUN npm ci --production=false
COPY src/dashboard/frontend/ ./
RUN npm run build

# ---- Stage 2: Python runtime ----
FROM python:3.13-slim AS runtime

# System deps for psycopg (PostgreSQL driver)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy source code
COPY src/ ./src/
COPY README.md LICENSE pyproject.toml ./

# Copy built React frontend
COPY --from=frontend /app/frontend/dist ./src/dashboard/frontend/dist

# Copy logo assets
COPY selqorLogos/ ./selqorLogos/

# Install dependencies after the source tree is available so the runtime can
# import the copied application tree and serve bundled assets correctly.
RUN pip install --no-cache-dir .

# Non-root user for security. Give the runtime a writable dashboard state dir
# so the local demo stack can start without requiring elevated permissions.
RUN useradd --create-home --shell /bin/bash selqor \
    && mkdir -p /home/selqor/dashboard \
    && chown -R selqor:selqor /home/selqor

USER selqor

EXPOSE 8787

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/src

CMD ["python", "-m", "selqor_forge", "dashboard", "--state", "/home/selqor/dashboard", "--port", "8787", "--host", "0.0.0.0", "--i-know-what-im-doing"]
