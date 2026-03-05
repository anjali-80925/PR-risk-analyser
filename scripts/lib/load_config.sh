#!/bin/bash
# ── Shared config loader ─────────────────────────────────────────────────────
# Pure bash — sources config.env into shell variables. No Python needed.
# Usage: source "$SCRIPT_DIR/lib/load_config.sh"

_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_DIR="$(cd "$_LIB_DIR/.." && pwd)"
WORKSPACE_ROOT="$(dirname "$SCRIPT_DIR")"
CONFIG_FILE="$WORKSPACE_ROOT/config.env"

if [[ ! -f "$CONFIG_FILE" ]]; then
  echo "❌ No config.env found in workspace root."
  echo "   Run:  bash scripts/init.sh"
  exit 1
fi

# Source the .env file (skip comments and blank lines)
set -a
while IFS='=' read -r key value; do
  # Skip comments and empty lines
  [[ -z "$key" || "$key" =~ ^[[:space:]]*# ]] && continue
  # Trim whitespace
  key=$(echo "$key" | xargs)
  value=$(echo "$value" | xargs)
  export "$key=$value"
done < "$CONFIG_FILE"
set +a

# Map .env names to CFG_* variables used by scripts
CFG_GIT_PROVIDER="${GIT_PROVIDER:-bitbucket-server}"
CFG_REPO_BASE_URL="${REPO_BASE_URL:?REPO_BASE_URL not set in config.env}"
CFG_SVC_MODE="${SERVICE_DISCOVERY_MODE:-manual}"
CFG_MAX_PARALLEL="${MAX_PARALLEL:-4}"
CFG_CACHE_TTL="${REF_CACHE_TTL:-600}"
CFG_JIRA_KEYS="${JIRA_PROJECT_KEYS:-}"

# Build services array from comma-separated list
IFS=',' read -ra CFG_SERVICES <<< "${SERVICES:-}"
