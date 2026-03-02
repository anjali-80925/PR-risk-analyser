#!/usr/bin/env python3
"""
Enhanced PR analysis extractor.
Reads a git diff + repo path and produces a rich summary.json with:
  - changed_files (filtered, no lockfiles)
  - signature_changes (params/return type changes)
  - removed_features (deleted imports, component usages, test blocks)
  - new_status_values (added enum/const entries)
  - blast_radius (callers of changed exports not in the diff)
  - test_changes (modified assertions, removed/added tests)
  - diff_stats (lines added/removed, new files)

Usage:
  python3 scripts/lib/extract_enhanced.py \
    --diff <changes.diff> \
    --repo <path/to/repo> \
    --service <name> \
    --jira <JIRA_ID_1,JIRA_ID_2,...> \
    --commits <commits_jsonl_file> \
    --out <output_dir>
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path


# ── Files to exclude from analysis ────────────────────────────────────────────
EXCLUDE_PATTERNS = [
    r'package-lock\.json$',
    r'yarn\.lock$',
    r'pnpm-lock\.yaml$',
    r'\.lock$',
    r'\.min\.js$',
    r'\.map$',
    r'dist/',
    r'build/',
    r'node_modules/',
]


def should_exclude(filepath: str) -> bool:
    return any(re.search(p, filepath) for p in EXCLUDE_PATTERNS)


def parse_diff(diff_text: str) -> dict:
    """Parse unified diff into per-file sections."""
    files = {}
    current_file = None
    current_lines = []

    for line in diff_text.splitlines():
        if line.startswith('diff --git'):
            if current_file:
                files[current_file] = '\n'.join(current_lines)
            # Extract b/ path
            match = re.search(r'b/(.+)$', line)
            current_file = match.group(1) if match else None
            current_lines = [line]
        elif current_file:
            current_lines.append(line)

    if current_file:
        files[current_file] = '\n'.join(current_lines)

    return files


def get_changed_files(file_diffs: dict) -> list:
    """Return filtered list of changed files."""
    return sorted(f for f in file_diffs if not should_exclude(f))


def get_diff_stats(file_diffs: dict) -> dict:
    """Compute lines added/removed and identify new files."""
    added = 0
    removed = 0
    new_files = []
    deleted_files = []

    for filepath, diff in file_diffs.items():
        if should_exclude(filepath):
            continue
        if 'new file mode' in diff:
            new_files.append(filepath)
        if 'deleted file mode' in diff:
            deleted_files.append(filepath)
        for line in diff.splitlines():
            if line.startswith('+') and not line.startswith('+++'):
                added += 1
            elif line.startswith('-') and not line.startswith('---'):
                removed += 1

    return {
        "files_changed": len([f for f in file_diffs if not should_exclude(f)]),
        "lines_added": added,
        "lines_removed": removed,
        "new_files": new_files,
        "deleted_files": deleted_files,
    }


def extract_signature_changes(file_diffs: dict) -> list:
    """Detect function signature changes (params/return type)."""
    changes = []

    for filepath, diff in file_diffs.items():
        if should_exclude(filepath):
            continue

        old_sigs = {}
        new_sigs = {}

        for line in diff.splitlines():
            # Match function/const arrow declarations
            # Patterns: export const foo = (...) => | export function foo(...) | const foo = (...)
            sig_match = re.search(
                r'^[-+]\s*(?:export\s+)?(?:const|function|let|var)\s+'
                r'(\w+)\s*(?::\s*\w+)?\s*=?\s*(?:<[^>]+>\s*)?\(([^)]*)\)',
                line
            )
            if sig_match:
                name = sig_match.group(1)
                params = sig_match.group(2).strip()
                if line.startswith('-'):
                    old_sigs[name] = params
                elif line.startswith('+'):
                    new_sigs[name] = params

        # Find changed signatures
        for name in set(old_sigs) & set(new_sigs):
            if old_sigs[name] != new_sigs[name]:
                changes.append({
                    "function": name,
                    "file": os.path.basename(filepath),
                    "old_params": f"({old_sigs[name]})",
                    "new_params": f"({new_sigs[name]})",
                })

    # Also detect return type changes via type annotations
    for filepath, diff in file_diffs.items():
        if should_exclude(filepath):
            continue

        old_returns = {}
        new_returns = {}

        for line in diff.splitlines():
            ret_match = re.search(
                r'^[-+]\s*(?:export\s+)?(?:const|function)\s+(\w+).*\)\s*(?::\s*(.+?)\s*(?:=>|{|\{))',
                line
            )
            if ret_match:
                name = ret_match.group(1)
                ret_type = ret_match.group(2).strip()
                if line.startswith('-'):
                    old_returns[name] = ret_type
                elif line.startswith('+'):
                    new_returns[name] = ret_type

        for name in set(old_returns) & set(new_returns):
            if old_returns[name] != new_returns[name]:
                # Check if already captured
                existing = [c for c in changes if c['function'] == name]
                if existing:
                    existing[0]['old_return'] = old_returns[name]
                    existing[0]['new_return'] = new_returns[name]
                else:
                    changes.append({
                        "function": name,
                        "file": os.path.basename(filepath),
                        "old_return": old_returns[name],
                        "new_return": new_returns[name],
                    })

    return changes


def extract_removed_features(file_diffs: dict) -> list:
    """Detect removed imports, component usages, and deleted code blocks."""
    removed = []

    for filepath, diff in file_diffs.items():
        if should_exclude(filepath):
            continue
        fname = os.path.basename(filepath)

        # Removed imports
        for line in diff.splitlines():
            if line.startswith('-') and not line.startswith('---'):
                import_match = re.search(r'import\s+.*\{([^}]+)\}.*from', line)
                if import_match:
                    names = [n.strip() for n in import_match.group(1).split(',')]
                    # Check if any of these names are NOT re-added
                    added_lines = [l for l in diff.splitlines() if l.startswith('+')]
                    for name in names:
                        if not any(name in al for al in added_lines):
                            removed.append(f"{name} import removed from {fname}")

                # Removed component usage in JSX
                comp_match = re.search(r'<(\w+)[\s/>]', line[1:])
                if comp_match:
                    comp_name = comp_match.group(1)
                    # Upper-case = likely a component, not HTML
                    if comp_name[0].isupper():
                        added_lines = [l for l in diff.splitlines() if l.startswith('+')]
                        if not any(f'<{comp_name}' in al for al in added_lines):
                            removed.append(f"<{comp_name}> usage removed from {fname}")

    # Deduplicate
    return list(dict.fromkeys(removed))


def extract_new_status_values(file_diffs: dict) -> list:
    """Detect new entries in enums, const objects, arrays, Records."""
    new_values = []

    for filepath, diff in file_diffs.items():
        if should_exclude(filepath):
            continue
        fname = os.path.basename(filepath)

        for line in diff.splitlines():
            if not line.startswith('+') or line.startswith('+++'):
                continue
            clean = line[1:].strip()

            # Pattern: [ENUM.VALUE]: 'color' or [ENUM.VALUE]: value
            enum_match = re.search(r'\[(\w+\.\w+)\]\s*:\s*[\'"]?(\w+)', clean)
            if enum_match:
                new_values.append({
                    "file": fname,
                    "entry": enum_match.group(1),
                    "value": enum_match.group(2),
                })
                continue

            # Pattern: added to array/list (e.g., 'cancelled' added to status array)
            arr_match = re.search(r"['\"](\w[\w\s]+\w)['\"]", clean)
            if arr_match and not clean.startswith('//') and not clean.startswith('*'):
                # Check if this is within an array context by checking surrounding removed lines
                val = arr_match.group(1)
                # Only flag if the line before was also from the same array (heuristic)
                if re.search(r"[\[\],]", clean):
                    new_values.append({
                        "file": fname,
                        "entry": "array/list",
                        "value": val,
                    })

    # Deduplicate by entry+value
    seen = set()
    unique = []
    for v in new_values:
        key = f"{v['entry']}:{v['value']}"
        if key not in seen:
            seen.add(key)
            unique.append(v)

    return unique


def extract_test_changes(file_diffs: dict) -> dict:
    """Analyze test file changes: modified assertions, removed/added test blocks."""
    modified_assertions = []
    removed_tests = []
    added_tests = []

    for filepath, diff in file_diffs.items():
        if not re.search(r'\.(test|spec)\.(tsx?|jsx?|js)$', filepath):
            continue
        if should_exclude(filepath):
            continue

        for line in diff.splitlines():
            clean = line[1:].strip() if len(line) > 1 else ''

            # Removed test blocks
            if line.startswith('-'):
                test_match = re.search(r"(?:it|test|describe)(?:\.each)?\s*\(\s*['\"`](.+?)['\"`]", clean)
                if test_match:
                    test_name = test_match.group(1)
                    # Check if same test exists in added lines (just modified)
                    added_lines = [l for l in diff.splitlines() if l.startswith('+')]
                    if not any(test_name in al for al in added_lines):
                        removed_tests.append(test_name)

            # Added test blocks
            if line.startswith('+'):
                test_match = re.search(r"(?:it|test|describe)\s*\(\s*['\"`](.+?)['\"`]", clean)
                if test_match:
                    test_name = test_match.group(1)
                    removed_lines = [l for l in diff.splitlines() if l.startswith('-')]
                    if not any(test_name in rl for rl in removed_lines):
                        added_tests.append(test_name)

            # Modified assertions (expect value changes)
            if line.startswith('-'):
                expect_match = re.search(r"expect\(.*\)\.to\w+\((.+)\)", clean)
                if expect_match:
                    old_val = expect_match.group(1).strip()
                    # Find corresponding + line with same expect pattern
                    for aline in diff.splitlines():
                        if aline.startswith('+'):
                            aclean = aline[1:].strip()
                            aexpect = re.search(r"expect\(.*\)\.to\w+\((.+)\)", aclean)
                            if aexpect:
                                new_val = aexpect.group(1).strip()
                                if old_val != new_val and _similar_context(clean, aclean):
                                    modified_assertions.append(f"{old_val} → {new_val}")
                                    break

    return {
        "modified_assertions": list(dict.fromkeys(modified_assertions))[:20],
        "removed_tests": list(dict.fromkeys(removed_tests)),
        "added_tests": list(dict.fromkeys(added_tests)),
    }


def _similar_context(line_a: str, line_b: str) -> bool:
    """Check if two lines are likely the same assertion modified."""
    # Strip values and compare structure
    a = re.sub(r"['\"].*?['\"]", 'X', line_a)
    b = re.sub(r"['\"].*?['\"]", 'X', line_b)
    a = re.sub(r'\d+', 'N', a)
    b = re.sub(r'\d+', 'N', b)
    return a == b


def find_blast_radius(file_diffs: dict, repo_path: str, changed_files: list) -> list:
    """Find callers of changed exports that are NOT in the diff."""
    if not repo_path or not os.path.isdir(repo_path):
        return []

    # Extract exported names from changed files
    exported_names = set()
    for filepath, diff in file_diffs.items():
        if should_exclude(filepath):
            continue
        for line in diff.splitlines():
            # Both added and removed lines indicate the export was touched
            if line.startswith('+') or line.startswith('-'):
                clean = line[1:].strip()
                # export const/function name
                exp_match = re.search(r'export\s+(?:const|function|type|interface|let|var)\s+(\w+)', clean)
                if exp_match:
                    exported_names.add(exp_match.group(1))
                # export { Name }
                exp_brace = re.search(r'export\s+\{([^}]+)\}', clean)
                if exp_brace:
                    for n in exp_brace.group(1).split(','):
                        name = n.strip().split(' as ')[0].strip()
                        if name:
                            exported_names.add(name)

    if not exported_names:
        return []

    # Build grep pattern for all exported names
    pattern = '|'.join(re.escape(n) for n in exported_names)
    changed_basenames = {os.path.basename(f) for f in changed_files}

    blast = []
    try:
        result = subprocess.run(
            ['grep', '-rl', '-E', pattern, '--include=*.ts', '--include=*.tsx',
             '--include=*.js', '--include=*.jsx', '--exclude-dir=node_modules',
             '--exclude-dir=dist', '--exclude-dir=build', '--exclude-dir=.git'],
            capture_output=True, text=True, cwd=repo_path, timeout=30
        )
        if result.returncode == 0:
            for hit_file in result.stdout.strip().splitlines():
                hit_base = os.path.basename(hit_file)
                # Skip files already in the diff
                if hit_base not in changed_basenames and hit_file not in changed_files:
                    # Confirm it actually imports/uses the name
                    for name in exported_names:
                        try:
                            grep2 = subprocess.run(
                                ['grep', '-l', name, hit_file],
                                capture_output=True, text=True, cwd=repo_path, timeout=5
                            )
                            if grep2.returncode == 0:
                                blast.append({
                                    "file": hit_file,
                                    "uses": name,
                                })
                        except subprocess.TimeoutExpired:
                            continue
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    # Deduplicate and group by file
    grouped = {}
    for item in blast:
        f = item['file']
        if f not in grouped:
            grouped[f] = {"file": f, "uses": []}
        if item['uses'] not in grouped[f]['uses']:
            grouped[f]['uses'].append(item['uses'])

    return list(grouped.values())


def read_commits(commits_file: str) -> list:
    """Read JSONL commits file."""
    commits = []
    if not commits_file or not os.path.exists(commits_file):
        return commits
    with open(commits_file) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    commits.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return commits


def main():
    parser = argparse.ArgumentParser(description='Enhanced PR analysis extractor')
    parser.add_argument('--diff', required=True, help='Path to changes.diff file')
    parser.add_argument('--repo', default='', help='Path to local repo (for blast radius)')
    parser.add_argument('--service', required=True, help='Service name')
    parser.add_argument('--jira', required=True, help='Comma-separated JIRA IDs (e.g., ABC-123,ABC-124)')
    parser.add_argument('--commits', default='', help='Path to commits JSONL file')
    parser.add_argument('--out', required=True, help='Output directory')
    args = parser.parse_args()

    # Read diff
    diff_path = Path(args.diff)
    if not diff_path.exists() or diff_path.stat().st_size == 0:
        print(f"[ERROR] Diff file empty or missing: {args.diff}", file=sys.stderr)
        sys.exit(1)

    diff_text = diff_path.read_text(encoding='utf-8', errors='replace')
    file_diffs = parse_diff(diff_text)
    changed_files = get_changed_files(file_diffs)

    print(f"[*] Analyzing {len(changed_files)} source files (filtered from {len(file_diffs)} total)...")

    # Run all extractions
    stats = get_diff_stats(file_diffs)
    signatures = extract_signature_changes(file_diffs)
    removed = extract_removed_features(file_diffs)
    new_statuses = extract_new_status_values(file_diffs)
    tests = extract_test_changes(file_diffs)
    blast = find_blast_radius(file_diffs, args.repo, changed_files)
    commits = read_commits(args.commits)

    # Parse comma-separated JIRA IDs
    jira_ids_list = [jid.strip() for jid in args.jira.split(',')]

    # Build summary
    summary = {
        "service": args.service,
        "jira_id": jira_ids_list if len(jira_ids_list) > 1 else jira_ids_list[0],
        "jira_ids_analyzed": jira_ids_list,
        "changed_files": changed_files,
        "signature_changes": signatures,
        "removed_features": removed,
        "new_status_values": new_statuses,
        "blast_radius": blast,
        "test_changes": tests,
        "diff_stats": stats,
        "commits": commits,
    }

    # Write output
    os.makedirs(args.out, exist_ok=True)
    out_path = os.path.join(args.out, 'summary.json')
    with open(out_path, 'w') as f:
        json.dump(summary, f, indent=2)

    # Copy diff (filtered — exclude lockfiles)
    filtered_diff_path = os.path.join(args.out, 'changes.diff')
    with open(filtered_diff_path, 'w', encoding='utf-8') as f:
        for filepath, diff_content in file_diffs.items():
            if not should_exclude(filepath):
                f.write(diff_content)
                f.write('\n')

    # Print summary
    print(f"[OK] {args.service}: {len(changed_files)} files, {len(signatures)} signature changes, "
          f"{len(removed)} removals, {len(new_statuses)} new values, "
          f"{len(blast)} blast-radius files, "
          f"{len(tests.get('removed_tests', []))} removed tests")


if __name__ == '__main__':
    main()
