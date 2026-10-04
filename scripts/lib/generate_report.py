#!/usr/bin/env python3
"""
PR Risk Analysis Report Generator — QA Tester Perspective
Produces UI steps + API steps + cross-service system flow.
No code-level noise — every scenario tells the tester exactly what to click and what API to check.
"""

import sys
import json
import webbrowser
from pathlib import Path
from typing import Dict, List, Optional
import argparse
from datetime import datetime


# ── Feature area detection ─────────────────────────────────────────────────

def detect_feature_areas(changed_files: List[str], new_statuses: List, removed_features: List[str], added_tests: List[str]) -> List[Dict]:
    """
    Convert raw changed-file lists into meaningful tester feature areas.
    Returns a list of feature area dicts that drive scenario generation.
    Driven by actual changed file paths — NOT hardcoded to any specific PR.
    """
    files_lower = [f.lower() for f in changed_files]

    def has(pattern: str) -> bool:
        return any(pattern in f for f in files_lower)

    def has_any(*patterns: str) -> bool:
        return any(has(p) for p in patterns)

    # Extract new constant values added to config/constants files
    new_countries = [
        (v.get("value", v) if isinstance(v, dict) else str(v))
        for v in new_statuses
        if isinstance(v, dict) and "constants" in v.get("file", "").lower()
        and not v.get("value", "").startswith("should ")
    ]
    country_list = ", ".join(new_countries[:10]) + ("…" if len(new_countries) > 10 else "")

    removed_lower = [r.lower() for r in removed_features]
    def was_removed(keyword: str) -> bool:
        return any(keyword in r for r in removed_lower)

    areas = []

    # ── Microservice Migration detection ───────────────────────────────
    # Triggers when endpoints are explicitly migrated out of a monolith
    _is_microservice_migration = (
        was_removed("removed from") or
        was_removed("migrated to") or
        (was_removed("route removed") and has("api"))
    )
    if _is_microservice_migration:
        _svc_name = "new microservice"
        for r in removed_lower:
            if "svc-" in r:
                _svc_name = r.split("svc-")[1].split()[0]
                break

        areas.append({
            "id": "MIGRATE-ROUTE",
            "name": "API Route Change",
            "emoji": "🔀",
            "risk": "HIGH",
            "description": f"API routes migrated to {_svc_name}. All API calls must use the new base path.",
            "regression_guard": "Network tab shows requests hitting the new service route, not the old monolith path",
            "scenarios": [
                "Use the migrated feature → Network tab: requests hit new route, not old monolith path",
                "Old route returns 404 — no silent fallback keeping old service alive",
                "Auth header present on new route: Authorization: Bearer <token> in each request",
            ],
        })
        areas.append({
            "id": "MIGRATE-ENDPOINTS",
            "name": "Migrated Endpoints — Functional Parity",
            "emoji": "⚙️",
            "risk": "HIGH",
            "description": f"Endpoints moved to {_svc_name}. Response contract must be identical — same fields, same pagination, same error codes.",
            "regression_guard": "Migrated endpoint response has same top-level fields as before — no missing fields",
            "scenarios": [
                "Call migrated endpoints with various filters → results load with same data structure as before migration",
                "Empty search or no-match query → returns empty result set (not 500 from new service)",
            ],
        })
        areas.append({
            "id": "MIGRATE-AUTH",
            "name": "Auth & Access Control on New Service",
            "emoji": "🔐",
            "risk": "MEDIUM",
            "description": f"New microservice ({_svc_name}) must have auth/authZ configured. Verify tokens accepted and roles enforced.",
            "regression_guard": "Logged-in user accesses migrated feature — no 401/403 returned by new service",
            "scenarios": [
                "Logged-in user accesses migrated feature → no 401 Unauthorized from new service endpoints",
                "Expired session or no token → 401 returned (not silently broken page)",
                "User without permission → access is blocked (role enforcement works on new service)",
            ],
        })

    # ── Icons & Tooltips (visual FE component changes only) ────────────
    if has_any("icon", "tooltip", "logo") and not _is_microservice_migration:
        areas.append({
            "id": "ICON",
            "name": "Icons & Tooltips",
            "emoji": "🎨",
            "risk": "LOW",
            "description": "Icon stylesheet and tooltip wrapper components updated. Visual-only changes — check rendering across all pages.",
            "regression_guard": "Hover any info tooltip — tooltip appears and dismisses correctly",
            "scenarios": [
                "All module pages — no broken icon placeholders, no missing glyphs",
                "Tooltips on action/info buttons appear on hover and disappear on mouse-out (no tooltip stuck open)",
            ],
            "ui_steps": [
                {"step": "Check icons across all pages", "action": "Navigate through main pages → verify all icons render with no broken placeholders or missing glyphs", "verify": "All icons visible, correctly sized, no blank squares or default browser image icons", "risk": "LOW"},
                {"step": "Hover tooltips", "action": "Hover over each icon that shows a tooltip (info icons, action buttons, status icons)", "verify": "Tooltip text appears correctly, is readable, does not overflow off-screen, and disappears on mouse-out", "risk": "LOW"},
                {"step": "Check dark/light mode rendering", "action": "If the app supports theme toggle — switch theme and recheck icon visibility", "verify": "Icons visible in both themes; no pure-white icon on white background or pure-black on black background", "risk": "LOW"},
            ],
            "api_steps": []
        })

    # ── Locale / i18n Constants — New Locales Added ────────────────────
    if has_any("localization", "locale", "i18n"):
        areas.append({
            "id": "LOCALE-CONST",
            "name": "Locale Constants — New Locale Definitions",
            "emoji": "🌍",
            "risk": "HIGH",
            "description": "Locale/i18n constants updated. Verify new locale codes are selectable and content loads correctly.",
            "regression_guard": "Locale dropdown contains newly added locale codes",
            "scenarios": [
                "New locale codes selectable in locale dropdown",
                "Locale display names are correct and match expected format",
                "Select new locale → content loads or graceful empty state shown (no 400 error, no blank screen)",
            ],
            "ui_steps": [
                {"step": "Verify new locale codes appear in locale dropdown", "action": "Open locale/language selector dropdown", "verify": "All newly added locale codes are present and selectable", "risk": "HIGH"},
                {"step": "Select a newly added locale and load content", "action": "Select a new locale → load page content", "verify": "Content loads without error; if no content exists, a meaningful 'no content' message is shown (not a blank/broken UI)", "risk": "HIGH"},
            ],
            "api_steps": [
                {"endpoint": "GET /api/locales", "method": "GET", "headers": {"Authorization": "Bearer <token>"}, "params": {}, "verify": "Response includes all new locale codes with correct display names", "risk": "HIGH"},
            ]
        })

    # ── Asset Management — Locale Support ───────────────────────────────
    if has_any("assets", "description", "download"):
        areas.append({
            "id": "ASSET-LOCALE",
            "name": "Asset Management — Locale-aware Content",
            "emoji": "🖼️",
            "risk": "HIGH",
            "description": "Asset pages updated to support new locales. Locale dropdown must show all new locale codes.",
            "regression_guard": "Select a new locale on asset page — page loads without JS error",
            "scenarios": [
                "Locale dropdowns contain all new locale codes",
                "UI headers use browser UI language, NOT selected content locale",
                "Selecting new locale that has no content → meaningful empty state, not a white screen or 500 error",
            ],
            "ui_steps": [
                {"step": "Check locale dropdown on asset page", "action": "Open asset page → select any item → open locale selector", "verify": "All new locale codes appear in the dropdown", "risk": "HIGH"},
                {"step": "Switch locale and verify content loads", "action": "Select a newly added locale → observe content area", "verify": "Content loads for that locale or a 'no content available' message shown; no JS error or blank white area", "risk": "HIGH"},
                {"step": "Download asset modal", "action": "Click download on an asset → modal opens", "verify": "Modal opens, options render correctly, download works", "risk": "LOW"},
            ],
            "api_steps": [
                {"endpoint": "GET /api/assets/{id}/descriptions?locale={locale}", "method": "GET", "headers": {"Authorization": "Bearer <token>"}, "params": {"id": "{id}", "locale": "{locale}"}, "verify": "200 OK with content data; or empty array with 200 if no content for this locale (NOT a 4xx error)", "risk": "HIGH"},
            ]
        })

    # ── Configuration — Locale Unification ──────────────────────────────
    if has_any("transformation", "configuration") and has_any("locale", "i18n"):
        areas.append({
            "id": "CONFIG-LOCALE",
            "name": "Configuration — Locale Unification",
            "emoji": "🔗",
            "risk": "HIGH",
            "description": "Configuration step now uses the unified locale list. Locale selection must match the shared locale set across modules.",
            "regression_guard": "Configuration locale dropdown shows unified locale codes, no separate Language dropdown visible",
            "scenarios": [
                "Locale list in configuration matches other modules (same codes, same display names)",
                "Save configuration with new locale → no validation error, persists on page reload",
                "No ghost/empty language selector where deprecated code was removed — UI is clean",
            ],
            "ui_steps": [
                {"step": "Check locale dropdown in configuration", "action": "Open configuration → locale dropdown", "verify": "Locale dropdown contains the unified locale list; old-format names replaced", "risk": "HIGH"},
                {"step": "Save configuration with a new locale", "action": "Select a new locale → save", "verify": "Saved with new locale code; no validation error; on re-load, locale is pre-selected correctly", "risk": "HIGH"},
            ],
            "api_steps": [
                {"endpoint": "GET /api/config/{id}?locale={locale}", "method": "GET", "headers": {"Authorization": "Bearer <token>"}, "params": {}, "verify": "Returns configuration for the new locale code; no 400 for valid new locale codes", "risk": "HIGH"},
            ]
        })

    # ── New Constants / Enum Values Added ────────────────────────────────
    if has("constants") and new_countries:
        areas.append({
            "id": "NEW-CONSTANTS",
            "name": "New Constant Values Added",
            "emoji": "🌐",
            "risk": "HIGH",
            "regression_guard": "Dropdown/selector includes newly added constant values",
            "scenarios": [
                f"All newly added values selectable in relevant dropdown: {country_list}",
                "Create new entity with a new value → POST returns 201, value persists on GET",
                "Internal IDs in Network tab request body are correct mappings, not just display names",
            ],
            "description": f"New constant values added: {country_list}. These must be selectable in the relevant UI selectors.",
            "ui_steps": [
                {"step": "Open selector dropdown", "action": "Open the relevant creation/edit form → open the selector dropdown", "verify": f"All newly added values are present and selectable: {country_list}", "risk": "HIGH"},
                {"step": "Create entity with a new value", "action": "Select a new value from the dropdown → complete form → save", "verify": "Entity created successfully; new value stored and shown in list view", "risk": "HIGH"},
            ],
            "api_steps": [
                {"endpoint": "POST /api/{resource}", "method": "POST", "headers": {"Authorization": "Bearer <token>", "Content-Type": "application/json"}, "params": {}, "verify": "201 Created; entity visible in list; new value persists on GET", "risk": "HIGH"},
            ]
        })

    # ── Data Transformations / Rules Engine ──────────────────────────────
    if has_any("transformation", "rule", "lookup", "fallback") and not (has("constants") and new_countries):
        areas.append({
            "id": "TRANSFORM",
            "name": "Data Transformations / Rules Engine",
            "emoji": "2️⃣",
            "risk": "HIGH",
            "description": "Transformation/rule components refactored. Verify CRUD operations and toggle persistence.",
            "regression_guard": "Open existing entity in edit mode → transformation list loads without blank/broken components",
            "scenarios": [
                "Add transformation → save → appears in list with correct data and no missing fields",
                "Toggle options: enable → save → reload → persists as enabled (and disable also saves)",
                "PATCH request in Network tab — FE-only internal properties are NOT present in request body",
            ],
            "ui_steps": [
                {"step": "Verify transformations load", "action": "Open entity in Edit Mode → navigate to transformation step", "verify": "Transformation list renders correctly; no blank/broken components", "risk": "HIGH"},
                {"step": "Add a transformation", "action": "Click 'Add' → select attribute → configure → save", "verify": "Item renders with all fields; saved correctly; appears in list", "risk": "HIGH"},
                {"step": "Delete a transformation", "action": "Click delete icon → confirm in modal", "verify": "Transformation removed; UI updates; backend reflects removal", "risk": "MEDIUM"},
            ],
            "api_steps": [
                {"endpoint": "GET /api/{resource}/{id}/transformations", "method": "GET", "headers": {"Authorization": "Bearer <token>"}, "params": {}, "verify": "Returns transformation list; FE-only state properties NOT present in response", "risk": "HIGH"},
                {"endpoint": "PATCH /api/{resource}/{id}/transformations", "method": "PATCH", "headers": {"Authorization": "Bearer <token>", "Content-Type": "application/json"}, "params": {}, "verify": "200 OK; FE-only properties stripped before send", "risk": "HIGH"},
            ]
        })

    # ── Data Sync / Export Management ────────────────────────────────────
    if has_any("syndication", "export", "sync"):
        areas.append({
            "id": "SYNC",
            "name": "Data Sync / Export Management",
            "emoji": "🔁",
            "risk": "MEDIUM",
            "description": "Sync/export actions and list rendering updated.",
            "regression_guard": "Completed exports render with action buttons visible and expand/collapse works",
            "scenarios": [
                "Expand/collapse list row — no layout shift or broken rendering",
                "Re-run action on completed export — loading state shown, feedback displayed after completion",
            ],
            "ui_steps": [
                {"step": "View completed exports list", "action": "Go to export management page → check the completed section", "verify": "Completed items render in list; action buttons are visible", "risk": "MEDIUM"},
                {"step": "Expand/collapse row", "action": "Click to expand a row → then collapse it", "verify": "Row expands showing detail; collapse works cleanly; no layout shift", "risk": "LOW"},
                {"step": "Perform action on completed export", "action": "Click 'Re-run' on a completed export", "verify": "Loading state shown; success/failure feedback displayed after action completes", "risk": "MEDIUM"},
            ],
            "api_steps": [
                {"endpoint": "GET /api/exports", "method": "GET", "headers": {"Authorization": "Bearer <token>"}, "params": {}, "verify": "Returns both ongoing and completed export lists; actions array per item is correct", "risk": "MEDIUM"},
            ]
        })

    # ── User Preferences / Settings ──────────────────────────────────────
    if has_any("preference", "settings", "frequency"):
        areas.append({
            "id": "PREFS",
            "name": "User Preferences / Settings",
            "emoji": "⭐",
            "risk": "MEDIUM",
            "description": "Preferences modal and user settings updated.",
            "regression_guard": "Preferences modal opens — settings render correctly",
            "scenarios": [
                "Preference options display correctly with updated values",
                "Change a setting → saves and persists on modal reopen; PATCH /preferences accepted without error",
            ],
            "ui_steps": [
                {"step": "Open preferences modal", "action": "Click 'Preferences' or settings icon → check options", "verify": "Settings load with correct values; no blank sections", "risk": "MEDIUM"},
                {"step": "Change a setting", "action": "In preferences modal → change an option → save", "verify": "Setting saved; modal closes; persists on next open; API request sent with correct value", "risk": "MEDIUM"},
            ],
            "api_steps": [
                {"endpoint": "GET /api/preferences", "method": "GET", "headers": {"Authorization": "Bearer <token>"}, "params": {}, "verify": "Returns current preferences", "risk": "MEDIUM"},
                {"endpoint": "PATCH /api/preferences", "method": "PATCH", "headers": {"Authorization": "Bearer <token>", "Content-Type": "application/json"}, "params": {}, "verify": "200 OK; re-fetch confirms saved values", "risk": "MEDIUM"},
            ]
        })

    # ── Backend Service Logic detection ──────────────────────────────────
    _be_files = [f for f in changed_files if f.lower().endswith('.java') or '/be/' in f.lower() or '\\be\\' in f.lower()]
    _ns_text = " ".join(
        f"{v.get('entry','')} {v.get('value','')}".lower()
        for v in new_statuses if isinstance(v, dict)
    )
    _be_lower = " ".join(f.lower() for f in _be_files) + " " + _ns_text
    if _be_files or was_removed("backend"):
        def _be_has(kw): return kw in _be_lower
        if _be_has("download") or _be_has("kpi") or "download" in " ".join(removed_lower):
            areas.append({
                "id": "BE-DOWNLOAD",
                "name": "Download Flow & Analytics",
                "emoji": "📊",
                "risk": "HIGH",
                "description": "Backend download service logic changed. Verify downloads complete and analytics data is recorded correctly.",
                "regression_guard": "Trigger a download — file received and no error returned from backend",
                "scenarios": [
                    "Download resource → verify file received and no 500 errors",
                    "Download with invalid/expired session → verify 401 returned, no partial analytics write",
                ],
                "ui_steps": [
                    {"step": "Trigger download", "action": "Select resource → Download", "verify": "Download completes; file received; no error toast", "risk": "HIGH"},
                ],
                "api_steps": [
                    {"endpoint": "POST /api/download", "method": "POST", "headers": {"Authorization": "Bearer <token>"}, "params": {}, "verify": "200 OK; file stream returned", "risk": "HIGH"},
                ]
            })
        if _be_has("confidential") or _be_has("kpi") or _be_has("analytics"):
            areas.append({
                "id": "BE-ANALYTICS",
                "name": "Analytics Data Persistence",
                "emoji": "🗄️",
                "risk": "MEDIUM",
                "description": "Analytics/KPI recording logic updated. Verify data integrity and no regression in main flow.",
                "regression_guard": "No duplicate entries; main flow completes even if analytics write fails (non-blocking)",
                "scenarios": [
                    "Verify analytics saved with correct metadata on trigger event",
                    "Verify main flow is non-blocking — analytics write failure does not break user flow",
                ],
                "ui_steps": [],
                "api_steps": [
                    {"endpoint": "GET /api/analytics/dashboard", "method": "GET", "headers": {"Authorization": "Bearer <token>"}, "params": {}, "verify": "Counts increment correctly after each trigger event", "risk": "MEDIUM"},
                ]
            })

    return areas


