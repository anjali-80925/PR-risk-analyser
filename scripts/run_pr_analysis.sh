#!/bin/bash
set -uo pipefail

# Usage: ./scripts/run_pr_analysis.sh <SERVICE> <JIRA_ID_1,JIRA_ID_2,...>
SERVICE=${1:?"Usage: ./scripts/run_pr_analysis.sh <SERVICE> <JIRA_ID_1,JIRA_ID_2,...>"}
JIRA_IDS=${2:?"Usage: ./scripts/run_pr_analysis.sh <SERVICE> <JIRA_ID_1,JIRA_ID_2,...>"}

# Parse comma-separated IDs into array
IFS=',' read -ra JIRA_ARRAY <<< "$JIRA_IDS"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/load_config.sh"

REPO_URL="$CFG_REPO_BASE_URL/$SERVICE.git"
LOCAL_REPO="$WORKSPACE_ROOT/$SERVICE"
OUT_DIR="$WORKSPACE_ROOT/pr-analysis/$SERVICE"

mkdir -p "$OUT_DIR"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " PR Analysis: $SERVICE / ${JIRA_ARRAY[@]}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ── Auto-clone if repo missing ────────────────────────────────────────────────
if [[ ! -d "$LOCAL_REPO/.git" ]]; then
  echo "📦 Cloning $SERVICE (first run)..."
  git clone --quiet "$REPO_URL" "$LOCAL_REPO" 2>/dev/null || {
    echo "❌ Clone failed for $SERVICE ($REPO_URL)"
    exit 1
  }
fi

# ── Single fetch — one network round-trip ─────────────────────────────────────
echo "🔄 Fetching refs (single call)..."
git -C "$LOCAL_REPO" fetch --all --prune --quiet 2>/dev/null || {
  echo "⚠️  Fetch failed — using cached refs"
}

# ── Find matching commits (single git log) ────────────────────────────────────
echo "🔎 Searching commits..."

# Build regex pattern for all JIRA IDs: (ID1|ID2|ID3)
GREP_PATTERN=$(IFS='|'; echo "${JIRA_ARRAY[*]}")

mapfile -t COMMITS < <(
  git -C "$LOCAL_REPO" log --all --grep="$GREP_PATTERN" --pretty=%H --reverse 2>/dev/null \
    | awk '!seen[$0]++'
)

if [[ ${#COMMITS[@]} -eq 0 ]]; then
  echo "❌ No commits found mentioning any JIRA ID: ${JIRA_ARRAY[@]}"
  exit 1
fi

echo "   Found ${#COMMITS[@]} commit(s)"

# ── Temp files ────────────────────────────────────────────────────────────────
AGG_DIFF_TMP=$(mktemp)
COMMITS_TMP=$(mktemp)
trap "rm -f $AGG_DIFF_TMP $COMMITS_TMP" EXIT

# ── Determine diff range ──────────────────────────────────────────────────────
OLDEST="${COMMITS[0]}"
NEWEST="${COMMITS[-1]}"

# Check if the newest commit is a merge commit (has 2+ parents)
PARENTS=$(git -C "$LOCAL_REPO" rev-parse "${NEWEST}^@" 2>/dev/null | wc -l | tr -d ' ')
IS_MERGE=false
if [[ "$PARENTS" -gt 1 ]]; then
  IS_MERGE=true
fi

if [[ "$IS_MERGE" == true ]]; then
  # Merge commit: diff parent1 (target branch) vs the merge commit
  DIFF_FROM=$(git -C "$LOCAL_REPO" rev-parse "${NEWEST}^1" 2>/dev/null)
  DIFF_TO="$NEWEST"
  echo "📋 Merge commit detected — diffing parent1 ($DIFF_FROM) → merge ($DIFF_TO)"
else
  # Normal commits: find merge-base against default branch
  DEFAULT_BRANCH=$(git -C "$LOCAL_REPO" symbolic-ref refs/remotes/origin/HEAD 2>/dev/null \
    | sed 's|refs/remotes/origin/||' || echo "main")

  DIFF_FROM=$(git -C "$LOCAL_REPO" merge-base "origin/$DEFAULT_BRANCH" "$NEWEST" 2>/dev/null || echo "")

  if [[ -z "$DIFF_FROM" ]]; then
    DIFF_FROM=$(git -C "$LOCAL_REPO" rev-parse "${OLDEST}^" 2>/dev/null || echo "$OLDEST")
  fi
  DIFF_TO="$NEWEST"

  # Safety: if merge-base == tip, fall back to parent
  if [[ "$DIFF_FROM" == "$DIFF_TO" ]]; then
    DIFF_FROM=$(git -C "$LOCAL_REPO" rev-parse "${NEWEST}^" 2>/dev/null || echo "$NEWEST")
    echo "📋 Merge-base = tip — falling back to parent ($DIFF_FROM) → $DIFF_TO"
  else
    echo "📋 Range: $DIFF_FROM → $DIFF_TO"
  fi
fi

# ── Generate unified diff ────────────────────────────────────────────────────
echo "📋 Generating unified diff ($DIFF_FROM → $DIFF_TO)..."
git -C "$LOCAL_REPO" diff -W "$DIFF_FROM" "$DIFF_TO" > "$AGG_DIFF_TMP" 2>/dev/null || true

if [[ ! -s "$AGG_DIFF_TMP" ]]; then
  echo "⚠️  Empty diff — nothing to analyse"
  exit 1
fi

# ── Commit metadata (single log call) ────────────────────────────────────────
echo "📝 Collecting commit metadata..."
git -C "$LOCAL_REPO" log --all --grep="$GREP_PATTERN" --reverse \
  --pretty=format:'{"hash":"%H","short":"%h","author":"%an","date":"%ad","subject":"%s"}' \
  --date=short 2>/dev/null > "$COMMITS_TMP" || true

# ── Enhanced extraction (signature changes, blast radius, test changes, etc.) ─
echo "🔬 Running enhanced extraction..."
python3 "$SCRIPT_DIR/lib/extract_enhanced.py" \
  --diff "$AGG_DIFF_TMP" \
  --repo "$LOCAL_REPO" \
  --service "$SERVICE" \
  --jira "$JIRA_IDS" \
  --commits "$COMMITS_TMP" \
  --out "$OUT_DIR"

echo "✅ Analysis complete for $SERVICE"