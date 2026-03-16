#!/bin/bash
# ── PR Risk Analyser — Shared Utilities ───────────────────────────────────────
# Source this file in every script for consistent logging, validation, and
# git helpers.  Pure bash — no external dependencies.
#
# Usage (from any script under scripts/):
#   SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
#   source "$SCRIPT_DIR/lib/common.sh"       # if caller is in scripts/
#   source "$_LIB_DIR/common.sh"             # if caller is already in lib/

# ── Guard against double-sourcing ─────────────────────────────────────────────
[[ -n "${_COMMON_SH_LOADED:-}" ]] && return 0
_COMMON_SH_LOADED=1

# ── Path resolution (idempotent) ─────────────────────────────────────────────
_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPTS_DIR="$(cd "$_LIB_DIR/.." && pwd)"
WORKSPACE_ROOT="$(cd "$SCRIPTS_DIR/.." && pwd)"

# Jenkins persistence: repos/cache survive workspace re-clones
if [[ -n "${WORKSPACE:-}" ]]; then
  PERSISTENCE_ROOT="$WORKSPACE"
else
  PERSISTENCE_ROOT="$WORKSPACE_ROOT"
fi

SERVICE_REPOS_DIR="$PERSISTENCE_ROOT/.service-repos"
ANALYSIS_DIR="$WORKSPACE_ROOT/pr-analysis"
CACHE_DIR="$PERSISTENCE_ROOT/pr-analysis/.cache"

# ── Logging ───────────────────────────────────────────────────────────────────
log_info()  { echo "  ℹ️  $*"; }
log_ok()    { echo "  ✅ $*"; }
log_warn()  { echo "  ⚠️  $*"; }
log_error() { echo "  ❌ $*" >&2; }
log_step()  { echo ""; echo "── $* ──"; }

# ── JIRA ID helpers ───────────────────────────────────────────────────────────

# Validate a single JIRA ID.  Returns 0 on valid, 1 on invalid.
validate_jira_id() {
  [[ "$1" =~ ^[A-Z]+-[0-9]+$ ]]
}

# Parse a comma-separated string of JIRA IDs into the global JIRA_ARRAY.
# Exits on first invalid ID.
#   parse_jira_ids "PROJ-1,PROJ-2"
#   → JIRA_ARRAY=(PROJ-1 PROJ-2)
parse_jira_ids() {
  local raw="${1:?parse_jira_ids: missing argument}"
  IFS=',' read -ra JIRA_ARRAY <<< "$raw"
  for jid in "${JIRA_ARRAY[@]}"; do
    if ! validate_jira_id "$jid"; then
      log_error "Invalid JIRA ID format: $jid (expected: ABC-123)"
      exit 1
    fi
  done
}

# Build grep pattern "ID1|ID2|ID3" for use with git log --grep / grep -E.
jira_grep_pattern() {
  local IFS='|'
  echo "${JIRA_ARRAY[*]}"
}

# Validate commit filter mode.  Returns 0 on valid, 1 on invalid.
validate_filter_mode() {
  [[ "$1" =~ ^(any|all|only)$ ]]
}

