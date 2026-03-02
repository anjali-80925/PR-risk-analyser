# PR Risk Analyser

Cross-service, risk-based PR analysis tool for QA teams. Detects testing risks, generates plain-English risk intelligence, and posts it directly to JIRA.

## Prerequisites

- **Git** (with SSH access to your repos)
- **Python 3.x** (for enhanced extraction — signature changes, blast radius, test changes)
- **VS Code** with **GitHub Copilot**

## Quick Start (3 steps)

### 1. Clone this repo

```bash
git clone <this-repo-url> qa-workspace
cd qa-workspace
```

### 2. Run setup wizard (one-time)

```bash
bash scripts/init.sh
```

The wizard asks for:
- Git provider (Bitbucket/GitHub/GitLab)
- Base repo URL
- Service names (or auto-detect mode)
- JIRA project key

### 3. Open VS Code and use Copilot Chat

```
Analyze PROJ-123 and post to PROJ-456
```

**That's it.** Service repos are cloned automatically on first analysis. No manual git clone needed.

## How It Works

```
You say: "Analyze PROJ-123 and post to PROJ-456"
         |
Step 1:  detect_services.sh scans all repos in parallel
         (cached remote refs + local commit search + auto-clone)
         |
Step 2:  run_all_analyses.sh runs per-service analysis in parallel
         (fetch → single diff → enhanced extraction)
         |
Step 3:  Copilot reads enhanced summary.json + filtered changes.diff
         (signature changes, blast radius, removed features, test changes)
         |
Step 4:  Generates 3-6 risk blocks in plain English
         |
Step 5:  Preview → Confirm → Posts to JIRA verbatim
```

## Configuration

All settings live in `config.env` (created by setup wizard):

| Setting | Purpose |
|---------|---------|
| `GIT_PROVIDER` | bitbucket-server, bitbucket-cloud, github, gitlab |
| `REPO_BASE_URL` | SSH/HTTPS base URL for all repos |
| `SERVICE_DISCOVERY_MODE` | `"auto"` (scan workspace) or `"manual"` (listed) |
| `SERVICES` | Comma-separated repo names (manual mode only) |
| `JIRA_PROJECT_KEYS` | JIRA project prefixes for validation |
| `MAX_PARALLEL` | Concurrent service scans (default: 4) |
| `REF_CACHE_TTL` | How long to cache git remote refs in seconds |

## Enhanced Extraction (summary.json)

Each service analysis produces a rich `summary.json` with:

| Field | Description |
|-------|-------------|
| `changed_files` | Source files only (lockfiles filtered out) |
| `signature_changes` | Functions where parameters or return types changed |
| `removed_features` | Deleted imports, removed component usages |
| `new_status_values` | Added entries in enums, constants, type definitions |
| `blast_radius` | Files that use changed exports but are NOT in the diff |
| `test_changes` | Modified assertions, removed/added test blocks |
| `diff_stats` | Files changed, lines added/removed, new/deleted files |
| `commits` | Commit metadata (hash, author, date, subject) |

## Adding a New Service

**Auto-detect mode:** Just ensure the repo is accessible at `REPO_BASE_URL/<name>.git`. It will be cloned automatically when a matching JIRA ID is found.

**Manual mode:** Edit `config.env`:
```bash
SERVICES=existing-service,new-service
```

## Workspace Structure

```
qa-workspace/
  .github/copilot-instructions.md   <- Copilot agent prompt
  .vscode/mcp.json                  <- JIRA MCP server config
  scripts/
    init.sh                          <- Setup wizard
    lib/load_config.sh               <- Shared config loader (pure bash)
    lib/extract_enhanced.py          <- Enhanced extraction engine
    detect_services.sh               <- Service detection (COMMAND 1)
    run_pr_analysis.sh               <- Single-service analysis
    run_all_analyses.sh              <- Parallel orchestrator (COMMAND 2)
  pr-analysis/                       <- Output (gitignored)
  config.env                         <- Your team's config (pure bash)
  package.json                       <- NPM scripts for convenience
```

## NPM Scripts (optional convenience)

```bash
npm run setup              # Interactive config wizard
npm run detect -- JIRA-123 # Find which services have changes
npm run analyze -- JIRA-123 # Run full analysis
npm run clean              # Remove all analysis output
```

## Team Onboarding

1. Clone this repo
2. Run `bash scripts/init.sh`
3. Open VS Code -> Copilot Chat -> `"Analyze JIRA-123 and post to JIRA-456"`

No other configuration needed. No manual git clones. No maintenance.