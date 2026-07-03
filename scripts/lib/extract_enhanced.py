#!/usr/bin/env python3
"""
Enhanced PR analysis extractor — language-aware.

Detects the primary language(s) from the diff and applies the correct patterns
for signature changes, imports, test frameworks, exports, and blast-radius
file extensions.

Supported language families:
  - javascript / typescript  (JS/TS/JSX/TSX)
  - java                     (Java / Kotlin / Groovy)
  - python
  - go
  - csharp                   (C# / .NET)
  - generic                  (fallback — still produces diff_stats)

Adding a new language:  add a LANG_* dict and register it in LANGUAGE_PROFILES.

Usage:
  python3 scripts/lib/extract_enhanced.py \\
    --diff <changes.diff> \\
    --repo <path/to/repo> \\
    --service <name> \\
    --jira <JIRA_ID_1,JIRA_ID_2,...> \\
    --commits <commits_jsonl_file> \\
    --out <output_dir>
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

# ═══════════════════════════════════════════════════════════════════════════════
# LANGUAGE PROFILES
# ═══════════════════════════════════════════════════════════════════════════════
# Each profile defines patterns for ONE language family.  The detector picks
# profiles based on file extensions found in the diff.

LANG_JS = {
    "name": "javascript",
    "extensions": {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"},
    "exclude_patterns": [
        r'package-lock\.json$', r'yarn\.lock$', r'pnpm-lock\.yaml$',
        r'\.min\.js$', r'\.map$', r'node_modules/', r'dist/', r'build/',
    ],
    "grep_includes": ["*.ts", "*.tsx", "*.js", "*.jsx"],
    "grep_excludes": ["node_modules", "dist", "build", ".git"],
    # --- signatures ---
    "sig_pattern": (
        r'^[-+]\s*(?:export\s+)?(?:const|function|let|var)\s+'
        r'(\w+)\s*(?::\s*\w+)?\s*=?\s*(?:<[^>]+>\s*)?\(([^)]*)\)'
    ),
    "ret_pattern": (
        r'^[-+]\s*(?:export\s+)?(?:const|function)\s+(\w+).*\)\s*(?::\s*(.+?)\s*(?:=>|{|\{))'
    ),
    # --- imports ---
    "import_pattern": r'import\s+.*\{([^}]+)\}.*from',
    "component_pattern": r'<(\w+)[\s/>]',
    # --- exports (for blast radius) ---
    "export_patterns": [
        r'export\s+(?:const|function|type|interface|let|var)\s+(\w+)',
        r'export\s+\{([^}]+)\}',
    ],
    # --- enums / status values ---
    "enum_pattern": r'\[(\w+\.\w+)\]\s*:\s*[\'"]?(\w+)',
    "array_value_pattern": r"['\"](\w[\w\s]+\w)['\"]",
    "comment_prefixes": ("//", "*"),
    # --- tests ---
    "test_file_pattern": r'\.(test|spec)\.(tsx?|jsx?|js)$',
    "test_block_pattern": r"(?:it|test|describe)(?:\.each)?\s*\(\s*['\"`](.+?)['\"`]",
    "assertion_pattern": r"expect\(.*\)\.to\w+\((.+)\)",
}

LANG_JAVA = {
    "name": "java",
    "extensions": {".java", ".kt", ".groovy", ".scala"},
    "exclude_patterns": [
        r'/target/', r'\.class$', r'\.jar$', r'\.war$', r'\.ear$',
        r'build/', r'\.gradle\.kts?$', r'gradle-wrapper',
    ],
    "grep_includes": ["*.java", "*.kt", "*.groovy", "*.scala"],
    "grep_excludes": ["target", "build", ".git", ".gradle"],
    "sig_pattern": (
        r'^[-+]\s*(?:public|protected|private|static|final|abstract|synchronized|\s)*'
        r'(?:[\w<>\[\],\s]+)\s+(\w+)\s*\(([^)]*)\)'
    ),
    "ret_pattern": (
        r'^[-+]\s*(?:public|protected|private|static|final|abstract|\s)*'
        r'([\w<>\[\]]+)\s+(\w+)\s*\('
    ),
    "import_pattern": r'import\s+([\w.]+(?:\.\*)?)\s*;',
    "component_pattern": None,
    "export_patterns": [
        r'(?:public|protected)\s+(?:static\s+)?(?:final\s+)?(?:class|interface|enum|record)\s+(\w+)',
        r'(?:public|protected)\s+(?:static\s+)?(?:[\w<>\[\]]+)\s+(\w+)\s*\(',
    ],
    "enum_pattern": r'^\s*(\w+)\s*\((.+?)\)',
    "array_value_pattern": r'"(\w[\w\s]+\w)"',
    "comment_prefixes": ("//", "*", "/*"),
    "test_file_pattern": r'(?:Test|IT|Spec)\.(java|kt|groovy|scala)$',
    "test_block_pattern": r'(?:@Test|@ParameterizedTest|@RepeatedTest|def\s+"(.+?)").*?(?:void|fun)\s+(\w+)\s*\(',
    "assertion_pattern": r'(?:assert\w+|assertThat|expect\w*)\s*\((.+?)\)',
}

LANG_PYTHON = {
    "name": "python",
    "extensions": {".py", ".pyx", ".pyi"},
    "exclude_patterns": [
        r'__pycache__/', r'\.pyc$', r'\.pyo$', r'\.egg-info/',
        r'dist/', r'build/', r'venv/', r'\.venv/', r'poetry\.lock$',
        r'Pipfile\.lock$',
    ],
    "grep_includes": ["*.py"],
    "grep_excludes": ["__pycache__", "venv", ".venv", "dist", "build", ".git"],
    "sig_pattern": r'^[-+]\s*(?:async\s+)?def\s+(\w+)\s*\(([^)]*)\)',
    "ret_pattern": r'^[-+]\s*(?:async\s+)?def\s+(\w+)\s*\(.*\)\s*->\s*(.+?)\s*:',
    "import_pattern": r'(?:from\s+([\w.]+)\s+import\s+(.+)|import\s+([\w.]+))',
    "component_pattern": None,
    "export_patterns": [
        r'(?:def|class)\s+(\w+)',
        r'(\w+)\s*=\s*',
    ],
    "enum_pattern": r'(\w+)\s*=\s*[\'"](\w+)[\'"]',
    "array_value_pattern": r'[\'"](\w[\w\s]+\w)[\'"]',
    "comment_prefixes": ("#",),
    "test_file_pattern": r'(?:test_\w+|_test)\.py$',
    "test_block_pattern": r'(?:def\s+(test_\w+)|class\s+(Test\w+))',
    "assertion_pattern": r'(?:assert\s+(.+)|self\.assert\w+\((.+?)\)|pytest\.\w+\((.+?)\))',
}

LANG_GO = {
    "name": "go",
    "extensions": {".go"},
    "exclude_patterns": [
        r'vendor/', r'go\.sum$',
    ],
    "grep_includes": ["*.go"],
    "grep_excludes": ["vendor", ".git"],
    "sig_pattern": r'^[-+]\s*func\s+(?:\(\w+\s+\*?\w+\)\s+)?(\w+)\s*\(([^)]*)\)',
    "ret_pattern": r'^[-+]\s*func\s+(?:\(\w+\s+\*?\w+\)\s+)?(\w+)\s*\(.*\)\s+(.+?)\s*\{',
    "import_pattern": r'"([\w./\-]+)"',
    "component_pattern": None,
    "export_patterns": [
        r'func\s+(?:\(\w+\s+\*?\w+\)\s+)?([A-Z]\w*)\s*\(',
        r'type\s+([A-Z]\w*)\s+(?:struct|interface)',
    ],
    "enum_pattern": r'(\w+)\s*=\s*(?:iota|"(\w+)")',
    "array_value_pattern": r'"(\w[\w\s]+\w)"',
    "comment_prefixes": ("//",),
    "test_file_pattern": r'_test\.go$',
    "test_block_pattern": r'func\s+(Test\w+|Benchmark\w+)\s*\(',
    "assertion_pattern": r'(?:assert\.\w+|require\.\w+)\s*\(\s*\w+\s*,\s*(.+?)\)',
}

LANG_CSHARP = {
    "name": "csharp",
    "extensions": {".cs", ".csx"},
    "exclude_patterns": [
        r'/bin/', r'/obj/', r'\.dll$', r'\.exe$', r'\.nupkg$',
    ],
    "grep_includes": ["*.cs"],
    "grep_excludes": ["bin", "obj", ".git"],
    "sig_pattern": (
        r'^[-+]\s*(?:public|protected|private|internal|static|virtual|override|async|\s)*'
        r'(?:[\w<>\[\]?]+)\s+(\w+)\s*\(([^)]*)\)'
    ),
    "ret_pattern": (
        r'^[-+]\s*(?:public|protected|private|internal|static|virtual|override|async|\s)*'
        r'([\w<>\[\]?]+)\s+(\w+)\s*\('
    ),
    "import_pattern": r'using\s+([\w.]+)\s*;',
    "component_pattern": None,
    "export_patterns": [
        r'(?:public|internal)\s+(?:partial\s+)?(?:class|interface|enum|record|struct)\s+(\w+)',
        r'(?:public|internal)\s+(?:static\s+)?(?:[\w<>\[\]?]+)\s+(\w+)\s*\(',
    ],
    "enum_pattern": r'^\s*(\w+)\s*=\s*(\d+)',
    "array_value_pattern": r'"(\w[\w\s]+\w)"',
    "comment_prefixes": ("//", "*", "/*"),
    "test_file_pattern": r'(?:Tests?|Spec)\.cs$',
    "test_block_pattern": r'(?:\[(?:Test|Fact|Theory)\].*?)?(?:public|private)\s+(?:async\s+)?(?:Task\s+|void\s+)(\w+)\s*\(',
    "assertion_pattern": r'(?:Assert\.\w+|Should\.\w+|Expect\.\w+)\s*\((.+?)\)',
}

# Registry — order matters only for tie-breaking; detection counts extensions.
LANGUAGE_PROFILES = [LANG_JS, LANG_JAVA, LANG_PYTHON, LANG_GO, LANG_CSHARP]


# ═══════════════════════════════════════════════════════════════════════════════
# LANGUAGE DETECTION
# ═══════════════════════════════════════════════════════════════════════════════

def detect_languages(file_diffs: dict) -> list:
    """Return list of matching language profiles sorted by file count (desc)."""
    ext_counts = {}
    for filepath in file_diffs:
        ext = _file_ext(filepath)
        ext_counts[ext] = ext_counts.get(ext, 0) + 1

    profile_scores = []
    for profile in LANGUAGE_PROFILES:
        score = sum(ext_counts.get(e, 0) for e in profile["extensions"])
        if score > 0:
            profile_scores.append((score, profile))

    profile_scores.sort(key=lambda x: x[0], reverse=True)
    profiles = [p for _, p in profile_scores]

    if not profiles:
        # Fallback — return a minimal "generic" profile
        profiles = [_generic_profile()]

    return profiles


def _file_ext(filepath: str) -> str:
    return os.path.splitext(filepath)[1].lower()


def _generic_profile() -> dict:
    """Minimal profile that still produces diff_stats for unknown languages."""
    return {
        "name": "generic",
        "extensions": set(),
        "exclude_patterns": [r'\.lock$', r'dist/', r'build/'],
        "grep_includes": [],
        "grep_excludes": [".git"],
        "sig_pattern": None,
        "ret_pattern": None,
        "import_pattern": None,
        "component_pattern": None,
        "export_patterns": [],
        "enum_pattern": None,
        "array_value_pattern": None,
        "comment_prefixes": ("//", "#", "*"),
        "test_file_pattern": None,
        "test_block_pattern": None,
        "assertion_pattern": None,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# EXCLUDE FILTER — union of all matched profiles
# ═══════════════════════════════════════════════════════════════════════════════

def build_exclude_checker(profiles: list):
    """Return a should_exclude(filepath) function combining all profiles."""
    all_patterns = []
    for p in profiles:
        all_patterns.extend(p.get("exclude_patterns", []))
    # Deduplicate
    all_patterns = list(dict.fromkeys(all_patterns))
    compiled = [re.compile(pat) for pat in all_patterns]

    def _check(filepath: str) -> bool:
        return any(rx.search(filepath) for rx in compiled)

    return _check


# ═══════════════════════════════════════════════════════════════════════════════
# DIFF PARSING (language-agnostic)
# ═══════════════════════════════════════════════════════════════════════════════

def parse_diff(diff_text: str) -> dict:
    """Parse unified diff into per-file sections.

    Handles both standard git format (diff --git a/foo b/foo)
    and Bitbucket Server format (diff --git src://foo dst://foo).
    """
    files = {}
    current_file = None
    current_lines = []

    def _extract_filename(git_line: str) -> str:
        # Standard format: diff --git a/path b/path
        m = re.search(r'\bb/(.+)$', git_line)
        if m:
            return m.group(1).strip()
        # Bitbucket Server format: diff --git src://path dst://path
        m = re.search(r'dst://(.+)$', git_line)
        if m:
            return m.group(1).strip()
        # Fallback: last token after space
        parts = git_line.split()
        return parts[-1].lstrip('/') if parts else None

    def _is_phantom(f: str) -> bool:
        return f is None or "/dev/null" in f or f.startswith("+++ ")

    for line in diff_text.splitlines():
        if line.startswith('diff --git'):
            if current_file and not _is_phantom(current_file):
                files[current_file] = '\n'.join(current_lines)
            current_file = _extract_filename(line)
            current_lines = [line]
        elif current_file:
            # If we got a generic filename from _extract_filename and now
            # see +++ src:// or +++ dst:// we can refine it
            if line.startswith('+++ '):
                refined = re.sub(r'^\+\+\+\s+(dst://|b/)', '', line).strip()
                if refined and refined != '/dev/null':
                    current_file = refined
            current_lines.append(line)

    if current_file and not _is_phantom(current_file):
        files[current_file] = '\n'.join(current_lines)

    return files


def get_changed_files(file_diffs: dict, should_exclude) -> list:
    return sorted(
        f for f in file_diffs
        if not should_exclude(f)
        and "/dev/null" not in f
        and not f.startswith("+++ ")
    )


def get_diff_stats(file_diffs: dict, should_exclude) -> dict:
    added = removed = 0
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


# ═══════════════════════════════════════════════════════════════════════════════
# EXTRACTION FUNCTIONS — driven by profile patterns
# ═══════════════════════════════════════════════════════════════════════════════

def _profile_for_file(filepath: str, profiles: list) -> dict:
    """Return the best-matching profile for a filepath, or the first profile."""
    ext = _file_ext(filepath)
    for p in profiles:
        if ext in p["extensions"]:
            return p
    return profiles[0]


def extract_signature_changes(file_diffs: dict, profiles: list, should_exclude) -> list:
    changes = []

    for filepath, diff in file_diffs.items():
        if should_exclude(filepath):
            continue
        prof = _profile_for_file(filepath, profiles)
        sig_pat = prof.get("sig_pattern")
        if not sig_pat:
            continue

        old_sigs = {}
        new_sigs = {}

        for line in diff.splitlines():
            m = re.search(sig_pat, line)
            if m:
                name = m.group(1)
                params = m.group(2).strip() if m.lastindex >= 2 else ""
                if line.startswith('-'):
                    old_sigs[name] = params
                elif line.startswith('+'):
                    new_sigs[name] = params

        for name in set(old_sigs) & set(new_sigs):
            if old_sigs[name] != new_sigs[name]:
                changes.append({
                    "function": name,
                    "file": os.path.basename(filepath),
                    "old_params": f"({old_sigs[name]})",
                    "new_params": f"({new_sigs[name]})",
                })

        # Return type changes
        ret_pat = prof.get("ret_pattern")
        if not ret_pat:
            continue

        old_ret = {}
        new_ret = {}
        for line in diff.splitlines():
            m = re.search(ret_pat, line)
            if m:
                # For Java-style the return type is group(1), name is group(2)
                if prof["name"] in ("java", "csharp"):
                    ret_type, name = m.group(1).strip(), m.group(2)
                else:
                    name, ret_type = m.group(1), m.group(2).strip()
                if line.startswith('-'):
                    old_ret[name] = ret_type
                elif line.startswith('+'):
                    new_ret[name] = ret_type

        for name in set(old_ret) & set(new_ret):
            if old_ret[name] != new_ret[name]:
                existing = [c for c in changes if c['function'] == name]
                if existing:
                    existing[0]['old_return'] = old_ret[name]
                    existing[0]['new_return'] = new_ret[name]
                else:
                    changes.append({
                        "function": name,
                        "file": os.path.basename(filepath),
                        "old_return": old_ret[name],
                        "new_return": new_ret[name],
                    })

    return changes


def extract_removed_features(file_diffs: dict, profiles: list, should_exclude) -> list:
    removed = []

    for filepath, diff in file_diffs.items():
        if should_exclude(filepath):
            continue
        prof = _profile_for_file(filepath, profiles)
        fname = os.path.basename(filepath)
        added_lines = [l for l in diff.splitlines() if l.startswith('+')]

        for line in diff.splitlines():
            if not line.startswith('-') or line.startswith('---'):
                continue
            clean = line[1:].strip()

            # Imports
            imp_pat = prof.get("import_pattern")
            if imp_pat:
                imp_m = re.search(imp_pat, clean)
                if imp_m:
                    # Handle multi-group patterns (JS destructured, Python from..import)
                    names = []
                    for g in imp_m.groups():
                        if g:
                            names.extend(n.strip() for n in g.split(','))
                    for name in names:
                        name = name.strip().rstrip(';')
                        if name and not any(name in al for al in added_lines):
                            removed.append(f"{name} import removed from {fname}")

            # JSX components (JS/TS only)
            comp_pat = prof.get("component_pattern")
            if comp_pat:
                comp_m = re.search(comp_pat, clean)
                if comp_m:
                    comp_name = comp_m.group(1)
                    if comp_name[0].isupper():
                        if not any(f'<{comp_name}' in al for al in added_lines):
                            removed.append(f"<{comp_name}> usage removed from {fname}")

    return list(dict.fromkeys(removed))


def extract_new_status_values(file_diffs: dict, profiles: list, should_exclude) -> list:
    new_values = []

    for filepath, diff in file_diffs.items():
        if should_exclude(filepath):
            continue
        prof = _profile_for_file(filepath, profiles)
        fname = os.path.basename(filepath)
        comment_pats = prof.get("comment_prefixes", ("//", "#", "*"))

        for line in diff.splitlines():
            if not line.startswith('+') or line.startswith('+++'):
                continue
            clean = line[1:].strip()
            if any(clean.startswith(c) for c in comment_pats):
                continue

            enum_pat = prof.get("enum_pattern")
            if enum_pat:
                em = re.search(enum_pat, clean)
                if em:
                    new_values.append({
                        "file": fname,
                        "entry": em.group(1),
                        "value": em.group(2) if em.lastindex >= 2 else em.group(1),
                    })
                    continue

            arr_pat = prof.get("array_value_pattern")
            if arr_pat:
                am = re.search(arr_pat, clean)
                if am and re.search(r'[\[\],;]', clean):
                    new_values.append({
                        "file": fname,
                        "entry": "array/list",
                        "value": am.group(1),
                    })

    seen = set()
    unique = []
    for v in new_values:
        key = f"{v['entry']}:{v['value']}"
        if key not in seen:
            seen.add(key)
            unique.append(v)
    return unique


def extract_test_changes(file_diffs: dict, profiles: list, should_exclude) -> dict:
    modified_assertions = []
    removed_tests = []
    added_tests = []

    for filepath, diff in file_diffs.items():
        if should_exclude(filepath):
            continue
        prof = _profile_for_file(filepath, profiles)
        test_file_pat = prof.get("test_file_pattern")
        if not test_file_pat or not re.search(test_file_pat, filepath):
            continue

        test_pat = prof.get("test_block_pattern")
        assert_pat = prof.get("assertion_pattern")
        diff_lines = diff.splitlines()
        added_lines = [l for l in diff_lines if l.startswith('+')]
        removed_lines = [l for l in diff_lines if l.startswith('-')]

        for line in diff_lines:
            clean = line[1:].strip() if len(line) > 1 else ''

            if test_pat:
                if line.startswith('-'):
                    tm = re.search(test_pat, clean)
                    if tm:
                        test_name = next((g for g in tm.groups() if g), None)
                        if test_name and not any(test_name in al for al in added_lines):
                            removed_tests.append(test_name)

                if line.startswith('+'):
                    tm = re.search(test_pat, clean)
                    if tm:
                        test_name = next((g for g in tm.groups() if g), None)
                        if test_name and not any(test_name in rl for rl in removed_lines):
                            added_tests.append(test_name)

            if assert_pat and line.startswith('-'):
                am = re.search(assert_pat, clean)
                if am:
                    old_val = next((g.strip() for g in am.groups() if g), None)
                    if old_val:
                        for aline in added_lines:
                            aclean = aline[1:].strip()
                            am2 = re.search(assert_pat, aclean)
                            if am2:
                                new_val = next((g.strip() for g in am2.groups() if g), None)
                                if new_val and old_val != new_val and _similar_context(clean, aclean):
                                    modified_assertions.append(f"{old_val} → {new_val}")
                                    break

    return {
        "modified_assertions": list(dict.fromkeys(modified_assertions))[:20],
        "removed_tests": list(dict.fromkeys(removed_tests)),
        "added_tests": list(dict.fromkeys(added_tests)),
    }


def _similar_context(line_a: str, line_b: str) -> bool:
    a = re.sub(r"['\"].*?['\"]", 'X', line_a)
    b = re.sub(r"['\"].*?['\"]", 'X', line_b)
    a = re.sub(r'\d+', 'N', a)
    b = re.sub(r'\d+', 'N', b)
    return a == b


def find_blast_radius(file_diffs: dict, repo_path: str, changed_files: list,
                      profiles: list, should_exclude) -> list:
    if not repo_path or not os.path.isdir(repo_path):
        if not repo_path:
            print("[blast_radius] SKIP: --repo not provided; intra-repo impact analysis skipped",
                  file=sys.stderr)
        else:
            print(f"[blast_radius] SKIP: repo path does not exist: {repo_path}",
                  file=sys.stderr)
        return []

    # Collect exported names using per-file profile
    exported_names = set()
    for filepath, diff in file_diffs.items():
        if should_exclude(filepath):
            continue
        prof = _profile_for_file(filepath, profiles)
        export_pats = prof.get("export_patterns", [])

        for line in diff.splitlines():
            if not (line.startswith('+') or line.startswith('-')):
                continue
            clean = line[1:].strip()
            for pat in export_pats:
                em = re.search(pat, clean)
                if em:
                    for g in em.groups():
                        if g:
                            for n in g.split(','):
                                name = n.strip().split(' as ')[0].strip()
                                if name and name[0].isalpha():
                                    exported_names.add(name)

    if not exported_names:
        return []

    # Build grep args from all profiles
    include_args = []
    exclude_args = []
    seen_inc = set()
    seen_exc = set()
    for prof in profiles:
        for inc in prof.get("grep_includes", []):
            if inc not in seen_inc:
                include_args.extend(["--include", inc])
                seen_inc.add(inc)
        for exc in prof.get("grep_excludes", []):
            if exc not in seen_exc:
                exclude_args.extend([f"--exclude-dir={exc}"])
                seen_exc.add(exc)

    if not include_args:
        return []

    pattern = '|'.join(re.escape(n) for n in exported_names)
    changed_basenames = {os.path.basename(f) for f in changed_files}

    blast = []
    try:
        cmd = ['grep', '-rl', '-E', pattern] + include_args + exclude_args
        result = subprocess.run(
            cmd, capture_output=True, text=True, cwd=repo_path, timeout=30
        )
        if result.returncode == 0:
            for hit_file in result.stdout.strip().splitlines():
                hit_base = os.path.basename(hit_file)
                if hit_base not in changed_basenames and hit_file not in changed_files:
                    for name in exported_names:
                        try:
                            g2 = subprocess.run(
                                ['grep', '-l', name, hit_file],
                                capture_output=True, text=True,
                                cwd=repo_path, timeout=5
                            )
                            if g2.returncode == 0:
                                blast.append({"file": hit_file, "uses": name})
                        except subprocess.TimeoutExpired:
                            continue
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    grouped = {}
    for item in blast:
        f = item['file']
        if f not in grouped:
            grouped[f] = {"file": f, "uses": []}
        if item['uses'] not in grouped[f]['uses']:
            grouped[f]['uses'].append(item['uses'])
    return list(grouped.values())


# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def read_commits(commits_file: str) -> list:
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


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

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

    # Detect language(s) and build exclude filter
    profiles = detect_languages(file_diffs)
    lang_names = [p["name"] for p in profiles]
    print(f"[*] Detected language(s): {', '.join(lang_names)}")

    should_exclude = build_exclude_checker(profiles)
    changed_files = get_changed_files(file_diffs, should_exclude)

    print(f"[*] Analyzing {len(changed_files)} source files (filtered from {len(file_diffs)} total)...")

    # Run all extractions
    stats = get_diff_stats(file_diffs, should_exclude)
    signatures = extract_signature_changes(file_diffs, profiles, should_exclude)
    removed = extract_removed_features(file_diffs, profiles, should_exclude)
    new_statuses = extract_new_status_values(file_diffs, profiles, should_exclude)
    tests = extract_test_changes(file_diffs, profiles, should_exclude)
    blast = find_blast_radius(file_diffs, args.repo, changed_files, profiles, should_exclude)
    commits = read_commits(args.commits)

    jira_ids_list = [jid.strip() for jid in args.jira.split(',')]

    summary = {
        "service": args.service,
        "jira_id": jira_ids_list if len(jira_ids_list) > 1 else jira_ids_list[0],
        "jira_ids_analyzed": jira_ids_list,
        "languages_detected": lang_names,
        "changed_files": changed_files,
        "signature_changes": signatures,
        "removed_features": removed,
        "new_status_values": new_statuses,
        "blast_radius": blast,
        "test_changes": tests,
        "diff_stats": stats,
        "commits": commits,
    }

    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, 'summary.json'), 'w') as f:
        json.dump(summary, f, indent=2)

    with open(os.path.join(args.out, 'changes.diff'), 'w', encoding='utf-8') as f:
        for filepath, diff_content in file_diffs.items():
            if not should_exclude(filepath):
                f.write(diff_content)
                f.write('\n')

    print(f"[OK] {args.service}: {len(changed_files)} files, {len(signatures)} signature changes, "
          f"{len(removed)} removals, {len(new_statuses)} new values, "
          f"{len(blast)} blast-radius files, "
          f"{len(tests.get('removed_tests', []))} removed tests")


if __name__ == '__main__':
    main()
