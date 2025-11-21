#!/bin/bash
# SARASVATI Backend Start Script (Phase 6: Megh)
# ===============================================
# This script is used by Render to start the backend service.

set -e

echo "=========================================="
echo "SARASVATI Backend Starting..."
echo "=========================================="

# Print environment info (without secrets)
echo "PORT: ${PORT:-8000}"
echo "FRONTEND_URL: ${FRONTEND_URL:-not set}"
echo "REDIS_URL: ${REDIS_URL:+configured}"
echo "GROQ_API_KEY: ${GROQ_API_KEY:+configured}"

# Run any migrations or health checks here
# python -m sarasvati.migrations.run  # Future: if we add migrations

# Start Uvicorn on 0.0.0.0 with Render's $PORT
exec uvicorn sarasvati.api.server:app \
    --host 0.0.0.0 \
    --port "${PORT:-8000}" \
    --workers 1 \
    --log-level info
