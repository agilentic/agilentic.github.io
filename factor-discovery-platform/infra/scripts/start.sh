#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "==> Factor Discovery Platform — starting services"

if [ ! -f "$ROOT_DIR/.env" ]; then
  echo "==> Copying .env.example -> .env"
  cp "$ROOT_DIR/.env.example" "$ROOT_DIR/.env"
fi

docker compose -f "$ROOT_DIR/infra/docker-compose.yml" up --build "$@"
