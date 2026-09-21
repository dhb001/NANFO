#!/usr/bin/env bash
set -euo pipefail

# Stops NANFO local development dependencies started via docker compose.
# Use --purge to also remove named volumes.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
BACKEND_DIR="${ROOT_DIR}/backend"

if ! command -v docker >/dev/null 2>&1; then
  echo "[error] docker not found."
  exit 1
fi

cd "${BACKEND_DIR}"

if [[ "${1:-}" == "--purge" ]]; then
  echo "[step] Stopping containers and removing volumes..."
  docker compose down -v
else
  echo "[step] Stopping containers..."
  docker compose down
fi

echo "[done] NANFO services stopped."