# ── Cross-service system flow ──────────────────────────────────────────────

# ── Cross-service system flow ──────────────────────────────────────────────

def _extract_gateway_routes(pr_dir) -> List[Dict]:
    """
    Parse Spring Cloud Gateway diffs to find newly added route predicates.
    Returns list of {external, internal, service} dicts.
    """
    import re as _r
    routes = []
    if not pr_dir:
        return routes
    pr_path = Path(pr_dir)
    if not pr_path.exists():
        return routes
    for svc_dir in pr_path.iterdir():
        if not svc_dir.is_dir() or 'gateway' not in svc_dir.name.lower():
            continue
        diff_file = svc_dir / 'changes.diff'
        if not diff_file.exists():
            continue
        try:
            text = diff_file.read_text(encoding='utf-8', errors='replace')
        except Exception:
            continue
        # Only look at added lines
        added = [line[1:] for line in text.splitlines() if line.startswith('+') and not line.startswith('+++')]
        # Collect Path predicates and SetPath/RewritePath filters in order
        external_paths, internal_paths = [], []
        for line in added:
            # Each YAML line after stripping the diff '+' looks like: '            - Path=/api/searchIconography'
            stripped = line.strip().lstrip('-').strip()
            if stripped.startswith('Path='):
                external_paths.append(stripped[5:].strip())
            elif stripped.startswith('SetPath='):
                internal_paths.append(stripped[8:].strip())
            elif stripped.startswith('RewritePath='):
                # RewritePath=/api/foo/(?<seg>.*), /foo/${seg}  → take last segment
                parts = stripped[12:].split(',', 1)
                if parts:
                    internal_paths.append(parts[-1].strip())
        # Routes may appear in multiple YAML files (application.yml + application-local.yml) — deduplicate
        seen_routes = set()
        for i, ext in enumerate(external_paths):
            internal = internal_paths[i] if i < len(internal_paths) else '(backend service root)'
            key = (ext, internal)
            if key not in seen_routes:
                seen_routes.add(key)
                routes.append({'external': ext, 'internal': internal, 'service': svc_dir.name})
    return routes


