#!/usr/bin/env python3
"""
Test Case Selector — Intelligently selects tests based on PR risk analysis.

Usage:
  python3 select_tests_for_pr.py \
    --consolidated-summary pr-analysis/PROJ-1234/consolidated_summary.json \
    --test-index .test-cache/test_index.json \
    --output pr-analysis/PROJ-1234/test_selection.json

Selection Algorithm:
  1. For each HIGH-RISK service: select ALL tests for that service
  2. For each MEDIUM-RISK service: select feature-specific + regression pack (70%)
  3. For each LOW-RISK service: select regression pack only (30%)
  4. Always include: permission/auth tests, cross-service integration tests
  5. Add: performance/load tests if cache/scheduling changes detected

Output:
  test_selection.json with list of selected test cases + execution strategy
"""

import sys
import json
from pathlib import Path
from typing import Dict, List, Set, Any
import argparse


class TestSelector:
    """Selects tests based on risk analysis"""

    def __init__(self, consolidated_summary: Dict, test_index: Dict):
        self.consolidated = consolidated_summary
        self.test_index = test_index
        self.selected_tests = []
        self.selection_reasons = {}

    def select(self) -> Dict[str, Any]:
        """Execute test selection"""
        selected_test_ids = set()
        reasons = {}

        # 1. Select tests for each service based on risk level
        service_risks = self.consolidated.get("service_risks", {})
        for service, risk_data in service_risks.items():
            risk_level = risk_data.get("risk_level", "medium")
            tests_for_service = self._get_tests_for_service(service)

            if risk_level == "high":
                # HIGH RISK: Select ALL tests for this service
                selected_count = len(tests_for_service)
                selected_test_ids.update(t["id"] for t in tests_for_service)
                reasons[service] = f"HIGH RISK: Selected all {selected_count} tests"

            elif risk_level == "medium":
                # MEDIUM RISK: Select feature-specific tests + 70% regression
                # Derive changed feature/function names from high/medium_risk_changes for this service
                service_features = [
                    c.get("function", "") for c in self.consolidated.get("high_risk_changes", [])
                    if c.get("service") == service and c.get("function")
                ] + [
                    c.get("feature", "") for c in self.consolidated.get("medium_risk_changes", [])
                    if c.get("service") == service and c.get("feature")
                ]
                feature_tests = self._get_tests_by_feature(
                    tests_for_service,
                    service_features
                )
                regression_tests = self._get_regression_pack(tests_for_service, ratio=0.7)
                selected = set(t["id"] for t in feature_tests + regression_tests)
                selected_test_ids.update(selected)
                reasons[service] = f"MEDIUM RISK: {len(feature_tests)} feature tests + {len(regression_tests)} regression (70%)"

            else:  # low
                # LOW RISK: Select 30% regression pack only
                regression_tests = self._get_regression_pack(tests_for_service, ratio=0.3)
                selected_test_ids.update(t["id"] for t in regression_tests)
                reasons[service] = f"LOW RISK: {len(regression_tests)} regression tests (30%)"

        # 2. Include auth/login tests ONLY if the PR directly touches auth/login/permission code
        # (not as a blanket "HIGH RISK detected" fallback — login UI tests don't cover API auth enforcement)
        _AUTH_KWS = ("auth", "permission", "login", "cognito", "token", "role", "security", "access")

        def _item_matches_auth(item: dict) -> bool:
            return any(
                kw in str(item.get("function", "")).lower()
                or kw in str(item.get("file", "")).lower()
                or kw in str(item.get("feature", "")).lower()
                for kw in _AUTH_KWS
            )

        auth_relevant_services = [
            svc for svc in service_risks
            if any(_item_matches_auth(c) for c in self.consolidated.get("high_risk_changes", []) if c.get("service") == svc)
            or any(_item_matches_auth(c) for c in self.consolidated.get("medium_risk_changes", []) if c.get("service") == svc)
        ]
        if auth_relevant_services:
            auth_tests = self._get_tests_by_feature(
                self._all_tests(),
                ["auth", "permission", "authorization", "login", "security"]
            )
            auth_count_before = len(selected_test_ids)
            selected_test_ids.update(t["id"] for t in auth_tests)
            if len(selected_test_ids) > auth_count_before:
                reasons["auth_tests"] = f"AUTH CODE CHANGED in {', '.join(auth_relevant_services)}: Added {len(selected_test_ids) - auth_count_before} auth/login tests"

        # 3. Always include: cross-service integration tests
        transitive_impact = self.consolidated.get("transitive_impact", {})
        if transitive_impact:
            integration_tests = self._get_integration_tests(
                self._all_tests(),
                list(transitive_impact.keys()) + [s for impacts in transitive_impact.values() for s in impacts]
            )
            integration_count_before = len(selected_test_ids)
            selected_test_ids.update(t["id"] for t in integration_tests)
            if len(selected_test_ids) > integration_count_before:
                reasons["integration_tests"] = f"CROSS-SERVICE: Added {len(selected_test_ids) - integration_count_before} integration tests"

        # 4. Detect special patterns: cache, scheduling, etc.
        shared_impacts = self.consolidated.get("cross_service_analysis", {}).get("shared_cache_changes", [])
        if shared_impacts:
            cache_tests = self._get_tests_by_feature(
                self._all_tests(),
                ["cache", "redis", "memcached", "ttl"]
            )
            cache_count_before = len(selected_test_ids)
            selected_test_ids.update(t["id"] for t in cache_tests)
            if len(selected_test_ids) > cache_count_before:
                reasons["cache_tests"] = f"CACHE CHANGES: Added {len(selected_test_ids) - cache_count_before} cache tests"

        # 5. Convert IDs to full test objects
        all_tests_by_id = {t["id"]: t for t in self._all_tests()}
        selected_test_objects = [
            all_tests_by_id[test_id] for test_id in selected_test_ids
            if test_id in all_tests_by_id
        ]

        # Generate execution plan
        return {
            "jira_id": self.consolidated.get("jira_id", ""),
            "selection_timestamp": self.consolidated.get("analysis_timestamp", ""),
            "services_analyzed": self.consolidated.get("services_analyzed", []),
            "tests_selected": len(selected_test_objects),
            "selection_breakdown": reasons,
            "test_cases": selected_test_objects,
            "execution_strategy": self._generate_execution_plan(selected_test_objects),
        }

    def _all_tests(self) -> List[Dict]:
        """Get all tests from index"""
        return self.test_index.get("tests", [])

    def _get_tests_for_service(self, service: str) -> List[Dict]:
        """Get tests relevant to a service.

        Matching order:
        1. Exact service name match on test.service or test.tags
        2. Keyword match on file path / feature / tags using service name keywords
        3. No fallback — if nothing matches, return empty (avoids random unrelated tests)
        """
        all_tests = self._all_tests()

        # 1. Exact match (also allow substring match for org-prefixed service names)
        exact = [
            t for t in all_tests
            if t.get("service") == service
            or service in t.get("tags", [])
            or (t.get("service") and t["service"] in service)
            or (t.get("service") and service in t["service"])
        ]
        if exact:
            return exact

        # 2. Keyword match — strip org/module prefixes in order (longest first to avoid partial matches)
        # e.g. myorg-app-auth-service → auth-service → ['auth', 'service']
        # Add your org-specific prefixes here (longest first):
        svc_stripped = service
        for prefix in ("svc-",):
            svc_stripped = svc_stripped.replace(prefix, "", 1) if svc_stripped.startswith(prefix) else svc_stripped
        keywords = [k for k in svc_stripped.split("-") if len(k) > 1]
        if keywords:
            keyword_matched = [
                t for t in all_tests
                if any(
                    kw in (t.get("file", "") + t.get("feature", "") + " ".join(t.get("tags", [])) + t.get("service", "")).lower()
                    for kw in keywords)
            ]
            if keyword_matched:
                matched_dirs = {str(Path(t["file"]).parent) for t in keyword_matched}
                return [t for t in all_tests if str(Path(t["file"]).parent) in matched_dirs]

        # No match — return empty; do not fall back to the full suite
        return []

    def _get_tests_by_feature(self, tests: List[Dict], features: List[str]) -> List[Dict]:
        """Get tests matching any of the given features"""
        if not features:
            return []

        selected = []
        feature_keywords = [f.lower() for f in features]

        for test in tests:
            test_feature = test.get("feature", "").lower()
            test_tags = " ".join(t.lower() for t in test.get("tags", []))

            if any(kw in test_feature or kw in test_tags for kw in feature_keywords):
                selected.append(test)

        return selected

    def _get_regression_pack(self, tests: List[Dict], ratio: float) -> List[Dict]:
        """Select a percentage of tests as regression pack"""
        # Prefer tests tagged with @regression or critical paths
        critical_tests = [
            t for t in tests
            if "regression" in " ".join(t.get("tags", [])).lower() or
            "critical" in " ".join(t.get("tags", [])).lower()
        ]

        # If critical tests >= ratio, use them
        if len(critical_tests) >= len(tests) * ratio:
            return critical_tests[:int(len(tests) * ratio)]

        # Otherwise, mix critical + random selection
        remaining = int(len(tests) * ratio) - len(critical_tests)
        other_tests = [t for t in tests if t not in critical_tests]
        return critical_tests + other_tests[:remaining]

    def _get_integration_tests(self, all_tests: List[Dict], services: List[str]) -> List[Dict]:
        """Get tests that cover integration between services"""
        selected = []

        for test in all_tests:
            tags = " ".join(t.lower() for t in test.get("tags", []))
            # Look for tests tagged with multiple services or "integration"
            if "integration" in tags or "e2e" in tags or "end-to-end" in tags:
                selected.append(test)
            # Or tests for the affected services
            elif any(svc in test.get("service", "").lower() for svc in services):
                if "integration" in test.get("feature", "").lower():
                    selected.append(test)

        return selected

    def _generate_execution_plan(self, tests: List[Dict]) -> Dict[str, Any]:
        """Generate execution strategy"""
        # Group tests by framework
        by_framework = {}
        for test in tests:
            framework = test.get("framework", "unknown")
            if framework not in by_framework:
                by_framework[framework] = []
            by_framework[framework].append(test)

        # Estimate execution time (rough heuristic)
        estimated_minutes = sum(
            len(tests) * {
                "pytest": 0.5,
                "jest": 0.3,
                "junit": 0.7,
                "gherkin": 1.0,
                "golang": 0.5,
            }.get(framework, 0.5)
            for framework, tests in by_framework.items()
        )

        return {
            "total_tests": len(tests),
            "by_framework": {
                framework: len(tests) for framework, tests in by_framework.items()
            },
            "estimated_execution_minutes": int(estimated_minutes),
            "parallel_execution": len(by_framework) > 1,
            "execution_order": sorted(by_framework.keys()),
        }


