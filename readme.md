# PR Risk Analyser

Cross-service, risk-based PR analysis tool for QA teams. Automatically detects testing risks across multiple repositories and languages, generates plain-English risk intelligence, and posts it directly to JIRA.

**Key features:**

- **Project-agnostic** — works with any git-hosted project (Bitbucket, GitHub, GitLab)
- **Multi-language** — auto-detects and analyses JS/TS, Java, Python, Go, C# (with generic fallback)
- **Cross-service** — scans multiple repos in parallel, merges overlapping risks
- **Plain English** — outputs risk blocks readable by testers, PMs, and business stakeholders
- **Two commands** — the entire pipeline runs exactly 2 shell commands; everything else is handled by Copilot

## Prerequisites

- **Git** (with SSH or HTTPS access to your repos)
- **Python 3.x** (stdlib only — no `pip install` needed)
- **VS Code** with **GitHub Copilot** (Chat + JIRA MCP server for posting)

## Quick Start

### 1. Clone and configure

```bash
git clone <this-repo-url> qa-workspace
cd qa-workspace

# Option A: interactive wizard (recommended)
bash scripts/init.sh

# Option B: copy and edit the example
cp config.env.example config.env
```

The wizard asks for:

- Git provider (Bitbucket Server / Bitbucket Cloud / GitHub / GitLab)
- Base repo URL (SSH or HTTPS)
- Service names (comma-separated, or auto-detect from workspace)
- JIRA project key prefix(es)
- Performance tuning (parallelism, cache TTL)

### 2. Analyse a PR

Open VS Code Copilot Chat and say:

```
Analyze PROJ-123 and post to PROJ-456
```

That's it. Service repos are cloned automatically on first run. No manual git clone needed.

## How It Works

```
You say: "Analyze PROJ-123 and post to PROJ-456"
         │
Step 1:  detect_services.sh — scans all repos in parallel
         (cached remote refs → local commit search → branch name match)
         │
Step 2:  run_all_analyses.sh — runs per-service analysis in parallel
         (fetch → diff → language-aware enhanced extraction)
         │
Step 3:  Copilot reads summary.json + changes.diff per service
         (signature changes, blast radius, removed features, test changes)
         │
Step 4:  Generates 3–6 risk blocks in plain English (High / Medium only)
         │
Step 5:  Preview → Confirm → Posts to JIRA verbatim
```

Only **two shell commands** are executed. Risk analysis, merging, preview, and JIRA posting all happen inside the Copilot agent.

## Configuration

All settings live in `config.env` (created by the setup wizard or copied from `config.env.example`):

| Setting | Purpose | Default |
|---------|---------|---------|
| `GIT_PROVIDER` | `bitbucket-server`, `bitbucket-cloud`, `github`, `gitlab` | — |
| `REPO_BASE_URL` | SSH/HTTPS base URL for all repos | — |
| `SERVICE_DISCOVERY_MODE` | `auto` (scan workspace) or `manual` (explicit list) | `manual` |
| `SERVICES` | Comma-separated repo names (manual mode) | — |
| `JIRA_PROJECT_KEYS` | JIRA project prefix(es) for validation | — |
| `MAX_PARALLEL` | Concurrent service scans | `4` |
| `REF_CACHE_TTL` | Remote ref cache lifetime (seconds) | `600` |

> `config.env` is gitignored — each team member / project gets their own.

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

## Enhanced Extraction (summary.json)

Each service analysis produces a rich `summary.json`:

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

## Adding a New Service

**Auto-detect mode:** Ensure the repo is accessible at `REPO_BASE_URL/<name>.git`. It will be cloned automatically when a matching JIRA ID is found.

**Manual mode:** Edit `config.env`:

```bash
SERVICES=existing-service,new-service
```

## Workspace Structure

