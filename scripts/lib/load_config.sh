#!/bin/bash
# ── PR Risk Analyser — Config Loader ─────────────────────────────────────────
# Parses config.env into CFG_* variables.  Sources common.sh for shared paths.
# Usage: source "$SCRIPTS_DIR/lib/load_config.sh"
#        (common.sh must be sourced first, or will be auto-sourced here)

# ── Auto-source common.sh if not already loaded ──────────────────────────────
_LC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -z "${_COMMON_SH_LOADED:-}" ]]; then
  source "$_LC_DIR/common.sh"
fi

# ── Guard against double-sourcing ─────────────────────────────────────────────
[[ -n "${_LOAD_CONFIG_SH_LOADED:-}" ]] && return 0
_LOAD_CONFIG_SH_LOADED=1

# ── Read config.env ───────────────────────────────────────────────────────────
CONFIG_FILE="$WORKSPACE_ROOT/config.env"

if [[ ! -f "$CONFIG_FILE" ]]; then
  log_error "No config.env found in workspace root."
  log_info  "Run:  bash scripts/init.sh"
  exit 1
fi

# Source the .env file (skip comments and blank lines)
# BUT: preserve any env vars already set (e.g., from Jenkins)
set -a
while IFS='=' read -r key value; do
  [[ -z "$key" || "$key" =~ ^[[:space:]]*# ]] && continue
  key=$(echo "$key" | xargs)
  value=$(echo "$value" | xargs)
  # Only set if not already in environment (allows Jenkins overrides)
  [[ -n "${!key:-}" ]] && continue
  export "$key=$value"
done < "$CONFIG_FILE"
set +a

# ── Map raw env names → CFG_* variables ───────────────────────────────────────
CFG_GIT_PROVIDER="${GIT_PROVIDER:-bitbucket-server}"
CFG_REPO_BASE_URL="${REPO_BASE_URL:?REPO_BASE_URL not set in config.env}"
CFG_SVC_MODE="${SERVICE_DISCOVERY_MODE:-manual}"
CFG_MAX_PARALLEL="${MAX_PARALLEL:-4}"
CFG_CACHE_TTL="${REF_CACHE_TTL:-600}"
CFG_JIRA_KEYS="${JIRA_PROJECT_KEYS:-}"
CFG_COMMIT_FILTER_MODE="${COMMIT_FILTER_MODE:-any}"
CFG_TEST_REPOS="${TEST_REPOS:-}"

# Build services array from comma-separated list
IFS=',' read -ra CFG_SERVICES <<< "${SERVICES:-}"
