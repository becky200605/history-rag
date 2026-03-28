#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
COMPOSE_FILE="$PROJECT_ROOT/docker/docker-compose.prod.yaml"
PROJECT_NAME="${COMPOSE_PROJECT_NAME:-history-rag-prod}"
BACKEND_ENV_FILE="$PROJECT_ROOT/backend/.production.env"
FRONTEND_ENV_FILE="$PROJECT_ROOT/frontend/.production.env"

require_file() {
  local path="$1"
  if [[ ! -f "$path" ]]; then
    echo "Missing required file: $path" >&2
    exit 1
  fi
}

require_command() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "Missing required command: $cmd" >&2
    exit 1
  fi
}

require_command docker
require_file "$BACKEND_ENV_FILE"
require_file "$FRONTEND_ENV_FILE"
require_file "$PROJECT_ROOT/config.yaml"
require_file "$COMPOSE_FILE"

mkdir -p "$PROJECT_ROOT/backend/.deer-flow" "$PROJECT_ROOT/knowledge" "$PROJECT_ROOT/logs"

echo "Starting MySQL..."
cd "$PROJECT_ROOT/docker"
docker compose --env-file "$BACKEND_ENV_FILE" -p "$PROJECT_NAME" -f "$(basename "$COMPOSE_FILE")" up -d mysql

echo "Running Better Auth migrations..."
docker compose --env-file "$BACKEND_ENV_FILE" -p "$PROJECT_NAME" -f "$(basename "$COMPOSE_FILE")" run --rm auth-migrate

echo "Deploying history-rag with docker compose..."
docker compose --env-file "$BACKEND_ENV_FILE" -p "$PROJECT_NAME" -f "$(basename "$COMPOSE_FILE")" up -d --build --remove-orphans nginx frontend gateway langgraph

echo "Deployment completed."
docker compose --env-file "$BACKEND_ENV_FILE" -p "$PROJECT_NAME" -f "$(basename "$COMPOSE_FILE")" ps
