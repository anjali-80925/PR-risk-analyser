# PR Risk Analyser

Cross-service, risk-based PR analysis tool for QA teams. Automatically detects testing risks across multiple repositories and languages, generates plain-English risk intelligence, and posts it directly to JIRA.

**Key features:**

- **Project-agnostic** — works with any git-hosted project (Bitbucket, GitHub, GitLab)
- **Multi-language** — auto-detects and analyses JS/TS, Java, Python, Go, C# (with generic fallback)
- **Cross-service** — scans multiple repos in parallel, merges overlapping risks
- **Plain English** — outputs risk blocks readable by testers, PMs, and business stakeholders
- **Two commands** — the entire pipeline runs exactly 2 shell commands; everything else is handled by Copilot

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

## Jenkins CI

`Jenkinsfile-pr-analysis` provides a ready-to-use declarative pipeline with automatic credential detection:

**Features:**
- **Auto-detects Git credentials** from your Pipeline SCM configuration — no hardcoding needed
- **Parameters:** `JIRA_IDS` (required), `COMMIT_FILTER_MODE` (only/any), `GIT_CREDENTIAL_ID` (optional override)
- **Stages:** Validate Input → Detect Services → Run Analysis → Archive Artifacts
- **Artifacts:** `summary.json` files are archived automatically per service

**Setup for Your Team (5 minutes):**

1. **Create Pipeline Job** in Jenkins
   - Select "Pipeline script from SCM"
   - Configure your Git SCM URL and select your team's credential
   - Set script path: `Jenkinsfile-pr-analysis`
   - Jenkins will automatically use the same credential for service repo cloning

2. **Configure `config.env`** on Jenkins workspace (or commit it to a team branch):
   ```bash
   cp config.env.example config.env
   # Edit with your Git provider, service repos, and JIRA keys
   ```

3. **Run builds:**
   - Click "Build with Parameters"
   - Enter JIRA IDs (e.g., `PROJ-123,PROJ-456`)
   - Select filter mode
   - Done!

**Multi-Team Support:**
Different teams can use the same Jenkinsfile with different credentials:
- Team A: Uses credential `team-a-github` (auto-detected from their SCM config)
- Team B: Uses credential `team-b-bitbucket` (auto-detected from their SCM config)
- No Jenkinsfile modifications required ✅

## Porting to Another Project

This tool is designed to be reused across teams with zero code changes:

1. **Fork/clone the repo** into your team's namespace
2. **Create config:**
   ```bash
   cp config.env.example config.env
   # Edit with your project's repos, git provider, and JIRA key
   ```
   Or run `bash scripts/init.sh` for the interactive wizard.
3. **Set up Jenkins** (see above) or **use locally** via VS Code Copilot

The only project-specific file is `config.env` (gitignored). Everything else — scripts, Copilot prompt, extraction engine — works across any project, language, or git provider.