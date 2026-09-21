#!/usr/bin/env bash
set -euo pipefail

# Arch Linux dependency installer for NANFO backend development.
# Uses pacman packages only (no AUR required).

if [[ "${EUID}" -ne 0 ]]; then
  echo "[info] This script uses pacman and needs sudo privileges."
fi

echo "[step] Installing required packages..."
sudo pacman -S --needed \
  docker \
  docker-compose \
  python \
  python-poetry \
  make \
  git \
  openssl

echo "[step] Enabling docker service for manual start capability..."
sudo systemctl enable docker >/dev/null 2>&1 || true

echo "[step] Adding current user to docker group..."
sudo usermod -aG docker "$USER" || true

echo "[done] Dependencies installed."
echo "[important] Re-login (or run: newgrp docker) so docker group changes apply."
echo "[next] Run: ./scripts/dev-start.sh"
