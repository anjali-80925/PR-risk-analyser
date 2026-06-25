#!/usr/bin/env python3
"""
Symbol Index Builder — Pre-indexes all service repos for instant cross-repo lookups.

Walks all repos in .service-repos/, extracts identifiable symbols (class names,
method names, service references) and builds a reverse index:
  symbol → [{repo, file, line, snippet}]

This lets analyze_dependencies.py skip live scanning entirely — lookups are
<2s instead of 30-90s. Re-run whenever repos are pulled.

Usage:
  python3 index_symbols.py --repos-dir .service-repos --output .service-repos/.symbol-index.json
  python3 index_symbols.py --repos-dir .service-repos  # writes default output path

The index is invalidated and regenerated if older than --max-age-hours (default 24h).
"""

import sys
import os
import re
import json
import argparse
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Set, Any
from datetime import datetime, timezone
from collections import defaultdict

# ── Config ────────────────────────────────────────────────────────────────────

_SKIP_DIRS: Set[str] = {
    ".git", "node_modules", ".gradle", "build", "target",
    "dist", "out", "__pycache__", ".pytest_cache", ".venv", "venv",
}

_SOURCE_EXTS: Set[str] = {
    ".java", ".kt", ".py", ".ts", ".tsx", ".js", ".jsx",
    ".go", ".cs", ".rb", ".php", ".scala",
}

_CONFIG_EXTS: Set[str] = {
    ".xml", ".yaml", ".yml", ".properties", ".json", ".gradle",
}

# Patterns to extract symbols from source lines
_JAVA_METHOD = re.compile(
    r'(?:public|protected|private|static|\s)+[\w<>\[\]]+\s+(\w{4,})\s*\(', re.MULTILINE
)
_JAVA_CLASS = re.compile(r'\bclass\s+(\w{3,})')
_TS_FUNC = re.compile(r'(?:function|async function|const|let|var)\s+(\w{4,})\s*[=(]')
_TS_CLASS = re.compile(r'\bclass\s+(\w{3,})')
_PY_DEF = re.compile(r'^\s*(?:async\s+)?def\s+(\w{4,})\s*\(')
_PY_CLASS = re.compile(r'^\s*class\s+(\w{3,})')
_SERVICE_REF = re.compile(
    r'(?:import|from|require|@FeignClient|@Service|@Component|@RestController|url:|baseUrl:)'
    r'[^"\'`\n]*["\']([a-z][a-z0-9-]{3,})["\']'
)

# ── Extractor ─────────────────────────────────────────────────────────────────

def _extract_symbols_from_file(fpath: Path, repo_dir: Path) -> List[Dict]:
    """
    Return list of {symbol, repo, file, line, type} for a single file.
    'type' is one of: method, class, service_ref
    """
    try:
        text = fpath.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []

    repo_name = repo_dir.name
    hits = []
    ext = fpath.suffix.lower()

    if ext in (".java", ".kt", ".scala"):
        for m in _JAVA_METHOD.finditer(text):
            line = text[:m.start()].count("\n") + 1
            hits.append({"symbol": m.group(1), "type": "method", "line": line})
        for m in _JAVA_CLASS.finditer(text):
            line = text[:m.start()].count("\n") + 1
            hits.append({"symbol": m.group(1), "type": "class", "line": line})

    elif ext in (".ts", ".tsx", ".js", ".jsx"):
        for m in _TS_FUNC.finditer(text):
            line = text[:m.start()].count("\n") + 1
            hits.append({"symbol": m.group(1), "type": "method", "line": line})
        for m in _TS_CLASS.finditer(text):
            line = text[:m.start()].count("\n") + 1
            hits.append({"symbol": m.group(1), "type": "class", "line": line})

    elif ext == ".py":
        for m in _PY_DEF.finditer(text):
            line = text[:m.start()].count("\n") + 1
            hits.append({"symbol": m.group(1), "type": "method", "line": line})
        for m in _PY_CLASS.finditer(text):
            line = text[:m.start()].count("\n") + 1
            hits.append({"symbol": m.group(1), "type": "class", "line": line})

    # Service references from any file type
    for m in _SERVICE_REF.finditer(text):
        svc = m.group(1)
        if "-" in svc or len(svc) > 8:  # likely a service name not a plain word
            line = text[:m.start()].count("\n") + 1
            hits.append({"symbol": svc, "type": "service_ref", "line": line})

    try:
        rel = str(fpath.relative_to(repo_dir))
    except ValueError:
        rel = fpath.name

    return [
        {"symbol": h["symbol"], "type": h["type"],
         "repo": repo_name, "file": rel, "line": h["line"]}
        for h in hits
    ]


def _walk_repo(repo_dir: Path) -> List[Dict]:
    """Walk one repo and extract all symbols. Returns flat list."""
    repo_name = repo_dir.name
    all_hits = []
    for root, dirs, files in os.walk(repo_dir):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for fname in files:
            ext = Path(fname).suffix.lower()
            if ext not in _SOURCE_EXTS and ext not in _CONFIG_EXTS:
                continue
            if ext in _CONFIG_EXTS:
                # For config files, only extract service references
                fpath = Path(root) / fname
                try:
                    text = fpath.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                for m in _SERVICE_REF.finditer(text):
                    svc = m.group(1)
                    if "-" in svc or len(svc) > 8:
                        line = text[:m.start()].count("\n") + 1
                        try:
                            rel = str(fpath.relative_to(repo_dir))
                        except ValueError:
                            rel = fname
                        all_hits.append({
                            "symbol": svc, "type": "service_ref",
                            "repo": repo_name, "file": rel, "line": line,
                        })
                continue
            fpath = Path(root) / fname
            hits = _extract_symbols_from_file(fpath, repo_dir)
            all_hits.extend(hits)
    return all_hits


