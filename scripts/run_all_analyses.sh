#!/bin/bash
set -uo pipefail

# Usage: ./scripts/run_all_analyses.sh <JIRA_ID_1,JIRA_ID_2,...>
# Runs run_pr_analysis.sh for ALL detected services IN PARALLEL.

JIRA_IDS=${1:?"Usage: ./scripts/run_all_analyses.sh <JIRA_ID_1,JIRA_ID_2,...>"}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/load_config.sh"

DETECTED_FILE="$WORKSPACE_ROOT/pr-analysis/detected_services.txt"

if [[ ! -f "$DETECTED_FILE" || ! -s "$DETECTED_FILE" ]]; then
  echo "❌ $DETECTED_FILE missing or empty. Run detect_services.sh first."
  exit 1
fi

mapfile -t SERVICES < "$DETECTED_FILE"
MAX_PARALLEL="${CFG_MAX_PARALLEL:-4}"

echo "========================================"
echo " Parallel PR Analysis: ${JIRA_IDS}"
echo " Services: ${SERVICES[*]}"
echo " Max parallel: $MAX_PARALLEL"
echo "========================================"
echo ""

PIDS=()
LOGS=()
SVC_MAP=()

# ── Launch all services in parallel (with concurrency limit) ──────────────────
for SERVICE in "${SERVICES[@]}"; do
  # Wait if at max concurrency
  while [[ ${#PIDS[@]} -ge $MAX_PARALLEL ]]; do
    NEW_PIDS=()
    NEW_LOGS=()
    NEW_SVC=()
    for i in "${!PIDS[@]}"; do
      if kill -0 "${PIDS[$i]}" 2>/dev/null; then
        NEW_PIDS+=("${PIDS[$i]}")
        NEW_LOGS+=("${LOGS[$i]}")
        NEW_SVC+=("${SVC_MAP[$i]}")
      fi
    done
    PIDS=("${NEW_PIDS[@]}")
    LOGS=("${NEW_LOGS[@]}")
    SVC_MAP=("${NEW_SVC[@]}")
    if [[ ${#PIDS[@]} -ge $MAX_PARALLEL ]]; then
      sleep 1
    fi
  done

  LOG_FILE="$WORKSPACE_ROOT/pr-analysis/$SERVICE/run.log"
  mkdir -p "$WORKSPACE_ROOT/pr-analysis/$SERVICE"
  bash "$SCRIPT_DIR/run_pr_analysis.sh" "$SERVICE" "$JIRA_IDS" > "$LOG_FILE" 2>&1 &
  PIDS+=($!)
  LOGS+=("$LOG_FILE")
  SVC_MAP+=("$SERVICE")
  echo "  ▶ Started $SERVICE (PID $!)"
done

echo ""
echo "⏳ Waiting for all analyses to complete..."
echo ""

# ── Collect results ───────────────────────────────────────────────────────────
# Re-read from detected file to preserve full order for reporting
mapfile -t ALL_SERVICES < "$DETECTED_FILE"
FAILED=()
SUCCEEDED=()

# Wait for any remaining PIDs
for PID in "${PIDS[@]}"; do
  wait "$PID" 2>/dev/null || true
done

# Check results by summary.json existence
for SERVICE in "${ALL_SERVICES[@]}"; do
  if [[ -f "$WORKSPACE_ROOT/pr-analysis/$SERVICE/summary.json" ]]; then
    echo "  ✅ $SERVICE — done"
    SUCCEEDED+=("$SERVICE")
  else
    echo "  ❌ $SERVICE — FAILED (see pr-analysis/$SERVICE/run.log)"
    FAILED+=("$SERVICE")
  fi
done

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " Results: ${#SUCCEEDED[@]} passed, ${#FAILED[@]} failed"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [[ ${#FAILED[@]} -gt 0 ]]; then
  echo ""
  echo "Failed services:"
  for SVC in "${FAILED[@]}"; do
    echo "  ❌ $SVC"
    tail -3 "$WORKSPACE_ROOT/pr-analysis/$SVC/run.log" 2>/dev/null | sed 's/^/     /'
  done
  exit 1
fi

echo "✅ All ${#ALL_SERVICES[@]} service(s) analysed successfully."
echo "========================================"
