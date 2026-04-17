---
description: Set up a projects directory for the drvr plugin
argument-hint: "[clone-url]"
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, AskUserQuestion, mcp__driver-mcp__get_codebase_names
---

# /drvr:setup Command

Set up a projects directory for the drvr plugin. This command is idempotent — safe to re-run at any time.

## Config Path

Plugin configuration lives at `~/.driver/config.json`. This is independent of the plugin's install method and survives plugin updates.

```
~/.driver/config.json
```

## Workflow

### Step 1: Wrong-Directory Detection

Check if `.claude-plugin/plugin.json` exists in the current directory using Glob.

**If found:** The user is inside the plugin repo, not a projects directory. Tell them:

> "You're currently in the driver-sdlc-plugin directory. The `/drvr:setup` command configures a **projects directory** — a separate repo where your features, research, and plans live."
>
> "Would you like to:"
> 1. "Create a new projects directory (I'll guide you through it)"
> 2. "Clone an existing team projects repo"

If the user picks option 1, ask them to `cd` to where they want the projects directory and run `/drvr:setup` again. If option 2, ask for the clone URL and proceed to Step 3C.

### Step 2: Route to the Appropriate Path

**If an argument was provided** (looks like a URL — contains `://` or starts with `git@`):
- Treat it as a clone URL → go to Step 3C

**If features/ or CLAUDE.md already exist in the current directory:**
- Auto-detect as existing repo → go to Step 3B
- Tell the user: "Detected an existing projects directory. Running setup audit..."

**Otherwise, ask the user:**

> "Are you setting up a new projects repo, or does your team already have one?"
> 1. "New — I'm starting fresh"
> 2. "My team has one and I have it cloned locally" (current directory)
> 3. "My team has one but I need to clone it"

- Option 1 → Step 3A
- Option 2 → Step 3B
- Option 3 → Step 3C

### Step 3A: Fresh Start

Create a new projects directory from scratch.

1. **Ask:** "Where do you want to create your projects directory?" (e.g., `~/projects`, `~/work`, `.`)
   - Expand `~` and resolve to an absolute path

2. **Ask:** "What do you want to call it?" (e.g., `my-team-sdlc`, `acme-projects`)

3. **Create the directory** at `<parent>/<name>/`:
   ```bash
   mkdir -p <parent>/<name>
   ```

4. **Create `.gitignore`** in the new directory. Write this exact content to `<parent>/<name>/.gitignore`:
   ```
   # Environment and secrets
   .env
   .env.local
   .env.*.local

   # MCP configuration (may contain API keys)
   .mcp.json

   # OS files
   .DS_Store
   Thumbs.db

   # IDE/Editor
   .idea/
   .vscode/

   # Claude Code local state
   .claude/

   # Temporary files
   tmp/
   temp/
   ```

5. **Create `.mcp.json`** in the new directory. Write this exact content to `<parent>/<name>/.mcp.json`:
   ```json
   {
     "mcpServers": {
       "driver-mcp": {
         "type": "http",
         "url": "https://api.us1.driverai.com/mcp/v1"
       }
     }
   }
   ```

6. **Create `CLAUDE.md`** in the new directory. Generate it from the template below, replacing `{{TEAM_NAME}}` with the directory name from step 2 and `{{DATE}}` with today's date. Leave the Codebases table as a placeholder — codebases are configured per-feature during `/drvr:feature` setup. Write the result to `<parent>/<name>/CLAUDE.md`.

7. **Git init** in the new directory:
   ```bash
   cd <parent>/<name> && git init
   ```

8. **Initial commit**:
   ```bash
   cd <parent>/<name> && git add CLAUDE.md .gitignore && git commit -m "Initialize SDLC projects directory"
   ```
   Do NOT add `.mcp.json` — it's gitignored (may contain API keys).

9. **Tell the user:**
   > "Your projects directory is ready at `<absolute-path>`. To start using it:"
   > 1. "Open Claude Code in that directory: `cd <path> && claude --permission-mode auto`"
   > 2. "Run `/drvr:feature <name>` to start your first feature"

### Step 3B: Existing Repo Audit

Check for required files and fill gaps.