def build_cross_service_flow(consolidated: Dict, gateway_routes: List[Dict] = None) -> List[Dict]:
    """
    Dynamically generate cross-service test scenarios from real consolidated analysis data.
    Dynamically generates scenarios from consolidated analysis data.

    Logic:
    - Identifies FE vs BE services from file extensions
    - Detects shared concerns: API contracts, permissions, data models, config
    - Generates targeted integration scenarios per service pair
    """
    import re as _cre

    # Known client-class → target-service mappings (add your project's mappings here)
    _CLIENT_SVC_MAP = {}

    def _infer_target_service(class_name: str) -> str:
        lower = class_name.lower().replace("client", "")
        if lower + "client" in _CLIENT_SVC_MAP:
            return _CLIENT_SVC_MAP[lower + "client"]
        name = _cre.sub(r'(?i)client$', '', class_name, flags=_cre.IGNORECASE)
        kebab = _cre.sub(r'([A-Z]+)([A-Z][a-z])', r'\1-\2', name)
        kebab = _cre.sub(r'([a-z])([A-Z])', r'\1-\2', kebab)
        return kebab.lower().strip('-')

    service_risks = dict(consolidated.get("service_risks", {}))
    services = list(service_risks.keys())

    # Infer implicit cross-service deps from *Client.java in changed_features
    _inferred_svcs: dict = {}
    _IGNORE_CLIENTS = {"RestClient", "WebClient", "HttpClient", "RestTemplateClient",
                       "FeignClient", "OkHttpClient", "MockRestServiceServer"}
    for svc, svc_data in list(service_risks.items()):
        for cf in svc_data.get("changed_features", []):
            if cf.endswith("Client") and cf not in _IGNORE_CLIENTS:
                target = _CLIENT_SVC_MAP.get(cf.lower(), _infer_target_service(cf))
                if target and target not in service_risks and target not in _inferred_svcs:
                    _inferred_svcs[target] = {
                        "inferred": True,
                        "called_by": svc,
                        "client_class": cf,
                        "languages": ["java"],
                        "changed_features": [],
                        "signature_changes": [],
                        "removed_features": [],
                        "new_status_values": [],
                    }
    if _inferred_svcs:
        service_risks.update(_inferred_svcs)
        services = list(service_risks.keys())

    if len(services) < 2:
        return []  # no cross-service to analyse

    # ── Categorise services by their language fingerprint ─────────────────────
    fe_services = []
    be_services = []
    for svc, risk in service_risks.items():
        langs = risk.get("languages", [])
        files = risk.get("changed_files", [])
        file_str = " ".join(files).lower()
        if any(l in langs for l in ("javascript", "typescript")) or \
                any(f.endswith((".ts", ".tsx", ".js", ".jsx")) for f in files):
            fe_services.append(svc)
        else:
            be_services.append(svc)
        # A service with Java files is always BE
        if "java" in langs or any(f.endswith(".java") for f in files):
            if svc not in be_services:
                be_services.append(svc)

    # ── Detect shared change signals ──────────────────────────────────────────
    # Note: consolidated_summary.json stores counts (int) while manual consolidated.json
    # stores full lists — handle both gracefully.
    def _as_list(v):
        """Return v if it's already a list; empty list if it's an int/None."""
        return v if isinstance(v, list) else []

    all_files = [f.lower() for r in service_risks.values() for f in _as_list(r.get("changed_files", []))]
    all_sigs = [s.get("function", "").lower() for r in service_risks.values() for s in _as_list(r.get("signature_changes", []))]
    all_removed = [x.lower() for r in service_risks.values() for x in _as_list(r.get("removed_features", []))]

    # Filter new_status_values to user-visible values only — strip Java code fragments,
    # DTO names, method calls, array/list internals etc.
    def _is_user_visible_status(v: str) -> bool:
        if not v or len(v.strip()) < 2:
            return False
        junk_markers = ('(', '{', '.', 'isempty', 'isnull', 'utils', 'response',
                        'request', ' dto', 'dto ', 'entity', 'new_class', 'array',
                        'list', 'null', 'empty', 'true', 'false', 'string', 'collection',
                        'attribute', 'updated', 'info', 'endpoint', 'param', 'mock',
                        'class', 'import', 'object', 'service', 'repository')
        vl = v.lower().strip()
        return not any(j in vl for j in junk_markers)

    all_new_statuses = [
        s.get("value", "")
        for r in service_risks.values()
        for s in _as_list(r.get("new_status_values", []))
        if _is_user_visible_status(s.get("value", ""))
    ]
    sig_text = " ".join(all_sigs + all_files)

    def _has(*kws): return any(kw in sig_text for kw in kws)
    def _risk(r): return service_risks.get(r, {}).get("risk_level", "MEDIUM").upper()
    def _files(svc): return _as_list(service_risks.get(svc, {}).get("changed_files", []))
    def _sigs(svc): return [s["function"] for s in _as_list(service_risks.get(svc, {}).get("signature_changes", []))]

    scenarios = []
    idx = 1

    # ── FE ↔ BE API contract scenarios ────────────────────────────────────────
    if fe_services and be_services:
        fe_svc = fe_services[0]
        be_svc = be_services[0]
        fe_risk = _risk(fe_svc)
        be_risk = _risk(be_svc)
        combined_risk = "HIGH" if "HIGH" in (fe_risk, be_risk) else "MEDIUM"

        fe_files = [f for f in _files(fe_svc) if not f.endswith(('.xml', 'pom.xml'))]
        be_files = [f for f in _files(be_svc) if not f.endswith(('.xml', 'pom.xml'))]
        fe_feature_hint = f" (changed screens/components: {', '.join(f.split('/')[-1] for f in fe_files[:3])})"\
            if fe_files else ""
        be_feature_hint = f" (changed endpoints/services: {', '.join(f.split('/')[-1] for f in be_files[:3])})"\
            if be_files else ""

        scenarios.append({
            "id": f"FLOW-T{idx}", "type": "FE → BE API Contract",
            "scenario": f"As a tester, when both the frontend and backend changed for the same feature, "
                        f"then what I see in the UI must match what the backend now returns",
            "tester_action": f"1. Open the feature area marked HIGH risk above{fe_feature_hint}. "
                             f"2. Perform the main user action (submit / load / trigger). "
                             f"3. Watch the Network tab — confirm the API response contains the new fields. "
                             f"4. Verify the new data appears correctly in the UI — no blank fields, no 'undefined', no spinner stuck.",
            "expected_result": f"UI shows the new data from the backend. No blank sections or console errors. "
                               f"API returns 200 with the updated response shape{be_feature_hint}.",
            "risk_level": combined_risk,
            "risk_note": f"Frontend and backend both changed — if either side missed the contract update, users will see blank or broken data",
        })
        idx += 1

    # ── Signature change propagation ──────────────────────────────────────────
    all_sig_names = list({s for r in service_risks.values() for s in [x["function"] for x in _as_list(r.get("signature_changes", []))]})
    if all_sig_names and len(services) > 1:
        sig_display = ", ".join(f"`{s}()`" for s in all_sig_names[:4])
        scenarios.append({
            "id": f"FLOW-T{idx}", "type": "Changed Function — All Callers",
            "scenario": f"As a tester, when function signatures changed ({sig_display}), "
                        f"then all services calling these functions still work correctly",
            "tester_action": f"1. Identify all features that depend on the changed functions. "
                             f"2. Exercise each affected feature end-to-end (not just unit-test level). "
                             f"3. Watch for: TypeError in browser console, 500 errors in Network tab, "
                             f"broken renders or missing data.",
            "expected_result": "No runtime errors from callers of the changed functions. "
                               "Feature behaviour unchanged — only implementation internals changed.",
            "risk_level": "HIGH",
            "risk_note": f"Signature changes in {', '.join(services)} may break callers that were not updated",
        })
        idx += 1

    # ── Removed feature / import impact ───────────────────────────────────────
    if all_removed:
        removed_display = "; ".join(all_removed[:3])
        scenarios.append({
            "id": f"FLOW-T{idx}", "type": "Removed Feature — Consumer Impact",
            "scenario": f"As a tester, when features/imports were removed ({removed_display}), "
                        f"then no other service still depends on the removed code",
            "tester_action": "1. Navigate to every area of the app that used the removed feature. "
                             "2. Verify no broken UI, missing labels, or 404 errors on assets. "
                             "3. Check browser console for 'undefined is not a function' or import errors. "
                             "4. Run the full regression suite for affected modules.",
            "expected_result": "Removed code has no visible consumer. All UI sections load without errors. "
                               "No references to removed functions in console or network failures.",
            "risk_level": "HIGH",
            "risk_note": f"Removed items: {removed_display} — verify no undiscovered callers across services",
        })
        idx += 1

    # ── New status values → state machine consistency ─────────────────────────
    if all_new_statuses:
        statuses_display = ", ".join(f'"{v}"' for v in all_new_statuses[:4])
        # Identity/account-type values get a login-centric scenario
        identity_types = [v for v in all_new_statuses if v.lower() in ('sso', 'click', 'external', 'internal', 'b2b', 'b2c', 'admin', 'partner')]
        if identity_types:
            id_list = ", ".join(identity_types)
            scenarios.append({
                "id": f"FLOW-T{idx}", "type": "User Type / Identity Branching",
                "scenario": f"As a tester, when the system now handles different user identity types ({id_list}), "
                            f"then each user type sees the correct data and no type gets another type's data",
                "tester_action": f"1. Log in as a {identity_types[0]} user — verify their account-specific data (sold-to number, account name, account type) displays correctly. "
                                f"2. Repeat for each identity type: {id_list}. "
                                f"3. Check edge case: a {identity_types[0]} user with no account data linked — verify a clean 'not available' message, not a crash or blank screen. "
                                f"4. Verify one user type cannot see another type's data.",
                "expected_result": f"Each identity type ({id_list}) sees their own account data. "
                                   f"No cross-contamination between user types. "
                                   f"Users with missing data see a graceful message, not an error.",
                "risk_level": "HIGH",
                "risk_note": f"Identity type branching ({id_list}) — if the lookup fails silently, users see blank KPI data with no error indication",
            })
        else:
            scenarios.append({
                "id": f"FLOW-T{idx}", "type": "New Status Values — Full State Transition",
                "scenario": f"As a tester, when new values ({statuses_display}) were introduced in the system, "
                            f"then every screen that shows this data displays the new values correctly",
                "tester_action": f"1. Navigate to the feature area where these values appear in the UI. "
                                f"2. Trigger the action that produces a record with value '{all_new_statuses[0]}'. "
                                f"3. Verify the value displays as expected — not as 'UNKNOWN', blank, or an error code. "
                                f"4. Check the old values still display correctly — no regression on existing data.",
                "expected_result": f"New values ({statuses_display}) display correctly in the UI. "
                                   f"Existing records with old values are unaffected. "
                                   f"No 'UNKNOWN' or fallback placeholder shown.",
                "risk_level": "HIGH",
                "risk_note": "New values introduced — all UI screens and downstream services that render this data must handle the new values",
            })
        idx += 1

    # ── Multi-BE service dependency ────────────────────────────────────────────
    if len(be_services) >= 2:
        svc_a, svc_b = be_services[0], be_services[1]
        # Surface the shared changed files to give tester a concrete handle
        a_files = [f.split('/')[-1] for f in _files(svc_a) if f.endswith('.java')][:2]
        b_files = [f.split('/')[-1] for f in _files(svc_b) if f.endswith('.java')][:2]
        a_hint = f" ({', '.join(a_files)})" if a_files else ""
        b_hint = f" ({', '.join(b_files)})" if b_files else ""
        scenarios.append({
            "id": f"FLOW-T{idx}", "type": "Shared Data — Cross-Service Consistency",
            "scenario": f"As a tester, when {svc_a}{a_hint} and {svc_b}{b_hint} both changed and share data, "
                        f"then what one service writes the other service reads correctly",
            "tester_action": f"1. Open the feature that reads data produced by both services (e.g. KPI dashboard, account detail screen). "
                             f"2. Perform a full end-to-end action — create or trigger a workflow that involves both services. "
                             f"3. Verify the resulting data in the UI is complete — no missing fields, no stale data from before the change. "
                             f"4. Check the error path: if one service is unavailable, does the UI show a clear error instead of silently showing wrong data?",
            "expected_result": f"Data flows correctly between {svc_a} and {svc_b} — no missing or stale fields in the UI. "
                               f"End-to-end action completes without 502/504. "
                               f"If one service is down, user sees a clear error message.",
            "risk_level": "MEDIUM",
            "risk_note": f"Both backend services changed — a mismatch in the data each one produces/expects will show up as blank or wrong data in the UI",
        })
        idx += 1

    # ── Permission / auth cross-service ───────────────────────────────────────
    if _has("permission", "auth", "role", "access", "token", "oauth"):
        scenarios.append({
            "id": f"FLOW-T{idx}", "type": "Cross-Service Permission Boundary",
            "scenario": "As a tester, when auth/permission logic changed in one or more services, "
                        "then user roles still see only what they're allowed to across all services",
            "tester_action": "1. Test with each user role (admin, read-only, standard user). "
                             "2. Verify restricted actions return 403 (not 200 or 500). "
                             "3. Verify permitted actions still work for authorized roles. "
                             "4. Test the boundary: a user at the edge of a permission should not gain or lose access unexpectedly.",
            "expected_result": "Role-based access unchanged for existing roles. "
                               "New permissions (if any) require explicit grant. "
                               "No privilege escalation. 401 → redirect to login. 403 → access denied message.",
            "risk_level": "HIGH",
            "risk_note": "Auth/permission changes have cross-service blast radius — a change in one service's token validation affects all callers",
        })
        idx += 1

    # ── Data model / schema change ─────────────────────────────────────────────
    if _has("model", "entity", "dto", "schema", "repository", "dao", "migration"):
        scenarios.append({
            "id": f"FLOW-T{idx}", "type": "Data Model Consistency",
            "scenario": "As a tester, when data model or DB schema changed, "
                        "then all services reading/writing that data produce and consume consistent structures",
            "tester_action": "1. Create/update a record using the primary service. "
                             "2. Read it back from every other service that consumes the same data. "
                             "3. Check: field names match, no null fields that weren't null before, "
                             "no extra fields breaking strict parsers. "
                             "4. Test backward compatibility: data written before the change still readable.",
            "expected_result": "All services read/write the same field structure. "
                               "No data loss or silent field truncation. "
                               "Existing records (pre-migration) readable without errors.",
            "risk_level": "HIGH",
            "risk_note": "Model/schema changes require all consumers to be updated in lockstep — check DB migration ran correctly",
        })
        idx += 1

    # ── New Gateway Routes ─────────────────────────────────────────────────────
    # Auto-extracted from Spring Cloud Gateway diff — surfaces specific endpoints
    if gateway_routes:
        route_items = ""
        for r in gateway_routes:
            route_items += (
                f'<br>• <code>{r["external"]}</code> '
                f'→ <code>{r["internal"]}</code> '
                f'(via <em>{r["service"]}</em>)'
            )
        route_list_str = " | ".join(
            f'{r["external"]} → {r["internal"]}' for r in gateway_routes[:4]
        )
        steps_text = (
            "1. Using Postman (or browser Network tab + DevTools), call each new route with a valid auth token:\n"
        )
        for r in gateway_routes[:5]:
            steps_text += f"   • GET {r['external']} — should return 200 with data from {r['service']}\n"
        steps_text += (
            "2. Verify each returns 200 (not 502 Bad Gateway, 404, or 500).\n"
            "3. Verify auth is enforced: call the same routes WITHOUT a token — expect 401 Unauthorized."
        )
        scenarios.append({
            "id": f"FLOW-T{idx}", "type": "New Gateway Route",
            "scenario": (
                f"As a tester, when {len(gateway_routes)} new API gateway route(s) were added "
                f"({', '.join(r['external'] for r in gateway_routes[:3])}{'…' if len(gateway_routes) > 3 else ''}), "
                f"then each endpoint must respond correctly through the gateway and reject unauthenticated calls"
            ),
            "tester_action": steps_text.strip(),
            "expected_result": (
                f"All {len(gateway_routes)} new route(s) return valid 200 responses through the gateway. "
                f"Auth token required — 401 returned without a token. "
                f"No 502 Bad Gateway (confirms the backend service is reachable). "
                f"Response body matches the expected schema from the backend service."
            ),
            "risk_level": "HIGH",
            "risk_note": (
                f"New routes registered: {route_list_str[:120]}{'…' if len(route_list_str) > 120 else ''}. "
                f"If routing is misconfigured or the backend is unreachable, calls silently fail as 502."
            ),
        })
        idx += 1

    return scenarios


# ── Filter relevant automation tests ──────────────────────────────────────

def filter_relevant_tests(test_selection: Dict, added_tests: List[str], changed_files: List[str], feature_areas: List[Dict] = None) -> List[Dict]:
    """
    Return only tests relevant to the actual changes.
    Excludes login/auth tests only when auth is NOT a risk area for this ticket.
    """
    # Determine if auth is explicitly a risk area (e.g. microservice migration)
    auth_is_risk = feature_areas and any(
        a.get("id", "").startswith("MIGRATE-AUTH") or "auth" in a.get("id", "").lower()
        for a in feature_areas
    )

    LOGIN_KEYWORDS = (
        "login", "cognito", "signin", "sign_in", "logout",
        "password", "token_refresh", "session_init"
    )
    all_tests = test_selection.get("test_cases", [])
    filtered = []
    excluded = []
    for t in all_tests:
        name = (t.get("id", "") + " " + t.get("file", "")).lower()
        is_login_test = any(k in name for k in LOGIN_KEYWORDS)
        if is_login_test and not auth_is_risk:
            # Login UI test is irrelevant — ticket doesn't touch auth/login code
            excluded.append(t)
        elif is_login_test and auth_is_risk:
            # Auth IS a risk area — but only keep login tests if frontend
            # LOGIN/AUTH components were actually changed (login page, Cognito
            # redirect handler, auth context).
            # Backend DTO classes like CognitoUserData.java are NOT login UI code.
            FRONTEND_EXTS = ('.ts', '.tsx', '.js', '.jsx')
            login_ui_changed = any(
                any(k in str(cf).lower() for k in ("login", "cognito-redirect", "auth-callback", "sign-in"))
                and any(str(cf).lower().endswith(ext) for ext in FRONTEND_EXTS)
                for cf in changed_files
            )
            if login_ui_changed:
                filtered.append(t)
            else:
                excluded.append(t)
        else:
            filtered.append(t)

    # Surface newly added test names as "must run" highlights
    highlights = []
    cm_related = ["channel", "stepper", "download", "transformation", "upc", "ean", "readiness", "submit", "syndication"]
    for test_name in added_tests[:30]:
        if any(k in test_name.lower() for k in cm_related):
            highlights.append(test_name)

    return filtered, excluded, highlights


# ── Render helpers ─────────────────────────────────────────────────────────

def render_badge(risk):
    colors = {"HIGH": "#d32f2f", "MEDIUM": "#e65100", "LOW": "#2e7d32"}
    c = colors.get(risk, "#888")
    return f'<span style="background:{c};color:#fff;border-radius:4px;padding:3px 9px;font-size:0.8em;font-weight:700;">{risk}</span>'


