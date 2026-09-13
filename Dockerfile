FROM python:3.12-slim AS base

# Bytecode caching is pointless in a container that is rebuilt, and unbuffered
# output is what makes docker logs show anything before a crash.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# psycopg2-binary ships wheels, so no build toolchain is needed. curl is here
# for the container healthcheck below.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Dependencies first: this layer is cached until requirements.txt changes,
# so an application edit does not reinstall the world.
COPY requirements.txt requirements-prod.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-prod.txt

COPY . .

# Run as a non-root user: a container breakout starts from whatever the
# process already had, and root in the container is root on the host kernel.
RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

# Migrations run before the server so a new column is never served by a
# process whose database lacks it.
CMD ["sh", "-c", "alembic upgrade head && exec gunicorn main:app \
    --worker-class uvicorn_worker.UvicornWorker \
    --workers ${WEB_CONCURRENCY:-2} \
    --bind 0.0.0.0:${PORT:-8000} \
    --access-logfile - --error-logfile -"]
