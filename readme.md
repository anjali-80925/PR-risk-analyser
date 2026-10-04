# PR Risk Analyser

Cross-service, risk-based PR analysis tool for QA teams. Automatically detects testing risks across multiple repositories and languages, generates plain-English risk intelligence, and renders a dark-themed HTML report directly in your browser.

**Key features:**

- **Project-agnostic** — works with any git-hosted project (Bitbucket, GitHub, GitLab)
- **Multi-language** — auto-detects and analyses JS/TS, Java, Python, Go, C# (with generic fallback)
- **Cross-service** — scans multiple repos in parallel, merges overlapping risks
- **Plain English** — outputs risk scenarios readable by testers, PMs, and business stakeholders
- **One trigger** — configure once, then just type a ticket ID in VS Code Copilot Chat

## Prerequisites

- **VS Code** with **GitHub Copilot** (agent mode enabled)
- **Atlassian MCP** server running and connected (provides Jira + Confluence access)
- **WSL or Git Bash** (scripts require bash; on Windows use WSL or the bundled Git Bash terminal)
- **Python 3.9+** in path (`python3`)
- **Git** with SSH access to your service repositories

## Quick Start

### 1. Configure

Run the interactive setup wizard once per team/project:

```bash
bash scripts/init.sh
```

The wizard asks for:

- Git provider (`bitbucket-server` | `bitbucket-cloud` | `github` | `gitlab`)
- Base repo URL — everything before the repo name (e.g. `git@github.com:your-org`)
- Service repo names — must match actual repo names exactly (one per line)
- JIRA project key prefix (e.g. `PROJ`, `MYAPP`)
- Test automation repo name (optional — enables test selection)

This writes `config.env` in the workspace root. Edit it any time to add/remove services.

### 2. Analyse a ticket

In **VS Code Copilot Chat** (PR-analyser mode), type the Jira ticket ID:

```
PROJ-1234
```

That's it. Service repos are cloned automatically on first run into `.service-repos/`. No manual git clone needed.

The report opens in your browser automatically when complete.

## How It Works

The pipeline runs in three phases, fully orchestrated by the Copilot agent:

```
Phase 1 — Agent (MCP fetch)
  ├── Fetch Jira issue (*all fields)
  ├── Search Confluence for related pages (ticket ID + epic ID)
  ├── Fetch full page content for each match
  └── Write jira_issue.json + confluence_pages.json to pr-analysis/<JIRA_ID>/

Phase 2 — Script (git diff + extraction)
  ├── Detect affected services from git log (commit messages matching JIRA_ID)
  ├── Per-service diff extraction in parallel (extract_enhanced.py)
  ├── Cross-service dependency + blast-radius analysis (analyze_dependencies.py)
  ├── QA risk profile generation (analyze_pr_with_profile.py)
  ├── Test selection from automation repo (select_tests_for_pr.py)
  └── Consolidate everything into agent_context.json (extract_agent_context.py)

Phase 3 — Agent (report generation)
  ├── Read agent_context.json (single file — no sequential reads)
  ├── Generate grounded test scenarios from diff data
  ├── Write dark-themed analysis_report.html (create_file tool)
  └── Open report in browser
```

**Important:** The agent generates scenarios grounded only in detected diff data — it does not invent behavior or architecture.

## Language Support

The extraction engine (`extract_enhanced.py`) auto-detects languages from file extensions in the diff and applies the correct patterns for each:

| Language | Extensions | What it detects |
|----------|-----------|-----------------|
| **JavaScript / TypeScript** | `.js`, `.ts`, `.jsx`, `.tsx` | Function signatures, imports/exports, React components, Jest/Vitest tests |
| **Java** | `.java`, `.kt`, `.groovy` | Method signatures, imports, Spring annotations, JUnit/TestNG tests |
| **Python** | `.py` | `def`/`class` signatures, imports, pytest/unittest tests |
| **Go** | `.go` | `func` signatures, imports, `_test.go` files |
| **C# / .NET** | `.cs` | Method signatures, `using` statements, NUnit/xUnit tests |
| **Generic** | (fallback) | Diff stats, commit metadata (no language-specific extraction) |

