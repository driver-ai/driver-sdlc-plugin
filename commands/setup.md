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

6. **Create `CLAUDE.md`** in the new directory. Read the canonical template from `${CLAUDE_PLUGIN_ROOT}/templates/CLAUDE.md.template` (fall back to globbing for `templates/CLAUDE.md.template` under the plugin directory if the env var is unset), then replace `{{TEAM_NAME}}` with the directory name from step 2 and `{{DATE}}` with today's date. Leave the Codebases table as a placeholder — codebases are configured per-feature during `/drvr:feature` setup. Write the result to `<parent>/<name>/CLAUDE.md`.

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
   | `CLAUDE.md` | Glob for `CLAUDE.md` | Offer to create from `${CLAUDE_PLUGIN_ROOT}/templates/CLAUDE.md.template` (ask for project name first) |
   | `.gitignore` | Glob for `.gitignore` | Offer to create using the .gitignore content from Step 3A |
   | `.mcp.json` | Glob for `.mcp.json` | Create with `driver-mcp` server using the .mcp.json content from Step 3A |

   **For `.mcp.json` that exists:** Read it and check if `mcpServers.driver-mcp` is present.
   - If `driver-mcp` is missing, warn: "Your `.mcp.json` does not include a `driver-mcp` server. The plugin requires this for codebase context. Would you like me to add it?"
   - If the user says yes, read the existing `.mcp.json`, add the `driver-mcp` entry to `mcpServers` (preserving all existing servers), and write it back.

2. **Report what was found and what was created.**

3. **Template version check** — If CLAUDE.md exists, read the first line. Look for `<!-- drvr:template-version:X.Y.Z -->`.

   - **If found and matches current version (1.2.0):** Skip migration. Report: "CLAUDE.md is up to date (template v1.2.0)."
   - **If found but outdated:** Look up the migration path in the Migration Registry below. Apply each migration in sequence, asking user approval for each.
   - **If not found:** Treat as pre-versioning (version 0). Apply the full migration path from v0 → current.
   - **If version is higher than current (1.2.0):** Warn: "CLAUDE.md has template version X.Y.Z which is newer than this plugin's current version (1.2.0). Skipping migration." and skip.

   After all migrations are applied, update the version comment on line 1 to the current version. If no version comment exists, add it as the first line. Before adding, scan the file for any existing `<!-- drvr:template-version:` comments and remove them to prevent duplicates.

### Migration Registry

Each row describes what changed between template versions and how to migrate existing CLAUDE.md files. Each migration step must be idempotent — check if the change has already been applied before making it.

| From | To | Changes | Migration Steps |
|------|----|---------|----------------|
| (none) | 1.0.0 | Initial versioned template. Commands qualified with `drvr:` prefix. Skills qualified in tables. | 1. Replace 8 unqualified command names with `drvr:`-prefixed versions (see table below). 2. Replace 5 unqualified skill names with `drvr:`-prefixed versions in Skills and Phase-Skill Mapping tables. 3. Add `<!-- drvr:template-version:1.0.0 -->` as first line. |
| 1.0.0 | 1.1.0 | Intent phase, internal review, open-pr, post-PR lifecycle, expanded agents list. | 1. Add Intent row (`drvr:intent-guidance`) to Phase-Skill Mapping table. 2. Add Internal Review (`/drvr:review`), Open PR (`/drvr:open-pr`), PR Review, Revision, Merge, Verification, Shipped, Retro rows to Phase-Skill Mapping. 3. Add 5 commands to Commands table: `/drvr:context`, `/drvr:review`, `/drvr:driverize`, `/drvr:un-driverize`, `/drvr:open-pr`. 4. Add `drvr:intent-guidance` to Skills table. 5. Add 7 agents to Agents table: commit-log, decisions-log, features-list, security-review, standards-review, test-coverage, dependency-analysis. 6. Update lifecycle diagram to include Intent phase and full post-assess flow. 7. Update version comment to `1.1.0`. |
| 1.1.0 | 1.2.0 | Per-plan PR model — each plan ships as its own stacked/parallel PR; the assess → review → docs → open-pr gate runs once per plan; `driver-docs/` becomes centralized per-plan; the Codebases table uses a Branch Prefix instead of a single Feature Branch. | 1. In the Phase-Skill Mapping table, rename the post-assessment phases to their per-plan forms — Assessment → **Per-plan Assessment** (`/drvr:assess <plan>`), Internal Review → **Per-plan Internal Review** (`/drvr:review <plan>`), Handoff → **Per-plan Handoff** (`/drvr:docs-artifacts <plan>`), Open PR → **Per-plan Open PR** (`/drvr:open-pr <plan>`), plus per-plan PR Review / Revision / Merge / Verification — and add a **Next Plan** row. 2. Replace the single-feature lifecycle diagram with the per-plan gate diagram (assess/review/docs/open-pr run per plan, then PR Review → Revision → Merge → Verification → Next plan; all plans shipped → Feature Shipped). 3. Add the **One plan = one PR, stacked** and **Each PR must stand alone** Key Principles. 4. In the Codebases table, replace the `Feature Branch` column with `Branch Prefix`; add the note that each plan gets its own branch (default `<prefix>/<NN-plan-slug>`). 5. Update the Project Structure block: mark `plans/` "one plan = one PR", `assessment/` as per-plan (`<plan>-test-curation.md`), and `driver-docs/` as centralized per-plan (`00-feature-overview.md` + `<plan>/`). 6. Ensure `/drvr:open-pr` is in the Commands table. 7. Update version comment to `1.2.0`. |

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

