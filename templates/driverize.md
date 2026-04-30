# Driverize — Install Driver Enforcement Stack

You are installing a defense-in-depth enforcement stack that ensures Claude Code uses Driver MCP for codebase intelligence instead of native exploration tools. The stack has four tiers:

1. **Permissions & hooks** — deterministic enforcement via `settings.json` deny rules and a PreToolUse hook
2. **Shadow agents** — replace built-in Explore, Plan, and general-purpose agents with Driver-only versions
3. **Context injection** — SessionStart and UserPromptSubmit hooks re-inject routing policy on every session event
4. **Thin CLAUDE.md** — decision tree and examples positioned at the top of CLAUDE.md

**You are running from the repo root.** Driver MCP is already connected. This prompt works standalone — no plugins required.

Follow these 6 phases in order.

---

## Phase 1: Read

### 1.1: Verify Driver Connectivity

Call `get_codebase_names`. If it fails, stop and tell the user:
> "Driver MCP is not responding. Check your MCP configuration in `.mcp.json`, verify your token is valid, and ensure your codebases are onboarded in Driver."

Store the list of available codebase names — you'll include these in the output summary.

### 1.2: Detect MCP Server Name

Read `.mcp.json` in the current directory. Also read `~/.claude/.mcp.json` if it exists. The file uses the format `{"mcpServers": {"server-name": {...}}}`. Look inside `mcpServers` for a key matching `*driver*` (case-insensitive). Apply these rules:

- If exactly one match → use it
- If `driver-mcp` exists → prefer it
- If multiple ambiguous matches → ask the user to confirm which one
- If no match → stop with: "Driver MCP server not found in `.mcp.json`. Configure it first, then re-run."

Store the detected name as `MCP_SERVER_NAME`. All tool references and settings will use this as the prefix (e.g., `mcp__driver-mcp__*` becomes `mcp__<MCP_SERVER_NAME>__*`).

Also note where Driver MCP is configured:
- **Project-scoped** (`.mcp.json` in repo root) — note for output summary warning
- **User-scoped** (`~/.claude/.mcp.json`) — no warning needed

### 1.3: Read Existing Configuration

Read the following if they exist. Store their content for Phase 2.

- `CLAUDE.md` (repo root)
- `.claude/settings.json`
- `.claude/hooks/` (list all files)
- `.claude/agents/` (list all files)
- `.claude/skills/` (list all directories)

If any `@` include directives exist in CLAUDE.md (lines starting with `@path/to/file.md`), read those files too.

---

## Phase 2: Analyze

### 2.1: Inventory Existing Config

If `.claude/settings.json` exists, parse it and note:
- Existing `permissions.deny` rules
- Existing `permissions.ask` rules
- Existing hook registrations (by event type and matcher)
- Any other top-level keys (preserve them in merge)

If it fails to parse as JSON, warn the user and proceed as if no settings.json exists.

If `.claude/hooks/` exists, note filenames — check for collisions with Driver hooks.
If `.claude/agents/` exists, note filenames — check for collisions with shadow agents.
If `.claude/skills/` exists, note directory names — check for collision with `explore-codebase`.

### 2.2: Parse CLAUDE.md

If CLAUDE.md exists, identify:
- The first heading (project title)
- Whether an existing "Driver" section exists (for in-place replacement)
- Core content sections (build commands, style rules, architecture, conventions, etc.)

### 2.3: Back Up Files

Create backups of files that will be modified:
- `CLAUDE.md` → `CLAUDE.md.pre-driver` (if CLAUDE.md exists)
- `.claude/settings.json` → `.claude/settings.json.pre-driver` (if settings.json exists)

### 2.4: Generate Verification Token

Generate a random verification token for the PreToolUse hook's flag file. Use:
```bash
VERIFY_TOKEN=$(head -c 32 /dev/urandom | base64 | tr -d '/+=' | head -c 24)
```

Store this — it will be embedded in the hook script.

---

## Phase 3: Generate

Generate all enforcement artifacts, substituting `__MCP_SERVER_NAME__` with the detected `MCP_SERVER_NAME` and `__DRIVER_VERIFY_TOKEN__` with the generated verification token.

