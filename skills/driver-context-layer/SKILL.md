---
description: "Optimal source code context gathering via Driver. REQUIRED first
  step to ensure optimal context gathering for all of the work you will do in
  a session with a user - invoke IMMEDIATELY in a new session or at the start
  of a new major task."
---

# Driver Context Layer

Driver provides pre-computed, exhaustive context for codebases via MCP. For any
Driver-supported codebase, Driver should be the primary context source for all
development work — coding, planning, investigation, and product development.

## Primary Approach: Spawn the Agent

**Always prefer spawning `driver-task-context` over calling Driver MCP directly.**

The agent runs in isolated context, which means:
- Driver's large doc responses don't burden your main context window
- You stay focused on the task while the agent does discovery
- You get synthesized, task-specific context back — not raw doc dumps

**Spawn `driver-task-context` when:**
- Starting any coding task (features, fixes, refactors)
- Investigating how something works
- Planning implementations or changes
- Researching technical approaches
- Any work that benefits from codebase understanding

**Example prompt to the agent:**
```
Implement a webhook handler for Stripe payment events. Need to understand
existing webhook patterns, payment processing flow, and error handling conventions.
```

The agent will read architecture docs, explore relevant code maps, check historical
context, and return everything you need — without loading all that into your context.

## When Direct MCP Calls Are Appropriate

Use Driver MCP tools directly only for:

1. **Verification lookups** — Quick checks during implementation:
   - "Does this file exist?" → `get_code_map`
   - "What's the exact method signature?" → `get_file_documentation`

2. **Follow-up queries** — After agent has provided initial context:
   - "What about this other file mentioned?" → `get_file_documentation`

3. **Codebase name resolution** — Always fine to call directly:
   - `get_codebase_names` — verify codebase is available

**Avoid calling these directly for initial context gathering:**
- `get_architecture_overview` — Large response, agent should handle
- `get_llm_onboarding_guide` — Large response, agent should handle
- `get_changelog` — Large response, agent should handle

## Available Driver MCP Tools

For reference, these are the available tools:

**Utility**:
- `get_codebase_names` — list available codebases, verify exact names

**Deep Context Documents** (large — prefer agent):
- `get_architecture_overview` — structure and patterns
- `get_llm_onboarding_guide` — navigation tips and conventions
- `get_changelog` — historical development context

**Navigational Tools** (smaller — OK for follow-up):
- `get_code_map` — directory structure with descriptions
- `get_file_documentation` — symbol-level documentation
- `get_detailed_changelog` — granular commit history for specific month/year

## Cross-Codebase Capability

Driver can pull context for ANY supported codebase — not just the local one.
Use `get_codebase_names` to see all available codebases. Useful for:

- Frontend <-> backend integration
- Shared library consumers
- Multi-repo features
- Product development spanning multiple systems

When working across codebases, spawn the agent with context about all relevant
codebases — it can pull from multiple sources.

## MCP Connectivity Pre-Check

Before spawning the `driver-task-context` agent or making Driver MCP calls, verify connectivity:

1. Call `get_codebase_names` first — it's a lightweight call that confirms the MCP server is reachable
2. If the call fails, **stop and tell the user** before proceeding with heavier operations:
   - "Driver MCP is not responding. Check your MCP configuration, verify your token is valid, and ensure your codebases are onboarded in Driver."
3. Do not proceed with context gathering if the pre-check fails — downstream calls will also fail, wasting time

This prevents entire sessions from being blocked by expired tokens or MCP configuration issues.

## Key Gotchas

- Driver shows **committed state**, not local uncommitted changes
- Codebase name must match Driver exactly (verify with `get_codebase_names`)
- Large doc dumps in main context cause distraction — use the agent