1. **Audit what exists:**

   | File | Check | If Missing |
   |------|-------|------------|
   | `CLAUDE.md` | Glob for `CLAUDE.md` | Offer to create from the CLAUDE.md template below (ask for project name first) |
   | `.gitignore` | Glob for `.gitignore` | Offer to create using the .gitignore content from Step 3A |
   | `.mcp.json` | Glob for `.mcp.json` | Create with `driver-mcp` server using the .mcp.json content from Step 3A |

   **For `.mcp.json` that exists:** Read it and check if `mcpServers.driver-mcp` is present.
   - If `driver-mcp` is missing, warn: "Your `.mcp.json` does not include a `driver-mcp` server. The plugin requires this for codebase context. Would you like me to add it?"
   - If the user says yes, read the existing `.mcp.json`, add the `driver-mcp` entry to `mcpServers` (preserving all existing servers), and write it back.

2. **Report what was found and what was created.**

3. **Template version check** — If CLAUDE.md exists, read the first line. Look for `<!-- drvr:template-version:X.Y.Z -->`.

   - **If found and matches current version (1.0.0):** Skip migration. Report: "CLAUDE.md is up to date (template v1.0.0)."
   - **If found but outdated:** Look up the migration path in the Migration Registry below. Apply each migration in sequence, asking user approval for each.
   - **If not found:** Treat as pre-versioning (version 0). Apply the full migration path from v0 → current.
   - **If version is higher than current (1.0.0):** Warn: "CLAUDE.md has template version X.Y.Z which is newer than this plugin's current version (1.0.0). Skipping migration." and skip.

   After all migrations are applied, update the version comment on line 1 to the current version. If no version comment exists, add it as the first line. Before adding, scan the file for any existing `<!-- drvr:template-version:` comments and remove them to prevent duplicates.

### Migration Registry

Each row describes what changed between template versions and how to migrate existing CLAUDE.md files. Each migration step must be idempotent — check if the change has already been applied before making it.

| From | To | Changes | Migration Steps |
|------|----|---------|----------------|
| (none) | 1.0.0 | Initial versioned template. Commands qualified with `drvr:` prefix. Skills qualified in tables. | 1. Replace 8 unqualified command names with `drvr:`-prefixed versions (see table below). 2. Replace 5 unqualified skill names with `drvr:`-prefixed versions in Skills and Phase-Skill Mapping tables. 3. Add `<!-- drvr:template-version:1.0.0 -->` as first line. |

**Command name replacements** (v0 → v1.0.0):

| Old | New |
|-----|-----|
| `/feature` | `/drvr:feature` |
| `/setup` | `/drvr:setup` |
| `/dry-run-plan` | `/drvr:dry-run-plan` |
| `/assess` | `/drvr:assess` |
| `/docs-artifacts` | `/drvr:docs-artifacts` |
| `/orchestrate` | `/drvr:orchestrate` |
| `/retro` | `/drvr:retro` |
| `/context` | `/drvr:context` |

**Skill name replacements** (v0 → v1.0.0):

| Old | New |
|-----|-----|
| `research-guidance` | `drvr:research-guidance` |
| `planning-guidance` | `drvr:planning-guidance` |
| `materialize-tasks` | `drvr:materialize-tasks` |
| `implementation-guidance` | `drvr:implementation-guidance` |
| `sdlc-orchestration` | `drvr:sdlc-orchestration` |

### Step 3C: Clone Team Repo

1. **Ask for clone URL** (if not provided as argument):
   > "What's the git clone URL for your team's projects repo?"

2. **Ask where to clone** (default: current directory):
   > "Where should I clone it? (default: current directory)"

3. **Clone:**
   ```bash
   git clone <url> [destination]
   ```
   - If the clone fails (invalid URL, auth failure, network error, destination exists), report the error and suggest common fixes:
     - "Check the URL is correct"
     - "For SSH: verify your SSH key is set up (`ssh -T git@github.com`)"
     - "For HTTPS: check your credentials/token"
     - "If the destination exists, try a different path"
   - Do NOT retry automatically. Let the user fix the issue and re-run `/drvr:setup`.

4. **cd into the cloned directory** and run Step 3B (audit and fill gaps).

### Step 4: Plugin Configuration

For all paths (A, B, C), after the projects directory is set up:

1. **Resolve the absolute path** of the projects directory:
   - For Path A: the `<parent>/<name>` from step 3
   - For Path B: the current working directory (`pwd`)
   - For Path C: the cloned directory

2. **Update `~/.driver/config.json`**:
   ```bash
   mkdir -p ~/.driver
   ```
   - Read existing `~/.driver/config.json` if it exists — preserve all fields (especially `friction_tracking`)
   - Set or update `projects_path` to the resolved absolute path
   - Write the updated config back to `~/.driver/config.json`

3. **Note:** Hooks are auto-registered via `hooks/hooks.json` — no configuration needed.