def render_step_table(steps, show_api=False):
    if not steps:
        return ""
    rows = ""
    for i, s in enumerate(steps, 1):
        bg = {"HIGH": "#fff5f5", "MEDIUM": "#fffbf0", "LOW": "#f0fff4"}.get(s.get("risk", "LOW"), "#fff")
        rows += f"""
        <tr style="background:{bg};border-bottom:1px solid #eee;">
          <td style="padding:10px 12px;font-weight:700;color:#555;white-space:nowrap;vertical-align:top;">{"API" if show_api else i}</td>
          <td style="padding:10px 12px;vertical-align:top;font-weight:600;color:#1a237e;">{s.get('step','') if not show_api else s.get('endpoint','')}</td>
          <td style="padding:10px 12px;vertical-align:top;">{"<span style='font-family:monospace;font-size:0.82em;background:#f5f5f5;padding:2px 6px;border-radius:3px;'>" + s.get('method','') + "</span>" if show_api else s.get('action','')}</td>
          <td style="padding:10px 12px;vertical-align:top;{'font-family:monospace;font-size:0.85em;color:#555;' if show_api else ''}">{s.get('verify','')}</td>
          <td style="padding:10px 12px;text-align:center;vertical-align:top;">{render_badge(s.get('risk','LOW'))}</td>
        </tr>"""
    header3 = "<th style='padding:10px 12px;background:#37474f;color:#fff;'>Method</th>" if show_api else "<th style='padding:10px 12px;background:#37474f;color:#fff;'>Steps (What to do)</th>"
    header2 = "<th style='padding:10px 12px;background:#37474f;color:#fff;'>Endpoint</th>" if show_api else "<th style='padding:10px 12px;background:#37474f;color:#fff;'>Test Step</th>"
    header4 = "<th style='padding:10px 12px;background:#37474f;color:#fff;'>Expected / What to verify</th>"
    return f"""<div style="overflow-x:auto;"><table style="width:100%;border-collapse:collapse;font-size:0.92em;">
  <thead><tr>
    <th style="padding:10px 12px;background:#37474f;color:#fff;width:40px;">#</th>
    {header2}{header3}{header4}
    <th style="padding:10px 12px;background:#37474f;color:#fff;text-align:center;white-space:nowrap;">Risk</th>
  </tr></thead>
  <tbody>{rows}</tbody>
</table></div>"""


def render_cross_service_table(scenarios):
    rows = ""
    for sc in scenarios:
        risk = sc.get("risk_level", "MEDIUM")
        bg = {"HIGH": "#fff5f5", "MEDIUM": "#fffbf0", "LOW": "#f0fff4"}.get(risk, "#fff")
        rows += f"""
        <tr style="background:{bg};border-bottom:1px solid #eee;">
          <td style="padding:10px 12px;font-weight:700;white-space:nowrap;vertical-align:top;color:#333;">{sc['id']}</td>
          <td style="padding:10px 12px;vertical-align:top;"><span style="background:#eee;border-radius:4px;padding:3px 7px;font-size:0.8em;font-weight:600;">{sc['type']}</span></td>
          <td style="padding:10px 12px;vertical-align:top;">{sc['scenario']}</td>
          <td style="padding:10px 12px;vertical-align:top;color:#1a237e;font-size:0.9em;">{sc['tester_action']}</td>
          <td style="padding:10px 12px;vertical-align:top;color:#1b5e20;font-size:0.9em;">{sc['expected_result']}</td>
          <td style="padding:10px 12px;text-align:center;vertical-align:top;">{render_badge(risk)}</td>
          <td style="padding:10px 12px;vertical-align:top;color:#666;font-size:0.85em;">{sc['risk_note']}</td>
        </tr>"""
    return f"""<div style="overflow-x:auto;"><table style="width:100%;border-collapse:collapse;font-size:0.92em;">
  <thead><tr style="background:#4a148c;color:#fff;">
    <th style="padding:10px 12px;text-align:left;">ID</th>
    <th style="padding:10px 12px;text-align:left;">Type</th>
    <th style="padding:10px 12px;text-align:left;min-width:180px;">Scenario</th>
    <th style="padding:10px 12px;text-align:left;min-width:220px;">Exact Steps (UI + API)</th>
    <th style="padding:10px 12px;text-align:left;min-width:180px;">Expected Result</th>
    <th style="padding:10px 12px;text-align:center;">Risk</th>
    <th style="padding:10px 12px;text-align:left;min-width:140px;">Risk Note</th>
  </tr></thead>
  <tbody>{rows}</tbody>
</table></div>"""


def render_params(params: Dict) -> str:
    if not params:
        return "<em>none</em>"
    parts = []
    for k, v in params.items():
        parts.append(f'<span style="color:#b71c1c;">{k}</span>: <span style="color:#1b5e20;">"{v}"</span>')
    return "{ " + ", ".join(parts) + " }"


# ── HTML generator ──────────────────────────────────────────────────────────

def _status_badge(status: str) -> str:
    color = {"Closed": "#2e7d32", "Done": "#2e7d32", "In Progress": "#1565c0", "Open": "#888", "To Do": "#888"}.get(status, "#555")
    return f'<span style="background:{color};color:#fff;border-radius:3px;padding:1px 7px;font-size:0.78em;">{status}</span>'


def render_jira_rich_section(jira: dict, confluence_pages: list) -> str:
    """Render the full Jira ticket section with subtasks, AC, linked tests, Confluence."""
    jira_id = jira.get("key", "UNKNOWN")
    jira_url = jira.get("url", "#")
    jira_title = jira.get("summary", "PR Risk Analysis")
    status = jira.get("status", "—")
    if isinstance(status, dict):
        status = status.get("name", "—")
    priority = jira.get("priority", "—")
    if isinstance(priority, dict):
        priority = priority.get("name", "—")
    assignee = jira.get("assignee", "—")
    reporter = jira.get("reporter", "—")
    epic = jira.get("epic", {}) or {}
    epic_key = jira.get("epic_key") or epic.get("key", "")
    epic_summary = epic.get("summary", "")
    sprint = jira.get("sprint", "")
    branch = jira.get("branch", "")
    description = jira.get("description", "")
    if isinstance(description, str):
        description = description[:800].replace("<", "&lt;").replace(">", "&gt;")

    # Acceptance Criteria
    ac_items = jira.get("acceptance_criteria", [])
    ac_html = ""
    if ac_items:
        rows = "".join(
            f'<li style="padding:4px 0;color:{"#1b5e20" if i["checked"] else "#333"};">' +
            ("&#9989; " if i["checked"] else "&#9744; ") +
            f'{i["text"]}{" <span style=\"color:#c62828;font-size:0.8em;\">(mandatory)</span>" if i.get("mandatory") else ""}</li>'
            for i in ac_items
        )
        ac_html = f'<h4 style="margin:16px 0 8px;font-size:0.95em;color:#555;text-transform:uppercase;letter-spacing:.05em;">Acceptance Criteria</h4><ul style="list-style:none;padding-left:8px;margin:0;">{rows}</ul>'

    # Subtasks
    subtasks = jira.get("subtasks", [])
    subtask_html = ""
    if subtasks:
        rows = "".join(
            f'<tr style="border-bottom:1px solid #f0f0f0;"><td style="padding:6px 10px;font-family:monospace;font-size:0.85em;">{s["key"]}</td>'
            f'<td style="padding:6px 10px;">{s["summary"]}</td>'
            f'<td style="padding:6px 10px;">{_status_badge(s["status"])}</td>'
            f'<td style="padding:6px 10px;font-size:0.82em;color:#888;">{s.get("priority","")}</td></tr>'
            for s in subtasks
        )
        subtask_html = f'<h4 style="margin:16px 0 8px;font-size:0.95em;color:#555;text-transform:uppercase;letter-spacing:.05em;">Subtasks</h4><table style="width:100%;border-collapse:collapse;"><thead><tr style="background:#f5f5f5;"><th style="padding:6px 10px;text-align:left;font-size:0.82em;">Key</th><th style="padding:6px 10px;text-align:left;font-size:0.82em;">Summary</th><th style="padding:6px 10px;text-align:left;font-size:0.82em;">Status</th><th style="padding:6px 10px;text-align:left;font-size:0.82em;">Priority</th></tr></thead><tbody>{rows}</tbody></table>'

    # Linked test cases
    issue_links = jira.get("issue_links", [])
    test_links = [l for l in issue_links if l.get("issue_type") == "Test" or l.get("type") == "Tests"]
    other_links = [l for l in issue_links if l not in test_links]
    test_link_html = ""
    if test_links:
        rows = "".join(
            f'<tr style="border-bottom:1px solid #f0f0f0;"><td style="padding:6px 10px;font-family:monospace;font-size:0.85em;color:#1565c0;">{l["key"]}</td>'
            f'<td style="padding:6px 10px;font-size:0.88em;">{l["summary"]}</td>'
            f'<td style="padding:6px 10px;">{_status_badge(l["status"])}</td></tr>'
            for l in test_links
        )
        test_link_html = f'<h4 style="margin:16px 0 8px;font-size:0.95em;color:#555;text-transform:uppercase;letter-spacing:.05em;">Linked Test Cases</h4><table style="width:100%;border-collapse:collapse;"><thead><tr style="background:#f5f5f5;"><th style="padding:6px 10px;text-align:left;font-size:0.82em;">Key</th><th style="padding:6px 10px;text-align:left;font-size:0.82em;">Summary</th><th style="padding:6px 10px;text-align:left;font-size:0.82em;">Status</th></tr></thead><tbody>{rows}</tbody></table>'

    # Other links (blocks, clones, etc.)
    other_link_html = ""
    if other_links:
        rows = "".join(
            f'<tr style="border-bottom:1px solid #f0f0f0;"><td style="padding:5px 10px;font-size:0.8em;color:#888;">{l.get("label",l.get("type",""))}</td>'
            f'<td style="padding:5px 10px;font-family:monospace;font-size:0.82em;">{l["key"]}</td>'
            f'<td style="padding:5px 10px;font-size:0.85em;">{l["summary"]}</td>'
            f'<td style="padding:5px 10px;">{_status_badge(l["status"])}</td></tr>'
            for l in other_links[:10]
        )
        other_link_html = f'<h4 style="margin:16px 0 8px;font-size:0.95em;color:#555;text-transform:uppercase;letter-spacing:.05em;">Related Issues</h4><table style="width:100%;border-collapse:collapse;"><tbody>{rows}</tbody></table>'

    # Confluence pages
    conf_html = ""
    if confluence_pages:
        items_list = []
        for p in confluence_pages[:8]:
            space_tag = f' <span style="color:#aaa;font-size:0.78em;">({p["space"]})</span>' if p.get("space") else ""
            items_list.append(
                '<li style="padding:4px 0;">'
                '<a href="' + p.get("url", "#") + '" target="_blank" style="color:#1565c0;text-decoration:none;font-size:0.9em;">'
                + p.get("title", "") + "</a>" + space_tag + "</li>"
            )
        items = "".join(items_list)
        conf_html = f'<h4 style="margin:16px 0 8px;font-size:0.95em;color:#555;text-transform:uppercase;letter-spacing:.05em;">&#128196; Related Confluence Pages</h4><ul style="list-style:none;padding-left:8px;">{items}</ul>'

    return f"""
  <table class="meta">
    <tr><td>Ticket</td><td><strong><a href="{jira_url}" target="_blank" style="color:#1a237e;">{jira_id}</a></strong></td></tr>
    <tr><td>Summary</td><td><strong>{jira_title}</strong></td></tr>
    <tr><td>Status</td><td>{_status_badge(status)}</td></tr>
    <tr><td>Priority</td><td>{priority}</td></tr>
    <tr><td>Assignee</td><td>{assignee}</td></tr>
    <tr><td>Reporter</td><td>{reporter}</td></tr>
    {f'<tr><td>Epic</td><td><span style="font-family:monospace;font-size:0.9em;">{epic_key}</span> — {epic_summary}</td></tr>' if epic_key else ''}
    {f'<tr><td>Sprint</td><td>{sprint}</td></tr>' if sprint else ''}
    {f'<tr><td>Branch</td><td><code style="font-size:0.85em;background:#f5f5f5;padding:2px 6px;border-radius:3px;">{branch}</code></td></tr>' if branch else ''}
  </table>
  {f'<div class="info" style="margin-top:14px;white-space:pre-wrap;font-size:0.88em;">{description}...</div>' if description else ''}
  {ac_html}
  {subtask_html}
  {test_link_html}
  {other_link_html}
  {conf_html}
"""


def _area_card(area: Dict) -> str:
    risk = area["risk"]
    guard = area.get("regression_guard", "")
    scenarios = area.get("scenarios", [])
    bullets = "".join(f"<li>{s}</li>" for s in scenarios)
    guard_html = f'<div class="guard"><strong>⚡ Guard:</strong> {guard}</div>' if guard else ""
    return f"""<div class="area-card {risk}">
  <div class="area-title">{area['emoji']} <span>{area['name']}</span> <span class="badge {risk}">{risk}</span></div>
  <div class="area-desc">{area.get('description','')}</div>
  {guard_html}<ul class="scenarios">{bullets}</ul>
</div>"""


def _matrix_row(area: Dict) -> str:
    risk = area["risk"]
    guard = area.get("regression_guard", "—")
    skip = "✓ Skip if no related ticket" if risk == "LOW" else ""
    return (f"<tr><td>{area['emoji']} {area['name']}</td>"
            f"<td><span class='badge {risk}'>{risk}</span></td>"
            f"<td style='font-size:0.85em;color:#555;'>{area.get('description','')[:90]}…</td>"
            f"<td style='font-size:0.85em;'>{guard}</td>"
            f"<td style='font-size:0.82em;color:#888;'>{skip}</td></tr>")


