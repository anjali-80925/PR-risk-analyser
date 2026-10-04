"""
save_ticket_data.py
===================
Receives Jira + Confluence data fetched by Copilot (via Atlassian MCP)
and saves it to the correct files for the PR analysis pipeline.

This script is called by the Copilot agent after it has fetched the data
using MCP tools. It does NOT make any network calls itself.

Usage:
  python3 scripts/lib/save_ticket_data.py \
    --ticket-id PROJ-1234 \
    --jira-json '<json_string>' \
    --confluence-json '<json_string>'

Or pipe JSON from stdin:
  echo '{"jira": {...}, "confluence": [...]}' | \
    python3 scripts/lib/save_ticket_data.py --ticket-id PROJ-1234 --from-stdin

Output files (created under pr-analysis/<TICKET_ID>/):
  jira_issue.json       — full Jira ticket details
  confluence_pages.json — list of related Confluence pages
"""
import argparse
import json
import sys
from pathlib import Path


def normalize_jira(raw: dict) -> dict:
    """Normalize Jira data from MCP response into clean schema."""
    # Handle both direct fields and nested .fields structure
    if "fields" in raw:
        fields = raw["fields"]
        issue = {
            "key": raw.get("key", ""),
            "id": raw.get("id", ""),
            "summary": fields.get("summary", ""),
            "description": (fields.get("description") or ""),
            "status": (fields.get("status") or {}).get("name", "Unknown"),
            "priority": (fields.get("priority") or {}).get("name", "Unknown"),
            "issue_type": (fields.get("issuetype") or {}).get("name", "Unknown"),
            "assignee": (fields.get("assignee") or {}).get("displayName", "Unassigned"),
            "reporter": (fields.get("reporter") or {}).get("displayName", "Unknown"),
            "labels": fields.get("labels", []),
            "created": fields.get("created", ""),
            "updated": fields.get("updated", ""),
            "due_date": fields.get("duedate", ""),
        }
        return issue

    # Already normalized (from MCP atlassian tool) — just ensure key fields exist
    out = dict(raw)
    # MCP returns status as dict sometimes
    if isinstance(out.get("status"), dict):
        out["status"] = out["status"].get("name", "Unknown")
    if isinstance(out.get("priority"), dict):
        out["priority"] = out["priority"].get("name", "Unknown")
    if isinstance(out.get("issue_type"), dict):
        out["issue_type"] = out["issue_type"].get("name", "Unknown")
    return out


def normalize_confluence_pages(raw) -> list:
    """Normalize Confluence search results into clean list."""
    if not raw:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return []
    pages = []
    for p in (raw if isinstance(raw, list) else raw.get("results", [])):
        # Normalise content: may be a string (agent-written), a Confluence API dict
        # {"value": "...", "representation": "storage"}, or a plain excerpt string.
        content_field = p.get("content", "")
        if isinstance(content_field, dict):
            body = content_field.get("value", "")
        else:
            body = content_field or ""
        pages.append({
            "id": p.get("id", ""),
            "title": p.get("title", ""),
            "url": p.get("url", ""),
            "space": (p.get("space") or {}).get("key", ""),
            "excerpt": p.get("excerpt") or body,
        })
    return pages


def main():
    parser = argparse.ArgumentParser(description="Save MCP-fetched Jira+Confluence data for PR analysis pipeline")
    parser.add_argument("--ticket-id", required=True, help="Jira ticket key, e.g. PROJ-1234")
    parser.add_argument("--output-dir", default=None, help="Override output dir (default: pr-analysis/<TICKET_ID>)")
    parser.add_argument("--jira-json", default=None, help="Jira issue JSON as string")
    parser.add_argument("--confluence-json", default=None, help="Confluence pages JSON as string")
    parser.add_argument("--from-stdin", action="store_true", help='Read {"jira":{...},"confluence":[...]} from stdin')
    args = parser.parse_args()

    ticket_id = args.ticket_id.upper()
    out_dir = Path(args.output_dir) if args.output_dir else Path("pr-analysis") / ticket_id
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.from_stdin:
        payload = json.loads(sys.stdin.read())
        jira_raw = payload.get("jira", {})
        conf_raw = payload.get("confluence", [])
    else:
        jira_raw = json.loads(args.jira_json) if args.jira_json else {}
        conf_raw = json.loads(args.confluence_json) if args.confluence_json else []

    jira = normalize_jira(jira_raw)
    confluence = normalize_confluence_pages(conf_raw)

    jira_path = out_dir / "jira_issue.json"
    conf_path = out_dir / "confluence_pages.json"

    jira_path.write_text(json.dumps(jira, indent=2, ensure_ascii=False), encoding="utf-8")
    conf_path.write_text(json.dumps(confluence, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"[OK] {jira_path}  ({jira_path.stat().st_size} bytes)")
    print(f"[OK] {conf_path}  ({conf_path.stat().st_size} bytes)")
    print(f"     Ticket  : {jira.get('key')} — {jira.get('summary', '')[:80]}")
    print(f"     Status  : {jira.get('status')}  |  Priority: {jira.get('priority')}")
    print(f"     Conf pgs: {len(confluence)}")


if __name__ == "__main__":
    main()
