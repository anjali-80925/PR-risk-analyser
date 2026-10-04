#!/usr/bin/env python3
"""
Test Suite Indexer — Scans automation repo and builds searchable test index.

Usage:
  python3 index_tests.py \
    --repo-url git@github.com:your-org/automated-tests.git \
    --cache-dir .test-cache \
    --output test_index.json

Output:
  test_index.json with structure:
    {
      "services": ["dtb-be", "dtb-fe-react-v1", ...],
      "frameworks": ["pytest", "jest", "junit", ...],
      "tests": [
        {
          "id": "test_auth_login",
          "file": "tests/auth/test_login.py",
          "framework": "pytest",
          "tags": ["@service:auth", "@feature:login", "@risk:high"],
          "service": "dtb-be",
          "feature": "login",
          "risk": "high",
          "class": "TestAuthLogin",
          "method": "test_login_success"
        },
        ...
      ]
    }
"""

import sys
import os
import json
import re
import subprocess
from pathlib import Path
from typing import Dict, List, Set, Any
from collections import defaultdict


class TestIndexer:
    """Scans test directories and builds searchable index"""

    def __init__(self, repo_path: Path):
        self.repo_path = repo_path
        self.tests = []
        self.services = set()
        self.frameworks = set()

    def index_all_tests(self):
        """Recursively scan repo for test files"""
        test_patterns = {
            "pytest": ["test_*.py", "*_test.py"],
            "jest": ["*.test.ts", "*.test.tsx", "*.test.js", "*.spec.ts", "*.spec.tsx", "*.spec.js", "*.spec.mts", "*.test.mts"],
            "junit": ["*Test.java", "*Tests.java"],
            "golang": ["*_test.go"],
            "nunit": ["*.Tests.cs", "*Test.cs"],
            "gherkin": ["*.feature"],
        }

        for framework, patterns in test_patterns.items():
            for pattern in patterns:
                for test_file in self.repo_path.rglob(pattern):
                    if self._is_valid_test_file(test_file):
                        self.frameworks.add(framework)
                        tests_found = self._parse_test_file(test_file, framework)
                        self.tests.extend(tests_found)

    def _is_valid_test_file(self, file_path: Path) -> bool:
        """Check if file should be indexed"""
        # Skip node_modules, vendor, dist, build, etc.
        skip_dirs = {"node_modules", "vendor", ".git", "dist", "build", "target", "bin"}
        for part in file_path.parts:
            if part in skip_dirs:
                return False
        return True

    def _parse_test_file(self, file_path: Path, framework: str) -> List[Dict]:
        """Parse test file and extract test cases"""
        tests = []

        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except Exception as e:
            print(f"[WARN] Cannot read {file_path}: {e}", file=sys.stderr)
            return tests

        # Extract service name from path (heuristic: directory structure)
        service = self._extract_service_name(file_path)
        if service:
            self.services.add(service)

        # Parse based on framework
        if framework == "pytest":
            tests = self._parse_pytest(file_path, content, service)
        elif framework == "jest":
            tests = self._parse_jest(file_path, content, service)
        elif framework == "junit":
            tests = self._parse_junit(file_path, content, service)
        elif framework == "gherkin":
            tests = self._parse_gherkin(file_path, content, service)

        return tests

    def _extract_service_name(self, file_path: Path) -> str:
        """Extract service name from file path.

        Strategy (first match wins):
        1. Scan path parts from innermost to outermost for known service prefixes.
           This catches a subdirectory like 'dtb-be' before the repo root
           'my-org-automated-tests'.
        2. Check the first 500 bytes of the file for an @service:<name> annotation.
        3. Fall back to the first path part (from innermost) that contains a hyphen
           and is not a generic directory name.
        """
        service_pattern = re.compile(
            r"^[\w]+-[\w-]+$"
        )
        # 1. Reversed path parts (file name itself excluded)
        for part in reversed(file_path.parts[:-1]):
            if service_pattern.match(part):
                return part

        # 2. @service: annotation in file header
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as _f:
                head = _f.read(500)
            m = re.search(r"@service[:\s]+([\w][\w-]*)", head)
            if m:
                return m.group(1)
        except Exception:
            pass

        return ""

    def _parse_pytest(self, file_path: Path, content: str, service: str) -> List[Dict]:
        """Extract test cases from pytest file"""
        tests = []

        # Extract @pytest decorators and test functions
        # Pattern: def test_something(...):
        test_func_pattern = r"def (test_\w+)\s*\("
        test_functions = re.findall(test_func_pattern, content)

        # Extract decorator/comment tags: @tag, # @service:*, # @feature:*, # @risk:*
        tags  = list(dict.fromkeys(re.findall(r"@(\w+(?::\w+)?)", content)))
        
        # Extract marks: @pytest.mark.service_auth, etc.
        marks = list(dict.fromkeys(re.findall(r"@pytest\.mark\.(\w+)", content)))

        for test_func in test_functions:
            test_data = {
                "id": f"{file_path.stem}::{test_func}",
                "name": test_func,
                "file": str(file_path.relative_to(self.repo_path)),
                "framework": "pytest",
                "function": test_func,
                "tags": tags or [f"@service:{service}"],
                "service": service or "unknown",
                "feature": self._extract_feature_from_tags(tags),
                "risk": self._extract_risk_from_tags(tags),
                "marks": marks,
            }
            tests.append(test_data)

        return tests

    def _parse_jest(self, file_path: Path, content: str, service: str) -> List[Dict]:
        """Extract test cases from Jest file"""
        tests = []

        # Pattern: describe(...) { test(...) { ... } }
        # Or: it(...) { ... }
        test_pattern = r"(?:describe|test|it)\s*\(\s*['\"]([^'\"]+)['\"]"
        test_cases = re.findall(test_pattern, content)

        # Extract tags from comments
        file_tags = list(dict.fromkeys(re.findall(r"@(\w+(?::\w+)?)", content)))

        for test_case in test_cases:
            inline_tags = list(dict.fromkeys(re.findall(r"@(\w+(?::\w+)?)", test_case)))
            effective_tags = inline_tags if inline_tags else file_tags
            test_data = {
                "id": f"{file_path.stem}::{test_case}",
                "name": test_case,
                "file": str(file_path.relative_to(self.repo_path)),
                "framework": "jest",
                "testCase": test_case,
                "tags": effective_tags or [f"@service:{service}"],
                "service": service or "unknown",
                "feature": self._extract_feature_from_tags(effective_tags),
                "risk": self._extract_risk_from_tags(effective_tags),
            }
            tests.append(test_data)

        return tests

    def _parse_junit(self, file_path: Path, content: str, service: str) -> List[Dict]:
        """Extract test cases from JUnit file"""
        tests = []

        # Pattern: public void testSomething() or @Test public void something()
        test_pattern = r"(?:public\s+)?void\s+(test\w+|check\w+)\s*\("
        test_methods = re.findall(test_pattern, content)

        # Extract class name
        class_pattern = r"public\s+class\s+(\w+)"
        class_match = re.search(class_pattern, content)
        class_name = class_match.group(1) if class_match else "Unknown"

        # Extract tags
        tags = list(dict.fromkeys(re.findall(r"@(\w+(?::\w+)?)", content)))

        for test_method in test_methods:
            test_data = {
                "id": f"{class_name}::{test_method}",
                "name": test_method,
                "file": str(file_path.relative_to(self.repo_path)),
                "framework": "junit",
                "class": class_name,
                "method": test_method,
                "tags": tags or [f"@service:{service}"],
                "service": service or "unknown",
                "feature": self._extract_feature_from_tags(tags),
                "risk": self._extract_risk_from_tags(tags),
            }
            tests.append(test_data)

        return tests

    def _parse_gherkin(self, file_path: Path, content: str, service: str) -> List[Dict]:
        """Extract scenarios from Gherkin files"""
        tests = []

        # Pattern: Scenario: Description
        scenario_pattern = r"Scenario:\s+(.+?)(?=\n(?:Scenario:|Feature:|$))"
        scenarios = re.findall(scenario_pattern, content, re.DOTALL)

        # Extract tags
        tags = list(dict.fromkeys(re.findall(r"@(\w+(?::\w+)?)", content)))

        for scenario in scenarios:
            # Extract feature name
            feature_match = re.search(r"Feature:\s+(.+?)$", content, re.MULTILINE)
            feature = feature_match.group(1) if feature_match else "Unknown"

            scenario_title = scenario.split("\n")[0].strip()
            test_data = {
                "id": f"{file_path.stem}::{scenario_title[:50]}",
                "name": scenario_title,
                "file": str(file_path.relative_to(self.repo_path)),
                "framework": "gherkin",
                "scenario": scenario_title,
                "feature": feature,
                "tags": tags or [f"@service:{service}"],
                "service": service or "unknown",
                "risk": self._extract_risk_from_tags(tags),
            }
            tests.append(test_data)

        return tests

    @staticmethod
    def _extract_feature_from_tags(tags: List[str]) -> str:
        """Extract feature from @feature:name tag"""
        for tag in tags:
            if tag.startswith("feature:"):
                return tag.split(":")[1]
        return ""

    @staticmethod
    def _extract_risk_from_tags(tags: List[str]) -> str:
        """Extract risk level from @risk:level tag"""
        for tag in tags:
            if tag.startswith("risk:"):
                return tag.split(":")[1]
        return "medium"  # default

    def generate_index(self) -> Dict[str, Any]:
        """Generate searchable index"""
        return {
            "metadata": {
                "total_tests": len(self.tests),
                "services": sorted(list(self.services)),
                "frameworks": sorted(list(self.frameworks)),
            },
            "tests": self.tests,
        }


