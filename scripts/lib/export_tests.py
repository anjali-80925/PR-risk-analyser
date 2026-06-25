#!/usr/bin/env python3
"""
Test Export — Export selected tests in multiple formats.

Usage:
  python3 export_tests.py \
    --test-selection pr-analysis/DTB-17595/test_selection.json \
    --format json,csv,gherkin \
    --output-dir pr-analysis/DTB-17595/exports

Formats:
  - json: Machine-readable (default: test_selection.json)
  - csv: Jenkins-compatible CSV (columns: TestCase,Service,Framework,Feature,Risk,File)
  - gherkin: BDD scenario format (feature files)
  - jira-csv: JIRA issue format (Issue,Summary,Description)
"""

import sys
import json
import csv
from pathlib import Path
from typing import Dict, List, Any
import argparse


class TestExporter:
    """Exports test cases in multiple formats"""

    def __init__(self, test_selection: Dict):
        self.test_selection = test_selection
        self.tests = test_selection.get("test_cases", [])

    def export_json(self, output_file: Path):
        """Export as JSON"""
        with open(output_file, "w") as f:
            json.dump(self.test_selection, f, indent=2)
        print(f"[OK] Exported to {output_file} ({output_file.stat().st_size} bytes)", file=sys.stderr)

    def export_csv(self, output_file: Path):
        """Export as CSV for Jenkins/CI systems"""
        with open(output_file, "w", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["TestID", "Service", "Framework", "Feature", "Risk", "File", "Tags"],
                extrasaction="ignore"
            )
            writer.writeheader()

            for test in self.tests:
                writer.writerow({
                    "TestID": test.get("id", ""),
                    "Service": test.get("service", ""),
                    "Framework": test.get("framework", ""),
                    "Feature": test.get("feature", ""),
                    "Risk": test.get("risk", "medium"),
                    "File": test.get("file", ""),
                    "Tags": ",".join(test.get("tags", [])),
                })

        print(f"[OK] Exported to {output_file} ({len(self.tests)} test cases)", file=sys.stderr)

    def export_gherkin(self, output_dir: Path):
        """Export as Gherkin feature files"""
        output_dir.mkdir(parents=True, exist_ok=True)

        # Group tests by service and feature
        features_by_service = {}
        for test in self.tests:
            service = test.get("service", "unknown")
            feature = test.get("feature", "General")

            key = f"{service}/{feature}"
            if key not in features_by_service:
                features_by_service[key] = []
            features_by_service[key].append(test)

        # Generate feature files
        file_count = 0
        for feature_key, tests in features_by_service.items():
            service, feature = feature_key.split("/", 1)
            filename = output_dir / f"{service}_{feature.replace(' ', '_').lower()}.feature"

            with open(filename, "w") as f:
                # Write feature header
                tags = self._collect_tags(tests)
                if tags:
                    f.write(f"{tags}\n")

                f.write(f"Feature: {feature} ({service})\n")
                f.write(f"  Test scenarios for {service} {feature} feature\n\n")

                # Write scenarios
                for test in tests:
                    risk = test.get("risk", "medium").upper()
                    test_id = test.get("id", "Unknown")
                    name = test.get("name") or test.get("title") or test_id
                    role = test.get("role", "user")
                    action = test.get("action") or f"use the {feature} feature"
                    expected = test.get("expected") or f"the {feature} operation completes successfully"
                    notes = test.get("notes", "")

                    f.write(f"  @risk:{risk}\n")
                    f.write(f"  Scenario: {test_id} — {name}\n")
                    if notes:
                        f.write(f"    # {notes}\n")
                    f.write(f"    Given I am a {role} with access to the system\n")
                    f.write(f"    When I {action}\n")
                    f.write(f"    Then {expected}\n\n")

            file_count += 1
            print(f"[OK] Generated {filename} ({len(tests)} scenarios)", file=sys.stderr)

        print(f"[OK] Exported {file_count} Gherkin feature files to {output_dir}", file=sys.stderr)

    def export_jira_csv(self, output_file: Path):
        """Export as JIRA issue CSV (for bulk import)"""
        with open(output_file, "w", newline="") as f:
            writer = csv.writer(f)
            # JIRA import format: Summary,Description,Issue Type,etc.
            writer.writerow(["Summary", "Description", "Component", "Priority", "Labels"])

            for test in self.tests:
                risk_priority = {"high": "High", "medium": "Medium", "low": "Low"}.get(
                    test.get("risk", "medium"), "Medium"
                )
                writer.writerow([
                    f"Test: {test.get('id', 'Unknown')}",
                    f"Service: {test.get('service')}, Feature: {test.get('feature')}\nFramework: {test.get('framework')}",
                    test.get("service", ""),
                    risk_priority,
                    ",".join(test.get("tags", [])),
                ])

        print(f"[OK] Exported to {output_file} ({len(self.tests)} test cases)", file=sys.stderr)

    def export_html(self, output_file: Path):
        """Export as HTML report"""
        html = self._generate_html_report()
        with open(output_file, "w") as f:
            f.write(html)
        print(f"[OK] Exported to {output_file}", file=sys.stderr)

    def _generate_html_report(self) -> str:
        """Generate HTML report"""
        strategy = self.test_selection.get("execution_strategy", {})

        html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Test Selection Report</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; }}
        h1 {{ color: #333; }}
        .summary {{ background: #f5f5f5; padding: 10px; border-radius: 5px; margin: 20px 0; }}
        table {{ border-collapse: collapse; width: 100%; margin: 20px 0; }}
        th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
        th {{ background-color: #4CAF50; color: white; }}
        tr:nth-child(even) {{ background-color: #f9f9f9; }}
        .high {{ color: #d32f2f; font-weight: bold; }}
        .medium {{ color: #f57c00; }}
        .low {{ color: #388e3c; }}
    </style>
</head>
<body>
    <h1>Test Case Selection Report</h1>
    
    <div class="summary">
        <h2>Summary</h2>
        <p><strong>JIRA ID:</strong> {self.test_selection.get('jira_id', 'N/A')}</p>
        <p><strong>Tests Selected:</strong> {self.test_selection['tests_selected']}</p>
        <p><strong>Estimated Execution:</strong> {strategy.get('estimated_execution_minutes', 0)} minutes</p>
        <p><strong>Services:</strong> {', '.join(self.test_selection.get('services_analyzed', []))}</p>
    </div>
    
    <h2>Selection Breakdown</h2>
    <table>
        <tr><th>Category</th><th>Reason</th></tr>
"""
        for category, reason in self.test_selection.get("selection_breakdown", {}).items():
            html += f"        <tr><td>{category}</td><td>{reason}</td></tr>\n"

        html += """
    </table>
    
    <h2>Selected Test Cases</h2>
    <table>
        <tr>
            <th>Test ID</th>
            <th>Service</th>
            <th>Framework</th>
            <th>Feature</th>
            <th>Risk</th>
            <th>File</th>
        </tr>
"""
        for test in self.tests:
            risk_class = test.get("risk", "medium").lower()
            html += f"""        <tr>
            <td>{test.get('id', '')}</td>
            <td>{test.get('service', '')}</td>
            <td>{test.get('framework', '')}</td>
            <td>{test.get('feature', '')}</td>
            <td class="{risk_class}">{test.get('risk', 'medium').upper()}</td>
            <td>{test.get('file', '')}</td>
        </tr>
"""

        html += """
    </table>
    
    <h2>Execution Strategy</h2>
    <ul>
"""
        for framework, count in strategy.get("by_framework", {}).items():
            html += f"        <li><strong>{framework}:</strong> {count} tests</li>\n"

        html += f"""
        <li><strong>Parallel Execution:</strong> {'Yes' if strategy.get('parallel_execution') else 'No'}</li>
    </ul>
    
</body>
</html>
"""
        return html

    @staticmethod
    def _collect_tags(tests: List[Dict]) -> str:
        """Collect unique tags from tests"""
        all_tags = set()
        for test in tests:
            all_tags.update(test.get("tags", []))
        return " ".join(sorted(all_tags))


def main():
    parser = argparse.ArgumentParser(description="Export selected tests in multiple formats")
    parser.add_argument("--test-selection", required=True, help="Path to test_selection.json")
    parser.add_argument(
        "--format",
        default="json",
        help="Export formats (comma-separated): json,csv,gherkin,jira-csv,html"
    )
    parser.add_argument("--output-dir", help="Output directory (for multi-file formats)")
    parser.add_argument("--output-file", help="Output file (for single-file formats)")

    args = parser.parse_args()

    # Load test selection
    try:
        with open(args.test_selection) as f:
            test_selection = json.load(f)
    except Exception as e:
        print(f"[ERROR] Cannot load test selection: {e}", file=sys.stderr)
        sys.exit(1)

    exporter = TestExporter(test_selection)
    formats = [f.strip() for f in args.format.split(",")]

    # Determine output paths
    output_dir = Path(args.output_dir or ".")
    output_dir.mkdir(parents=True, exist_ok=True)

    # Export each format
    for fmt in formats:
        fmt = fmt.lower().strip()

        if fmt == "json":
            output_file = output_dir / "test_selection.json"
            exporter.export_json(output_file)

        elif fmt == "csv":
            output_file = output_dir / "test_selection.csv"
            exporter.export_csv(output_file)

        elif fmt == "gherkin":
            exporter.export_gherkin(output_dir / "gherkin")

        elif fmt == "jira-csv":
            output_file = output_dir / "test_selection_jira.csv"
            exporter.export_jira_csv(output_file)

        elif fmt == "html":
            output_file = output_dir / "test_selection_report.html"
            exporter.export_html(output_file)

        else:
            print(f"[WARN] Unknown format: {fmt}", file=sys.stderr)

    print(f"[OK] Export complete", file=sys.stderr)


if __name__ == "__main__":
    main()