```
qa-workspace/
├── .github/
│   └── copilot-instructions.md    # Copilot agent prompt (risk analysis logic)
├── .vscode/
│   └── mcp.json                   # JIRA MCP server configuration
├── scripts/
│   ├── init.sh                    # Interactive setup wizard
│   ├── detect_services.sh         # Service detection (COMMAND 1 of 2)
│   ├── run_pr_analysis.sh         # Single-service analysis
│   ├── run_all_analyses.sh        # Parallel orchestrator (COMMAND 2 of 2)
│   └── lib/
│       ├── common.sh              # Shared utilities (logging, git helpers, JIRA parsing)
│       ├── load_config.sh         # config.env parser
│       └── extract_enhanced.py    # Language-aware extraction engine
├── pr-analysis/                   # Output directory (gitignored)
├── .service-repos/                # Cached repo clones (gitignored)
├── config.env                     # Team config (gitignored — created by init.sh)
├── config.env.example             # Template for new projects
├── Jenkinsfile-pr-analysis        # CI pipeline (optional)
└── package.json                   # NPM convenience scripts
```

## NPM Scripts

```bash
npm run setup               # Interactive config wizard
npm run detect -- JIRA-123  # Find which services have changes
npm run analyze -- JIRA-123 # Run full analysis for all detected services
npm run clean               # Remove analysis output (keep repo clones)
npm run clean:all           # Remove everything (output + repo clones)
```

## Jenkins CI (Optional)

`Jenkinsfile-pr-analysis` provides a ready-to-use declarative pipeline:

- **Parameters:** `JIRA_IDS` (required), `AGENT_LABEL` (default: `ubuntu`), `TIMEOUT_MINUTES` (default: `15`)
- **Stages:** Validate Input → Detect Services → Run Analysis → Verify Results
- **Artifacts:** `summary.json`, `changes.diff`, and `run.log` per service are archived automatically

To use in your project:

1. Copy `Jenkinsfile-pr-analysis` into your Jenkins job config
2. Edit the `@Library` line to match your Jenkins shared libraries (or remove it)
3. Edit `AGENT_LABEL` default to match your available agents
4. Ensure `config.env` exists in the repo

## Porting to Another Project

This tool is designed to be reused across teams with zero code changes:

1. **Clone the repo** into a new workspace
2. **Create config:**
   ```bash
   cp config.env.example config.env
   # Edit with your project's repos, git provider, and JIRA key
   ```
   Or run `bash scripts/init.sh` for the interactive wizard.
3. **Open VS Code** and start analysing — `"Analyze PROJ-123 and post to PROJ-456"`

The only project-specific file is `config.env` (gitignored). Everything else — scripts, Copilot prompt, extraction engine — works across any project, language, or git provider.

## Shared Library (scripts/lib/)

All scripts share common utilities via `common.sh` to eliminate duplicated code:

| Function | Purpose |
|----------|---------|
| `parse_jira_ids()` | Validate and split comma-separated JIRA IDs |
| `jira_grep_pattern()` | Build `ID1\|ID2` pattern for git log grep |
| `ensure_repo()` | Clone or fetch a service repo (one network round-trip) |
| `resolve_services()` | Populate service list from config (auto or manual mode) |
| `cleanup_analysis()` | Remove old results while preserving cache |
| `log_info/ok/warn/error/step()` | Consistent logging across all scripts |

Path constants (`WORKSPACE_ROOT`, `SERVICE_REPOS_DIR`, `ANALYSIS_DIR`, `CACHE_DIR`) are defined once and reused everywhere. Jenkins persistence is handled automatically — repos and cache survive workspace re-clones.

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `config.env` not found | Run `bash scripts/init.sh` or `cp config.env.example config.env` |
| No services detected | Verify JIRA ID has commits in at least one repo; check SSH access |
| Clone/fetch failed | Verify `REPO_BASE_URL` in `config.env`; test `git ls-remote <url>` manually |
| Empty `summary.json` | Check `pr-analysis/<service>/run.log` for errors |
| Wrong language detected | Verify file extensions in the diff; add a language profile if needed |
| Windows: scripts fail | Ensure Git Bash is installed; scripts run via `bash -c "..."` automatically |

## Team Onboarding

1. Clone this repo
2. Run `bash scripts/init.sh`
3. Open VS Code → Copilot Chat → `"Analyze JIRA-123 and post to JIRA-456"`

No other configuration needed. No manual git clones. No maintenance.