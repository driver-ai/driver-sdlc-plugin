---
description: Set up a projects directory for the Driver SDLC plugin
argument-hint: "[clone-url]"
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, AskUserQuestion, mcp__driver-mcp__get_codebase_names
---

# /setup Command

Set up a projects directory for the Driver SDLC plugin. This command is idempotent — safe to re-run at any time.

## Workflow

### Step 1: Wrong-Directory Detection

Check if `.claude-plugin/plugin.json` exists in the current directory using Glob.

**If found:** The user is inside the plugin repo, not a projects directory. Tell them:

> "You're currently in the driver-sdlc-plugin directory. The `/setup` command configures a **projects directory** — a separate repo where your features, research, and plans live."
>
> "Would you like to:"
> 1. "Create a new projects directory (I'll guide you through it)"
> 2. "Clone an existing team projects repo"

If the user picks option 1, ask them to `cd` to where they want the projects directory and run `/setup` again. If option 2, ask for the clone URL and proceed to Step 3C.

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

4. **Create `.gitignore`** in the new directory
   Read the template at `templates/gitignore.template` (relative to the plugin directory). Write its contents to `<parent>/<name>/.gitignore`.

5. **Create `.mcp.json`** in the new directory
   Write this exact content to `<parent>/<name>/.mcp.json`:
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

6. **Create `CLAUDE.md`** in the new directory
   Read the template at `templates/CLAUDE.md.template` (relative to the plugin directory). Use it as a structural guide to generate the final CLAUDE.md:
   - Replace `{{TEAM_NAME}}` with the directory name from step 2
   - Replace `{{DATE}}` with today's date
   - Leave the Codebases table as a placeholder — codebases are configured per-feature during `/feature` setup
   - Write the result to `<parent>/<name>/CLAUDE.md`

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
   > 2. "Run `/feature <name>` to start your first feature"

### Step 3B: Existing Repo Audit

Check for required files and fill gaps.

1. **Audit what exists:**

   | File | Check | If Missing |
   |------|-------|------------|
   | `CLAUDE.md` | Glob for `CLAUDE.md` | Offer to create from template (ask for team name + codebases first) |
   | `.gitignore` | Glob for `.gitignore` | Offer to create from template |
   | `.mcp.json` | Glob for `.mcp.json` | Create with `driver-mcp` server |
   | `features/` | Glob for `features/` | Create directory |

   **For `.mcp.json` that exists:** Read it and check if `mcpServers.driver-mcp` is present.
   - If `driver-mcp` is missing, warn: "Your `.mcp.json` does not include a `driver-mcp` server. The plugin requires this for codebase context. Would you like me to add it?"
   - If the user says yes, read the existing `.mcp.json`, add the `driver-mcp` entry to `mcpServers` (preserving all existing servers), and write it back.

2. **Report what was found and what was created.**

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
   - Do NOT retry automatically. Let the user fix the issue and re-run `/setup`.

4. **cd into the cloned directory** and run Step 3B (audit and fill gaps).

### Step 4: Plugin Configuration

For all paths (A, B, C), after the projects directory is set up:

1. **Resolve the absolute path** of the current projects directory:
   ```bash
   pwd
   ```
   This gives the absolute path. Store it as `projects_path`.

2. **Update `config.local.json`** in the plugin directory:
   - The plugin directory can be found relative to this command file (this file is at `commands/setup.md`, so the plugin root is `..` relative to it). Use `Bash` to resolve: the plugin knows its own location.
   - Read existing `config.local.json` if it exists — preserve all fields (especially `friction_tracking`)
   - Set or update `projects_path` to the resolved absolute path
   - Write the updated config back

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
- features/: <created | already exists>

**Plugin configuration:**
- config.local.json: projects_path set to <path>
- Hooks: auto-registered via hooks.json

**Driver MCP:** <connected (N codebases) | not connected — see above>

**Next step:** Run `/feature <name>` to start your first feature.
```
