FROM node:22-alpine AS web
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY index.html vite.config.ts tsconfig.json ./
COPY src ./src
COPY public ./public
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY server ./server
COPY migrations ./migrations
COPY scripts ./scripts
COPY alembic.ini ./
COPY --from=web /app/dist ./dist
COPY .env.example README.md ./
RUN groupadd --gid 10001 supportapp && useradd --uid 10001 --gid supportapp --no-create-home supportapp \
    && mkdir -p /app/data/uploads && chown -R supportapp:supportapp /app/data
USER 10001:10001
EXPOSE 8000
CMD ["uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "8000", "--limit-concurrency", "64", "--timeout-keep-alive", "5", "--backlog", "128", "--no-access-log"]
