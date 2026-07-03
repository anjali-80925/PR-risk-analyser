#!/bin/bash
# ── PR Risk Analyser — Master Orchestration Script ────────────────────────────
# Orchestrates complete workflow from Jira ID → PR analysis → test selection → report
#
# Usage:
#   bash scripts/run_analysis_by_jira_id.sh <JIRA_ID> [OPTIONS]
#
# Examples:
#   bash scripts/run_analysis_by_jira_id.sh DTB-17595
#   bash scripts/run_analysis_by_jira_id.sh DTB-17595 --skip-tests --no-fetch
#
# Workflow:
#   1. Fetch Jira ticket details (Atlassian MCP)
#   2. Detect PR and affected services (git log)
#   3. Run per-service analysis (extract_enhanced.py)
#   4. Consolidate with cross-service dependencies (analyze_dependencies.py)
#   5. Index test automation repo (index_tests.py)
#   6. Select tests based on risk (select_tests_for_pr.py)
#   7. Export in multiple formats (export_tests.py)
#   8. Generate unified report (generate_report.py)

set -euo pipefail

# ── Setup ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/common.sh"
source "$SCRIPT_DIR/lib/load_config.sh"

# ── Usage & Arguments ─────────────────────────────────────────────────────────
usage() {
  cat <<'EOF'
Usage: bash scripts/run_analysis_by_jira_id.sh <JIRA_ID> [OPTIONS]

Arguments:
  <JIRA_ID>              Jira ticket ID (e.g., DTB-17595)

Options:
  --filter-mode <mode>   Commit filter: any (default) | only | all
  --no-fetch             Skip Jira API calls (use git log only)
  --skip-tests           Skip test selection and export
  --no-report            Skip report generation
  --output-dir <path>    Output directory (default: pr-analysis/<JIRA_ID>)

Output:
  ✓ jira_issue.json              Ticket details
  ✓ consolidated_summary.json    Cross-service analysis
  ✓ test_index.json              Test inventory
  ✓ test_selection.json          Selected tests
  ✓ exports/
    - test_selection.json
    - test_selection.csv
    - test_selection_jira.csv
    - test_selection_report.html
    - gherkin/*.feature
  ✓ analysis_report.html         Unified report
EOF
  exit 1
}

if [[ $# -lt 1 ]]; then
  usage
fi

JIRA_ID="${1:?Missing JIRA_ID}"
FILTER_MODE="any"
SKIP_JIRA_FETCH=0
SKIP_TESTS=0
NO_REPORT=0
OUTPUT_DIR=""
TARGETED_SERVICES=""

# Parse optional arguments
shift || true
while [[ $# -gt 0 ]]; do
  case "$1" in
    --filter-mode)
      FILTER_MODE="${2:?Missing filter mode value}"
      shift 2
      ;;
    --no-fetch)
      SKIP_JIRA_FETCH=1
      shift
      ;;
    --skip-tests)
      SKIP_TESTS=1
      shift
      ;;
    --no-report)
      NO_REPORT=1
      shift
      ;;
    --output-dir)
      OUTPUT_DIR="${2:?Missing output directory}"
      shift 2
      ;;
    --services)
      TARGETED_SERVICES="${2:?Missing services value}"
      shift 2
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      ;;
  esac
done

# Validate input
if ! validate_jira_id "$JIRA_ID"; then
  log_error "Invalid JIRA ID format: $JIRA_ID (expected: ABC-123)"
  exit 1
fi

if ! validate_filter_mode "$FILTER_MODE"; then
  log_error "Invalid filter mode: $FILTER_MODE (expected: any|all|only)"
  exit 1
fi

# Default output directory
if [[ -z "$OUTPUT_DIR" ]]; then
  OUTPUT_DIR="$ANALYSIS_DIR/$JIRA_ID"
fi
mkdir -p "$OUTPUT_DIR"

PIPELINE_LOG="$OUTPUT_DIR/pipeline.log"
# Rotate log on each fresh run
> "$PIPELINE_LOG"

log_step "PR Risk Analysis — Complete Workflow"
log_info "JIRA ID: $JIRA_ID"
log_info "Filter mode: $FILTER_MODE"
log_info "Output dir: $OUTPUT_DIR"

# -- Step 1: Load Jira ticket details (pre-fetched by Copilot agent via Atlassian MCP) ---
log_step "Step 1: Loading Jira ticket details"

JIRA_DETAILS="$OUTPUT_DIR/jira_issue.json"

if [[ $SKIP_JIRA_FETCH -eq 0 ]]; then
  _jira_real=0
  if [[ -f "$JIRA_DETAILS" ]]; then
    _title=$(python3 - "$JIRA_DETAILS" 2>/dev/null <<'PYEOF'
import json, sys
try:
    d = json.load(open(sys.argv[1]))
    print(d.get("summary") or d.get("title", ""))
except Exception:
    pass
PYEOF
)
    if [[ -n "$_title" && "$_title" != "[Jira API]*" ]]; then
      _jira_real=1
    fi
  fi
  if [[ $_jira_real -eq 1 ]]; then
    log_ok "Jira data loaded: $_title"
  else
    log_error "No real Jira data found for $JIRA_ID."
    log_info  "The Copilot PR-analyser agent must pre-fetch Jira + Confluence via Atlassian MCP."
    log_info  "  1. mcp_atlassian_jira_get_issue -> jira_issue.json"
    log_info  "  2. mcp_atlassian_confluence_search -> confluence_pages.json"
    log_info  "  3. python3 scripts/lib/save_ticket_data.py --ticket-id $JIRA_ID ..."
    log_info  "  4. bash scripts/run_analysis_by_jira_id.sh $JIRA_ID --no-fetch --services svc1,svc2"
    log_info  "Or skip Jira entirely: add --no-fetch"
    exit 1
  fi
else
  log_info "Skipping Jira fetch (--no-fetch)"
  if [[ ! -f "$JIRA_DETAILS" ]]; then
    echo '{"key":"'"$JIRA_ID"'","fetched_via":"git_only"}' > "$JIRA_DETAILS"
  fi
fi

# ── Step 2: Parse JIRA ID and resolve services ────────────────────────────
log_step "Step 2: Detecting affected services"

parse_jira_ids "$JIRA_ID"

if [[ -n "$TARGETED_SERVICES" ]]; then
  IFS="," read -ra SERVICE_LIST <<< "$TARGETED_SERVICES"
  log_info "Using targeted services from agent: ${SERVICE_LIST[*]}"
elif [[ -f "$JIRA_DETAILS" ]]; then
  # Fallback 1: parse affected_services[] from saved jira_issue.json
  _affected=$(python3 - "$JIRA_DETAILS" 2>/dev/null <<'PYEOF'
import json, sys
try:
    d = json.load(open(sys.argv[1]))
    svcs = d.get("affected_services", [])
    if svcs:
        print(",".join(svcs))
except Exception:
    pass
PYEOF
)
  if [[ -n "$_affected" ]]; then
    IFS="," read -ra SERVICE_LIST <<< "$_affected"
    log_info "Services from jira_issue.json: ${SERVICE_LIST[*]}"
  else
    resolve_services
  fi
else
  resolve_services
fi

log_ok "Services to analyze: ${SERVICE_LIST[*]}"
echo "${SERVICE_LIST[@]}" > "$OUTPUT_DIR/affected_services.txt"

# ── Step 3: Run per-service analysis (PARALLEL) ─────────────────────────
log_step "Step 3: Running per-service PR analysis (parallel, max ${MAX_PARALLEL:-10} jobs)"

# Per-service worker — runs entirely in a subshell, no shared mutable state.
# ensure_repo sets LOCAL_REPO which is subshell-local, so no races between services.
_scan_one_service() {
  local service="$1"
  local results_dir="$2"
  local svc_log="$results_dir/$service.log"
  local status_file="$results_dir/$service.status"

  if ! ensure_repo "$service" --quiet >> "$svc_log" 2>&1; then
    echo "clone_failed" > "$status_file"
    return
  fi

  local commits
  commits=$(get_matching_commits "$LOCAL_REPO" "$FILTER_MODE" 2>>"$svc_log" | sort -u) || true

  if [[ -z "$commits" ]]; then
    echo "no_commits" > "$status_file"
    return
  fi

  local svc_dir="$OUTPUT_DIR/$service"
  mkdir -p "$svc_dir"

  local diff_file="$svc_dir/changes.diff"
  > "$diff_file"
  while IFS= read -r commit; do
    git -C "$LOCAL_REPO" show "$commit" >> "$diff_file" 2>>"$svc_log" || true
  done <<< "$commits"

  local summary_file="$svc_dir/summary.json"
  if ! python3 "$_LIB_DIR/extract_enhanced.py" \
    --service "$service" \
    --jira "$JIRA_ID" \
    --diff "$diff_file" \
    --repo "$LOCAL_REPO" \
    --out "$svc_dir" >> "$svc_log" 2>&1; then
    echo "extract_failed" > "$status_file"
    return
  fi

  echo "ok" > "$status_file"
}

_SCAN_TMP="$(mktemp -d)"
MAX_PARALLEL="${MAX_PARALLEL:-10}"
declare -a _pids=()

for service in "${SERVICE_LIST[@]}"; do
  ( _scan_one_service "$service" "$_SCAN_TMP" ) &
  _pids+=("$!")
  # Throttle: when at capacity, wait for the oldest job before launching a new one
  while (( ${#_pids[@]} >= MAX_PARALLEL )); do
    wait "${_pids[0]}" 2>/dev/null || true
    _pids=("${_pids[@]:1}")
  done
done

# Wait for all remaining jobs
for _pid in "${_pids[@]}"; do
  wait "$_pid" 2>/dev/null || true
done

# Collect results in original service order (deterministic log output)
SERVICES_ANALYZED=()
for service in "${SERVICE_LIST[@]}"; do
  _svc_log="$_SCAN_TMP/$service.log"
  _status_file="$_SCAN_TMP/$service.status"

  # Append per-service log to main pipeline log
  [[ -f "$_svc_log" ]] && cat "$_svc_log" >> "$PIPELINE_LOG"

  _status=""
  [[ -f "$_status_file" ]] && _status=$(cat "$_status_file")

  case "$_status" in
    ok)
      SUMMARY_FILE="$OUTPUT_DIR/$service/summary.json"
      FILES_CHANGED=$(python3 -c "import json; d=json.load(open('$SUMMARY_FILE')); print(len(d.get('changed_files', [])))" 2>/dev/null || echo "?")
      log_ok "  $service: $FILES_CHANGED files changed"
      SERVICES_ANALYZED+=("$service")
      ;;
    no_commits)
      log_warn "  No matching commits for $service"
      ;;
    clone_failed)
      log_warn "  Skipping $service (clone failed)"
      ;;
    extract_failed)
      log_warn "  Extraction failed for $service (see pipeline.log)"
      ;;
    *)
      log_warn "  No result for $service"
      ;;
  esac
done

rm -rf "$_SCAN_TMP"

if [[ ${#SERVICES_ANALYZED[@]} -eq 0 ]]; then
  log_error "No services were successfully analyzed"
  exit 1
fi

log_ok "Analyzed services: ${SERVICES_ANALYZED[*]}"

# ── Step 4: Consolidate cross-service analysis ────────────────────────────
log_step "Step 4: Cross-service dependency analysis"

CONSOLIDATED_FILE="$OUTPUT_DIR/consolidated_summary.json"
if ! python3 "$_LIB_DIR/analyze_dependencies.py" \
  --analysis-dir "$OUTPUT_DIR" \
  --jira-id "$JIRA_ID" \
  --repos-dir "$SERVICE_REPOS_DIR" \
  --output "$CONSOLIDATED_FILE" 2>>"$PIPELINE_LOG"; then
  log_warn "Dependency analysis failed (see pipeline.log)"
  echo '{"services": ["'$(IFS='", "'; echo "${SERVICES_ANALYZED[*]}")'"]}'  > "$CONSOLIDATED_FILE"
else
  RISK_SUMMARY=$(python3 -c "import json; d=json.load(open('$CONSOLIDATED_FILE')); r=d.get('risk_summary',{}); print(f\"HIGH:{r.get('high_risk_services',0)} MED:{r.get('medium_risk_services',0)} LOW:{r.get('low_risk_services',0)}\")" 2>/dev/null || echo "?")
  log_ok "Cross-service analysis complete: $RISK_SUMMARY"
fi

# ── Step 4b: QA profile analysis (risk triggers, regression signals, edge rules) ──
QA_ANALYSIS_FILE="$OUTPUT_DIR/qa_analysis.md"
if python3 "$_LIB_DIR/analyze_pr_with_profile.py" \
  --consolidated-file "$CONSOLIDATED_FILE" \
  --output "$QA_ANALYSIS_FILE" 2>>"$PIPELINE_LOG"; then
  log_ok "QA profile analysis complete: $QA_ANALYSIS_FILE"
else
  log_warn "QA profile analysis failed (see pipeline.log)"
fi

# ── Step 5: Test automation integration (optional) ─────────────────────────
log_step "Step 5: Test case selection"

TEST_SELECTION_FILE="$OUTPUT_DIR/test_selection.json"

if [[ $SKIP_TESTS -eq 1 ]]; then
  log_info "Skipping test selection (--skip-tests)"
  echo '{"tests_selected": 0, "reason": "Skipped"}' > "$TEST_SELECTION_FILE"
else
  # Build automation repo URL from TEST_REPOS name + REPO_BASE_URL (same pattern as services)
  AUTOMATION_REPO=""
  if [[ -n "${CFG_TEST_REPOS:-}" ]]; then
    AUTOMATION_REPO="${CFG_REPO_BASE_URL}/${CFG_TEST_REPOS}"
  fi

  if [[ -z "$AUTOMATION_REPO" ]]; then
    log_info "No automation repo configured, skipping test selection"
    echo '{"tests_selected": 0, "reason": "No automation repo"}' > "$TEST_SELECTION_FILE"
  else
    log_info "Indexing test automation repo: $CFG_TEST_REPOS"
    TEST_INDEX_FILE="$OUTPUT_DIR/test_index.json"

    # Clone via ensure_repo (uses git.exe — same as all service repos)
    # Note: do NOT pass --quiet here — pull failures must be visible for test repo
    if ! ensure_repo "$CFG_TEST_REPOS"; then
      log_warn "Test indexing failed (could not clone $CFG_TEST_REPOS)"
      echo '{"tests_selected": 0, "reason": "Clone failed"}' > "$TEST_SELECTION_FILE"
    elif python3 "$_LIB_DIR/index_tests.py" \
      --repo-path "$LOCAL_REPO" \
      --output "$TEST_INDEX_FILE" 2>>"$PIPELINE_LOG"; then
      
      TEST_COUNT=$(python3 -c "import json; d=json.load(open('$TEST_INDEX_FILE')); print(d.get('metadata',{}).get('total_tests',0))" 2>/dev/null || echo "?")
      log_ok "Test index created: $TEST_COUNT tests"
      
      log_info "Selecting tests based on risk..."
      if python3 "$_LIB_DIR/select_tests_for_pr.py" \
        --consolidated-summary "$CONSOLIDATED_FILE" \
        --test-index "$TEST_INDEX_FILE" \
        --output "$TEST_SELECTION_FILE" 2>>"$PIPELINE_LOG"; then
        
        SELECTED=$(python3 -c "import json; d=json.load(open('$TEST_SELECTION_FILE')); print(d.get('tests_selected',0))" 2>/dev/null || echo "?")
        ESTIMATED=$(python3 -c "import json; d=json.load(open('$TEST_SELECTION_FILE')); print(d.get('execution_strategy',{}).get('estimated_execution_minutes',0))" 2>/dev/null || echo "?")
        log_ok "Tests selected: $SELECTED (estimated $ESTIMATED minutes)"
      else
        log_warn "Test selection failed"
        echo '{"tests_selected": 0, "reason": "Selection failed"}' > "$TEST_SELECTION_FILE"
      fi
    else
      log_warn "Test indexing failed"
      echo '{"tests_selected": 0, "reason": "Indexing failed"}' > "$TEST_SELECTION_FILE"
    fi
  fi
fi

# ── Step 5b: Extract lean agent context (eliminates sequential reads in Phase 3) ──
AGENT_CONTEXT_FILE="$OUTPUT_DIR/agent_context.json"
if python3 "$_LIB_DIR/extract_agent_context.py" \
  --analysis-dir "$OUTPUT_DIR" \
  --jira-id "$JIRA_ID" \
  --output "$AGENT_CONTEXT_FILE" 2>>"$PIPELINE_LOG"; then
  CTX_SIZE=$(python3 -c "import os; print(f'{os.path.getsize(\"$AGENT_CONTEXT_FILE\")/1024:.1f}')" 2>/dev/null || echo "?")
  log_ok "Agent context extracted: ${CTX_SIZE} KB → $AGENT_CONTEXT_FILE"
else
  log_warn "Agent context extraction failed (see pipeline.log) — report generation will fall back to raw files"
fi

# ── Step 6: Generate unified report ──────────────────────────────────────
log_step "Step 6: Generating unified analysis report"

if [[ $NO_REPORT -eq 0 ]]; then
  REPORT_FILE="$OUTPUT_DIR/analysis_report.html"
  if python3 "$_LIB_DIR/generate_report.py" \
    --jira-file "$JIRA_DETAILS" \
    --consolidated-file "$CONSOLIDATED_FILE" \
    --test-selection-file "$TEST_SELECTION_FILE" \
    --output "$REPORT_FILE" 2>>"$PIPELINE_LOG"; then
    log_ok "Report generated: $REPORT_FILE"
  else
    log_warn "Report generation failed (see pipeline.log)"
  fi
else
  log_info "Skipping report generation (--no-report)"
fi

# ── Summary ──────────────────────────────────────────────────────────────────
# Print pipeline errors if any step failed
if [[ -s "$PIPELINE_LOG" ]]; then
  log_warn "Pipeline log (errors/warnings):"
  tail -20 "$PIPELINE_LOG" | while IFS= read -r line; do log_info "  $line"; done
fi

log_step "Analysis Complete ✓"
log_ok "JIRA ID: $JIRA_ID"
log_ok "Services analyzed: ${#SERVICES_ANALYZED[@]}"
log_ok "Output directory: $OUTPUT_DIR"
log_info ""
log_info "📊 Generated files:"
log_info "  • $JIRA_DETAILS"
log_info "  • $CONSOLIDATED_FILE"
log_info "  • $TEST_SELECTION_FILE"
log_info "  • $AGENT_CONTEXT_FILE"
if [[ $NO_REPORT -eq 0 ]]; then
  log_info "  • $REPORT_FILE"
fi
log_info ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Next steps:"
echo "  1. Review: open $OUTPUT_DIR/analysis_report.html"
echo "  2. Run tests: Use tags from $OUTPUT_DIR/test_selection.json in Jenkins"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
