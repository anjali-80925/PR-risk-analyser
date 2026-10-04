#!/usr/bin/env python3
"""
PR Analyzer Profile - QA Analysis Report Generator
Applies copilot-instructions PR Analyzer profile to generate clean QA analysis

Usage:
  python3 analyze_pr_with_profile.py \
    --consolidated-file pr-analysis/PROJ-1234/consolidated.json \
    --output pr-analysis/PROJ-1234/qa_analysis.md
"""

import sys
import json
from pathlib import Path
from typing import Dict, List, Any
import argparse


class PRAnalyzerProfile:
    """Implements PR Analyzer profile from copilot-instructions"""

    # Profile configuration from copilot-instructions.md
    RISK_CLASSIFICATION = {
        "high": [
            "Data loss or corruption",
            "Security/permission bypass",
            "Payment or financial impact",
            "Cross-service cascade failures",
            "Backward compatibility breaks",
        ],
        "medium": [
            "State transition errors",
            "Validation failures",
            "Filter/query incorrect results",
            "Performance degradation",
            "UI/UX blocking issues",
            "Edge case handling",
            "Minor UI inconsistencies",
            "Non-critical validation",
            "Logging or audit issues",
        ],
    }

    REGRESSION_SIGNALS = [
        "shared model changes",
        "permission logic updates",
        "filter/query modifications",
        "schedule/time logic",
    ]

    RISK_TRIGGERS = [
        "state/status changes",
        "filter updates",
        "permission checks",
        "data model updates",
        "caching/refresh logic",
    ]

    EDGE_RULES = {
        "validation change": "boundary tests",
        "filter change": "empty results",
        "permission change": "role limits",
        "new state": "transition tests",
        "schedule change": "timezone cases",
    }

    COVERAGE_AREAS = [
        "happy workflow",
        "validation failure",
        "permission boundary",
        "state transitions",
        "error handling",
        "multi-user behavior",
        "backward compatibility",
        "cross-service integration",
    ]

    def __init__(self, consolidated_data: Dict):
        self.consolidated = consolidated_data
        self.service_risks = consolidated_data.get("service_risks", {})
        self.high_risk_changes = consolidated_data.get("high_risk_changes", [])
        self.transitive_impact = consolidated_data.get("transitive_impact", {})

    def generate_analysis(self) -> str:
        """Generate QA analysis following PR Analyzer profile"""
        output = []
        
        # Header
        output.append("# PR Risk Analysis - QA Test Scenarios\n")
        output.append("_Generated using PR Analyzer Profile from copilot-instructions_\n")
        
        # Summary
        risk_summary = self.consolidated.get("risk_summary", {})
        output.append("## Risk Summary\n")
        output.append(f"- **High-Risk Services:** {risk_summary.get('high_risk_services', 0)}\n")
        output.append(f"- **Medium-Risk Services:** {risk_summary.get('medium_risk_services', 0)}\n")
        output.append(f"- **Low-Risk Services:** {risk_summary.get('low_risk_services', 0)}\n")
        output.append(f"- **Total Files Changed:** {risk_summary.get('total_files_changed', 0)}\n")
        output.append(f"- **API Signature Changes:** {risk_summary.get('total_signature_changes', 0)}\n")
        output.append(f"- **Features Removed:** {risk_summary.get('total_removed_features', 0)}\n\n")

        # Generate scenarios by service
        output.append("---\n\n")
        for service, risk_data in self.service_risks.items():
            output.append(f"## {service}\n\n")
            scenarios = self._generate_service_scenarios(service, risk_data)
            
            # Build table
            output.append("| ID | Type | Scenario | Tester Action | Expected Result | Risk | Risk Note |\n")
            output.append("|:---|:-----|:---------|:--------------|:----------------|:----:|:---------|\n")
            
            for idx, scenario in enumerate(scenarios, 1):
                scenario_id = f"PR-T{idx}"
                output.append(
                    f"| {scenario_id} | {scenario['type']} | {scenario['scenario']} | "
                    f"{scenario['tester_action']} | {scenario['expected_result']} | "
                    f"**{scenario['risk_level']}** | {scenario['risk_note']} |\n"
                )
            
            output.append("\n")

        # Cross-Service Tests
        if self.transitive_impact:
            output.append("---\n\n")
            output.append("## Cross-Service Tests\n\n")
            cross_scenarios = self._generate_cross_service_scenarios()
            
            output.append("| ID | Type | Scenario | Tester Action | Expected Result | Risk | Risk Note |\n")
            output.append("|:---|:-----|:---------|:--------------|:----------------|:----:|:---------|\n")
            
            for idx, scenario in enumerate(cross_scenarios, 1):
                scenario_id = f"CROSS-T{idx}"
                output.append(
                    f"| {scenario_id} | {scenario['type']} | {scenario['scenario']} | "
                    f"{scenario['tester_action']} | {scenario['expected_result']} | "
                    f"**{scenario['risk_level']}** | {scenario['risk_note']} |\n"
                )
            
            output.append("\n")

        # Coverage Areas
        output.append("---\n\n")
        output.append("## Required Test Coverage Areas\n\n")
        for area in self.COVERAGE_AREAS:
            output.append(f"- [ ] {area}\n")
        
        output.append("\n")

        # Edge Rules Applied
        output.append("---\n\n")
        output.append("## Edge Cases & Rules Applied\n\n")
        for trigger, edge_case in self.EDGE_RULES.items():
            output.append(f"- **{trigger}** → {edge_case}\n")

        return "".join(output)

    def _generate_service_scenarios(self, service: str, risk_data: Dict) -> List[Dict]:
        """Generate test scenarios for a service"""
        scenarios = []
        risk_level = risk_data.get("risk_level", "medium").upper()

        # Scenario 1: API Signature Changes
        if risk_data.get("signature_changes", 0) > 0:
            scenarios.append({
                "type": "Regression",
                "scenario": "Validate API signature changes don't break existing clients",
                "tester_action": "Call all modified API endpoints with both old and new parameter formats",
                "expected_result": "Old parameter formats handled gracefully (deprecated) OR new format only (breaking change documented)",
                "risk_level": "HIGH",
                "risk_note": f"{risk_data.get('signature_changes', 0)} API signatures changed - verify backward compatibility",
            })

        # Scenario 2: Removed Features
        if risk_data.get("removed_features", 0) > 0:
            scenarios.append({
                "type": "Edge Case",
                "scenario": "Validate removed features fail gracefully",
                "tester_action": "Attempt to access removed features (endpoints, UI elements, functionality)",
                "expected_result": "System returns 410 Gone or 404 Not Found; UI elements hidden/disabled; error messages are helpful",
                "risk_level": "HIGH",
                "risk_note": f"{risk_data.get('removed_features', 0)} features removed - verify users receive proper feedback",
            })

        # Scenario 3: Comprehensive Regression (High File Churn)
        if risk_data.get("files_changed", 0) > 50:
            scenarios.append({
                "type": "Regression",
                "scenario": "Complete regression test due to large codebase changes",
                "tester_action": "Execute happy path workflow: login → perform primary action → logout",
                "expected_result": "All critical workflows complete successfully with no data loss",
                "risk_level": "HIGH",
                "risk_note": f"{risk_data.get('files_changed', 0)} files changed - comprehensive testing required",
            })

            scenarios.append({
                "type": "Regression",
                "scenario": "Validate error handling paths still work",
                "tester_action": "Trigger error conditions: invalid input, missing required fields, timeout scenarios",
                "expected_result": "All error paths return appropriate HTTP codes (4xx/5xx) with informative messages",
                "risk_level": "MEDIUM",
                "risk_note": "Verify error handling wasn't accidentally broken",
            })

            scenarios.append({
                "type": "Regression",
                "scenario": "Validate database/cache consistency",
                "tester_action": "Perform operations that modify state: create, update, delete; then verify via different query/cache",
                "expected_result": "Data is consistent across database, cache, and API responses",
                "risk_level": "HIGH",
                "risk_note": "Large changes often affect data layers - verify integrity",
            })

        # Scenario 4: Permission/Security Changes
        if any("permission" in str(change).lower() or "auth" in str(change).lower() 
               for change in self.high_risk_changes):
            scenarios.append({
                "type": "Security",
                "scenario": "Validate permission boundaries after changes",
                "tester_action": "Login as different user roles (admin, user, guest) and attempt unauthorized actions",
                "expected_result": "Only authorized users can access/modify resources; all actions logged",
                "risk_level": "HIGH",
                "risk_note": "Permission changes are high-risk - test all role boundaries",
            })

        # Scenario 5: Test Coverage
        removed_tests = risk_data.get("test_changes", {}).get("removed_tests", [])
        if removed_tests:
            scenarios.append({
                "type": "Coverage",
                "scenario": "Verify removed tests are still covered by automation",
                "tester_action": "Review removed test list and confirm coverage exists in new tests",
                "expected_result": "All removed test scenarios are covered by new tests OR confirmed as intentional removal",
                "risk_level": "MEDIUM",
                "risk_note": f"{len(removed_tests)} tests removed - ensure no coverage gaps",
            })

        return scenarios

    def _generate_cross_service_scenarios(self) -> List[Dict]:
        """Generate cross-service test scenarios"""
        scenarios = []

        scenarios.append({
            "type": "Integration",
            "scenario": "Validate cross-service communication works end-to-end",
            "tester_action": "Execute workflow spanning multiple services: trigger action in Service A, verify impact in Service B",
            "expected_result": "Service B receives and processes Service A's changes correctly with proper latency",
            "risk_level": "HIGH",
            "risk_note": f"This PR affects {len(self.transitive_impact)} services - verify integration points",
        })

        scenarios.append({
            "type": "Integration",
            "scenario": "Test cascading failures between services",
            "tester_action": "Stop or break Service B, then attempt action from Service A that depends on B",
            "expected_result": "Service A handles Service B's failure gracefully: circuit breaker, retry, or user-friendly error",
            "risk_level": "HIGH",
            "risk_note": "Cross-service resilience test",
        })

        scenarios.append({
            "type": "Integration",
            "scenario": "Validate service version compatibility",
            "tester_action": "Roll out updated service while others are still on old version (rolling deployment)",
            "expected_result": "All services communicate correctly across versions without data loss",
            "risk_level": "MEDIUM",
            "risk_note": "Backward compatibility required for zero-downtime deployments",
        })

        return scenarios


def main():
    parser = argparse.ArgumentParser(
        description="Generate QA analysis using PR Analyzer profile from copilot-instructions"
    )
    parser.add_argument("--consolidated-file", required=True, help="Path to consolidated analysis JSON")
    parser.add_argument("--output", required=True, help="Output file path (Markdown)")

    args = parser.parse_args()

    # Load consolidated analysis
    try:
        with open(args.consolidated_file) as f:
            consolidated_data = json.load(f)
    except Exception as e:
        print(f"[ERROR] Cannot load consolidated analysis: {e}", file=sys.stderr)
        sys.exit(1)

    # Generate analysis
    profile = PRAnalyzerProfile(consolidated_data)
    analysis = profile.generate_analysis()

    # Save output
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(analysis)

    print(f"[OK] QA analysis generated: {output_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