### 3.1: PreToolUse Hook — `.claude/hooks/driver-first.sh`

```bash
#!/usr/bin/env bash
# PreToolUse hook: gate native exploration tools behind Driver context

if ! command -v jq &>/dev/null; then exit 0; fi

STDIN=$(cat)
SESSION=$(echo "$STDIN" | jq -r '.session_id')
TOOL=$(echo "$STDIN" | jq -r '.tool_name')

FLAG_FILE="/tmp/driver-context-loaded-${SESSION}"
UNAVAIL_FILE="/tmp/driver-unavailable-${SESSION}"
VERIFY_TOKEN="__DRIVER_VERIFY_TOKEN__"

if [ -f "$UNAVAIL_FILE" ]; then
  exit 0
fi

if echo "$TOOL" | grep -q '^mcp__'; then
  if echo "$TOOL" | grep -qE '(gather_task_context|get_architecture_overview|get_code_map)$'; then
    echo "$VERIFY_TOKEN" > "$FLAG_FILE"
  fi
  exit 0
fi

check_context_loaded() {
  [ -f "$FLAG_FILE" ] && [ "$(cat "$FLAG_FILE" 2>/dev/null)" = "$VERIFY_TOKEN" ]
}

if [ "$TOOL" = "Read" ]; then
  exit 0
fi

if [ "$TOOL" = "Grep" ] || [ "$TOOL" = "Glob" ]; then
  if ! check_context_loaded; then
    echo "Use Driver MCP tools instead: gather_task_context for broad context, get_code_map to navigate structure, get_file_documentation for symbol-level detail. Native $TOOL is blocked until Driver context is loaded." >&2
    exit 2
  fi
  exit 0
fi

if [ "$TOOL" = "Bash" ]; then
  if ! check_context_loaded; then
    CMD=$(echo "$STDIN" | jq -r '.tool_input.command // ""')
    if echo "$CMD" | grep -qiE '(^|[;&|( ])\s*(env |command |nice |nohup |xargs )?\s*(grep|rg|find|ag|ack|fd|tree)\b'; then
      echo "Use Driver MCP tools for codebase search: gather_task_context, get_code_map, get_file_documentation. Native search commands are blocked until Driver context is loaded." >&2
      exit 2
    fi
  fi
  exit 0
fi

if [ "$TOOL" = "Agent" ]; then
  SUBAGENT=$(echo "$STDIN" | jq -r '.tool_input.subagent_type // ""')
  case "$SUBAGENT" in
    Explore|Plan|general-purpose|claude-code-guide)
      echo "Use Driver MCP tools instead of the $SUBAGENT agent: gather_task_context for broad context, get_code_map for structure, get_file_documentation for details. Shadow agents in .claude/agents/ provide Driver-integrated alternatives." >&2
      exit 2
      ;;
    ""|null)
      echo "Agent calls require an explicit subagent_type. Use Driver MCP tools for exploration: gather_task_context, get_code_map, get_file_documentation." >&2
      exit 2
      ;;
  esac
  exit 0
fi

exit 0
```

### 3.2: SessionStart Hook — `.claude/hooks/inject-driver-policy.sh`