Multi-language PRs are supported — if a diff touches `.java` and `.ts` files, both profiles run together.

### Adding a new language

Add a `LANG_*` dictionary in `scripts/lib/extract_enhanced.py` and register it in the `LANGUAGE_PROFILES` list. Each profile defines: `extensions`, `sig_pattern`, `import_pattern`, `export_patterns`, `test_file_pattern`, `test_block_pattern`, `assertion_pattern`, and file exclusion rules.

Each service analysis produces a `summary.json`, which is then consolidated into `agent_context.json` — the single file the Copilot agent reads to generate the report:

| Field | Description |
|-------|-------------|
| `languages_detected` | Auto-detected language(s) from the diff |
| `changed_files` | Source files modified (lockfiles and generated files filtered out) |
| `signature_changes` | Functions/methods where parameters or return types changed |
| `removed_features` | Deleted imports, removed component usages |
| `new_status_values` | Added entries in enums, constants, type definitions |
| `blast_radius` | Files that use changed exports but are NOT in the diff |
| `test_changes` | Modified assertions, removed/added test blocks |
| `diff_stats` | `files_changed`, `lines_added`, `lines_removed`, `new_files`, `deleted_files` |
| `commits` | Commit metadata (hash, author, date, subject) |

## Output Files

All files are written to `pr-analysis/<JIRA_ID>/`:

| File | Description |
|------|-------------|
| `jira_issue.json` | Normalised Jira ticket data (written by agent in Phase 1) |
| `confluence_pages.json` | Related Confluence pages with full body text (Phase 1) |
| `consolidated_summary.json` | Cross-service analysis with risk scores |
| `qa_analysis.md` | Risk triggers and QA profile narrative |
| `test_index.json` | Full test inventory from the automation repo |
| `test_selection.json` | Tests selected proportional to risk (HIGH=100%, MED=70%, LOW=30%) |
| `agent_context.json` | Lean combined context for the agent — single read replaces all others |
| `analysis_report.html` | Final dark-themed report, auto-opened in browser |

## Script Reference

The main script can be run directly (outside Copilot) for debugging or CI use:

```bash
bash scripts/run_analysis_by_jira_id.sh <JIRA_ID> [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--no-fetch` | Skip Jira gate check — use when `jira_issue.json` already exists |
| `--no-report` | Skip `generate_report.py` — agent generates the HTML instead |
| `--skip-tests` | Skip test selection and export steps |
| `--filter-mode <any\|only>` | How commits are matched to the JIRA_ID (default: `any`) |
| `--output-dir <path>` | Custom output directory (default: `pr-analysis/<JIRA_ID>`) |

**Typical agent invocation (Phases 1+2):**
```bash
bash scripts/run_analysis_by_jira_id.sh PROJ-1234 --no-fetch --no-report
```

## config.env Reference

| Key | Description |
|-----|-------------|
| `GIT_PROVIDER` | `github` \| `gitlab` \| `bitbucket-server` \| `bitbucket-cloud` |
| `REPO_BASE_URL` | SSH/HTTPS base URL before the repo name (e.g. `git@github.com:your-org`) |
| `SERVICE_DISCOVERY_MODE` | `manual` (uses `SERVICES` list) \| `auto` (scans `.service-repos/`) |
| `SERVICES` | Comma-separated repo names to analyse |
| `JIRA_PROJECT_KEYS` | Comma-separated project key prefixes (e.g. `PROJ,MYAPP`) |
| `TEST_REPOS` | Automation test repo name — leave blank to disable test selection |
| `MAX_PARALLEL` | Max parallel service analysis jobs (default: `4`) |
| `REF_CACHE_TTL` | Remote ref cache lifetime in seconds (default: `600`) |

## Porting to Another Project

The only project-specific file is `config.env` (gitignored). All scripts, the Copilot agent instructions, and the extraction engine work across any project, language, or git provider.

1. Copy this workspace to your team's machine
2. Run `bash scripts/init.sh` to generate a fresh `config.env`
3. Ensure your SSH key has read access to all repos listed in `SERVICES`
4. Type a ticket ID in VS Code Copilot Chat — done
