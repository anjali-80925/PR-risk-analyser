#!/usr/bin/env bash
# ────────────────────────────────────────────────────────────────────────────
# reindex.sh — (Re)build the cross-repo symbol index.
#
# Run this once after cloning / pulling all service repos. It walks every
# repo under .service-repos/ and builds an inverted symbol index stored at
# .service-repos/.symbol-index.json.
#
# Subsequent `run_analysis_by_jira_id.sh` calls will use the index for
# instant (<2s) cross-repo impact lookups instead of live grep scans.
#
# Usage:
#   bash scripts/reindex.sh              # auto-detects SERVICE_REPOS_DIR
#   bash scripts/reindex.sh --force      # rebuild even if index is fresh
#   bash scripts/reindex.sh --repos-dir /path/to/repos
# ────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB_DIR="$SCRIPT_DIR/lib"

# Load config (defines SERVICE_REPOS_DIR)
source "$SCRIPT_DIR/lib/load_config.sh" 2>/dev/null || true
source "$SCRIPT_DIR/lib/common.sh"      2>/dev/null || true

REPOS_DIR="${SERVICE_REPOS_DIR:-}"
FORCE_FLAG=""

# Parse CLI args
while [[ $# -gt 0 ]]; do
  case "$1" in
    --repos-dir)
      REPOS_DIR="$2"; shift 2 ;;
    --repos-dir=*)
      REPOS_DIR="${1#*=}"; shift ;;
    --force)
      FORCE_FLAG="--force"; shift ;;
    *)
      echo "[WARN] Unknown arg: $1" >&2; shift ;;
  esac
done

if [[ -z "$REPOS_DIR" || ! -d "$REPOS_DIR" ]]; then
  echo "[ERROR] SERVICE_REPOS_DIR not set or not a directory: '$REPOS_DIR'" >&2
  echo "  Set it in config.env or pass --repos-dir <path>" >&2
  exit 1
fi

echo "[INFO] Building symbol index for: $REPOS_DIR"
echo "       Index output: $REPOS_DIR/.symbol-index.json"

# Use Windows Python for NTFS repos — os.walk via WSL is ~100x slower
# Falls back to python3 (WSL) if Windows python.exe not available
PYTHON_CMD="python3"
if command -v python.exe &>/dev/null; then
  PYTHON_CMD="python.exe"
elif command -v /mnt/c/Users/anl/scoop/apps/python/current/python.exe &>/dev/null; then
  PYTHON_CMD="/mnt/c/Users/anl/scoop/apps/python/current/python.exe"
fi

"$PYTHON_CMD" "$LIB_DIR/index_symbols.py" \
  --repos-dir "$REPOS_DIR" \
  --output "$REPOS_DIR/.symbol-index.json" \
  $FORCE_FLAG

echo "[DONE] Reindex complete. Future analyses will use the symbol index."