### Step 5: MCP Connectivity Verification

1. Call `get_codebase_names` from Driver MCP (tool: `mcp__driver-mcp__get_codebase_names`)

2. **If successful:** Report the available codebases:
   > "Driver MCP is connected. Found N codebases: [list first 5-10 names]"

3. **If it fails:** Warn but don't block:
   > "Driver MCP is not connected. This is needed for codebase context during research and planning. Check:"
   > - "Your Driver API token is configured"
   > - "The `.mcp.json` file has the correct URL"
   > - "Visit [driverai.com](https://driverai.com) for setup instructions"

### Step 6: Status Report

Print a summary of everything that was done:

```
## Setup Complete

**Projects directory:** <absolute path>
**Files created/verified:**
- CLAUDE.md: <created | already exists>
- .gitignore: <created | already exists>
- .mcp.json: <created | already exists | driver-mcp verified>

**Plugin configuration:**
- ~/.driver/config.json: projects_path set to <path>
- Hooks: auto-registered via hooks.json

**Driver MCP:** <connected (N codebases) | not connected — see above>

**Next step:** Run `/drvr:feature <name>` to start your first feature.
```

---

## CLAUDE.md Template

Use this template when creating CLAUDE.md for a new projects directory. Replace `{{TEAM_NAME}}` with the project name and `{{DATE}}` with today's date.

````markdown
<!-- drvr:template-version:1.0.0 -->
# {{TEAM_NAME}} — SDLC Project Instructions