```bash
#!/usr/bin/env bash
# SessionStart hook: inject Driver routing policy on startup/resume/clear/compact

if ! command -v jq &>/dev/null; then exit 0; fi

STDIN=$(cat)
SESSION=$(echo "$STDIN" | jq -r '.session_id')
CWD=$(echo "$STDIN" | jq -r '.cwd')

rm -f "/tmp/driver-context-loaded-${SESSION}" "/tmp/driver-unavailable-${SESSION}"

DRIVER_FOUND=false
for MCP_PATH in "${CWD}/.mcp.json" "${HOME}/.claude/.mcp.json"; do
  if [ -f "$MCP_PATH" ]; then
    if jq -e '(.mcpServers // .) | to_entries[] | select(.key | test("driver"; "i"))' "$MCP_PATH" >/dev/null 2>&1; then
      DRIVER_FOUND=true
      break
    fi
  fi
done

if [ "$DRIVER_FOUND" = true ]; then
  rm -f "/tmp/driver-unavailable-${SESSION}"

  POLICY=$(cat <<'POLICY_EOF'
## Driver MCP Routing Policy

This project uses Driver MCP for codebase intelligence. Native exploration tools (Grep, Glob, search Bash commands, Explore/Plan/general-purpose agents) are blocked by project hooks until Driver context is loaded.

**Decision tree — pick the Driver tool that fits your need:**

| Need | Driver Tool |
|------|-------------|
| Broad task context, suggested approach | `gather_task_context` (start here for new tasks) |
| Architecture overview, system design | `get_architecture_overview` |
| Directory structure, navigate codebase | `get_code_map` |
| Symbol-level detail for a specific file | `get_file_documentation` |
| Read actual source code | `get_source_file` (or native `Read` after Driver identifies the file) |
| Recent changes, development history | `get_changelog` / `get_detailed_changelog` |
| Onboarding, conventions, navigation tips | `get_llm_onboarding_guide` |

**After Driver returns context**, use native Read/Edit/Write for surgical file modifications.
POLICY_EOF
)

  POLICY_JSON=$(echo "$POLICY" | jq -Rs .)
  printf '{"continue": true, "additionalContext": %s}' "$POLICY_JSON"
else
  touch "/tmp/driver-unavailable-${SESSION}"

  WARNING="## Driver MCP Not Configured\n\nDriver MCP server was not found in .mcp.json. Native exploration tools (Grep, Glob, Bash search, Agent) are allowed as fallback. To enable Driver enforcement, configure Driver MCP in .mcp.json or ~/.claude/.mcp.json."
  WARNING_JSON=$(printf '%s' "$WARNING" | jq -Rs .)
  printf '{"continue": true, "additionalContext": %s}' "$WARNING_JSON"
fi
```

### 3.3: UserPromptSubmit Hook — `.claude/hooks/route-to-driver.sh`

```bash
#!/usr/bin/env bash
# UserPromptSubmit hook: detect exploration prompts and re-inject Driver routing

if ! command -v jq &>/dev/null; then exit 0; fi

STDIN=$(cat)
PROMPT=$(echo "$STDIN" | jq -r '.prompt')

if echo "$PROMPT" | tr '[:upper:]' '[:lower:]' | grep -qE 'where is|how does|what does|trace the|explore the|find the file|find the function|find the class|search the code|search for the|architecture of|navigate to|callers of|usage of|references to|who calls|defined in|implemented in|grep for|locate the'; then
  RULE="Reminder: Use Driver MCP tools for codebase exploration. Start with gather_task_context for broad context, get_code_map for structure, or get_file_documentation for symbol-level detail. Native search tools are blocked by project hooks until Driver context is loaded."
  RULE_JSON=$(printf '%s' "$RULE" | jq -Rs .)
  printf '{"continue": true, "additionalContext": %s}' "$RULE_JSON"
fi

exit 0
```

### 3.4: Shadow Agent — `.claude/agents/Explore.md`

```markdown
---
name: Explore
description: "Search and explore the codebase using Driver MCP tools. Use for: finding files, tracing code paths, locating symbols, understanding architecture, navigating structure."
model: sonnet
tools: mcp____MCP_SERVER_NAME____*, Read
---

Use Driver MCP tools to explore the codebase. Pick the tool that fits:

| Need | Tool |
|------|------|
| Broad task context | `gather_task_context` — start here |
| Directory structure | `get_code_map` |
| Symbol-level detail | `get_file_documentation` |
| Architecture overview | `get_architecture_overview` |
| Read source code | `get_source_file` or `Read` |
| Recent changes | `get_changelog` |

Use `Read` for targeted file access after Driver identifies the file. Do not attempt Grep, Glob, or Bash search commands — they are blocked by project hooks.
```

### 3.5: Shadow Agent — `.claude/agents/Plan.md`

