#!/usr/bin/env bash
set -euo pipefail

# Starts NANFO local development dependencies (Postgres, Neo4j, Redis)
# using backend/docker-compose.yml.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
BACKEND_DIR="${ROOT_DIR}/backend"

if ! command -v docker >/dev/null 2>&1; then
  echo "[error] docker not found. Install dependencies first: ./scripts/install-deps-arch.sh"
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "[info] Docker daemon is not running. Attempting to start it..."
  if command -v systemctl >/dev/null 2>&1; then
    sudo systemctl start docker
  fi
fi

if ! docker info >/dev/null 2>&1; then
  echo "[error] Docker daemon is still not available. Start it manually and retry."
  exit 1
fi

cd "${BACKEND_DIR}"

if [[ ! -f .env ]]; then
  echo "[warn] backend/.env not found. Creating from .env.example"
  cp .env.example .env
  echo "[warn] Update backend/.env secrets before exposing services beyond localhost."
fi

echo "[step] Starting infrastructure containers..."
docker compose up -d

echo "[step] Waiting for container health checks..."
# Print quick status; healthy checks are defined in docker-compose.yml
sleep 2
docker compose ps

echo

echo "[done] NANFO services started."
echo "[info] PostgreSQL: localhost:5432"
echo "[info] Neo4j HTTP: http://localhost:7474  | Bolt: localhost:7687"
echo "[info] Redis: localhost:6379"
echo

echo "[next] Optional backend app run:"
echo "       cd backend && poetry install && poetry run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000"
