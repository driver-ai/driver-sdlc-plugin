---
description: Gather codebase context for a specific task
argument-hint: <task description> [--codebases name1,name2]
allowed-tools: Agent, Bash, mcp__driver-mcp__get_codebase_names
---

# /drvr:context Command

Spawn the `driver-task-context` agent to gather comprehensive codebase context
for a specific task. The agent runs in isolated context, keeping your main
conversation clean while it explores architecture docs, code maps, and
synthesizes what you need.

## Workflow

### Step 1: Parse Arguments

Parse `$ARGUMENTS` for:
- **Task description**: The main text describing what the user wants to accomplish
- **Codebase hint** (optional): `--codebases name1,name2` (one or more, comma-separated)

Examples:
- `/drvr:context implement webhook handler` → task only
- `/drvr:context implement webhook handler --codebases python-backend` → task + single codebase
- `/drvr:context design auth flow --codebases webapp-frontend,python-backend` → task + multiple codebases

If task description is empty, ask:
> "What task do you need context for? (e.g., 'implement user authentication',
> 'debug slow API responses', 'design the payment flow')"

### Step 2: Resolve Codebases

Determine the relevant Driver codebase(s) using these sources (in order of precedence):

1. **User-provided**: If `--codebases` flag was provided, use those names
2. **Local git context**: If in a git repo, try `git remote get-url origin` to detect repo name
3. **Conversation context**: Consider any codebases mentioned in the current conversation
4. **Ask user**: If no codebases can be determined, call `get_codebase_names` and ask user to select

**Important considerations**:
- Multiple codebases are valid and valuable for cross-codebase work
- Non-local scenarios (Claude Desktop, web chat, background agents) won't have git context — rely on user input or ask
- Verify any detected/provided names against `get_codebase_names` to ensure they're valid Driver codebases

### Step 3: Spawn Context Agent

Spawn the `driver-task-context` agent with a prompt that communicates the task and codebases. Keep it simple — the agent has its own detailed instructions.

**Prompt format**:
```
Task: [user's task description]

Codebase(s): [comma-separated list of codebase names, or "to be determined" if asking agent to discover]

[Any additional context from the user or conversation that would help the agent]
```

Do NOT include detailed instructions for the agent — it already knows what to do.

### Step 4: Display Results

The agent returns synthesized context. Display it to the user without modification.

## Examples

```
/drvr:context implement webhook handler for Stripe events
/drvr:context debug why authentication is slow --codebases python-backend
/drvr:context understand how the payment flow works
/drvr:context design auth integration --codebases webapp-frontend,python-backend
/drvr:context refactor the notification system to support SMS
```

## Notes

- This command only spawns the agent; it does no file operations itself
- The agent runs in isolated context, keeping your main conversation clean
- Supports single or multiple codebases — Driver's value includes cross-codebase context
- Works in both local (git repo) and non-local (Claude Desktop, web chat) scenarios
- For quick lookups of specific files/symbols, use Driver MCP tools directly