This repository organizes development work by feature, with each feature containing its own lifecycle of artifacts. It is managed by the [Driver SDLC Plugin (drvr)](https://github.com/driver-ai/driver-sdlc-plugin) for Claude Code.

---

## Project Structure

```
{{TEAM_NAME}}/
├── CLAUDE.md                # Agent instructions (this file)
├── .mcp.json                # MCP server configuration (gitignored)
├── .gitignore
├── features/                # Feature development projects
│   └── <feature-name>/
│       ├── FEATURE_LOG.md   # Lifecycle state — the source of truth
│       ├── research/        # Problem exploration and design decisions
│       ├── plans/           # Implementation plans
│       │   ├── 00-overview.md  # Multi-plan overview (when needed)
│       │   └── NN-plan-name/   # Directory named after plan file (sans .md)
│       │       └── tasks/      # Materialized task documents
│       │           └── NN-task-name.md
│       ├── dry-runs/        # Plan validation results
│       ├── implementation/  # Implementation logs per plan
│       ├── assessment/      # Test suite curation results
│       ├── tests/           # Markdown test plans (optional)
│       │   └── results/     # Timestamped test results
│       └── driver-docs/     # Handoff documentation
```

| Folder | Purpose | When Created |
|--------|---------|-------------|
| `FEATURE_LOG.md` | Source of truth for lifecycle state | `/drvr:feature` scaffolding |
| `research/` | Problem statements, explorations, trade-off analysis | `/drvr:feature` scaffolding |
| `plans/` | Implementation plans with concrete steps | Planning phase |
| `dry-runs/` | Plan validation results with gap analysis | `/drvr:dry-run-plan` |
| `implementation/` | Implementation logs tracking deviations per plan | Implementation phase |
| `assessment/` | Test suite curation results | `/drvr:assess` |
| `tests/` | Markdown test plans executed by LLM agents | When manual testing is needed |
| `driver-docs/` | Handoff documentation | `/drvr:docs-artifacts` |

Use `/drvr:feature <name>` to scaffold a new feature project. Use `/drvr:orchestrate <feature-path>` to resume an existing feature.

---

## Frontmatter Schema

All artifacts use YAML frontmatter for structured metadata.

**Required fields** (all types):
```yaml
---
type: <type>
status: <status>
created: "YYYY-MM-DD"
updated: "YYYY-MM-DD"
---
```

**Types:** `research`, `plan`, `task`, `implementation_log`, `feature_log`, `decision`, `deviation`, `learning`, `test_plan`, `test_result`, `assessment`, `open_question`

**Statuses:** `not_started`, `in_progress`, `complete`, `approved`, `accepted`, `pending_review`, `resolved`, `open`, `confirmed`, `unverified`

**Type-specific fields:**
- `task`: `plan` (parent plan name), `task_number` (sequential position, integer), `depends_on` (list of task paths), `materialized_at` (ISO 8601 timestamp)
- `decision`: `topic`, `choice`
- `deviation`: `severity` (low/medium/high), `task` (source task)
- `plan`: `depends_on`, `blocks` (for dependency graph resolution)

---

## SDLC Lifecycle

Features follow a phased development lifecycle. Each phase has a dedicated skill that provides guidance.

```
/drvr:feature -> Research -> Planning -> Validation -> Materialization -> Implementation -> Review -> Bookkeeping -> Next Plan -> ...
                                                                                                                          |
                                                                                                             All plans complete
                                                                                                                          |
                                                                                                                          v
                                                                                                 /drvr:assess -> /drvr:docs-artifacts -> Handoff
```

### Phase -> Skill Mapping

| Phase | Skill / Command | What It Does |
|-------|----------------|-------------|
| Research | `drvr:research-guidance` | Why-What-How methodology, document organization, completion criteria |
| Planning | `drvr:planning-guidance` | TDD-first task design, test strategy, architecture fit, task breakdown |
| Validation | `/drvr:dry-run-plan` | Walk through plan as-if implementing, severity-classified gaps |
| Materialization | `drvr:materialize-tasks` | Convert plan tasks into standalone task docs for sub-agent execution |
| Implementation | `drvr:implementation-guidance` | Plan-driven task execution, deviation tracking, commit discipline |
| Review | `drvr:sdlc-orchestration` | Present deviations for user approval before bookkeeping |
| Bookkeeping | `drvr:implementation-guidance` | Update plan status, overview, cascade check |
| Assessment | `/drvr:assess` | Curate test suite — categorize, prune scaffolding, promote valuable tests |
| Handoff | `/drvr:docs-artifacts` | Generate feature-overview, architecture, testing-guide, risk-assessment |

### Key Principles

- **User controls all decisions** — skills suggest, the user decides. No auto-fixing, no silent bookkeeping.
- **Deviations are reviewed** — after implementation, deviations are presented for approval before bookkeeping.
- **Plans are the source of truth** — implementation builds exactly what the plan specifies, nothing more.
- **Research before building** — the SDLC is front-loaded: most time goes into Research and Planning.

---

## Commands

| Command | Purpose |
|---------|---------|
| `/drvr:setup` | Set up this projects directory (first-time configuration) |
| `/drvr:feature <name>` | Scaffold a new feature project with FEATURE_LOG.md |
| `/drvr:orchestrate <path>` | Resume a feature — read log, report state, suggest next action |
| `/drvr:dry-run-plan <plan>` | Walk through a plan to identify gaps before implementation |
| `/drvr:assess` | Curate test suite after implementation — categorize, prune, promote |
| `/drvr:docs-artifacts` | Generate handoff documentation for code review |
| `/drvr:retro` | Evaluate session quality, patterns, and improvements |

## Skills

| Skill | Purpose |
|-------|---------|
| `drvr:research-guidance` | Why-What-How methodology, document organization |
| `drvr:planning-guidance` | TDD-first plans, test strategy, task breakdown |
| `drvr:materialize-tasks` | Materialize approved plan tasks into standalone task docs |
| `drvr:implementation-guidance` | Plan-driven execution, deviation tracking, bookkeeping |
| `drvr:sdlc-orchestration` | Lifecycle coordination, phase transitions |

## Agents

| Agent | Purpose |
|-------|---------|
| `driver-task-context` | Gather task-specific context from Driver MCP |
| `cascade-check` | Analyze implementation deviations against downstream plans |
| `handoff-analyzer` | Synthesize process artifacts + git + Driver context for handoff |

---

## Codebases

| Codebase | Repo | Local Path | Default Branch | Description |
|----------|------|------------|----------------|-------------|
| _Add your codebases here_ | | | | |

---

## Engineering Guidelines

### Patterns We Follow

_Add your team's coding standards here. Examples:_
- _Naming conventions_
- _Error handling patterns_
- _Code organization rules_

### Patterns We Avoid

_Add anti-patterns your team has agreed to avoid. Examples:_
- _No mocking the database in integration tests_
- _No generic dict types for structured data_

### Testing Strategy

_Describe your team's testing approach. Examples:_
- _Test framework and commands_
- _Unit vs. integration test boundaries_
- _Coverage expectations_

---

## MCP Integrations

| Integration | Purpose | When to Use |
|-------------|---------|-------------|
| **Driver MCP** | Codebase architecture, file docs, code maps | Starting any research or planning |
| _Add additional MCP servers here_ | | |

---

## Key References

| Document | Purpose |
|----------|---------|
| _Add links to external resources here_ | |

---

_Generated by `/drvr:setup` on {{DATE}}_
````