def generate_manual_test_scenarios(jira: Dict, consolidated: Dict) -> str:
    """
    When no automation tests are found, generate manual test scenarios from Jira description.
    Particularly useful for microservice migrations and architectural changes.
    """
    description = jira.get("description", "").lower()
    services = consolidated.get("services_analyzed", [])
    
    # Detect microservice migration pattern
    is_microservice_migration = any(keyword in description for keyword in [
        "microservice", "independent", "migration", "separate service", "create new service"
    ])
    
    if not is_microservice_migration or not services:
        return ""
    
    # Generate test scenarios based on microservice migration
    test_scenarios = []
    scenario_id = 1
    
    # Gateway/Routing tests
    test_scenarios.append({
        "id": f"PR-T{scenario_id}",
        "type": "Positive",
        "scenario": "As a consumer when I call the new service endpoint then my request is routed correctly",
        "action": f"Send a request to new service endpoint for {services[0] if services else 'new service'}",
        "expected": "Service responds with 200 OK within SLA latency",
        "risk": "HIGH",
        "note": "Route misconfiguration could silently fail"
    })
    scenario_id += 1
    
    test_scenarios.append({
        "id": f"PR-T{scenario_id}",
        "type": "Negative",
        "scenario": "As a consumer when I call the old endpoint then it properly redirects or rejects",
        "action": "Send a request to old/legacy endpoint",
        "expected": "Returns 301 redirect or 410 Gone with helpful error message",
        "risk": "HIGH",
        "note": "Silent route breakage causes client failures"
    })
    scenario_id += 1
    
    # Auth/Access tests
    test_scenarios.append({
        "id": f"PR-T{scenario_id}",
        "type": "Positive",
        "scenario": "As a user when I access the new service then my permissions are enforced",
        "action": "Make request to new service with valid auth token",
        "expected": "Auth headers are preserved and new service validates token correctly",
        "risk": "HIGH",
        "note": "Permission boundaries may not be enforced in new service"
    })
    scenario_id += 1
    
    # Cross-service integration tests
    test_scenarios.append({
        "id": f"PR-T{scenario_id}",
        "type": "Integration",
        "scenario": "As a platform when services are deployed independently then system remains stable",
        "action": f"Deploy {services[0]} without deploying other services. Make requests.",
        "expected": "New service operates independently without cascading failures",
        "risk": "HIGH",
        "note": "Independent deployments not achieved if services fail without each other"
    })
    
    # Render test scenarios as HTML table (dark theme)
    test_rows_html = ""
    for test in test_scenarios:
        rb_bg = {"HIGH": "#ff6b6b", "MEDIUM": "#ffa94d", "LOW": "#69db7c"}[test["risk"]]
        rb_fg = {"HIGH": "#fff", "MEDIUM": "#000", "LOW": "#000"}[test["risk"]]
        type_cls = {"Positive": "type-positive", "Negative": "type-negative",
                    "Integration": "type-integration", "Exploratory": "type-exploratory"}.get(test["type"], "type-integration")
        test_rows_html += (
            f'<tr>'
            f'<td class="id">{test["id"]}</td>'
            f'<td><span class="type-badge {type_cls}">{test["type"]}</span></td>'
            f'<td>{test["scenario"]}</td>'
            f'<td style="color:#79c0ff;">{test["action"]}</td>'
            f'<td style="color:#3fb950;">{test["expected"]}</td>'
            f'<td><span class="risk-badge" style="background:{rb_bg};color:{rb_fg};">{test["risk"]}</span></td>'
            f'<td style="color:#8b949e;">{test["note"]}</td>'
            f'</tr>'
        )

    return f'''<div style="margin-top:10px;">
        <p style="font-size:0.87em;color:#8b949e;margin-bottom:10px;"><strong style="color:#c9d1d9;">Generated Manual Test Scenarios</strong> — Based on microservice architecture pattern detected in this ticket.</p>
        <table>
            <thead><tr>
                <th style="width:75px;">Test ID</th>
                <th>Type</th>
                <th>Scenario</th>
                <th>Tester Action</th>
                <th>Expected Result</th>
                <th style="width:80px;">Risk</th>
                <th>Risk Note</th>
            </tr></thead>
            <tbody>{test_rows_html}</tbody>
        </table>
    </div>'''


