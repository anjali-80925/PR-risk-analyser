"""
run_analysis.py
===============
Master orchestrator for the PR Risk Analysis pipeline.

Full flow:
  1. Validate inputs (ticket ID + service name)
  2. Cross-service dependency analysis  (analyze_dependencies.py)
  3. Test selection                      (select_tests_for_pr.py)
  4. HTML report generation              (generate_report.py)
  5. Open report in browser

NOTE: Jira + Confluence data (jira_issue.json, confluence_pages.json) must
      already exist under pr-analysis/<TICKET_ID>/.
      They are fetched by GitHub Copilot via Atlassian MCP before this script runs.

Usage:
  python3 scripts/lib/run_analysis.py --ticket-id PROJ-1234 [--service my-frontend-app]

Options:
  --ticket-id   Jira ticket key (required)
  --service     Repo / service name to analyse (optional, auto-detected from pr-analysis/)
  --no-browser  Skip opening the report in browser
  --skip-tests  Skip test selection step (faster)
"""
import argparse
import json
import os
import subprocess
import sys
import webbrowser
from pathlib import Path


SCRIPTS_DIR = Path(__file__).parent


def run(cmd: list, label: str, cwd: Path = None) -> bool:
    """Run a subprocess, stream output, return True on success."""
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    result = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        capture_output=False,
        text=True,
    )
    if result.returncode not in (0, 1):  # 1 = stderr warning from Python on Windows
        print(f"[WARN] Step exited with code {result.returncode}", file=sys.stderr)
        return False
    return True


def find_service(ticket_id: str, pr_analysis_dir: Path) -> str | None:
    """Try to auto-detect service name from pr-analysis directory."""
    # Look for summary.json or changes.diff in subdirs
    for d in pr_analysis_dir.iterdir():
        if d.is_dir() and d.name not in (ticket_id, f"{ticket_id}_test", ".cache", ".test-cache"):
            if (d / "summary.json").exists() or (d / "changes.diff").exists():
                return d.name
    return None


def main():
    parser = argparse.ArgumentParser(description="PR Risk Analysis Pipeline Orchestrator")
    parser.add_argument("--ticket-id", required=True, help="Jira ticket key, e.g. PROJ-1234")
    parser.add_argument("--service", default=None, help="Service/repo name (auto-detected if omitted)")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--skip-tests", action="store_true")
    args = parser.parse_args()

    ticket_id = args.ticket_id.upper()
    workspace = Path.cwd()
    pr_dir = workspace / "pr-analysis"
    ticket_dir = pr_dir / ticket_id

    print(f"\n{'#'*60}")
    print(f"  PR Risk Analysis Pipeline")
    print(f"  Ticket: {ticket_id}")
    print(f"{'#'*60}")

    # ── Step 0: Validate prerequisites ────────────────────────────────────────
    print("\n[0/4] Checking prerequisites...")

    jira_file = ticket_dir / "jira_issue.json"
    if not jira_file.exists():
        print(f"[ERROR] {jira_file} not found.", file=sys.stderr)
        print("        Copilot must fetch Jira data via MCP first.", file=sys.stderr)
        print(f"        Expected: pr-analysis/{ticket_id}/jira_issue.json", file=sys.stderr)
        sys.exit(1)

    with open(jira_file, encoding="utf-8-sig") as f:
        jira = json.load(f)
    print(f"  [OK] Jira: {jira.get('key')} — {jira.get('summary', '')[:70]}")

    confluence_file = ticket_dir / "confluence_pages.json"
    if confluence_file.exists():
        with open(confluence_file, encoding="utf-8-sig") as f:
            pages = json.load(f)
        print(f"  [OK] Confluence: {len(pages)} page(s)")
    else:
        print("  [SKIP] No confluence_pages.json (optional)")
        confluence_file = None

    # Detect service
    service = args.service or find_service(ticket_id, pr_dir)
    if not service:
        print("[ERROR] Could not auto-detect service. Use --service <name>", file=sys.stderr)
        sys.exit(1)

    summary_file = pr_dir / service / "summary.json"
    if not summary_file.exists():
        print(f"[ERROR] summary.json not found for service '{service}'. Expected: {summary_file}", file=sys.stderr)
        sys.exit(1)
    print(f"  [OK] Service: {service} (summary.json found)")

    # ── Step 1: Cross-service dependency analysis ──────────────────────────────
    consolidated_file = ticket_dir / "consolidated.json"
    run(
        [sys.executable, str(SCRIPTS_DIR / "analyze_dependencies.py"),
         "--analysis-dir", str(pr_dir / service),
         "--jira-id", ticket_id,
         "--output", str(consolidated_file)],
        label="Step 1/4 — Cross-Service Dependency Analysis",
        cwd=workspace,
    )

    # Fallback to _test dir if consolidated not generated
    if not consolidated_file.exists():
        fallback = pr_dir / f"{ticket_id}_test" / "consolidated.json"
        if fallback.exists():
            print(f"  [FALLBACK] Using existing consolidated.json from {fallback}")
            consolidated_file = fallback
        else:
            print("[ERROR] consolidated.json not found and analysis failed.", file=sys.stderr)
            sys.exit(1)

    # ── Step 2: Test selection (optional) ─────────────────────────────────────
    test_selection_file = ticket_dir / "test_selection.json"
    if not args.skip_tests:
        test_index = workspace / "pr-analysis" / ".cache" / "test_index.json"
        if test_index.exists():
            run(
                [sys.executable, str(SCRIPTS_DIR / "select_tests_for_pr.py"),
                 "--consolidated-summary", str(consolidated_file),
                 "--test-index", str(test_index),
                 "--output", str(test_selection_file)],
                label="Step 2/4 — Test Selection",
                cwd=workspace,
            )
        else:
            # Fallback to _test dir
            fallback_ts = pr_dir / f"{ticket_id}_test" / "test_selection.json"
            if fallback_ts.exists():
                print(f"  [FALLBACK] Using existing test_selection.json from {fallback_ts}")
                test_selection_file = fallback_ts
            else:
                print("  [SKIP] No test index found. Run index_tests.py first.")
                test_selection_file = None
    else:
        print("\n[SKIP] Test selection (--skip-tests)")
        fallback_ts = pr_dir / f"{ticket_id}_test" / "test_selection.json"
        if fallback_ts.exists():
            test_selection_file = fallback_ts

    # ── Step 3: Generate HTML report ──────────────────────────────────────────
    report_file = ticket_dir / "analysis_report.html"
    cmd = [
        sys.executable, str(SCRIPTS_DIR / "generate_report.py"),
        "--jira-file", str(jira_file),
        "--consolidated-file", str(consolidated_file),
        "--summary-file", str(summary_file),
        "--output", str(report_file),
        "--no-browser",
    ]
    if confluence_file:
        cmd += ["--confluence-file", str(confluence_file)]
    if test_selection_file and Path(test_selection_file).exists():
        cmd += ["--test-selection-file", str(test_selection_file)]

    success = run(cmd, label="Step 3/4 — HTML Report Generation", cwd=workspace)

    # ── Step 4: Open browser ───────────────────────────────────────────────────
    if report_file.exists():
        size_kb = report_file.stat().st_size // 1024
        print(f"\n{'='*60}")
        print(f"  [DONE] Report generated: {report_file} ({size_kb} KB)")
        print(f"{'='*60}\n")
        if not args.no_browser:
            webbrowser.open(report_file.resolve().as_uri())
    else:
        print(f"\n[ERROR] Report file not created: {report_file}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
