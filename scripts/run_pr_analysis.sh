#!/bin/bash
set -uo pipefail

# Usage: ./scripts/run_pr_analysis.sh <SERVICE> <JIRA_ID_1,JIRA_ID_2,...>
SERVICE=${1:?"Usage: ./scripts/run_pr_analysis.sh <SERVICE> <JIRA_ID_1,JIRA_ID_2,...>"}
JIRA_IDS=${2:?"Usage: ./scripts/run_pr_analysis.sh <SERVICE> <JIRA_ID_1,JIRA_ID_2,...>"}

# ── Bootstrap ─────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/load_config.sh"   # also pulls in common.sh

parse_jira_ids "$JIRA_IDS"
GREP_PATTERN=$(jira_grep_pattern)

OUT_DIR="$ANALYSIS_DIR/$SERVICE"
mkdir -p "$OUT_DIR"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " PR Analysis: $SERVICE / ${JIRA_ARRAY[*]}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ── Ensure local repo is cloned & up-to-date ──────────────────────────────────
ensure_repo "$SERVICE" || exit 1

# ── Find matching commits (single git log) ────────────────────────────────────
log_step "Searching commits"

mapfile -t COMMITS < <(
  git -C "$LOCAL_REPO" log --all --extended-regexp --grep="$GREP_PATTERN" --pretty=%H --reverse 2>/dev/null \
    | awk '!seen[$0]++'
)

if [[ ${#COMMITS[@]} -eq 0 ]]; then
  log_error "No commits found mentioning any JIRA ID: ${JIRA_ARRAY[*]}"
  exit 1
fi

log_info "Found ${#COMMITS[@]} commit(s)"

# ── Temp files ────────────────────────────────────────────────────────────────
AGG_DIFF_TMP=$(mktemp)
COMMITS_TMP=$(mktemp)
trap "rm -f $AGG_DIFF_TMP $COMMITS_TMP" EXIT

# ── Determine diff range ──────────────────────────────────────────────────────
# For multiple commits (esp. on diverged branches), generate diff for EACH commit
# relative to its parent, then combine.  This ensures all changes are captured.

if [[ ${#COMMITS[@]} -eq 1 ]]; then
  # Single commit: diff against parent
  SINGLE_COMMIT="${COMMITS[0]}"
  log_step "Generating unified diff for single commit"
  git -C "$LOCAL_REPO" diff "${SINGLE_COMMIT}^" "$SINGLE_COMMIT" > "$AGG_DIFF_TMP" 2>/dev/null || true
else
  # Multiple commits: collect diffs from each commit individually, combine
  log_step "Collecting diffs from ${#COMMITS[@]} commits"
  > "$AGG_DIFF_TMP"  # Clear file
  for COMMIT in "${COMMITS[@]}"; do
    git -C "$LOCAL_REPO" diff "${COMMIT}^" "$COMMIT" >> "$AGG_DIFF_TMP" 2>/dev/null || true
  done
fi

if [[ ! -s "$AGG_DIFF_TMP" ]]; then
  log_warn "Empty diff — nothing to analyse"
  exit 1
fi

# ── Commit metadata (single log call) ────────────────────────────────────────
log_step "Collecting commit metadata"
git -C "$LOCAL_REPO" log --all --extended-regexp --grep="$GREP_PATTERN" --reverse \
  --pretty=format:'{"hash":"%H","short":"%h","author":"%an","date":"%ad","subject":"%s"}' \
  --date=short 2>/dev/null > "$COMMITS_TMP" || true

# ── Enhanced extraction ───────────────────────────────────────────────────────
log_step "Running enhanced extraction"
python3 "$SCRIPT_DIR/lib/extract_enhanced.py" \
  --diff "$AGG_DIFF_TMP" \
  --repo "$LOCAL_REPO" \
  --service "$SERVICE" \
  --jira "$JIRA_IDS" \
  --commits "$COMMITS_TMP" \
  --out "$OUT_DIR"

log_ok "Analysis complete for $SERVICE"