```markdown
---
name: Plan
description: "Plan implementation strategy using Driver MCP for codebase context. Use for: designing features, planning implementations, evaluating trade-offs, architectural decisions."
model: sonnet
tools: mcp____MCP_SERVER_NAME____*, Read
---

Before planning, gather codebase context using Driver MCP:

1. Call `gather_task_context` with a rich description of what you're planning
2. Use `get_architecture_overview` if you need the system design
3. Use `get_code_map` to understand directory structure
4. Use `get_file_documentation` for symbol-level detail on key files

Use `Read` for targeted file access after Driver identifies relevant files. Do not attempt Grep, Glob, or Bash search commands — they are blocked by project hooks.
```

### 3.6: Shadow Agent — `.claude/agents/general-purpose.md`

```markdown
---
name: general-purpose
description: "General-purpose agent with Driver MCP for codebase context and full implementation capability. Use for: complex tasks, multi-step operations, code changes requiring broad context."
model: sonnet
tools: mcp____MCP_SERVER_NAME____*, Read, Edit, Write, Bash
---

Before exploring or searching the codebase, gather context using Driver MCP:

1. Call `gather_task_context` with a description of what you need
2. Use `get_code_map` for directory navigation
3. Use `get_file_documentation` for symbol-level detail

After Driver returns context, use Read/Edit/Write/Bash for implementation. Prefer Driver tools over Bash search commands (grep, find, rg) — search commands are blocked by project hooks until Driver context is loaded.
```

### 3.7: Skill — `.claude/skills/explore-codebase/SKILL.md`

```markdown
---
description: "Explore the codebase using Driver MCP tools. Use when: searching for files, tracing code paths, understanding architecture, finding symbols, navigating structure, locating implementations."
---

# Explore Codebase

Use Driver MCP to explore and search the codebase:

1. **Start with `gather_task_context`** — give it a rich description of what you're looking for
2. **Navigate with `get_code_map`** — browse directory structure at any depth
3. **Drill into files with `get_file_documentation`** — get symbol-level detail
4. **Read source with `Read`** — after Driver identifies the relevant file

Native search tools (Grep, Glob, find, grep) are blocked by project hooks. Use Driver MCP instead.
```

### 3.8: Settings Template — `.claude/settings.json`

The following is the Driver settings block. It will be merged with any existing settings in Phase 4.

```json
{
  "permissions": {
    "deny": [
      "Bash(grep:*)",
      "Bash(rg:*)",
      "Bash(find:*)",
      "Bash(ag:*)",
      "Bash(ack:*)",
      "Bash(fd:*)",
      "Bash(tree:*)",
      "Bash(env grep:*)",
      "Bash(command grep:*)",
      "Bash(env rg:*)",
      "Bash(command rg:*)",
      "Bash(env find:*)",
      "Bash(command find:*)",
      "Bash(touch /tmp/driver:*)",
      "Bash(rm /tmp/driver:*)"
    ],
    "ask": [
      "Edit(.claude/**)",
      "Write(.claude/**)"
    ]
  },
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Grep|Glob|Read|Bash|Agent",
        "hooks": [
          {
            "type": "command",
            "command": "$CLAUDE_PROJECT_DIR/.claude/hooks/driver-first.sh",
            "timeout": 10
          }
        ]
      }
    ],
    "SessionStart": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "$CLAUDE_PROJECT_DIR/.claude/hooks/inject-driver-policy.sh",
            "timeout": 15
          }
        ]
      }
    ],
    "UserPromptSubmit": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "$CLAUDE_PROJECT_DIR/.claude/hooks/route-to-driver.sh",
            "timeout": 10
          }
        ]
      }
    ]
  }
}
```

### 3.9: CLAUDE.md Block

Insert this block near the top of CLAUDE.md — after the first heading (project title) but before detailed content sections. If an existing Driver block is detected (heading containing "Driver"), replace it in place.

