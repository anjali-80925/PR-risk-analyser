#!/bin/bash
set -uo pipefail

# Usage: ./scripts/run_all_analyses.sh <JIRA_ID_1,JIRA_ID_2,...>
# Runs run_pr_analysis.sh for ALL detected services IN PARALLEL.

JIRA_IDS=${1:?"Usage: ./scripts/run_all_analyses.sh <JIRA_ID_1,JIRA_ID_2,...>"}

# ── Bootstrap ─────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/load_config.sh"   # also pulls in common.sh

DETECTED_FILE="$ANALYSIS_DIR/detected_services.txt"

if [[ ! -f "$DETECTED_FILE" || ! -s "$DETECTED_FILE" ]]; then
  log_error "$DETECTED_FILE missing or empty. Run detect_services.sh first."
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

  LOG_FILE="$ANALYSIS_DIR/$SERVICE/run.log"
  mkdir -p "$ANALYSIS_DIR/$SERVICE"
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
mapfile -t ALL_SERVICES < "$DETECTED_FILE"
FAILED=()
SUCCEEDED=()

for PID in "${PIDS[@]}"; do
  wait "$PID" 2>/dev/null || true
done

for SERVICE in "${ALL_SERVICES[@]}"; do
  if [[ -f "$ANALYSIS_DIR/$SERVICE/summary.json" ]]; then
    log_ok "$SERVICE — done"
    SUCCEEDED+=("$SERVICE")
  else
    log_error "$SERVICE — FAILED (see pr-analysis/$SERVICE/run.log)"
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
    log_error "$SVC"
    tail -3 "$ANALYSIS_DIR/$SVC/run.log" 2>/dev/null | sed 's/^/     /'
  done
  exit 1
fi

log_ok "All ${#ALL_SERVICES[@]} service(s) analysed successfully."
echo "========================================"
