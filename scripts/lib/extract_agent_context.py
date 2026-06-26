#!/usr/bin/env python3
"""
extract_agent_context.py — Phase 2 post-processor.

Reads all script outputs for a JIRA_ID and emits a single lean
agent_context.json containing everything the Copilot agent needs to
generate the HTML report in one shot — no sequential file reads needed.

Usage:
    python3 scripts/lib/extract_agent_context.py \
        --analysis-dir pr-analysis/DTB-17595 \
        --jira-id DTB-17595
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

NOISE_TAGS = {"fixtures", "test", "pages", "TEST_DTB", "Navigation1", "MarketingAssets1"}


def _load_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default if default is not None else {}


def _condense_diff(diff_path: Path, max_lines: int = 120) -> str:
    """Return only the +/- lines from a diff, up to max_lines total."""
    if not diff_path.exists():
        return ""
    lines = []
    try:
        with open(diff_path, encoding="utf-8", errors="replace") as f:
            for line in f:
                stripped = line.rstrip()
                # Keep file headers, hunks, and +/- lines; skip unchanged context
                if (
                    stripped.startswith("diff --git")
                    or stripped.startswith("+++")
                    or stripped.startswith("---")
                    or stripped.startswith("@@")
                    or stripped.startswith("+")
                    or stripped.startswith("-")
                ):
                    lines.append(stripped)
                    if len(lines) >= max_lines:
                        lines.append("... (truncated)")
                        break
    except Exception:
        pass
    return "\n".join(lines)


def _extract_route_changes(diff_text: str) -> list:
    """Parse gateway YAML diff for new route predicates added."""
    routes = []
    current_id = None
    current_uri = None
    current_path = None
    current_rewrite = None
    in_added_block = False

    for line in diff_text.splitlines():
        if not line.startswith("+"):
            in_added_block = False
            continue
        content = line[1:].strip()
        if "id:" in content:
            in_added_block = True
            current_id = content.split("id:", 1)[-1].strip()
            current_uri = current_path = current_rewrite = None
        elif in_added_block:
            if "uri:" in content:
                current_uri = content.split("uri:", 1)[-1].strip()
            elif "Path=" in content:
                m = re.search(r"Path=([^\s,]+)", content)
                if m:
                    current_path = m.group(1)
            elif "SetPath=" in content or "RewritePath=" in content:
                current_rewrite = content.strip("- ").strip()
            # Emit when we have enough
            if current_id and current_path and current_rewrite:
                routes.append({
                    "route_id": current_id,
                    "from": current_path,
                    "to": current_rewrite,
                    "target": current_uri or "",
                })
                current_id = current_uri = current_path = current_rewrite = None
                in_added_block = False

    return routes


def _clean_tags(tags: list) -> list:
    seen = set()
    result = []
    for t in tags:
        if t not in NOISE_TAGS and t not in seen:
            seen.add(t)
            result.append(t)
    return result


def build_context(analysis_dir: Path, jira_id: str) -> dict:
    # ── Jira ────────────────────────────────────────────────────────────────
    jira = _load_json(analysis_dir / "jira_issue.json")
    jira_summary = jira.get("summary") or jira.get("title", jira_id)
    jira_status = jira.get("status", "Unknown")
    jira_priority = jira.get("priority", "Medium")
    jira_assignee = jira.get("assignee", "")
    jira_description = (jira.get("description") or "")[:1200]

    # ── Confluence ──────────────────────────────────────────────────────────
    confluence_pages = _load_json(analysis_dir / "confluence_pages.json", default=[])
    confluence_summaries = [
        {"title": p.get("title", ""), "url": p.get("url", ""),
         "snippet": (p.get("content") or "")[:300]}
        for p in (confluence_pages if isinstance(confluence_pages, list) else [])
    ]

    # ── Consolidated summary ────────────────────────────────────────────────
    consolidated = _load_json(analysis_dir / "consolidated_summary.json")
    risk_summary = consolidated.get("risk_summary", {})
    cross_service_impacts = consolidated.get("cross_service_impact", [])

    # Condense cross-service impacts — keep only high-impact repos
    cross_service_condensed = []
    for impact in cross_service_impacts:
        if impact.get("risk_level") in ("HIGH", "MEDIUM"):
            cross_service_condensed.append({
                "repo": impact.get("repo", ""),
                "risk_level": impact.get("risk_level", ""),
                "reason": impact.get("reason", ""),
                "matched_terms": impact.get("matched_terms", [])[:5],
                "total_references": impact.get("total_references", 0),
            })

    # ── Per-service data ─────────────────────────────────────────────────────
    services = []
    service_dirs = [d for d in analysis_dir.iterdir() if d.is_dir()]
    for svc_dir in sorted(service_dirs):
        summary_path = svc_dir / "summary.json"
        diff_path = svc_dir / "changes.diff"
        if not summary_path.exists():
            continue

        svc_summary = _load_json(summary_path)
        service_name = svc_dir.name

        # Key structured data
        signature_changes = svc_summary.get("signature_changes", [])
        removed_features = svc_summary.get("removed_features", [])
        # new_status_values can be huge (fixture string literals) — cap at 20 short items only
        raw_status_values = svc_summary.get("new_status_values", [])
        new_status_values = [
            v for v in raw_status_values
            if isinstance(v, str) and len(v) <= 40 and not v.startswith("{")
        ][:20]
        blast_radius = svc_summary.get("blast_radius", [])
        changed_files = svc_summary.get("changed_files", [])
        risk_level = svc_summary.get("risk_level") or (
            "HIGH" if len(changed_files) > 50 else
            "MEDIUM" if len(changed_files) > 10 else "LOW"
        )

        # Condensed diff (only +/- lines, capped at 120 lines)
        condensed_diff = _condense_diff(diff_path)

        # Route changes from gateway diff
        route_changes = []
        if "gateway" in service_name.lower():
            route_changes = _extract_route_changes(condensed_diff)

        services.append({
            "name": service_name,
            "risk_level": risk_level,
            "files_changed": len(changed_files),
            "signature_changes": signature_changes,
            "removed_features": removed_features,
            "new_status_values": new_status_values,
            "blast_radius": blast_radius[:10],
            "route_changes": route_changes,
            "diff_condensed": condensed_diff,
        })

    # ── Test selection ───────────────────────────────────────────────────────
    test_selection = _load_json(analysis_dir / "test_selection.json", default={})
    raw_cases = test_selection.get("test_cases", [])
    clean_cases = []
    for tc in raw_cases:
        clean_cases.append({
            "testCase": tc.get("testCase") or tc.get("test_name") or tc.get("name", ""),
            "file": tc.get("file", ""),
            "tags": _clean_tags(tc.get("tags", [])),
            "risk": tc.get("risk", ""),
        })

    # ── QA analysis hints ───────────────────────────────────────────────────
    qa_md_path = analysis_dir / "qa_analysis.md"
    qa_hints = ""
    if qa_md_path.exists():
        try:
            with open(qa_md_path, encoding="utf-8") as f:
                raw = f.read()
            # Extract just the risk triggers and edge rules sections
            for section_marker in ["## Risk", "## Edge", "## Required"]:
                idx = raw.find(section_marker)
                if idx != -1:
                    qa_hints += raw[idx:idx + 600] + "\n\n"
        except Exception:
            pass

    return {
        "jira_id": jira_id,
        "jira_summary": jira_summary,
        "jira_status": jira_status,
        "jira_priority": jira_priority,
        "jira_assignee": jira_assignee,
        "jira_description": jira_description,
        "confluence_pages": confluence_summaries,
        "risk_summary": risk_summary,
        "cross_service_impacts": cross_service_condensed,
        "services": services,
        "test_selection": {
            "tests_selected": test_selection.get("tests_selected", 0),
            "selection_breakdown": test_selection.get("selection_breakdown", {}),
            "test_cases": clean_cases,
            "estimated_minutes": test_selection.get("execution_strategy", {}).get(
                "estimated_execution_minutes", 0
            ),
        },
        "qa_hints": qa_hints,
    }


def main():
    parser = argparse.ArgumentParser(description="Extract lean agent context for report generation")
    parser.add_argument("--analysis-dir", required=True, help="Path to pr-analysis/<JIRA_ID>/")
    parser.add_argument("--jira-id", required=True, help="Jira ticket ID")
    parser.add_argument("--output", default=None, help="Output path (default: <analysis-dir>/agent_context.json)")
    args = parser.parse_args()

    analysis_dir = Path(args.analysis_dir)
    if not analysis_dir.exists():
        print(f"ERROR: analysis dir not found: {analysis_dir}", file=sys.stderr)
        sys.exit(1)

    output_path = Path(args.output) if args.output else analysis_dir / "agent_context.json"

    ctx = build_context(analysis_dir, args.jira_id)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(ctx, f, indent=2, ensure_ascii=False)

    size_kb = output_path.stat().st_size / 1024
    print(f"[OK] agent_context.json written: {size_kb:.1f} KB ({len(ctx['services'])} services, "
          f"{ctx['test_selection']['tests_selected']} tests)")


if __name__ == "__main__":
    main()