```markdown
## Codebase Intelligence — Driver MCP

This project uses Driver MCP for pre-computed codebase documentation. Native exploration tools (Grep, Glob, search commands, Explore/Plan agents) are blocked by project hooks until Driver context is loaded. Prefer Driver tools over native alternatives.

### Decision Tree

| I need to… | Use this Driver tool |
|------------|---------------------|
| Understand a task, get suggested approach | `gather_task_context` (start here) |
| See system architecture | `get_architecture_overview` |
| Navigate directory structure | `get_code_map` |
| Get symbol-level detail for a file | `get_file_documentation` |
| Read actual source code | `get_source_file` or native `Read` |
| See recent changes | `get_changelog` |
| Learn conventions, onboarding tips | `get_llm_onboarding_guide` |

### After Driver Returns

Use native Read/Edit/Write for surgical file modifications. Driver gives you the map; native tools do the surgery.

### Examples

**"Add retry logic to the API client"**
→ `gather_task_context` with description: "Add retry logic to the API client. Need to find the HTTP client implementation, understand error handling patterns, and identify where retries should be added."

**"Where is the authentication middleware defined?"**
→ `get_code_map` at the top level, then `get_file_documentation` on the auth-related file Driver identifies.

**"How does the billing service calculate invoices?"**
→ `gather_task_context` with description: "Trace the invoice calculation flow in the billing service. Need to understand the data model, calculation logic, and integration points."

**"Refactor the logger to use structured output"**
→ `gather_task_context` first, then `Read` the specific files, then `Edit` to make changes.
```

---

## Phase 4: Merge

Write files in this exact order. **settings.json is written LAST** because its permission rules apply dynamically — writing it earlier would trigger `ask` prompts for every subsequent `.claude/` file write.

### 4.1: Create Directories

```
mkdir -p .claude/hooks .claude/agents .claude/skills/explore-codebase
```

### 4.2: Write Hook Scripts

For each hook script (`driver-first.sh`, `inject-driver-policy.sh`, `route-to-driver.sh`):

1. Substitute `__DRIVER_VERIFY_TOKEN__` with the generated verification token (in `driver-first.sh` only)
2. Check if a file with the same name already exists in `.claude/hooks/`
3. If collision: rename the new file with a `-driver` suffix (e.g., `driver-first-driver.sh`) and update the settings.json command path to match. Note the collision in the output summary.
4. If no collision: write the file normally
5. Make executable: `chmod +x .claude/hooks/<filename>`

### 4.3: Write Shadow Agents

For each shadow agent (`Explore.md`, `Plan.md`, `general-purpose.md`):

1. Substitute `__MCP_SERVER_NAME__` with the detected MCP server name in the `tools:` field
2. Check if a file with the same name already exists in `.claude/agents/`
3. If collision: **DO NOT overwrite** — the customer's existing agent takes priority. Note in the output summary that this shadow agent could not be installed.
4. If no collision: write the file normally

### 4.4: Write Skill

1. Check if `.claude/skills/explore-codebase/` already exists
2. If collision: warn in summary and skip
3. If no collision: write `SKILL.md`

### 4.5: Write CLAUDE.md Block

If CLAUDE.md exists:
1. Look for an existing heading containing "Driver" (e.g., `## Codebase Intelligence — Driver MCP`, `## Driver MCP`)
2. If found: replace that entire section (up to the next same-level or higher heading) with the new block
3. If not found: insert the Driver block after the first heading (project title line) and before the next section
4. Preserve all other content — build commands, style rules, architecture, conventions, `@` includes, frontmatter

If CLAUDE.md does not exist:
1. Generate a new CLAUDE.md with:
   - `# <directory-name>` as the title
   - The Driver MCP block (from 3.9)
   - Placeholder sections for Build & Test, Code Style, Architecture with HTML comments

### 4.6: Write settings.json (LAST)

If existing settings.json was parsed successfully in Phase 2:
1. Load the existing JSON
2. Append Driver deny rules to `permissions.deny` array — skip any that already exist
3. Append Driver ask rules to `permissions.ask` array — skip any that already exist
4. For each hook event (PreToolUse, SessionStart, UserPromptSubmit):
   - If the event key exists, append the Driver matcher entry to the array — skip if an identical matcher already exists
   - If the event key does not exist, create it with the Driver entry
5. Preserve all other top-level keys (e.g., `allowedTools`, `model`, etc.)
6. Write the merged JSON

If no existing settings.json (or it failed to parse):
1. Write the Driver settings template directly

---

## Phase 5: Validate

