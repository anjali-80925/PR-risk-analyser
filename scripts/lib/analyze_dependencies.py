#!/usr/bin/env python3
"""
Cross-Service Dependency Analyzer
Consolidates per-service PR analysis and maps transitive dependencies.

Usage:
  python3 analyze_dependencies.py \
    --analysis-dir pr-analysis/DTB-17595 \
    --jira-id DTB-17595 \
    --output pr-analysis/DTB-17595/consolidated_summary.json

Output:
  consolidated_summary.json with:
    - all detected services
    - high-risk signature changes
    - transitive blast radius (cross-service impact)
    - shared model changes
    - risk scores and recommendations
"""

import sys
import os
import json
import argparse
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Set, Any, Tuple, Optional
from datetime import datetime
import re

# Optional symbol index for fast cross-repo lookups
try:
    from index_symbols import load_index, lookup_terms, build_index
    _SYMBOL_INDEX_AVAILABLE = True
except ImportError:
    _SYMBOL_INDEX_AVAILABLE = False


class ServiceAnalyzer:
    """Analyzes individual service summaries"""

    def __init__(self, service_dir: Path):
        self.service_dir = service_dir
        self.service_name = service_dir.name
        self.summary_file = service_dir / "summary.json"
        self.data = {}
        self._load()

    def _load(self):
        """Load and parse summary.json"""
        if not self.summary_file.exists():
            print(f"[WARN] No summary.json found for {self.service_name}", file=sys.stderr)
            return

        try:
            with open(self.summary_file) as f:
                self.data = json.load(f)
        except Exception as e:
            print(f"[WARN] Failed to parse {self.summary_file}: {e}", file=sys.stderr)

    @property
    def changed_files(self) -> List[str]:
        return self.data.get("changed_files", [])

    @property
    def signature_changes(self) -> List[Dict]:
        return self.data.get("signature_changes", [])

    @property
    def removed_features(self) -> List[str]:
        return self.data.get("removed_features", [])

    @property
    def blast_radius(self) -> List[Dict]:
        return self.data.get("blast_radius", [])

    @property
    def test_changes(self) -> Dict:
        return self.data.get("test_changes", {})

    @property
    def languages(self) -> List[str]:
        return self.data.get("languages_detected", [])

    def calculate_risk_score(self) -> Tuple[str, int]:
        """
        Calculate risk level and score.
        Returns: (risk_level: str, score: int)
        """
        score = 0

        # Signature changes = high risk (API/interface changes)
        score += len(self.signature_changes) * 3

        # Removed features = high risk
        score += len(self.removed_features) * 2

        # New status values = medium risk
        score += len(self.data.get("new_status_values", [])) * 1

        # Files changed = low per-file, but accumulative
        score += min(len(self.changed_files) // 5, 2)

        # Test removals = risk signal
        removed_tests = self.test_changes.get("removed_tests", [])
        score += len(removed_tests)

        if score >= 5:
            risk_level = "high"
        elif score >= 2:
            risk_level = "medium"
        else:
            risk_level = "low"

        return risk_level, score


class DependencyGraphBuilder:
    """Builds and analyzes service dependency graphs"""

    def __init__(self, analyzers: Dict[str, ServiceAnalyzer]):
        self.analyzers = analyzers
        self.graph = {}  # service -> set of dependencies
        self._build_graph()

    def _build_graph(self):
        """Build dependency graph from blast_radius entries"""
        # Initialize all services
        for service_name in self.analyzers.keys():
            self.graph[service_name] = set()

        # Parse blast_radius to find dependencies
        for service_name, analyzer in self.analyzers.items():
            for entry in analyzer.blast_radius:
                uses = entry.get("uses", [])
                for used_item in uses:
                    # Extract service name from patterns like:
                    # "@service/dtb-be", "import from dtb-be", "digital-toolbox-svc-common"
                    for other_service in self.analyzers.keys():
                        if other_service != service_name and other_service in used_item:
                            self.graph[service_name].add(other_service)

    def find_transitive_impact(self, service: str) -> Set[str]:
        """
        Find all services transitively affected by a change to 'service'.
        This is the reverse graph traversal.
        """
        affected = set()
        visited = set()

        def dfs(current):
            if current in visited:
                return
            visited.add(current)

            # Find services that depend on current (reverse edges)
            for other_service, dependencies in self.graph.items():
                if current in dependencies and other_service not in affected:
                    affected.add(other_service)
                    dfs(other_service)

        dfs(service)
        return affected

    def get_transitive_impact_map(self) -> Dict[str, Set[str]]:
        """Get transitive impact for all services"""
        impact_map = {}
        for service_name, analyzer in self.analyzers.items():
            if analyzer.changed_files:  # Only if service has changes
                affected = self.find_transitive_impact(service_name)
                if affected:
                    impact_map[service_name] = affected
        return impact_map


class ConsolidatedAnalysis:
    """Creates consolidated analysis report"""

    def __init__(self, analyzers: Dict[str, ServiceAnalyzer], graph_builder: DependencyGraphBuilder, jira_id: str):
        self.analyzers = analyzers
        self.graph_builder = graph_builder
        self.jira_id = jira_id

    def generate(self) -> Dict[str, Any]:
        """Generate consolidated analysis"""
        # Calculate risks
        service_risks = {}
        high_risk_changes = []
        medium_risk_changes = []

        for service_name, analyzer in self.analyzers.items():
            risk_level, score = analyzer.calculate_risk_score()
            service_risks[service_name] = {
                "risk_level": risk_level,
                "risk_score": score,
                "files_changed": len(analyzer.changed_files),
                "signature_changes": len(analyzer.signature_changes),
                "removed_features": len(analyzer.removed_features),
                "languages": analyzer.languages,
                "test_changes": analyzer.test_changes,
            }

            # Collect high-risk changes
            for sig_change in analyzer.signature_changes:
                high_risk_changes.append({
                    "service": service_name,
                    "type": "signature_change",
                    "file": sig_change.get("file", ""),
                    "function": sig_change.get("function", ""),
                    "old_params": sig_change.get("old_params", []),
                    "new_params": sig_change.get("new_params", []),
                    "old_return": sig_change.get("old_return", ""),
                    "new_return": sig_change.get("new_return", ""),
                    "impact": "BREAKING" if self._is_breaking_change(sig_change) else "COMPATIBLE",
                })

            for removed in analyzer.removed_features:
                medium_risk_changes.append({
                    "service": service_name,
                    "type": "removed_feature",
                    "feature": removed,
                })

        # Build consolidated report
        risk_summary = self._calculate_risk_summary(service_risks)
        transitive_impact = self.graph_builder.get_transitive_impact_map()
        shared_impacts = self._detect_shared_impacts()

        consolidated = {
            "analysis_timestamp": datetime.now().isoformat(),
            "jira_id": self.jira_id,
            "services_analyzed": list(self.analyzers.keys()),
            "service_count": len(self.analyzers),
            "risk_summary": risk_summary,
            "service_risks": service_risks,
            "high_risk_changes": high_risk_changes,
            "medium_risk_changes": medium_risk_changes,
            "service_dependencies": {k: list(v) for k, v in self.graph_builder.graph.items() if v},
            "transitive_impact": {k: list(v) for k, v in transitive_impact.items()},
            "cross_service_analysis": {
                "shared_model_changes": self._detect_shared_models(),
                "shared_permission_changes": self._detect_permission_changes(),
                "shared_cache_changes": self._detect_cache_changes(),
                "shared_impacts": shared_impacts,
            },
            "recommendations": self._generate_recommendations(service_risks, transitive_impact),
        }

        return consolidated

    @staticmethod
    def _is_breaking_change(sig_change: Dict) -> bool:
        """Determine if signature change is breaking"""
        old_params = len(sig_change.get("old_params", []))
        new_params = len(sig_change.get("new_params", []))

        # Parameter count decreased = likely breaking
        if new_params < old_params:
            return True

        # Return type changed = possibly breaking
        old_return = sig_change.get("old_return", "")
        new_return = sig_change.get("new_return", "")
        if old_return and new_return and old_return != new_return:
            return True

        return False

    def _calculate_risk_summary(self, service_risks: Dict) -> Dict:
        """Calculate aggregate risk statistics"""
        high = sum(1 for r in service_risks.values() if r["risk_level"] == "high")
        medium = sum(1 for r in service_risks.values() if r["risk_level"] == "medium")
        low = sum(1 for r in service_risks.values() if r["risk_level"] == "low")

        return {
            "high_risk_services": high,
            "medium_risk_services": medium,
            "low_risk_services": low,
            "total_files_changed": sum(r["files_changed"] for r in service_risks.values()),
            "total_signature_changes": sum(r["signature_changes"] for r in service_risks.values()),
            "total_removed_features": sum(r["removed_features"] for r in service_risks.values()),
        }

    def _detect_shared_models(self) -> List[Dict]:
        """Detect files modified by multiple services (shared models)"""
        file_map = {}
        for service_name, analyzer in self.analyzers.items():
            for file in analyzer.changed_files:
                basename = Path(file).name
                if basename not in file_map:
                    file_map[basename] = []
                file_map[basename].append(service_name)

        return [
            {"file": name, "services": services, "count": len(services)}
            for name, services in file_map.items()
            if len(services) > 1
        ]

    def _detect_permission_changes(self) -> List[Dict]:
        """Detect permission/authorization related changes"""
        permission_keywords = ["permission", "auth", "role", "access", "privilege", "admin", "jwt", "oauth", "bearer"]
        results = []

        for service_name, analyzer in self.analyzers.items():
            for sig_change in analyzer.signature_changes:
                func = sig_change.get("function", "").lower()
                file = sig_change.get("file", "").lower()
                if any(kw in func or kw in file for kw in permission_keywords):
                    results.append({
                        "service": service_name,
                        "type": "permission_change",
                        "function": sig_change.get("function"),
                        "file": sig_change.get("file"),
                        "risk": "HIGH - Permission logic changed, may impact dependent services",
                    })

        return results

    def _detect_cache_changes(self) -> List[Dict]:
        """Detect cache invalidation or refresh logic changes"""
        cache_keywords = ["cache", "redis", "memcached", "ttl", "refresh", "invalidate"]
        results = []

        for service_name, analyzer in self.analyzers.items():
            for file in analyzer.changed_files:
                if any(kw in file.lower() for kw in cache_keywords):
                    results.append({
                        "service": service_name,
                        "file": file,
                        "risk": "MEDIUM - Cache logic may impact dependent services",
                    })

        return results

    def _detect_shared_impacts(self) -> List[Dict]:
        """Identify services that could impact each other"""
        impacts = []
        service_names = list(self.analyzers.keys())

        for i, service_a in enumerate(service_names):
            for service_b in service_names[i+1:]:
                analyzer_a = self.analyzers[service_a]
                analyzer_b = self.analyzers[service_b]

                # Check if they share dependencies or impact areas
                deps_a = self.graph_builder.graph.get(service_a, set())
                deps_b = self.graph_builder.graph.get(service_b, set())

                shared_deps = deps_a & deps_b
                if shared_deps:
                    impacts.append({
                        "services": [service_a, service_b],
                        "shared_dependencies": list(shared_deps),
                        "risk": "Both services depend on same downstream services",
                    })

        return impacts

    def _generate_recommendations(self, service_risks: Dict, transitive_impact: Dict) -> List[str]:
        """Generate testing and deployment recommendations"""
        recommendations = []

        # Check for high-risk services
        high_risk_services = [s for s, r in service_risks.items() if r["risk_level"] == "high"]
        if high_risk_services:
            recommendations.append(f"HIGH PRIORITY: Run full regression tests for {', '.join(high_risk_services)}")

        # Check for transitive impact
        if transitive_impact:
            affected_services = set()
            for service, impacts in transitive_impact.items():
                affected_services.update(impacts)
            recommendations.append(f"Run integration tests for: {', '.join(affected_services)}")

        # Check for permission changes
        permission_changes = self._detect_permission_changes()
        if permission_changes:
            recommendations.append("SECURITY REVIEW: Permission/auth changes detected—coordinate with security team")

        # Check for removed features
        removed_count = sum(r["removed_features"] for r in service_risks.values())
        if removed_count > 0:
            recommendations.append(f"BACKWARD COMPATIBILITY: {removed_count} features removed—verify deprecation period")

        return recommendations if recommendations else ["No specific recommendations—standard test execution sufficient"]


# ── Source file extensions to scan for cross-repo references ─────────────────
_SOURCE_EXTS = {
    ".java", ".kt", ".py", ".ts", ".tsx", ".js", ".jsx",
    ".go", ".cs", ".rb", ".php", ".scala", ".gradle", ".xml",
    ".yaml", ".yml", ".properties", ".json",
}
# Directories to skip during cross-repo scanning
_SKIP_DIRS = {
    ".git", "node_modules", ".gradle", "build", "target",
    "dist", "out", "__pycache__", ".pytest_cache", ".venv", "venv",
}


class AllReposRiskScanner:
    """
    Scans ALL pre-cloned repos in .service-repos/ to find references to:
      - Affected service names
      - Changed class/method names (from signature_changes)
      - Removed feature names
      - Changed API routes / endpoint patterns
    Returns cross-repo risk findings that the current ticket's per-service diff
    analysis would miss.
    """

    def __init__(self, repos_dir: Path, analyzers: Dict[str, "ServiceAnalyzer"]):
        self.repos_dir = repos_dir
        self.analyzers = analyzers  # affected services only
        self.affected_service_names = set(analyzers.keys())

    # ── Build search terms from affected service summaries ────────────────────

    def _build_search_terms(self) -> Dict[str, List[str]]:
        """
        Return a dict:  term_category -> [term, ...]
        These are used to grep all non-affected repos.
        """
        terms: Dict[str, List[str]] = {
            "service_names": [],
            "changed_functions": [],
            "removed_features": [],
            "api_routes": [],
        }

        for svc_name, analyzer in self.analyzers.items():
            # Service name variants (e.g. "dtb-be", "dtbBe", "DtbBe")
            terms["service_names"].append(svc_name)
            # Camel-case / pascal-case variant
            camel = re.sub(r"[-_](.)", lambda m: m.group(1).upper(), svc_name)
            terms["service_names"].append(camel)

            # Changed function/method names
            for sig in analyzer.signature_changes:
                func = sig.get("function", "").strip()
                if func and len(func) > 3:
                    terms["changed_functions"].append(func)

            # Removed features
            for feat in analyzer.removed_features:
                clean = feat.strip()
                if clean and len(clean) > 3:
                    terms["removed_features"].append(clean)

            # API routes from changed files that look like controllers/routes
            for f in analyzer.changed_files:
                if any(kw in f.lower() for kw in ["controller", "route", "router", "endpoint", "api"]):
                    route_hint = Path(f).stem  # e.g. "IconographyController" -> "Iconography"
                    if route_hint and len(route_hint) > 3:
                        terms["api_routes"].append(route_hint)

        # Deduplicate
        return {k: list(dict.fromkeys(v)) for k, v in terms.items()}

    # ── Fast grep-based scan of a single repo ────────────────────────────────

    _RG_TYPE_ARGS = [
        "-t", "java", "-t", "kotlin", "-t", "py",
        "-t", "ts",   "-t", "js",
        "-t", "go",   "-t", "cs",
        "-t", "xml",  "-t", "yaml", "-t", "json",
    ]

    def _scan_repo(self, repo_dir: Path, all_patterns: List[str],
                   timeout_sec: int = 20) -> List[Dict]:
        """
        Scan one repo using ripgrep (rg) — parallelises within each repo,
        ~5-10× faster than grep. Falls back to grep, then Python walk on error.
        """
        if not all_patterns:
            return []

        findings: List[Dict] = []
        pattern_block = "\n".join(all_patterns)

        # ── Try ripgrep first ─────────────────────────────────────────────
        rg_available = False
        try:
            # Step 1: rg -Fl (fixed strings, list files only)
            result = subprocess.run(
                ["rg", "-Fl",
                 "--glob=!.git", "--glob=!node_modules", "--glob=!build",
                 "--glob=!target", "--glob=!dist", "--glob=!.gradle",
                 "-f", "/dev/stdin",
                 str(repo_dir),
                 ] + self._RG_TYPE_ARGS,
                input=pattern_block,
                capture_output=True, text=True, timeout=timeout_sec,
            )
            rg_available = True
            if result.returncode not in (0, 1):
                return []

            matched_files = [p.strip() for p in result.stdout.splitlines() if p.strip()]

            # Step 2: for each matched file, extract line-level hits (capped)
            for fpath_str in matched_files[:40]:  # cap to avoid huge JSON
                fpath = Path(fpath_str)
                file_hits: List[Dict] = []
                try:
                    text = fpath.read_text(encoding="utf-8", errors="ignore")
                    for i, line in enumerate(text.splitlines(), 1):
                        for pattern in all_patterns:
                            if pattern and pattern in line:
                                file_hits.append({
                                    "term": pattern,
                                    "line": i,
                                    "snippet": line.strip()[:120],
                                })
                                break
                        if len(file_hits) >= 10:  # cap per file
                            break
                except OSError:
                    pass
                if file_hits:
                    try:
                        rel = fpath.relative_to(repo_dir)
                    except ValueError:
                        rel = fpath
                    findings.append({"file": str(rel), "matches": file_hits})

        except subprocess.TimeoutExpired:
            print(f"[WARN] rg timed out scanning {repo_dir.name} (>{timeout_sec}s) — skipped",
                  file=sys.stderr)
        except FileNotFoundError:
            # rg not available — fall back to grep
            try:
                _GREP_INCLUDE = [
                    "--include=*.java", "--include=*.kt", "--include=*.py",
                    "--include=*.ts", "--include=*.tsx", "--include=*.js",
                    "--include=*.jsx", "--include=*.go", "--include=*.cs",
                    "--include=*.xml", "--include=*.yaml", "--include=*.yml",
                    "--include=*.properties", "--include=*.json",
                ]
                result = subprocess.run(
                    ["grep", "-Frl",
                     "--exclude-dir=.git", "--exclude-dir=node_modules",
                     "--exclude-dir=build", "--exclude-dir=target",
                     "--exclude-dir=dist", "--exclude-dir=.gradle",
                     "--exclude-dir=__pycache__",
                     "-f", "/dev/stdin",
                     ] + _GREP_INCLUDE + [str(repo_dir)],
                    input=pattern_block,
                    capture_output=True, text=True, timeout=timeout_sec,
                )
                matched_files = [p.strip() for p in result.stdout.splitlines() if p.strip()]
                for fpath_str in matched_files[:40]:
                    fpath = Path(fpath_str)
                    file_hits: List[Dict] = []
                    try:
                        text = fpath.read_text(encoding="utf-8", errors="ignore")
                        for i, line in enumerate(text.splitlines(), 1):
                            for pattern in all_patterns:
                                if pattern and pattern in line:
                                    file_hits.append({"term": pattern, "line": i,
                                                      "snippet": line.strip()[:120]})
                                    break
                            if len(file_hits) >= 10:
                                break
                    except OSError:
                        pass
                    if file_hits:
                        try:
                            rel = fpath.relative_to(repo_dir)
                        except ValueError:
                            rel = fpath
                        findings.append({"file": str(rel), "matches": file_hits})
            except (FileNotFoundError, subprocess.TimeoutExpired):
                # grep also unavailable — Python walk as last resort
                for root, dirs, files in os.walk(repo_dir):
                    dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
                    for fname in files:
                        if Path(fname).suffix.lower() not in _SOURCE_EXTS:
                            continue
                        fpath = Path(root) / fname
                        file_hits = []
                        try:
                            text = fpath.read_text(encoding="utf-8", errors="ignore")
                            for i, line in enumerate(text.splitlines(), 1):
                                for pattern in all_patterns:
                                    if pattern and pattern in line:
                                        file_hits.append({"term": pattern, "line": i,
                                                          "snippet": line.strip()[:120]})
                                        break
                        except OSError:
                            pass
                        if file_hits:
                            rel = fpath.relative_to(repo_dir)
                            findings.append({"file": str(rel), "matches": file_hits})
        except Exception:
            pass

        return findings

    # ── Public entry point ────────────────────────────────────────────────────

    def scan(self, total_timeout_sec: int = 90) -> List[Dict]:
        """
        Scan all repos in repos_dir that are NOT already in the affected set.

        Fast path (preferred): if a fresh symbol index exists at
        <repos_dir>/.symbol-index.json (built by index_symbols.py),
        results come from an in-memory dict lookup — typically <2s.

        Slow path (fallback): ripgrep → grep → Python walk, with per-repo
        20s timeout and 90s total wall-clock cap.
        """
        if not self.repos_dir or not self.repos_dir.is_dir():
            return []

        search_terms = self._build_search_terms()

        # ── Fast path: symbol index ───────────────────────────────────────
        if _SYMBOL_INDEX_AVAILABLE:
            index_path = self.repos_dir / ".symbol-index.json"
            idx = load_index(index_path, max_age_hours=24.0)
            if idx:
                print(
                    f"[INFO] Using symbol index ({idx.get('repos_indexed')} repos, "
                    f"{idx.get('unique_symbols', 0):,} symbols, "
                    f"built {idx.get('built_at', '?')[:19]})",
                    file=sys.stderr,
                )
                raw = lookup_terms(idx, search_terms)
                # Exclude repos already in affected set
                return [r for r in raw if r["repo"] not in self.affected_service_names]

        # ── Slow path: rg / grep scan ─────────────────────────────────────
        all_patterns = [t for terms in search_terms.values() for t in terms if t]
        if not all_patterns:
            return []

        results = []
        scan_start = time.monotonic()
        repos_scanned = 0
        repos_skipped = 0

        for repo_dir in sorted(self.repos_dir.iterdir()):
            if not repo_dir.is_dir() or repo_dir.name.startswith("."):
                continue
            if repo_dir.name in self.affected_service_names:
                continue  # already analyzed

            elapsed = time.monotonic() - scan_start
            if elapsed > total_timeout_sec:
                repos_skipped += (
                    sum(1 for r in self.repos_dir.iterdir()
                        if r.is_dir() and not r.name.startswith(".")
                        and r.name not in self.affected_service_names)
                    - repos_scanned
                )
                print(
                    f"[WARN] Cross-repo scan wall-clock cap ({total_timeout_sec}s) reached "
                    f"after {repos_scanned} repos. {repos_skipped} repo(s) not scanned. "
                    f"Run 'scripts/reindex.sh' to build a symbol index for instant results.",
                    file=sys.stderr,
                )
                break

            findings = self._scan_repo(repo_dir, all_patterns)
            repos_scanned += 1
            if not findings:
                continue

            # Classify risk based on what was matched
            matched_terms: Set[str] = {
                hit["term"]
                for f in findings for hit in f["matches"]
            }
            has_func_match = bool(matched_terms & set(search_terms["changed_functions"]))
            has_removed = bool(matched_terms & set(search_terms["removed_features"]))
            has_svc_name = bool(matched_terms & set(search_terms["service_names"]))

            if has_func_match or has_removed:
                risk = "HIGH"
                reason = "References changed/removed function signatures from affected services"
            elif has_svc_name:
                risk = "MEDIUM"
                reason = "References affected service name — may be an integration consumer"
            else:
                risk = "LOW"
                reason = "Contains keyword references to affected change areas"

            total_matches = sum(len(f["matches"]) for f in findings)
            results.append({
                "repo": repo_dir.name,
                "risk_level": risk,
                "reason": reason,
                "matched_terms": sorted(matched_terms),
                "total_references": total_matches,
                "files_with_references": len(findings),
                "references": findings[:20],
                "source": "grep_scan",
            })

        # Sort: HIGH first, then MEDIUM, then LOW
        rank = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
        results.sort(key=lambda x: rank.get(x["risk_level"], 3))
        return results


def main():
    parser = argparse.ArgumentParser(
        description="Consolidate per-service PR analysis with cross-service dependencies"
    )
    parser.add_argument("--analysis-dir", required=True, help="Directory containing per-service analysis")
    parser.add_argument("--jira-id", required=True, help="Jira ticket ID")
    parser.add_argument("--output", required=True, help="Output file for consolidated summary")
    parser.add_argument(
        "--repos-dir", default=None,
        help="Path to .service-repos/ with ALL pre-cloned repos (enables full cross-repo risk scan)"
    )
    parser.add_argument(
        "--no-cross-repo-scan", action="store_true",
        help="Skip scanning all repos (avoids slow 41-repo traversal; use when only config/route changes)"
    )

    args = parser.parse_args()

    analysis_dir = Path(args.analysis_dir)
    output_file = Path(args.output)
    repos_dir = Path(args.repos_dir) if args.repos_dir else None

    if not analysis_dir.exists():
        print(f"[ERROR] Analysis directory not found: {analysis_dir}", file=sys.stderr)
        sys.exit(1)

    # Load all service analyses (affected services only)
    analyzers = {}

    if (analysis_dir / "summary.json").exists():
        analyzer = ServiceAnalyzer(analysis_dir)
        if analyzer.data:
            analyzers[analysis_dir.name] = analyzer
    else:
        for service_dir in analysis_dir.iterdir():
            if service_dir.is_dir() and (service_dir / "summary.json").exists():
                analyzer = ServiceAnalyzer(service_dir)
                if analyzer.data:
                    analyzers[service_dir.name] = analyzer

    if not analyzers:
        print("[ERROR] No service analyses found", file=sys.stderr)
        sys.exit(1)

    print(f"[OK] Loaded {len(analyzers)} service analyses", file=sys.stderr)

    # Build dependency graph and consolidate (affected services)
    graph_builder = DependencyGraphBuilder(analyzers)
    consolidator = ConsolidatedAnalysis(analyzers, graph_builder, args.jira_id)
    consolidated = consolidator.generate()

    # Scan ALL other cloned repos for references to changed symbols/services
    if getattr(args, 'no_cross_repo_scan', False):
        consolidated["cross_repo_impact"] = []
        print("[INFO] Cross-repo scan skipped (--no-cross-repo-scan)", file=sys.stderr)
    elif repos_dir and repos_dir.is_dir():
        print(f"[OK] Scanning all repos in {repos_dir} for cross-repo impact...", file=sys.stderr)
        all_repos_scanner = AllReposRiskScanner(repos_dir, analyzers)
        cross_repo_risks = all_repos_scanner.scan()
        consolidated["cross_repo_impact"] = cross_repo_risks
        high_count = sum(1 for r in cross_repo_risks if r["risk_level"] == "HIGH")
        med_count  = sum(1 for r in cross_repo_risks if r["risk_level"] == "MEDIUM")
        print(
            f"     Cross-repo: {len(cross_repo_risks)} repos reference affected changes "
            f"({high_count} HIGH, {med_count} MEDIUM)",
            file=sys.stderr,
        )
        # Enrich transitive_impact using cross_repo_impact.
        # The blast_radius-derived graph is intra-repo only and produces no cross-service
        # edges (it greps symbol names, not service names). Use the AllReposRiskScanner
        # results instead: map each matched term back to the service that changed it,
        # then record the referencing repo as a transitive dependent of that service.
        if cross_repo_risks:
            term_to_service: Dict[str, str] = {}
            for svc_name, analyzer in analyzers.items():
                for sig in analyzer.signature_changes:
                    func = sig.get("function", "").strip()
                    if func:
                        term_to_service[func] = svc_name
                for feat in analyzer.removed_features:
                    clean = feat.strip()
                    if clean:
                        term_to_service[clean] = svc_name
                # Service name itself as a term
                term_to_service[svc_name] = svc_name

            ti = consolidated.setdefault("transitive_impact", {})
            for entry in cross_repo_risks:
                referencing_repo = entry.get("repo", "")
                if not referencing_repo:
                    continue
                for term in entry.get("matched_terms", []):
                    origin_svc = term_to_service.get(term)
                    if origin_svc and referencing_repo != origin_svc:
                        repos_list = ti.setdefault(origin_svc, [])
                        if referencing_repo not in repos_list:
                            repos_list.append(referencing_repo)
            if any(ti.values()):
                print(
                    f"     Transitive impact enriched from cross-repo scan: "
                    f"{sum(len(v) for v in ti.values())} service(s) downstream",
                    file=sys.stderr,
                )
    else:
        consolidated["cross_repo_impact"] = []
        if args.repos_dir:
            print(f"[WARN] --repos-dir not found: {args.repos_dir} — skipping cross-repo scan", file=sys.stderr)

    # Write output
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w") as f:
        json.dump(consolidated, f, indent=2)

    print(f"[OK] Consolidated analysis saved to {output_file}", file=sys.stderr)
    print(f"     Services: {consolidated['service_count']}", file=sys.stderr)
    print(f"     Risk: {consolidated['risk_summary']['high_risk_services']} high, "
          f"{consolidated['risk_summary']['medium_risk_services']} medium, "
          f"{consolidated['risk_summary']['low_risk_services']} low", file=sys.stderr)


if __name__ == "__main__":
    main()