def generate_html(jira, consolidated, summary, test_selection, confluence_pages=None, test_index=None, gateway_routes=None) -> str:
    if confluence_pages is None:
        confluence_pages = []
    jira_id = jira.get("key", consolidated.get("jira_id", "UNKNOWN"))
    jira_title = jira.get("summary", jira.get("title", "PR Risk Analysis"))
    jira_desc = jira.get("description", "")
    jira_status = jira.get("status", "—")
    if isinstance(jira_status, dict):
        jira_status = jira_status.get("name", "—")
    jira_priority = jira.get("priority", "—")
    if isinstance(jira_priority, dict):
        jira_priority = jira_priority.get("name", "—")
    sprint = jira.get("sprint", "—")
    assignee = jira.get("assignee", "—")

    risk_summary = consolidated.get("risk_summary", {})
    high_count = risk_summary.get("high_risk_services", 0)
    overall_risk = "HIGH" if high_count > 0 else "MEDIUM"
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")

    changed_files = summary.get("changed_files", [])
    new_statuses = summary.get("new_status_values", [])
    removed_features = summary.get("removed_features", [])
    added_tests = consolidated.get("service_risks", {}).get("dtb-fe-react-v1", {}).get("test_changes", {}).get("added_tests", [])

    feature_areas = detect_feature_areas(changed_files, new_statuses, removed_features, added_tests)

    # Fallback: when no FE-pattern areas matched, build areas directly from consolidated service_risks
    if not feature_areas:
        _service_risks = consolidated.get("service_risks", {})
        _high_changes = consolidated.get("high_risk_changes", [])
        _fallback_areas = []
        for _svc, _sdata in _service_risks.items():
            _rl = _sdata.get("risk_level", "low").upper()
            _fc = _sdata.get("files_changed", 0)
            _sc = _sdata.get("signature_changes", 0)
            _rm = _sdata.get("removed_features", 0)
            _langs = ", ".join(_sdata.get("languages", ["unknown"]))
            _assertions = _sdata.get("test_changes", {}).get("modified_assertions", [])
            _svc_changes = [c for c in _high_changes if c.get("service") == _svc]
            _scenarios = []
            for _c in _svc_changes[:4]:
                _fn = _c.get("function", "endpoint")
                _impact = _c.get("impact", "COMPATIBLE")
                _old_r, _new_r = _c.get("old_return", ""), _c.get("new_return", "")
                if _impact == "BREAKING" and _old_r and _new_r:
                    _scenarios.append(f"BREAKING: {_fn}() return type changed {_old_r} \u2192 {_new_r} \u2014 audit all callers for the new response schema")
                else:
                    _scenarios.append(f"Verify {_fn}() behaves correctly with updated parameters/return type")
            for _a in _assertions[:4]:
                _scenarios.append(f"Test assertion changed: {_a} \u2014 verify production behavior matches updated expectation")
            if _rm > 0:
                _scenarios.append(f"{_rm} endpoint/feature removal(s) \u2014 verify 404/410 returned, not 500 or silent empty response")
            if _fc > 50:
                _scenarios.append(f"Large change ({_fc} files, {_langs}) \u2014 run full happy path regression")
            if not _scenarios:
                _scenarios.append(f"{_fc} files changed \u2014 verify core {_svc} functionality end-to-end")
            _guard = (_svc_changes[0].get("function", "primary endpoint") + " returns expected response"
                      if _svc_changes else f"{_svc} core workflow completes without errors")
            _emoji = "\U0001f534" if _rl == "HIGH" else ("\U0001f7e1" if _rl == "MEDIUM" else "\U0001f7e2")
            _fallback_areas.append({
                "id": _svc.upper().replace("-", "_"),
                "name": _svc,
                "emoji": _emoji,
                "risk": _rl,
                "description": f"{_fc} files changed \u00b7 {_sc} signature change(s) \u00b7 {_rm} removal(s) \u00b7 {_langs}",
                "regression_guard": _guard,
                "scenarios": _scenarios,
            })
        feature_areas = _fallback_areas

    relevant_tests, excluded_tests, _ = filter_relevant_tests(test_selection, added_tests, changed_files, feature_areas)

    high_areas  = [a for a in feature_areas if a["risk"] == "HIGH"]
    med_areas   = [a for a in feature_areas if a["risk"] == "MEDIUM"]
    low_areas   = [a for a in feature_areas if a["risk"] == "LOW"]

    # ── Risk matrix ───────────────────────────────────────────────────────
    matrix_rows = "".join(_matrix_row(a) for a in feature_areas)

    # ── Area cards ────────────────────────────────────────────────────────
    high_cards = "".join(_area_card(a) for a in high_areas)
    med_cards  = "".join(_area_card(a) for a in med_areas)
    low_list   = "".join(
        f'<span style="display:inline-block;margin:4px 6px 4px 0;padding:4px 10px;background:#f0fff4;border:1px solid #a5d6a7;border-radius:4px;font-size:0.85em;">'
        f'{a["emoji"]} {a["name"]} <span class="badge LOW" style="margin-left:4px;">LOW</span></span>'
        for a in low_areas
    )

    # ── Linked test cases from Jira ───────────────────────────────────────
    test_links = [l for l in jira.get("issue_links", [])
                  if str(l.get("issue_type","")).lower() == "test" or str(l.get("type","")).lower() == "tests"]
    if test_links:
        test_links_html = (
            "<p style='font-size:0.88em;color:#555;margin-bottom:10px;'>Run these existing test cases — they directly cover changes in this PR:</p>"
            + "".join(
                f'<a class="test-link" href="https://your-jira-instance.example.com/browse/{l["key"]}" target="_blank">'
                f'<span class="badge MEDIUM" style="background:#1565c0;">{l["key"]}</span>'
                f'<span>{l.get("summary","")}</span></a>'
                for l in test_links
            )
        )
    else:
        test_links_html = '<p style="color:#aaa;font-size:0.88em;">No linked test cases found in Jira.</p>'

    # ── Subtask status ────────────────────────────────────────────────────
    subtasks = jira.get("subtasks", [])
    open_subtasks = [s for s in subtasks if s.get("status", "").lower() not in ("closed", "done", "resolved")]
    subtask_rows = ""
    for s in subtasks:
        st = s.get("status", "—")
        badge_cls = "CLOSED" if st.lower() in ("closed","done","resolved") else ("INPROGRESS" if "progress" in st.lower() else "OPEN")
        subtask_rows += (
            f'<div class="subtask-row">'
            f'<span class="badge {badge_cls}">{st}</span>'
            f'<span style="font-family:monospace;color:#555;">{s["key"]}</span>'
            f'<span>{s.get("summary","")}</span></div>'
        )
    open_subtask_warn = ""
    if open_subtasks:
        warn_items = "".join(f'<li>{s["key"]} — {s.get("summary","")}</li>' for s in open_subtasks)
        open_subtask_warn = f'<div class="warn"><strong>⚠ {len(open_subtasks)} subtask(s) still Open:</strong><ul style="margin:6px 0 0 18px;">{warn_items}</ul><p style="margin-top:6px;font-size:0.85em;">These may not be deployed yet — verify backend is ready before testing.</p></div>'

    # ── Skip list ─────────────────────────────────────────────────────────
    test_file_count = sum(1 for f in changed_files if ".test." in f.lower() or ".spec." in f.lower())
    skip_items = [f"<div class='skip-item'>{test_file_count} test files changed (.test.tsx/.test.ts) — unit test scaffolding only, no production logic</div>"]
    for a in low_areas:
        skip_items.append(f"<div class='skip-item'>{a['emoji']} {a['name']} — {a.get('description','').split('.')[0]}. Safe to skip unless visually broken.</div>")
    skip_html = "".join(skip_items) if skip_items else "<p style='color:#aaa;font-size:0.88em;'>Nothing identified as safe to skip.</p>"

    # ── Automation tests: test files → tags → Jenkins parameter ────────
    NOISE_TAGS = {'P1', 'P2', 'Critical', 'Negative', 'RegressionDTB', 'fixtures',
                  'test', 'pages', 'TEST_DTB', 'Navigation1', 'MarketingAssets1'}
    SKIP_WORDS = {
        'src', 'test', 'tests', 'spec', 'tsx', 'scss', 'json', 'yaml', 'html',
        'jsx', 'snap', 'frontend', 'backend', 'api', 'assets', 'styles',
        'components', 'hooks', 'utils', 'types', 'interfaces', 'mocks',
        'reducers', 'selectors', 'constants', 'services', 'state', 'public',
        'deploy', 'common', 'modal', 'index', 'config', 'webpack', 'jenkinsfile',
        'download', 'create', 'update', 'remove', 'delete', 'legacy', 'base',
        'step', 'steps', 'app', 'main', 'root', 'lib', 'dist', 'build',
    }
    RISK_ORDER = {'HIGH': 0, 'MEDIUM': 1, 'LOW': 2}

    import re as _re

    def _extract_change_keywords(file_paths, min_len=6):
        kws = set()
        for fp in file_paths:
            for part in _re.split(r'[/\\]', fp):
                name = _re.sub(r'\.[^.]+$', '', part)
                spaced = _re.sub(r'([a-z])([A-Z])', r'\1 \2', name)
                for w in _re.split(r'[^a-zA-Z]+', spaced):
                    wl = w.lower()
                    if len(wl) >= min_len and wl not in SKIP_WORDS:
                        kws.add(wl)
        return kws

    def _functional_tags(t):
        return sorted({tag for tag in t.get('tags', [])
                       if tag not in NOISE_TAGS and not tag.startswith('TEST_')})

    all_index_tests = test_index if test_index else []
    change_kws = _extract_change_keywords(changed_files)

    # Build: test_file → {test_obj, area_name, area_risk, area_emoji}
    # A test file may be claimed by multiple areas; keep highest-risk claim.
    test_to_area: dict = {}   # file path → area dict entry

    covered_area_ids = set()
    for area in feature_areas:
        area_risk  = area['risk']
        area_name  = area['name']
        area_emoji = area['emoji']
        area_id    = area['id']
        area_name_words = [w.lower() for w in _re.split(r'\W+', area_name) if len(w) >= 6]
        area_kws = [w for w in area_name_words if w in change_kws]
        if not area_kws:
            continue
        norm_map = {}
        for t in all_index_tests:
            norm = t.get('file', '').lower().replace('-','').replace('_','').replace('\\','/').replace('/','')
            if any(kw in norm for kw in area_kws):
                fp = t.get('file', '')
                existing = test_to_area.get(fp)
                if not existing or RISK_ORDER.get(area_risk, 2) < RISK_ORDER.get(existing['area_risk'], 2):
                    test_to_area[fp] = {
                        'test': t, 'area_name': area_name,
                        'area_risk': area_risk, 'area_emoji': area_emoji,
                    }
                covered_area_ids.add(area_id)

    gap_areas = [a for a in feature_areas if a['id'] not in covered_area_ids]
    gap_count = len(gap_areas)

    if relevant_tests:
        # ── Primary view: per-test-case from test_selection.json ──────────────
        # Shows each selected test with its Jira test ID, description, spec file,
        # deduplicated run tags, and risk. Provides a copy-paste run command.
        RUN_NOISE = {'fixtures', 'test', 'pages', 'TEST_DTB', 'Navigation1', 'MarketingAssets1'}

        def _clean_tags(raw):
            seen_t = set()
            result = []
            for tag in raw:
                if tag not in RUN_NOISE and tag not in seen_t:
                    seen_t.add(tag)
                    result.append(tag)
            return result

        def _test_id(tc_name):
            m = _re.search(r'DTB-(\d+)', tc_name or '')
            return f'TEST_DTB-{m.group(1)}' if m else None

        def _test_desc(tc_name):
            if '|' in tc_name:
                return tc_name.split('|', 1)[1].strip()
            cleaned = _re.sub(r'@\S+\s*', '', tc_name).strip()
            return cleaned or tc_name

        all_run_tags = []
        run_tag_seen = set()
        test_rows = ""
        for t in relevant_tests:
            tc_name = t.get('testCase', t.get('id', ''))
            tid = _test_id(tc_name)
            desc = _test_desc(tc_name)
            spec = t.get('file', '').replace('\\', '/').split('/')[-1].replace('.spec.ts', '')
            risk = t.get('risk', 'medium').upper()
            ctags = _clean_tags(t.get('tags', []))
            for tag in ctags:
                if tag not in run_tag_seen:
                    run_tag_seen.add(tag)
                    all_run_tags.append(tag)

            tag_chips = ''.join(
                f'<span style="display:inline-block;margin:1px 2px;padding:2px 8px;'
                f'background:#e8f5e9;border:1px solid #a5d6a7;border-radius:10px;'
                f'font-family:monospace;font-size:0.79em;color:#1b5e20;font-weight:600;">'
                f'@{tag}</span>'
                for tag in ctags
            ) or '<span style="color:#aaa;font-size:0.8em;">—</span>'

            id_badge = (
                f'<a href="https://your-jira-instance.example.com/browse/{tid}" target="_blank" '
                f'style="font-family:monospace;font-size:0.8em;background:#e3f2fd;'
                f'border:1px solid #90caf9;border-radius:3px;padding:1px 6px;color:#0d47a1;'
                f'text-decoration:none;">{tid}</a>'
            ) if tid else '<span style="color:#aaa;font-size:0.8em;">—</span>'

            bg = {'HIGH': '#fff8f8', 'MEDIUM': '#fffbf4', 'LOW': '#f7fdf7'}.get(risk, '#fff')
            test_rows += (
                f'<tr style="background:{bg};border-bottom:1px solid #f0f0f0;">'
                f'<td style="padding:6px 10px;white-space:nowrap;">{id_badge}</td>'
                f'<td style="padding:6px 10px;font-size:0.83em;">{desc}</td>'
                f'<td style="padding:6px 10px;font-family:monospace;font-size:0.79em;color:#1a237e;white-space:nowrap;">{spec}</td>'
                f'<td style="padding:6px 10px;text-align:center;"><span class="badge {risk}">{risk}</span></td>'
                f'<td style="padding:6px 10px;">{tag_chips}</td>'
                f'</tr>'
            )

        all_jenkins_tags = set(all_run_tags)
        tag_run_str = ' '.join(f'@{t}' for t in all_run_tags)
        grep_ids_set = []
        grep_seen = set()
        for t in relevant_tests:
            m = _re.search(r'DTB-\d+', t.get('testCase', t.get('id', '')))
            if m and m.group(0) not in grep_seen:
                grep_seen.add(m.group(0))
                grep_ids_set.append(m.group(0))
        grep_ids = '|'.join(grep_ids_set)

        run_box = (
            '<div style="background:#0d2117;border:1px solid #238636;border-radius:6px;'
            'padding:12px 16px;margin-bottom:10px;">'
            '<div style="font-size:0.78em;text-transform:uppercase;letter-spacing:.06em;'
            'color:#3fb950;font-weight:700;margin-bottom:6px;">Run These Tests</div>'
            + ('<div style="font-size:0.84em;color:#8b949e;margin-bottom:4px;">Tags (paste into Jenkins / test runner):</div>'
               f'<code style="display:block;font-size:0.9em;color:#79c0ff;word-break:break-all;'
               f'background:#0d1117;border:1px solid #30363d;padding:6px 10px;border-radius:4px;margin-bottom:8px;">'
               f'{tag_run_str}</code>' if tag_run_str else '')
            + (f'<div style="font-size:0.84em;color:#8b949e;margin-bottom:4px;">Or run by test ID (Jest grep):</div>'
               f'<code style="display:block;font-size:0.9em;color:#79c0ff;word-break:break-all;'
               f'background:#0d1117;border:1px solid #30363d;padding:6px 10px;border-radius:4px;">'
               f'--testNamePattern "{grep_ids}"</code>' if grep_ids else '')
            + '</div>'
        )

        gap_section = ""
        if gap_areas:
            gap_items = "".join(
                f'<li style="padding:2px 0;">{a["emoji"]} {a["name"]} '
                f'<span class="badge {a["risk"]}" style="font-size:0.72em;">{a["risk"]}</span></li>'
                for a in gap_areas
            )
            gap_section = (
                f'<div class="warn" style="margin-bottom:10px;">'
                f'<strong>⚠ {gap_count} area(s) have no automation coverage — manual testing required:</strong>'
                f'<ul style="margin:6px 0 0 18px;font-size:0.85em;color:#e3b341;">{gap_items}</ul></div>'
            )

        auto_tests_html = (
            run_box + gap_section
            + f'<div style="font-size:0.85em;color:#8b949e;margin-bottom:8px;">'
            + f'{len(relevant_tests)} test case(s) selected from automation suite</div>'
            + '<table>'
            + '<thead><tr>'
            + '<th>Test ID</th>'
            + '<th>Test Name</th>'
            + '<th>Spec File</th>'
            + '<th style="text-align:center;">Risk</th>'
            + '<th>Tags (to run)</th></tr></thead>'
            + f'<tbody>{test_rows}</tbody></table>'
        )
    else:
        all_jenkins_tags = set()
        open_test_subtask = next(
            (s["key"] + " — " + s.get("summary", "")
             for s in jira.get("subtasks", [])
             if s.get("status", "").lower() == "open"),
            "none found"
        )
        
        # Try to generate manual test scenarios if applicable
        manual_scenarios = generate_manual_test_scenarios(jira, consolidated)
        
        if manual_scenarios:
            auto_tests_html = (
                '<div class="warn"><strong>⚠ No automation coverage found</strong> — '
                'generating manual test scenarios based on architecture pattern detected in Jira.</div>'
                + manual_scenarios
            )
        else:
            auto_tests_html = (
                '<div class="warn"><strong>⚠ No automation coverage found for any risk area '
                'in this ticket.</strong><br>'
                f'<span style="font-size:0.87em;color:#e3b341;">The test suite has no tests matching these '
                f'changed components. All risk areas require manual testing.<br>'
                f'Open subtask for test creation: <strong>{open_test_subtask}</strong></span></div>'
            )

    # ── Confluence pages (compact) ────────────────────────────────────────
    conf_links = "".join(
        f'<a href="{p.get("url","#")}" target="_blank" style="display:inline-block;margin:3px 6px 3px 0;padding:4px 10px;background:#e8eaf6;border-radius:4px;font-size:0.83em;color:#283593;text-decoration:none;">'
        f'📄 {p.get("title","Page")}</a>'
        for p in confluence_pages[:5]
    )
    conf_section = (f'<div style="margin-top:10px;">{conf_links}</div>' if conf_links else "")

    # ── Cross-service integration scenarios ──────────────────────────────
    cross_scenarios = build_cross_service_flow(consolidated, gateway_routes=gateway_routes or [])
    if cross_scenarios:
        services_list = ", ".join(consolidated.get("services_analyzed", []))
        _cross_service_section_html = (
            '<div class="section">'
            '<h2>&#128257; Cross-Service Integration Tests</h2>'
            f'<p style="font-size:0.84em;color:#555;margin-bottom:10px;">'
            f'Changes detected in <strong>{len(consolidated.get("services_analyzed", []))}</strong> service(s): '
            f'<code style="background:#f5f5f5;padding:2px 6px;border-radius:3px;font-size:0.9em;">{services_list}</code>. '
            f'These scenarios test the boundaries between them.</p>'
            + render_cross_service_table(cross_scenarios)
            + '</div>'
        )
    else:
        _cross_service_section_html = ""

    # ── Dark theme helpers ────────────────────────────────────────────────
    _n_services = len(consolidated.get("services_analyzed", []))
    _n_scenarios = len(relevant_tests) if relevant_tests else 0

    # Risk border colour for header meta cards
    _risk_border = {"HIGH": "#ff6b6b", "MEDIUM": "#ffa94d", "LOW": "#69db7c"}.get(overall_risk, "#58a6ff")

    # Rebuild area cards in dark theme
    def _dark_area_card(area):
        risk = area.get("risk", "LOW")
        border = {"HIGH": "#ff6b6b", "MEDIUM": "#ffa94d", "LOW": "#69db7c"}.get(risk, "#58a6ff")
        bg     = {"HIGH": "#2d1117", "MEDIUM": "#2d1a0e", "LOW": "#0d2117"}.get(risk, "#161b22")
        badge_bg = {"HIGH": "#da3633", "MEDIUM": "#9a4b00", "LOW": "#238636"}.get(risk, "#1f6feb")
        scenarios_html = "".join(
            f'<li style="padding:3px 0 3px 18px;position:relative;font-size:0.87em;color:#c9d1d9;">'
            f'<span style="position:absolute;left:0;color:#58a6ff;">→</span>{s}</li>'
            for s in area.get("scenarios", [])
        )
        guard = area.get("regression_guard", "")
        return (
            f'<div style="border-left:4px solid {border};background:{bg};padding:12px 16px;'
            f'margin-bottom:10px;border-radius:0 6px 6px 0;">'
            f'<div style="font-weight:700;font-size:1em;display:flex;align-items:center;gap:8px;margin-bottom:5px;color:#c9d1d9;">'
            f'{area.get("emoji","")} {area.get("name","")}'
            f'<span style="background:{badge_bg};color:#fff;border-radius:3px;padding:1px 7px;font-size:0.75em;">{risk}</span></div>'
            f'<div style="color:#8b949e;font-size:0.87em;margin-bottom:8px;">{area.get("description","")}</div>'
            + (f'<div style="background:#161b22;border:1px solid #f9a825;border-radius:4px;padding:6px 10px;'
               f'font-size:0.85em;margin-bottom:8px;color:#e3b341;"><strong>Regression Guard:</strong> {guard}</div>' if guard else '')
            + (f'<ul style="list-style:none;padding:0;margin:0;">{scenarios_html}</ul>' if scenarios_html else '')
            + '</div>'
        )

    _high_cards_dark = "".join(_dark_area_card(a) for a in high_areas)
    _med_cards_dark  = "".join(_dark_area_card(a) for a in med_areas)
    _low_cards_dark  = "".join(_dark_area_card(a) for a in low_areas)

    # Rebuild matrix rows in dark theme
    _matrix_rows_dark = ""
    for area in feature_areas:
        risk = area.get("risk", "LOW")
        badge_bg = {"HIGH": "#da3633", "MEDIUM": "#9a4b00", "LOW": "#238636"}.get(risk, "#1f6feb")
        why = area.get("description", "")[:120] + ("…" if len(area.get("description", "")) > 120 else "")
        guard = area.get("regression_guard", "—")
        skip = "Skip if no related ticket" if risk == "LOW" else ("Test in scope" if risk == "MEDIUM" else "Must test")
        _matrix_rows_dark += (
            f'<tr style="border-bottom:1px solid #30363d;">'
            f'<td style="padding:9px 12px;color:#c9d1d9;">{area.get("emoji","")} {area.get("name","")}</td>'
            f'<td style="padding:9px 12px;"><span style="background:{badge_bg};color:#fff;border-radius:3px;padding:2px 8px;font-size:0.8em;font-weight:700;">{risk}</span></td>'
            f'<td style="padding:9px 12px;color:#8b949e;font-size:0.87em;">{why}</td>'
            f'<td style="padding:9px 12px;color:#c9d1d9;font-size:0.87em;">{guard}</td>'
            f'<td style="padding:9px 12px;color:#8b949e;font-size:0.84em;">✓ {skip}</td>'
            f'</tr>'
        )

    # Rebuild subtask rows in dark theme
    _subtask_rows_dark = ""
    for s in jira.get("subtasks", []):
        st = s.get("status", "OPEN").upper()
        st_bg = {"CLOSED": "#238636", "DONE": "#238636", "IN PROGRESS": "#1565c0", "INPROGRESS": "#1565c0"}.get(st, "#da3633")
        _subtask_rows_dark += (
            f'<div style="display:flex;align-items:center;gap:10px;padding:6px 0;border-bottom:1px solid #30363d;font-size:0.88em;">'
            f'<span style="background:{st_bg};color:#fff;border-radius:3px;padding:1px 7px;font-size:0.75em;white-space:nowrap;">{st}</span>'
            f'<a href="https://your-jira-instance.example.com/browse/{s.get("key","")}" target="_blank" style="color:#58a6ff;text-decoration:none;">{s.get("key","")}</a>'
            f'<span style="color:#8b949e;">{s.get("summary","")}</span>'
            f'</div>'
        )

    # Rebuild skip items in dark theme
    _skip_html_dark = "".join(
        f'<div style="padding:5px 0;font-size:0.87em;color:#8b949e;display:flex;gap:8px;align-items:flex-start;">'
        f'<span style="color:#3fb950;font-weight:700;flex-shrink:0;">✓</span>{item}</div>'
        for item in (skip_html.replace('<div class=\'skip-item\'>', '').replace('</div>', '\n').split('\n') if skip_html else [])
        if item.strip()
    )

    # Rebuild confluence links in dark theme
    _conf_links_dark = "".join(
        f'<a href="{p.get("url","#")}" target="_blank" style="display:inline-block;margin:3px 6px 3px 0;'
        f'padding:5px 11px;background:#161b22;border:1px solid #30363d;border-radius:4px;font-size:0.85em;'
        f'color:#58a6ff;text-decoration:none;">📄 {p.get("title","Page")}</a>'
        for p in confluence_pages[:5]
    )

    # Rebuild test links in dark theme
    _test_links_dark = ""
    for tc in jira.get("test_cases", []):
        key = tc.get("key", "")
        summ = tc.get("summary", tc.get("name", key))
        _test_links_dark += (
            f'<a href="https://your-jira-instance.example.com/browse/{key}" target="_blank" '
            f'style="display:inline-flex;align-items:center;gap:7px;padding:6px 12px;'
            f'background:#161b22;border:1px solid #30363d;border-radius:4px;font-size:0.86em;'
            f'text-decoration:none;color:#58a6ff;margin:3px 4px 3px 0;">{key} — {summ}</a>'
        )
    if not _test_links_dark:
        _test_links_dark = '<p style="color:#484f58;font-size:0.88em;">No linked test cases found in Jira.</p>'

    # Rebuild open-subtask warning in dark theme
    _open_warn_dark = ""
    if open_subtask_warn:
        _open_warn_dark = (
            '<div style="background:#2d1a0e;border-left:3px solid #ffa94d;padding:10px 14px;'
            'border-radius:0 4px 4px 0;font-size:0.87em;color:#e3b341;margin-bottom:12px;">'
            + open_subtask_warn.replace('<div class="warn">', '').replace('</div>', '')
            + '</div>'
        )

    # Rebuild cross-service section in dark theme
    _cross_dark = ""
    if cross_scenarios:
        services_list = ", ".join(consolidated.get("services_analyzed", []))
        _cross_dark = (
            '<section class="section">'
            '<h2>🔄 Cross-Service Integration Tests</h2>'
            f'<p style="font-size:0.87em;color:#8b949e;margin-bottom:14px;">'
            f'Changes detected in <strong style="color:#c9d1d9;">{_n_services}</strong> service(s): '
            f'<code style="background:#0d1117;padding:﻿
    # ── Copilot-style HTML builders ──────────────────────────────────────────
    import json as _json

    def _badge_cls(risk):
        return {"HIGH": "badge-high", "MEDIUM": "badge-med", "LOW": "badge-low"}.get(risk.upper(), "badge-low")

    _total_files = risk_summary.get("total_files_changed", sum(
        v.get("files_changed", 0) for v in consolidated.get("service_risks", {}).values()))
    _total_sig = risk_summary.get("total_signature_changes", 0)
    _total_removed = risk_summary.get("total_removed_features", 0)
    _overall_cls = "high" if overall_risk == "HIGH" else ("low" if overall_risk == "LOW" else "")
    _files_cls = "high" if _total_files > 100 else ""
    _sig_cls = "high" if _total_sig > 0 else ""
    _rm_cls = "high" if _total_removed > 0 else ""

    _svc_risk_data = consolidated.get("service_risks", {})
    _svc_table_rows = ""
    for _sn, _sd in sorted(_svc_risk_data.items(), key=lambda kv: {"high": 0, "medium": 1, "low": 2}.get(kv[1].get("risk_level", "low"), 3)):
        _rl = _sd.get("risk_level", "low").upper()
        _bc = _badge_cls(_rl)
        _fc = _sd.get("files_changed", 0)
        _sc2 = _sd.get("signature_changes", 0)
        _rm2 = _sd.get("removed_features", 0)
        _lng = ", ".join(s.capitalize() for s in _sd.get("languages", ["generic"]))
        _svc_table_rows += f'        <tr><td><code>{_sn}</code></td><td><span class="badge {_bc}">{_rl}</span></td><td>{_fc}</td><td>{_sc2}</td><td>{_rm2}</td><td>{_lng}</td></tr>\n'

    _svc_order2 = sorted(_svc_risk_data.items(), key=lambda kv: {"high": 0, "medium": 1, "low": 2}.get(kv[1].get("risk_level", "low"), 3))
    _svc_area_map = {svc: [] for svc, _ in _svc_order2}
    _done_ids = set()
    for _sn2, _sd2 in _svc_order2:
        _sr = _sd2.get("risk_level", "low").upper()
        for _a2 in feature_areas:
            if _a2["id"] not in _done_ids and _a2["risk"] == _sr:
                _svc_area_map[_sn2].append(_a2)
                _done_ids.add(_a2["id"])
    _first_svc2 = _svc_order2[0][0] if _svc_order2 else None
    for _a2 in feature_areas:
        if _a2["id"] not in _done_ids and _first_svc2:
            _svc_area_map[_first_svc2].append(_a2)
            _done_ids.add(_a2["id"])

    _tid_counter = [0]

    def _split_sc(s):
        for sep in (" \u2192 ", " \u2014 ", " \u2013 ", " -> ", " -- "):
            if sep in s:
                pts = s.split(sep, 1)
                return pts[0].strip(), pts[1].strip()
        return s.strip(), ""

    def _infer_sc_type(s, aname):
        sl = s.lower()
        if any(w in sl for w in ("regression", "existing", "unaffected", "smoke")):
            return "Regression"
        if any(w in sl for w in ("error", "unavailable", "timeout", "unmarshal", "exception")):
            return "Error Handling"
        if any(w in sl for w in ("empty", "no-match", "no match", "404", "400", "500")):
            return "Edge Case"
        if any(w in sl for w in ("auth", "unauthorized", "access", "permission", "group")):
            return "Auth / Access"
        if any(w in sl for w in ("route", "endpoint", "path", "url", "redirect")):
            return "Route Change"
        if any(w in sl for w in ("build", "deploy", "docker", "maven", "gradle", "jar")):
            return "Build / Deploy"
        if any(w in sl for w in ("download", "export")):
            return "Download"
        if any(w in sl for w in ("sort", "order", "priority")):
            return "Data Sort Order"
        return aname.split("\u2014")[0].strip() or "Functional"

    _per_svc_html = ""
    for _sn3, _sd3 in _svc_order2:
        _areas3 = _svc_area_map.get(_sn3, [])
        if not _areas3:
            continue
        _sr3 = _sd3.get("risk_level", "low").upper()
        _bc3 = _badge_cls(_sr3)
        _fc3 = _sd3.get("files_changed", 0)
        _lng3 = ", ".join(s.capitalize() for s in _sd3.get("languages", ["generic"]))
        _sc3 = _sd3.get("signature_changes", 0)
        _meta3 = f"Risk: {_sr3} &#160;|&#160; {_fc3} files &#160;|&#160; {_lng3}"
        if _sc3:
            _meta3 += f" &#160;|&#160; {_sc3} sig change(s)"
        _rows3 = ""
        for _a3 in _areas3:
            _ar3 = _a3.get("risk", "LOW").upper()
            _abc3 = _badge_cls(_ar3)
            _desc3 = _a3.get("description", "")[:120]
            for _sstr in _a3.get("scenarios", []):
                _tid_counter[0] += 1
                _stype3 = _infer_sc_type(_sstr, _a3.get("name", "Functional"))
                _act3, _exp3 = _split_sc(_sstr)
                if not _exp3:
                    _exp3 = _a3.get("regression_guard", "")
                _rows3 += (
                    f'        <tr><td>PR-T{_tid_counter[0]}</td>'
                    f'<td>{_stype3}</td>'
                    f'<td>{_act3}</td>'
                    f'<td>{_act3}</td>'
                    f'<td>{_exp3}</td>'
                    f'<td><span class="badge {_abc3}">{_ar3}</span></td>'
                    f'<td>{_desc3}</td></tr>\n'
                )
        _per_svc_html += (
            f'  <section>\n'
            f'    <h2>Tests for {_sn3}</h2>\n'
            f'    <div class="service-header"><div>'
            f'<div class="svc-name">{_sn3}</div>'
            f'<div class="svc-meta">{_meta3}</div>'
            f'</div><span class="badge {_bc3}">{_sr3}</span></div>\n'
            f'    <table>\n'
            f'      <thead><tr><th>ID</th><th>Type</th><th>Scenario</th>'
            f'<th>Tester Action</th><th>Expected Result</th><th>Risk</th><th>Risk Note</th></tr></thead>\n'
            f'      <tbody>\n{_rows3}      </tbody>\n    </table>\n  </section>\n'
        )

    _total_scenario_count = _tid_counter[0]

    _cross_copilot = ""
    if cross_scenarios:
        _cr_rows = ""
        for _ci, _csc in enumerate(cross_scenarios):
            _cr = _csc.get("risk", "MEDIUM").upper()
            _cbc = _badge_cls(_cr)
            _ctype = _csc.get("type", _csc.get("category", "Integration"))
            _cr_rows += (
                f'        <tr><td>CS-T{_ci+1}</td>'
                f'<td>{_ctype}</td>'
                f'<td>{_csc.get("scenario", _csc.get("description", ""))}</td>'
                f'<td>{_csc.get("steps", _csc.get("tester_action", ""))}</td>'
                f'<td>{_csc.get("expected", _csc.get("expected_result", ""))}</td>'
                f'<td><span class="badge {_cbc}">{_cr}</span></td>'
                f'<td>{_csc.get("risk_note", _csc.get("note", ""))}</td></tr>\n'
            )
        _cross_copilot = (
            '  <section>\n'
            '    <h2>Cross-Service Integration Tests</h2>\n'
            '    <table>\n'
            '      <thead><tr><th>ID</th><th>Type</th><th>Scenario</th>'
            '<th>Tester Action</th><th>Expected Result</th><th>Risk</th><th>Risk Note</th></tr></thead>\n'
            f'      <tbody>\n{_cr_rows}      </tbody>\n    </table>\n  </section>\n'
        )

    _tsd_cases = []
    for _t in (relevant_tests or []):
        _tsd_cases.append({
            "testCase": _t.get("testCase", _t.get("id", "")),
            "file": _t.get("file", "").replace("\\", "/").split("/")[-1],
            "tags": _t.get("tags", []),
        })
    _tsd_json = _json.dumps({"tests_selected": len(_tsd_cases), "test_cases": _tsd_cases}, ensure_ascii=False)
    _auto_count = len(_tsd_cases)

    _risk_area_rows = ""
    for _hrc in consolidated.get("high_risk_changes", [])[:12]:
        _fn2 = _hrc.get("function", _hrc.get("endpoint", "endpoint"))
        _imp = _hrc.get("impact", "BREAKING")
        _old2 = _hrc.get("old_return", _hrc.get("old_signature", ""))
        _new2 = _hrc.get("new_return", _hrc.get("new_signature", ""))
        _svc2 = _hrc.get("service", "")
        _rbc = "badge-high" if _imp == "BREAKING" else "badge-med"
        if _old2 and _new2:
            _det = f"<code>{_fn2}()</code>: <code>{_old2}</code> &#8594; <code>{_new2}</code>"
        else:
            _det = f"<code>{_fn2}()</code> &#8212; {_imp}"
        _imp_txt = f"Verify all consumers of <code>{_svc2}</code>" if _svc2 else "Verify all consumers"
        _risk_area_rows += f'        <tr><td><span class="badge {_rbc}">{_fn2}</span></td><td>{_det}</td><td>{_imp_txt}</td></tr>\n'

    _conf_refs = ""
    for _cp in confluence_pages[:5]:
        _conf_refs += f'      <li><a href="{_cp.get("url", "#")}" target="_blank">{_cp.get("title", "Page")}</a></li>\n'

    _risk_area_section = (
        '  <section>\n    <h2>Key Risk Areas</h2>\n    <table>\n'
        '      <thead><tr><th>Area</th><th>Detail</th><th>Impact</th></tr></thead>\n'
        f'      <tbody>\n{_risk_area_rows}      </tbody>\n    </table>\n  </section>\n'
    ) if _risk_area_rows else ""

    _conf_section = (
        '  <section>\n    <h2>Confluence References</h2>\n    <ul style="padding-left:18px;">\n'
        f'{_conf_refs}    </ul>\n  </section>\n'
    ) if _conf_refs else ""

    _script_block = (
        "<script>\n"
        "var TEST_SELECTION_DATA = " + _tsd_json + ";\n"
        "(function(){\n"
        '  var NOISE={"fixtures":1,"test":1,"pages":1,"TEST_DTB":1,"Navigation1":1,"MarketingAssets1":1};\n'
        '  var list=document.getElementById("auto-tests");\n'
        "  var tests=TEST_SELECTION_DATA.test_cases||[];\n"
        "  if(!tests.length){list.innerHTML='<li style=\"color:var(--muted)\">No automation tests mapped</li>';return;}\n"
        "  list.innerHTML=tests.map(function(t){\n"
        '    var name=t.testCase||"";\n'
        '    var file=(t.file||"").replace(".spec.ts","");\n'
        "    var tags=(t.tags||[]).filter(function(g){return !NOISE[g];});\n"
        "    var chips=tags.map(function(g){return '<span class=\"tag\">@'+g+\"</span>\";}).join(\"\");\n"
        "    var run=tags.length?\"<code style=\\\"display:block;margin-top:4px;font-size:11px;color:var(--muted)\\\">--grep \\\"\"+tags[0]+\"\\\"</code>\":\"\";\n"
        "    return \"<li style=\\\"padding:8px 0;border-bottom:1px solid var(--border);\\\"><span style=\\\"font-size:13px;\\\">\"+name+\"</span><br><span style=\\\"font-size:11px;color:var(--muted)\\\">\"+file+\"</span> \"+chips+run+\"</li>\";\n"
        '  }).join("");\n'
        "})();\n"
        "</script>"
    )

    return (
        "<!DOCTYPE html>\n"
        "<html lang=\"en\">\n"
        "<head>\n"
        "<meta charset=\"UTF-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">\n"
        f"<title>PR Risk Analysis - {jira_id}</title>\n"
        "<style>\n"
        "  :root { --bg:#0d1117;--surface:#161b22;--border:#30363d;--text:#c9d1d9;--muted:#8b949e;--accent:#58a6ff;--high:#f85149;--medium:#d29922;--low:#3fb950; }\n"
        "  *{box-sizing:border-box;margin:0;padding:0;}\n"
        "  body{background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;font-size:14px;line-height:1.6;}\n"
        "  .container{max-width:1200px;margin:0 auto;padding:24px;}\n"
        "  header{border-bottom:1px solid var(--border);padding-bottom:20px;margin-bottom:28px;}\n"
        "  header h1{font-size:22px;font-weight:600;color:#e6edf3;}\n"
        "  header .sub{color:var(--muted);font-size:13px;margin-top:4px;}\n"
        "  .stats-row{display:flex;gap:16px;flex-wrap:wrap;margin-bottom:28px;}\n"
        "  .stat-card{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:16px 20px;flex:1;min-width:140px;}\n"
        "  .stat-card .val{font-size:28px;font-weight:700;color:#e6edf3;}\n"
        "  .stat-card .lbl{font-size:12px;color:var(--muted);margin-top:2px;}\n"
        "  .stat-card.high .val{color:var(--high);}\n"
        "  .stat-card.low .val{color:var(--low);}\n"
        "  section{margin-bottom:32px;}\n"
        "  section h2{font-size:16px;font-weight:600;color:#e6edf3;padding-bottom:10px;border-bottom:1px solid var(--border);margin-bottom:16px;}\n"
        "  table{width:100%;border-collapse:collapse;font-size:13px;}\n"
        "  th{text-align:left;padding:8px 12px;background:var(--surface);color:var(--muted);font-weight:500;border-bottom:2px solid var(--border);white-space:nowrap;}\n"
        "  td{padding:10px 12px;border-bottom:1px solid var(--border);vertical-align:top;}\n"
        "  tr:hover td{background:rgba(255,255,255,0.02);}\n"
        "  .badge{display:inline-block;padding:2px 10px;border-radius:12px;font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:0.5px;}\n"
        "  .badge-high{background:rgba(248,81,73,0.15);border:1px solid rgba(248,81,73,0.5);color:var(--high);}\n"
        "  .badge-med{background:rgba(210,153,34,0.15);border:1px solid rgba(210,153,34,0.5);color:var(--medium);}\n"
        "  .badge-low{background:rgba(63,185,80,0.15);border:1px solid rgba(63,185,80,0.4);color:var(--low);}\n"
        "  .service-header{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:14px 18px;margin-bottom:12px;display:flex;align-items:center;gap:14px;}\n"
        "  .service-header .svc-name{font-weight:600;color:#e6edf3;font-size:15px;}\n"
        "  .service-header .svc-meta{color:var(--muted);font-size:12px;margin-top:2px;}\n"
        "  .test-list{list-style:none;}\n"
        "  a{color:var(--accent);text-decoration:none;}\n"
        "  a:hover{text-decoration:underline;}\n"
        "  code{background:rgba(110,118,129,0.2);padding:1px 6px;border-radius:4px;font-family:'SFMono-Regular',Consolas,monospace;font-size:12px;color:#e6edf3;}\n"
        "  .tag{display:inline-block;margin:1px 2px;padding:1px 7px;background:rgba(63,185,80,0.15);border:1px solid rgba(63,185,80,0.4);border-radius:10px;font-family:monospace;font-size:11px;color:#3fb950;}\n"
        "</style>\n"
        "</head>\n"
        "<body>\n"
        "<div class=\"container\">\n"
        "  <header>\n"
        f"    <h1>PR Risk Analysis &#8212; {jira_id}</h1>\n"
        f"    <div class=\"sub\">{jira_title} &#160;|&#160; Generated: {ts} &#160;|&#160; {_n_services} service(s) &#160;|&#160; {_total_files} files changed</div>\n"
        "  </header>\n"
        "  <div class=\"stats-row\">\n"
        f"    <div class=\"stat-card {_overall_cls}\"><div class=\"val\">{overall_risk}</div><div class=\"lbl\">Overall Risk</div></div>\n"
        f"    <div class=\"stat-card\"><div class=\"val\">{_n_services}</div><div class=\"lbl\">Services Analyzed</div></div>\n"
        f"    <div class=\"stat-card {_files_cls}\"><div class=\"val\">{_total_files}</div><div class=\"lbl\">Files Changed</div></div>\n"
        f"    <div class=\"stat-card {_sig_cls}\"><div class=\"val\">{_total_sig}</div><div class=\"lbl\">API Signature Changes</div></div>\n"
        f"    <div class=\"stat-card {_rm_cls}\"><div class=\"val\">{_total_removed}</div><div class=\"lbl\">Removed Features</div></div>\n"
        f"    <div class=\"stat-card\"><div class=\"val\">{_total_scenario_count}</div><div class=\"lbl\">Test Scenarios</div></div>\n"
        f"    <div class=\"stat-card low\"><div class=\"val\">{_auto_count}</div><div class=\"lbl\">Automation Tests</div></div>\n"
        "  </div>\n"
        "  <section>\n"
        "    <h2>Affected Services</h2>\n"
        "    <table>\n"
        "      <thead><tr><th>Service</th><th>Risk Level</th><th>Files Changed</th><th>Sig Changes</th><th>Removed Features</th><th>Languages</th></tr></thead>\n"
        f"      <tbody>\n{_svc_table_rows}      </tbody>\n"
        "    </table>\n"
        "  </section>\n"
        + _per_svc_html
        + _cross_copilot
        + "  <section>\n"
        "    <h2>Selected Automation Tests</h2>\n"
        "    <ul id=\"auto-tests\" class=\"test-list\"><li style=\"color:var(--muted)\">Loading...</li></ul>\n"
        "  </section>\n"
        + _risk_area_section
        + _conf_section
        + "</div>\n"
        + _script_block + "\n"
        + "</body>\n"
        + "</html>"
    )

tbody>{_matrix_rows_dark}</tbody>
  </table>
  </div>
</section>

<!-- 3. High Risk -->
{'<section class="section"><h2>🔴 High Risk — Must Test</h2>' + _high_cards_dark + '</section>' if high_areas else ''}

<!-- 4. Medium Risk -->
{'<section class="section"><h2>🟠 Medium Risk — Test in Scope</h2>' + _med_cards_dark + '</section>' if med_areas else ''}

<!-- 5. Low Risk -->
{'<section class="section"><h2>🟢 Low Risk</h2><p style="font-size:0.87em;color:#8b949e;margin-bottom:12px;">Verify guards only unless another ticket also touches these:</p>' + _low_cards_dark + '</section>' if low_areas else ''}

<!-- 6. Linked Test Cases -->
<section class="section">
  <h2>Linked Test Cases (Jira)</h2>
  {_test_links_dark}
</section>

<!-- 7. Subtask Status -->
<section class="section">
  <h2>Subtask Status</h2>
  {_subtask_rows_dark if _subtask_rows_dark else '<p style="color:#484f58;font-size:0.87em;">No subtasks.</p>'}
</section>

<!-- 8. Confluence -->
{'<section class="section"><h2>Confluence Pages</h2><div style="margin-top:8px;">' + _conf_links_dark + '</div></section>' if _conf_links_dark else ''}

<!-- 9. Safe to Skip -->
<section class="section">
  <h2>Safe to Skip</h2>
  {_skip_html_dark if _skip_html_dark else '<p style="color:#484f58;font-size:0.87em;">Nothing to skip — all areas require testing.</p>'}
</section>

<!-- 10. Automation Test Coverage -->
<section class="section">
  <h2>Automation Test Coverage ({len(all_jenkins_tags)} tag(s) · {gap_count} gap(s))</h2>
  {auto_tests_html}
</section>

<!-- 11. Cross-Service Integration Tests -->
{_cross_dark}

<footer>
  <p>Report Generated: {ts} | PR Risk Analysis for {jira_id}</p>
  <p style="margin-top:6px;color:#30363d;">Sprint: {sprint} · Assignee: {assignee}</p>
</footer>

</div>
</body></html>"""




# ── Report generator class ──────────────────────────────────────────────────

class ReportGenerator:
    def __init__(self):
        self.jira_data = {}
        self.consolidated_data = {}
        self.test_selection_data = {}
        self.summary_data = {}
        self.confluence_pages = []
        self.test_index = []
        self.pr_dir = None

    def load_files(self, jira_file, consolidated_file, test_selection_file, summary_file=None, confluence_file=None, test_index_file=None):
        if jira_file and Path(jira_file).exists():
            with open(jira_file, encoding="utf-8-sig") as f:
                self.jira_data = json.load(f)
            # Derive pr_dir from jira_file location (e.g. pr-analysis/PROJ-1234/)
            self.pr_dir = Path(jira_file).parent
        if consolidated_file and Path(consolidated_file).exists():
            with open(consolidated_file, encoding="utf-8-sig") as f:
                self.consolidated_data = json.load(f)
        if test_selection_file and Path(test_selection_file).exists():
            with open(test_selection_file, encoding="utf-8-sig") as f:
                self.test_selection_data = json.load(f)
        if summary_file and Path(summary_file).exists():
            with open(summary_file, encoding="utf-8-sig") as f:
                self.summary_data = json.load(f)
        else:
            guess = Path(str(consolidated_file)).parent / "summary.json"
            if guess.exists():
                with open(guess, encoding="utf-8-sig") as f:
                    self.summary_data = json.load(f)
            else:
                # Aggregate all per-service summary.json files from subdirectories
                merged: Dict = {
                    "changed_files": [], "new_status_values": [],
                    "removed_features": [],
                    "test_changes": {"modified_assertions": [], "removed_tests": [], "added_tests": []},
                }
                parent = Path(str(consolidated_file)).parent
                for service_dir in sorted(parent.iterdir()):
                    if service_dir.is_dir() and (service_dir / "summary.json").exists():
                        try:
                            with open(service_dir / "summary.json", encoding="utf-8-sig") as f:
                                svc = json.load(f)
                            merged["changed_files"].extend(svc.get("changed_files", []))
                            merged["new_status_values"].extend(svc.get("new_status_values", []))
                            merged["removed_features"].extend(svc.get("removed_features", []))
                            for k in ("modified_assertions", "removed_tests", "added_tests"):
                                merged["test_changes"][k].extend(
                                    svc.get("test_changes", {}).get(k, [])
                                )
                        except Exception:
                            pass
                self.summary_data = merged
        if confluence_file and Path(confluence_file).exists():
            with open(confluence_file, encoding="utf-8-sig") as f:
                self.confluence_pages = json.load(f)
        if test_index_file and Path(test_index_file).exists():
            with open(test_index_file, encoding="utf-8-sig") as f:
                raw = json.load(f)
                self.test_index = raw.get("tests", raw) if isinstance(raw, dict) else raw

    def generate_html(self):
        gateway_routes = _extract_gateway_routes(self.pr_dir)
        return generate_html(self.jira_data, self.consolidated_data, self.summary_data, self.test_selection_data, self.confluence_pages, self.test_index, gateway_routes=gateway_routes)


# ── main ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--jira-file")
    parser.add_argument("--consolidated-file", required=True)
    parser.add_argument("--test-selection-file")
    parser.add_argument("--summary-file")
    parser.add_argument("--confluence-file")
    parser.add_argument("--test-index-file")
    parser.add_argument("--output", required=True)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    gen = ReportGenerator()
    gen.load_files(args.jira_file, args.consolidated_file, args.test_selection_file, args.summary_file, args.confluence_file, args.test_index_file)

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(gen.generate_html())
    print(f"[OK] Report: {out}", file=sys.stderr)

    if not args.no_browser:
        webbrowser.open(out.resolve().as_uri())

if __name__ == "__main__":
    main()