def main():
    parser = argparse.ArgumentParser(description="Select test cases based on PR risk analysis")
    parser.add_argument("--consolidated-summary", required=True, help="Path to consolidated_summary.json")
    parser.add_argument("--test-index", required=True, help="Path to test_index.json")
    parser.add_argument("--output", required=True, help="Output file for test selection")

    args = parser.parse_args()

    # Load inputs
    try:
        with open(args.consolidated_summary) as f:
            consolidated = json.load(f)
    except Exception as e:
        print(f"[ERROR] Cannot load consolidated summary: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        with open(args.test_index) as f:
            test_index = json.load(f)
    except Exception as e:
        print(f"[ERROR] Cannot load test index: {e}", file=sys.stderr)
        sys.exit(1)

    # Select tests
    selector = TestSelector(consolidated, test_index)
    selection_result = selector.select()

    # Write output
    output_file = Path(args.output)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w") as f:
        json.dump(selection_result, f, indent=2)

    print(f"[OK] Test selection saved to {output_file}", file=sys.stderr)
    print(f"     Tests selected: {selection_result['tests_selected']}", file=sys.stderr)
    print(f"     Estimated execution: {selection_result['execution_strategy']['estimated_execution_minutes']} minutes", file=sys.stderr)
    print(f"     Frameworks: {', '.join(selection_result['execution_strategy']['by_framework'].keys())}", file=sys.stderr)


if __name__ == "__main__":
    main()
