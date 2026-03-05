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
OLDEST="${COMMITS[0]}"
NEWEST="${COMMITS[-1]}"

PARENTS=$(git -C "$LOCAL_REPO" rev-parse "${NEWEST}^@" 2>/dev/null | wc -l | tr -d ' ')
IS_MERGE=false
[[ "$PARENTS" -gt 1 ]] && IS_MERGE=true

if [[ "$IS_MERGE" == true ]]; then
  DIFF_FROM=$(git -C "$LOCAL_REPO" rev-parse "${NEWEST}^1" 2>/dev/null)
  DIFF_TO="$NEWEST"
  log_info "Merge commit detected — diffing parent1 → merge"
else
  DEFAULT_BRANCH=$(git -C "$LOCAL_REPO" symbolic-ref refs/remotes/origin/HEAD 2>/dev/null \
    | sed 's|refs/remotes/origin/||' || echo "main")

  DIFF_FROM=$(git -C "$LOCAL_REPO" merge-base "origin/$DEFAULT_BRANCH" "$NEWEST" 2>/dev/null || echo "")

  if [[ -z "$DIFF_FROM" ]]; then
    DIFF_FROM=$(git -C "$LOCAL_REPO" rev-parse "${OLDEST}^" 2>/dev/null || echo "$OLDEST")
  fi
  DIFF_TO="$NEWEST"

  if [[ "$DIFF_FROM" == "$DIFF_TO" ]]; then
    DIFF_FROM=$(git -C "$LOCAL_REPO" rev-parse "${NEWEST}^" 2>/dev/null || echo "$NEWEST")
    log_info "Merge-base = tip — falling back to parent"
  fi
fi

log_info "Range: ${DIFF_FROM:0:10} → ${DIFF_TO:0:10}"

# ── Generate unified diff ────────────────────────────────────────────────────
log_step "Generating unified diff"
git -C "$LOCAL_REPO" diff -W "$DIFF_FROM" "$DIFF_TO" > "$AGG_DIFF_TMP" 2>/dev/null || true

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