# ── Index builder ─────────────────────────────────────────────────────────────

def build_index(repos_dir: Path, output_path: Path, verbose: bool = True) -> Dict:
    """
    Walk all repos, build reverse index {symbol → [locations]}.
    Returns the index dict (also written to output_path).
    """
    start = time.monotonic()
    index: Dict[str, List[Dict]] = defaultdict(list)
    repos_indexed = 0
    total_symbols = 0

    repo_dirs = sorted(d for d in repos_dir.iterdir() if d.is_dir() and not d.name.startswith("."))

    for repo_dir in repo_dirs:
        if verbose:
            print(f"  Indexing {repo_dir.name}...", end="\r", file=sys.stderr)
        hits = _walk_repo(repo_dir)
        for h in hits:
            index[h["symbol"]].append({
                "repo": h["repo"],
                "file": h["file"],
                "line": h["line"],
                "type": h["type"],
            })
        repos_indexed += 1
        total_symbols += len(hits)

    elapsed = time.monotonic() - start

    out = {
        "built_at": datetime.now(timezone.utc).isoformat(),
        "repos_indexed": repos_indexed,
        "total_symbols": total_symbols,
        "unique_symbols": len(index),
        "build_seconds": round(elapsed, 1),
        "symbols": dict(index),
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"))  # compact — can be large

    if verbose:
        print(
            f"[OK] Symbol index built: {repos_indexed} repos, "
            f"{len(index):,} unique symbols, {round(elapsed, 1)}s → {output_path}",
            file=sys.stderr,
        )
    return out


def load_index(index_path: Path, max_age_hours: float = 24.0) -> Dict:
    """Load existing index if it exists and is fresh enough. Returns {} if stale/missing."""
    if not index_path.exists():
        return {}
    try:
        with open(index_path, encoding="utf-8") as f:
            data = json.load(f)
        built_at_str = data.get("built_at", "")
        if built_at_str:
            built_at = datetime.fromisoformat(built_at_str)
            age_hours = (datetime.now(timezone.utc) - built_at).total_seconds() / 3600
            if age_hours > max_age_hours:
                return {}
        return data
    except Exception:
        return {}


def lookup_terms(index: Dict, search_terms: Dict[str, List[str]]) -> List[Dict]:
    """
    Look up search_terms in the index. Returns same structure as AllReposRiskScanner.scan():
      [{repo, risk_level, reason, matched_terms, total_references, files_with_references, references}]
    """
    symbols = index.get("symbols", {})
    if not symbols:
        return []

    # Build per-repo aggregation
    repo_hits: Dict[str, Dict] = {}

    for category, terms in search_terms.items():
        for term in terms:
            if term not in symbols:
                continue
            for loc in symbols[term]:
                repo = loc["repo"]
                if repo not in repo_hits:
                    repo_hits[repo] = {
                        "matched_terms": set(),
                        "categories": set(),
                        "files": {},  # file → [hits]
                    }
                repo_hits[repo]["matched_terms"].add(term)
                repo_hits[repo]["categories"].add(category)
                f = loc["file"]
                if f not in repo_hits[repo]["files"]:
                    repo_hits[repo]["files"][f] = []
                repo_hits[repo]["files"][f].append({
                    "term": term,
                    "line": loc["line"],
                    "snippet": f"{loc['type']}: {term} (line {loc['line']})",
                })

    results = []
    for repo, data in repo_hits.items():
        cats = data["categories"]
        has_func = "changed_functions" in cats or "removed_features" in cats
        has_svc = "service_names" in cats

        if has_func:
            risk = "HIGH"
            reason = "References changed/removed function signatures from affected services"
        elif has_svc:
            risk = "MEDIUM"
            reason = "References affected service name — may be an integration consumer"
        else:
            risk = "LOW"
            reason = "Contains keyword references to affected change areas"

        refs = [
            {"file": f, "matches": hits[:10]}
            for f, hits in list(data["files"].items())[:20]
        ]
        total = sum(len(r["matches"]) for r in refs)

        results.append({
            "repo": repo,
            "risk_level": risk,
            "reason": reason,
            "matched_terms": sorted(data["matched_terms"]),
            "total_references": total,
            "files_with_references": len(data["files"]),
            "references": refs,
            "source": "symbol_index",
        })

    rank = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    results.sort(key=lambda x: rank.get(x["risk_level"], 3))
    return results


# ── CLI entry point ───────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Build symbol index for all service repos")
    parser.add_argument("--repos-dir", required=True, help="Path to .service-repos/")
    parser.add_argument(
        "--output",
        help="Output JSON path (default: <repos-dir>/.symbol-index.json)"
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Rebuild even if a fresh index already exists"
    )
    parser.add_argument(
        "--max-age-hours", type=float, default=24.0,
        help="Consider index stale after this many hours (default: 24)"
    )
    args = parser.parse_args()

    repos_dir = Path(args.repos_dir)
    if not repos_dir.is_dir():
        print(f"[ERROR] repos-dir not found: {repos_dir}", file=sys.stderr)
        sys.exit(1)

    output = Path(args.output) if args.output else repos_dir / ".symbol-index.json"

    if not args.force:
        existing = load_index(output, max_age_hours=args.max_age_hours)
        if existing:
            print(
                f"[OK] Index is fresh ({existing.get('repos_indexed')} repos, "
                f"{existing.get('unique_symbols'):,} symbols). Use --force to rebuild.",
                file=sys.stderr,
            )
            return

    build_index(repos_dir, output, verbose=True)


if __name__ == "__main__":
    main()
