#!/bin/bash
set -uo pipefail

# Usage: ./scripts/detect_services.sh <JIRA_ID_1,JIRA_ID_2,...>
# Scans all configured services for git commits/branches mentioning ANY of the JIRA IDs.
# Writes matched service names to pr-analysis/detected_services.txt

JIRA_IDS=${1:?"Usage: ./scripts/detect_services.sh <JIRA_ID_1,JIRA_ID_2,...>"}

# ── Bootstrap ─────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/load_config.sh"   # also pulls in common.sh

parse_jira_ids "$JIRA_IDS"
ensure_dirs
cleanup_analysis

OUT_FILE="$ANALYSIS_DIR/detected_services.txt"

echo ""
echo "========================================"
echo " Service Detection for JIRA IDs: ${JIRA_ARRAY[*]}"
echo "========================================"
echo ""

# ── Resolve service list from config ──────────────────────────────────────────
resolve_services   # → SERVICE_LIST[]

# ── Temp dir for parallel results ─────────────────────────────────────────────
TMPDIR_RESULTS=$(mktemp -d)
trap "rm -rf $TMPDIR_RESULTS" EXIT

check_service() {
  local SERVICE="$1"
  local RESULT_FILE="$TMPDIR_RESULTS/$SERVICE.match"
  local REPO_URL
  REPO_URL=$(repo_url_for "$SERVICE")
  local LOCAL_REPO="$SERVICE_REPOS_DIR/$SERVICE"
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

  # ── Layer 2: Local commit search ──────────────────────────────────────────
  ensure_repo "$SERVICE" --quiet || true

  if [[ -d "$LOCAL_REPO/.git" ]]; then
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
echo "🔍 Scanning ${#SERVICE_LIST[@]} services in parallel..."
echo ""

for SERVICE in "${SERVICE_LIST[@]}"; do
  check_service "$SERVICE" &
  PIDS+=($!)
done

for PID in "${PIDS[@]}"; do
  wait "$PID" 2>/dev/null || true
done

# ── Collect results ───────────────────────────────────────────────────────────
MATCHED=()
for SERVICE in "${SERVICE_LIST[@]}"; do
  if [[ -f "$TMPDIR_RESULTS/$SERVICE.match" ]]; then
    MATCHED+=("$SERVICE")
    log_ok "$SERVICE — INCLUDED"
  else
    echo "  ⬜ $SERVICE — not matched"
  fi
done

echo ""
echo "========================================"

if [[ ${#MATCHED[@]} -eq 0 ]]; then
  log_warn "No services matched any JIRA ID: ${JIRA_ARRAY[*]}"
  exit 1
fi

printf '%s\n' "${MATCHED[@]}" > "$OUT_FILE"

echo ""
log_ok "Matched ${#MATCHED[@]} service(s):"
printf '  - %s\n' "${MATCHED[@]}"
echo ""
log_info "Results saved to: $OUT_FILE"
echo "========================================"
