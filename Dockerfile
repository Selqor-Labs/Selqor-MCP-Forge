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

# Install Python dependencies
COPY pyproject.toml ./
RUN pip install --no-cache-dir .

# Copy source code
COPY src/ ./src/

# Copy built React frontend
COPY --from=frontend /app/frontend/dist ./src/dashboard/frontend/dist

# Copy logo assets
COPY selqorLogos/ ./selqorLogos/

# Non-root user for security
RUN useradd --create-home --shell /bin/bash selqor
USER selqor

EXPOSE 8787

ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "selqor_forge", "dashboard", "--port", "8787", "--host", "0.0.0.0"]
