# Public demo image for Render (render.yaml): the FastAPI service + frozen model, serving the built React dashboard
# from the same origin. It contains NO NBA data: on first start it builds the SYNTHETIC demo league into an empty
# database (python -m nba_lineups.demo.seed). See docs/deployment.md.

# ---- 1. dashboard: static build (demo mode, API on the same origin)
FROM node:22.12-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
ENV VITE_API_BASE_URL=/api/v1 \
    VITE_DEMO_MODE=1
RUN npx vite build

# ---- 2. API + model
FROM python:3.12.3-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install -e . && useradd --create-home --uid 10001 app
# the frozen model and the evaluation reports the API serves (no data)
COPY models/final ./models/final
COPY reports/phase6/findings_dev.json ./reports/phase6/findings_dev.json
COPY reports/phase6/holdout/holdout_findings.json ./reports/phase6/holdout/holdout_findings.json
COPY --from=web /web/dist ./web/dist
ENV NBA_DEMO_MODE=1 \
    NBA_API_STATIC_DIR=/app/web/dist \
    NBA_API_MODEL_DIR=/app/models/final \
    NBA_API_REPORTS_DIR=/app/reports/phase6 \
    NBA_API_REQUIRE_GIT_FREEZE=0 \
    NBA_API_POOL_MAX=4 \
    PORT=10000
USER app
EXPOSE 10000
# Serve at once; seed in the background. /health answers 503 ("seeding") until the synthetic league is loaded, so
# Render only routes traffic to a ready instance. A failed seed keeps /health at 503 and Render restarts the service.
CMD ["sh", "-c", "python -m nba_lineups.demo.seed & exec uvicorn nba_lineups.api.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
