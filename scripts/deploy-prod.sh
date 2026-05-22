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

load_env_file() {
  local path="$1"
  set -a
  # shellcheck disable=SC1090
  source "$path"
  set +a
}

load_env_file "$BACKEND_ENV_FILE"
load_env_file "$FRONTEND_ENV_FILE"

PROD_STATE_DIR="${PROD_STATE_DIR:-/var/lib/history-rag/backend/.deer-flow}"
PROD_KNOWLEDGE_DIR="${PROD_KNOWLEDGE_DIR:-/var/lib/history-rag/knowledge}"

mkdir -p "$PROD_STATE_DIR" "$PROD_KNOWLEDGE_DIR" "$PROJECT_ROOT/logs"

cd "$PROJECT_ROOT/docker"

compose() {
  docker compose --env-file "$BACKEND_ENV_FILE" -p "$PROJECT_NAME" -f "$(basename "$COMPOSE_FILE")" "$@"
}

assert_env_present() {
  local service="$1"
  local env_name="$2"

  if ! compose exec -T "$service" sh -lc "[ -n \"\${$env_name:-}\" ]"; then
    echo "Required env $env_name is missing inside service $service" >&2
    exit 1
  fi
}

echo "Running Better Auth migrations..."
compose run --rm auth-migrate

echo "Deploying history-rag with docker compose..."
compose up -d --build --remove-orphans frontend gateway langgraph nginx

echo "Verifying runtime environment inside containers..."
assert_env_present gateway OPENAI_API_KEY
assert_env_present gateway VOLCENGINE_API_KEY
assert_env_present langgraph OPENAI_API_KEY
assert_env_present langgraph VOLCENGINE_API_KEY

echo "Reloading nginx to pick up mounted config changes..."
compose restart nginx

echo "Ingesting new structured docs and rebuilding SQLite indexes..."
compose exec -T gateway sh -c "python /app/scripts/ingest_structured_docs_to_db.py"

echo "Deployment completed."
compose ps
