FROM node:22-alpine AS web
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY index.html vite.config.ts tsconfig.json ./
COPY src ./src
COPY public ./public
RUN npm run build

# Debian trixie supplies pg_dump 17, compatible with the documented PG16 server.
FROM python:3.12-slim-trixie
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends age postgresql-client gosu \
    && rm -rf /var/lib/apt/lists/*
COPY requirements*.txt ./
RUN pip install --no-cache-dir -r requirements-ops.txt
COPY server ./server
COPY migrations ./migrations
COPY scripts ./scripts
COPY deploy ./deploy
COPY alembic.ini .env.example README.md OPERATIONS.md ./
COPY --from=web /app/dist ./dist
RUN groupadd --gid 10001 supportapp && useradd --uid 10001 --gid supportapp --no-create-home supportapp \
    && mkdir -p /app/data && chown supportapp:supportapp /app/data
ENTRYPOINT ["/bin/sh", "/app/deploy/railway/entrypoint.sh"]
CMD ["python", "scripts/railway_runtime.py"]