def _git_cmd() -> str:
    """Use git.exe (Windows Git with SSH agent) if available, else fall back to git."""
    import shutil
    return "git.exe" if shutil.which("git.exe") else "git"


def clone_repo(repo_url: str, cache_dir: Path) -> Path:
    """Clone or update automation repo"""
    repo_name = repo_url.rstrip("/").split("/")[-1].removesuffix(".git")
    repo_path = cache_dir / repo_name
    git = _git_cmd()

    if repo_path.exists():
        print(f"[INFO] Fetching latest changes from {repo_url}...", file=sys.stderr)
        result = subprocess.run(
            [git, "-C", str(repo_path), "fetch", "--all"],
            capture_output=True,
        )
        if result.returncode != 0:
            print(f"[WARN] Fetch failed: {result.stderr.decode()}", file=sys.stderr)
    else:
        print(f"[INFO] Cloning {repo_url}...", file=sys.stderr)
        cache_dir.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            [git, "clone", repo_url, str(repo_path)],
            capture_output=True,
        )
        if result.returncode != 0:
            print(f"[ERROR] Clone failed: {result.stderr.decode()}", file=sys.stderr)
            return None

    return repo_path


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Index test automation repository")
    parser.add_argument("--repo-url", help="Git URL of automation repo (used when --repo-path not set)")
    parser.add_argument("--repo-path", help="Local path to already-cloned automation repo (skips cloning)")
    parser.add_argument("--cache-dir", default=".test-cache", help="Cache directory for cloned repo")
    parser.add_argument("--output", required=True, help="Output JSON file")

    args = parser.parse_args()

    if args.repo_path:
        repo_path = Path(args.repo_path)
        if not repo_path.exists():
            print(f"[ERROR] --repo-path does not exist: {repo_path}", file=sys.stderr)
            sys.exit(1)
        print(f"[INFO] Using local repo at {repo_path}", file=sys.stderr)
    elif args.repo_url:
        cache_dir = Path(args.cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        repo_path = clone_repo(args.repo_url, cache_dir)
        if not repo_path:
            sys.exit(1)
    else:
        print("[ERROR] Either --repo-url or --repo-path must be provided", file=sys.stderr)
        sys.exit(1)

    print(f"[OK] Repo ready at {repo_path}", file=sys.stderr)

    # Index tests
    print(f"[INFO] Indexing tests...", file=sys.stderr)
    indexer = TestIndexer(repo_path)
    indexer.index_all_tests()

    index_data = indexer.generate_index()

    # Write output
    output_file = Path(args.output)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w") as f:
        json.dump(index_data, f, indent=2)

    print(f"[OK] Index saved to {output_file}", file=sys.stderr)
    print(f"     Total tests: {index_data['metadata']['total_tests']}", file=sys.stderr)
    print(f"     Services: {', '.join(index_data['metadata']['services'][:5])}{'...' if len(index_data['metadata']['services']) > 5 else ''}", file=sys.stderr)
    print(f"     Frameworks: {', '.join(index_data['metadata']['frameworks'])}", file=sys.stderr)


if __name__ == "__main__":
    main()