# Get commits based on filter mode.
# Modes:
#   any  — Commits mentioning AT LEAST ONE of the provided IDs (default, current behavior)
#   all  — Commits mentioning ALL of the provided IDs
#   only — Commits mentioning ONLY the provided IDs (no other JIRA IDs)
#
# Usage:
#   get_matching_commits <repo_path> <filter_mode>
#   Prints commit hashes, one per line, deduplicated
get_matching_commits() {
  local repo_path="$1"
  local filter_mode="${2:-any}"
  local temp_file
  temp_file=$(mktemp)
  trap "rm -f $temp_file" RETURN

  if ! validate_filter_mode "$filter_mode"; then
    log_error "Invalid filter mode: $filter_mode (expected: any|all|only)"
    return 1
  fi

  case "$filter_mode" in
    any)
      # Search FULL COMMIT MESSAGE (subject + body) for at least one ID
      # This is the original behavior - gets broader results
      local pattern
      pattern=$(jira_grep_pattern)
      git -C "$repo_path" log --all --extended-regexp --grep="$pattern" --pretty=%H --reverse 2>/dev/null
      ;;
    all)
      # Commits mentioning ALL provided IDs in FULL COMMIT MESSAGE
      if [[ ${#JIRA_ARRAY[@]} -eq 0 ]]; then
        log_error "No JIRA IDs provided for 'all' filter mode"
        return 1
      fi

      local temp_commits
      temp_commits=$(mktemp)
      git -C "$repo_path" log --all --extended-regexp --grep="${JIRA_ARRAY[0]}" --pretty=%H --reverse 2>/dev/null > "$temp_commits"

      local commit
      while IFS= read -r commit; do
        [[ -z "$commit" ]] && continue
        local found_all=true
        for jid in "${JIRA_ARRAY[@]:1}"; do
          if ! git -C "$repo_path" log -1 "$commit" --pretty=%B 2>/dev/null | grep -q "$jid"; then
            found_all=false
            break
          fi
        done
        [[ "$found_all" == "true" ]] && echo "$commit"
      done < "$temp_commits"
      rm -f "$temp_commits"
      ;;
    only)
      # Commits mentioning ONLY the provided IDs in the SUBJECT/TITLE (not body)
      # OPTIMIZED: Search by pattern first (faster), then filter for no-other-IDs
      local pattern
      pattern=$(jira_grep_pattern)

      # START with commits matching our pattern (much faster than scanning all)
      git -C "$repo_path" log --all --extended-regexp --grep="$pattern" --pretty="%H_%s" --reverse 2>/dev/null | while IFS='_' read -r commit_hash subject; do
        [[ -z "$commit_hash" ]] && continue

        # Extract all JIRA-like IDs from SUBJECT ONLY: PROJ-123
        local all_found_ids
        all_found_ids=$(echo "$subject" | grep -oE '[A-Z][A-Z0-9]*-[0-9]+' | sort -u)

        # REQUIREMENT 1: Subject MUST contain at least ONE of our target IDs
        local has_target_id=false
        while IFS= read -r found_id; do
          [[ -z "$found_id" ]] && continue
          for our_id in "${JIRA_ARRAY[@]}"; do
            if [[ "$found_id" == "$our_id" ]]; then
              has_target_id=true
              break
            fi
          done
          [[ "$has_target_id" == "true" ]] && break
        done <<< "$all_found_ids"

        # Skip if subject doesn't contain any of our target IDs
        if [[ "$has_target_id" != "true" ]]; then
          continue
        fi

        # REQUIREMENT 2: Subject must contain NO other JIRA IDs (only our allowed ones)
        local has_other=false
        while IFS= read -r found_id; do
          [[ -z "$found_id" ]] && continue
          local is_allowed=false
          for our_id in "${JIRA_ARRAY[@]}"; do
            if [[ "$found_id" == "$our_id" ]]; then
              is_allowed=true
              break
            fi
          done
          if [[ "$is_allowed" != "true" ]]; then
            has_other=true
            break
          fi
        done <<< "$all_found_ids"

        # Output commit only if subject has target ID + no other IDs
        [[ "$has_other" != "true" ]] && echo "$commit_hash"
      done
      ;;
  esac
}

# ── Service resolution ────────────────────────────────────────────────────────

# Populate SERVICE_LIST array from config.  Requires load_config.sh sourced first.
resolve_services() {
  SERVICE_LIST=()
  if [[ "$CFG_SVC_MODE" == "auto" ]]; then
    for dir in "$WORKSPACE_ROOT"/*/; do
      local name
      name=$(basename "$dir")
      if [[ -d "$dir/.git" && "$name" != "pr-analysis" && "$name" != "scripts" \
            && "$name" != ".github" && "$name" != ".vscode" ]]; then
        SERVICE_LIST+=("$name")
      fi
    done
    # Fall back to manual list when nothing cloned yet
    if [[ ${#SERVICE_LIST[@]} -eq 0 && ${#CFG_SERVICES[@]} -gt 0 ]]; then
      SERVICE_LIST=("${CFG_SERVICES[@]}")
    fi
  else
    SERVICE_LIST=("${CFG_SERVICES[@]}")
  fi

  if [[ ${#SERVICE_LIST[@]} -eq 0 ]]; then
    log_error "No services configured. Run: bash scripts/init.sh"
    exit 1
  fi
}

# ── Git helpers ───────────────────────────────────────────────────────────────

# Build the remote URL for a given service name.
repo_url_for() {
  echo "${CFG_REPO_BASE_URL}/${1}.git"
}

# Ensure a local clone exists and is up-to-date.
#   ensure_repo <service_name> [--quiet]
#   Sets LOCAL_REPO to the checked-out path.
ensure_repo() {
  local service="$1"
  local quiet="${2:-}"
  LOCAL_REPO="$SERVICE_REPOS_DIR/$service"
  local url
  url=$(repo_url_for "$service")

  if [[ ! -d "$LOCAL_REPO/.git" ]]; then
    [[ "$quiet" != "--quiet" ]] && log_info "$service — cloning (first run)..."
    if ! git clone --quiet "$url" "$LOCAL_REPO" &>/dev/null; then
      log_error "Clone failed for $service ($url)"
      return 1
    fi
  fi

  # Single fetch — one network round-trip
  git -C "$LOCAL_REPO" fetch --all --prune --quiet &>/dev/null || {
    [[ "$quiet" != "--quiet" ]] && log_warn "$service — fetch failed, using cached refs"
  }
  return 0
}

# ── Analysis directory helpers ────────────────────────────────────────────────

# Remove previous analysis results (keeps .cache for speed).
cleanup_analysis() {
  log_info "Cleaning up old analysis results..."
  # Remove service analysis folders
  find "$ANALYSIS_DIR" -maxdepth 1 -mindepth 1 -type d ! -name ".cache" -exec rm -rf {} + 2>/dev/null || true
  rm -f "$ANALYSIS_DIR/detected_services.txt" 2>/dev/null || true
}

# Ensure base directories exist.
ensure_dirs() {
  mkdir -p "$ANALYSIS_DIR" "$CACHE_DIR" "$SERVICE_REPOS_DIR"
}
