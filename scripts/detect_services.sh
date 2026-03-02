#!/bin/bash
set -uo pipefail

# Usage: ./scripts/detect_services.sh <JIRA_ID_1,JIRA_ID_2,...>
# Scans all configured services for git commits/branches mentioning ANY of the JIRA IDs.
# Writes matched service names to pr-analysis/detected_services.txt

JIRA_IDS=${1:?"Usage: ./scripts/detect_services.sh <JIRA_ID_1,JIRA_ID_2,...>"}

# Parse comma-separated IDs into array
IFS=',' read -ra JIRA_ARRAY <<< "$JIRA_IDS"

# Validate format for each ID
for JID in "${JIRA_ARRAY[@]}"; do
  if ! [[ "$JID" =~ ^[A-Z]+-[0-9]+$ ]]; then
    echo "❌ Invalid JIRA ID format: $JID (expected: ABC-123)"
    exit 1
  fi
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/load_config.sh"

OUT_FILE="$WORKSPACE_ROOT/pr-analysis/detected_services.txt"
CACHE_DIR="$WORKSPACE_ROOT/pr-analysis/.cache"
mkdir -p "$CACHE_DIR" "$(dirname "$OUT_FILE")"

# ── Clean up old analysis results (keep cache for speed) ────────────────────
echo "🧹 Cleaning up old analysis results..."
find "$WORKSPACE_ROOT/pr-analysis" -maxdepth 1 -type d ! -name ".cache" -exec rm -rf {} + 2>/dev/null || true
rm -f "$OUT_FILE" 2>/dev/null || true

echo ""
echo "========================================"
echo " Service Detection for JIRA IDs: ${JIRA_ARRAY[@]}"
echo "========================================"
echo ""

# ── Resolve service list from config ──────────────────────────────────────────
SERVICE_ARRAY=()

if [[ "$CFG_SVC_MODE" == "auto" ]]; then
  # Auto-discover: find .git directories in workspace
  for DIR in "$WORKSPACE_ROOT"/*/; do
    DIRNAME=$(basename "$DIR")
    if [[ -d "$DIR/.git" && "$DIRNAME" != "pr-analysis" && "$DIRNAME" != "scripts" && "$DIRNAME" != ".github" && "$DIRNAME" != ".vscode" ]]; then
      SERVICE_ARRAY+=("$DIRNAME")
    fi
  done
  # If no repos cloned yet in auto mode, fall back to ls-remote scan of common names
  if [[ ${#SERVICE_ARRAY[@]} -eq 0 && ${#CFG_SERVICES[@]} -gt 0 ]]; then
    SERVICE_ARRAY=("${CFG_SERVICES[@]}")
  fi
else
  # Manual mode: use services from config
  SERVICE_ARRAY=("${CFG_SERVICES[@]}")
fi

if [[ ${#SERVICE_ARRAY[@]} -eq 0 ]]; then
  echo "❌ No services configured. Run: bash scripts/init.sh"
  exit 1
fi

REPO_BASE_URL="$CFG_REPO_BASE_URL"

# ── Temp dir for parallel results ─────────────────────────────────────────────
TMPDIR_RESULTS=$(mktemp -d)
trap "rm -rf $TMPDIR_RESULTS" EXIT

check_service() {
  local SERVICE="$1"
  local RESULT_FILE="$TMPDIR_RESULTS/$SERVICE.match"
  local REPO_URL="$REPO_BASE_URL/$SERVICE.git"
  local LOCAL_REPO="$WORKSPACE_ROOT/$SERVICE"
  local CACHE_FILE="$CACHE_DIR/${SERVICE}.refs"

  # ── Layer 1: git ls-remote with configurable cache ────────────────────────
  local NOW CACHE_AGE=99999
  NOW=$(date +%s)
  if [[ -f "$CACHE_FILE" ]]; then
    local CACHE_MTIME
    CACHE_MTIME=$(stat -c %Y "$CACHE_FILE" 2>/dev/null || stat -f %m "$CACHE_FILE" 2>/dev/null || echo 0)
    CACHE_AGE=$(( NOW - CACHE_MTIME ))
  fi

  local REFS=""
  if [[ -f "$CACHE_FILE" && $CACHE_AGE -lt $CFG_CACHE_TTL ]]; then
    REFS=$(cat "$CACHE_FILE")
  else
    REFS=$(git ls-remote --heads --tags "$REPO_URL" 2>/dev/null || true)
    if [[ -n "$REFS" ]]; then
      echo "$REFS" > "$CACHE_FILE"
    fi
  fi

  # Check if ANY JIRA ID is in refs
  for JID in "${JIRA_ARRAY[@]}"; do
    if echo "$REFS" | grep -qi "$JID"; then
      echo "$SERVICE" > "$RESULT_FILE"
      return 0
    fi
  done

  # ── Layer 2: Local commit search ────────────────────────────────────────────
  # Auto-clone if missing (needed for commit search and later analysis)
  if [[ ! -d "$LOCAL_REPO/.git" ]]; then
    echo "  📦 $SERVICE — cloning (first run)..."
    git clone --quiet "$REPO_URL" "$LOCAL_REPO" &>/dev/null || true
  else
    # Fetch latest refs so we don't miss recent commits
    git -C "$LOCAL_REPO" fetch --all --prune --quiet &>/dev/null || true
  fi

  if [[ -d "$LOCAL_REPO/.git" ]]; then
    # Search for ANY JIRA ID in commits
    for JID in "${JIRA_ARRAY[@]}"; do
      if git -C "$LOCAL_REPO" log --all --oneline --grep="$JID" -1 2>/dev/null | grep -q .; then
        echo "$SERVICE" > "$RESULT_FILE"
        return 0
      fi
    done

    # ── Layer 3: Remote-tracking branch name ────────────────────────────────
    for JID in "${JIRA_ARRAY[@]}"; do
      if git -C "$LOCAL_REPO" branch -r 2>/dev/null | grep -qi "$JID"; then
        echo "$SERVICE" > "$RESULT_FILE"
        return 0
      fi
    done
  fi
}

# ── Launch all checks in parallel ─────────────────────────────────────────────
PIDS=()
echo "🔍 Scanning ${#SERVICE_ARRAY[@]} services in parallel..."
echo ""

for SERVICE in "${SERVICE_ARRAY[@]}"; do
  check_service "$SERVICE" &
  PIDS+=($!)
done

for PID in "${PIDS[@]}"; do
  wait "$PID" 2>/dev/null || true
done

# ── Collect results ───────────────────────────────────────────────────────────
MATCHED=()
for SERVICE in "${SERVICE_ARRAY[@]}"; do
  if [[ -f "$TMPDIR_RESULTS/$SERVICE.match" ]]; then
    MATCHED+=("$SERVICE")
    echo "  ✅ $SERVICE — INCLUDED"
  else
    echo "  ⬜ $SERVICE — not matched"
  fi
done

echo ""
echo "========================================"

if [[ ${#MATCHED[@]} -eq 0 ]]; then
  echo "⚠️  No services matched any JIRA ID: ${JIRA_ARRAY[@]}"
  exit 1
fi

printf '%s\n' "${MATCHED[@]}" > "$OUT_FILE"

echo ""
echo "✅ Matched ${#MATCHED[@]} service(s):"
printf '  - %s\n' "${MATCHED[@]}"
echo ""
echo "📄 Results saved to: $OUT_FILE"
echo "========================================"
