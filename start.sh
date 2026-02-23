#!/bin/bash
set -e

echo "Starting Agent Marketplace API..."
echo "DATABASE_URL: ${DATABASE_URL:0:30}..."

echo "Running migrations..."
alembic upgrade head

echo "Starting server on port ${PORT:-8000}..."
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