1. Verify all expected files exist:
   - `.claude/hooks/driver-first.sh` (or `-driver` variant)
   - `.claude/hooks/inject-driver-policy.sh` (or `-driver` variant)
   - `.claude/hooks/route-to-driver.sh` (or `-driver` variant)
   - `.claude/agents/Explore.md` (unless collision)
   - `.claude/agents/Plan.md` (unless collision)
   - `.claude/agents/general-purpose.md` (unless collision)
   - `.claude/skills/explore-codebase/SKILL.md` (unless collision)
   - `.claude/settings.json`
   - `CLAUDE.md` (with Driver block)

2. Verify all hook scripts are executable: `test -x .claude/hooks/*.sh`

3. Verify settings.json is valid JSON: read it back and parse it

4. Verify the CLAUDE.md Driver block exists: look for the "Codebase Intelligence — Driver MCP" heading

---

## Phase 6: Output

Print a summary to the user:

```
## Driver Enforcement Stack Installed

### What was configured:

**Tier 1 — Permissions & Hooks (deterministic enforcement)**
- `.claude/settings.json` — deny rules block native search commands (grep, rg, find, ag, ack, fd, tree) and wrapper bypasses (env grep, command grep, etc.)
- `.claude/hooks/driver-first.sh` — PreToolUse hook blocks Grep/Glob/search-Bash/native-Agent before Driver context is loaded
- Flag file protection: deny rules prevent forgery of `/tmp/driver-*` flag files
- Tamper resistance: ask rules require user approval before modifying `.claude/` config

**Tier 2 — Shadow Agents (structural channeling)**
- `.claude/agents/Explore.md` — replaces built-in Explore with Driver-only version
- `.claude/agents/Plan.md` — replaces built-in Plan with Driver-only version
- `.claude/agents/general-purpose.md` — replaces built-in with Driver-first version (keeps Edit/Write/Bash)

**Tier 3 — Context Injection (self-healing)**
- `.claude/hooks/inject-driver-policy.sh` — re-injects routing policy on startup, resume, clear, and compact
- `.claude/hooks/route-to-driver.sh` — detects exploration prompts and re-injects routing

**Tier 4 — CLAUDE.md (prompt steering)**
- Decision tree and examples added near the top of CLAUDE.md

### Available codebases:
<list codebase names from Phase 1>

### Merge notes:
<list any collisions, skipped files, or warnings>

### Backups:
- `CLAUDE.md.pre-driver` — original CLAUDE.md
- `.claude/settings.json.pre-driver` — original settings (if existed)

### Known limitations:
- `--allowedTools "*"` bypasses deny rules and hooks — enforcement is disabled
- `--dangerously-skip-permissions` bypasses all permission checks
- Managed settings with org-level agent definitions cannot be shadowed
- Headless mode (`-p`) has known issues with hooks (Claude Code issue #36071)
<if Driver is project-scoped>
- Driver MCP is configured at project scope (`.mcp.json`). Shadow agents work most reliably when Driver MCP is at user scope (`~/.claude/.mcp.json`). Consider moving the config if you encounter issues with agent tool access (known bugs: #13605, #13898, #25200).
</if>

### To verify:
Start a new Claude Code session in this directory and ask an exploration question (e.g., "Where is the main entry point?"). The agent should use Driver MCP tools instead of native exploration.

### To rollback:
mv CLAUDE.md.pre-driver CLAUDE.md
mv .claude/settings.json.pre-driver .claude/settings.json
rm .claude/hooks/driver-first.sh .claude/hooks/inject-driver-policy.sh .claude/hooks/route-to-driver.sh
rm .claude/agents/Explore.md .claude/agents/Plan.md .claude/agents/general-purpose.md 
rm -rf .claude/skills/explore-codebase 
```

---

## Reminders

- **Write settings.json LAST** — permission rules apply dynamically and would block your own writes
- **Never overwrite existing customer agents** — their customizations take priority
- **Substitute all placeholders** — `__MCP_SERVER_NAME__` and `__DRIVER_VERIFY_TOKEN__` must be replaced before writing
- **This prompt works without any plugins** — it only needs Driver MCP connected
- **The verification token is unique per installation** — it prevents flag file forgery