### In-Flight Features (1.1.0 → 1.2.0)

The Migration Registry above migrates a project's **`CLAUDE.md`** to the per-plan model. It does **not** restructure feature artifacts already on disk. A feature that entered its post-implementation phases under 1.1.0 has 1.1.0-shaped artifacts that the per-plan commands do not recognize:

| 1.1.0 artifact | 1.2.0 expectation |
|----------------|-------------------|
| `assessment/test-curation-<date>.md` (feature-wide) | `assessment/<plan>-test-curation.md` (per-plan) |
| flat `driver-docs/{feature-overview,architecture,testing-guide,risk-assessment}.md` | `driver-docs/<plan>/*` + `driver-docs/00-feature-overview.md` rollup |
| single Feature Branch per codebase | per-plan branches derived from a Branch Prefix |
| feature-wide `pr_created` / `pr_merged` FEATURE_LOG events | per-plan `pr_created_<plan>` / `pr_merged_<plan>` events |

Because of this, `/drvr:assess <plan>`, `/drvr:docs-artifacts <plan>`, and `/drvr:open-pr <plan>` will **BLOCK** on a feature scaffolded under 1.1.0 — they look for `assessment/<plan>-test-curation.md` and `driver-docs/<plan>/`, which don't exist yet.

**Recommended:** finish any feature already past implementation on the 1.1.0 flow. Pin the plugin to the version the feature started on and run its single-PR handoff (`/drvr:assess` → `/drvr:docs-artifacts` → `/drvr:open-pr`) to completion. Adopt the per-plan model for features that start fresh under 1.2.0.

**If you must move an in-flight feature to per-plan**, migrate its artifacts by hand before running the per-plan gate — this is deliberately manual, since how a feature-wide assessment maps onto individual plans is a judgment call:

1. Rename `assessment/test-curation-<date>.md` → `assessment/<plan>-test-curation.md` for the plan you're shipping (split it if it covered multiple plans).
2. Move the flat `driver-docs/*.md` under `driver-docs/<plan>/` and create the `driver-docs/00-feature-overview.md` cross-plan rollup.
3. In `plans/00-overview.md`, replace the single Feature Branch with a PR Stack table (one row per plan) and set each plan's Base Branch from its `depends_on` (feature parent if independent; upstream plan's Feature Branch if dependent).
4. Backfill any `pr_created` / `pr_merged` entries in `FEATURE_LOG.md` to their `_<plan>` forms.

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

The canonical CLAUDE.md template is a **single source of truth** at
`${CLAUDE_PLUGIN_ROOT}/templates/CLAUDE.md.template` — the same file the plugin's
tests validate. When creating a new projects directory (Step 3A) or filling a gap
in an existing repo (Step 3B), read that file, substitute `{{TEAM_NAME}}` with the
project name and `{{DATE}}` with today's date, and write the result. When migrating
an existing CLAUDE.md, apply the Migration Registry steps above in sequence.

Do not embed a second copy of the template here — keeping it in one place ensures
the scaffold, the migrations, and the tests never drift.
