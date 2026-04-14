# Driver SDLC Plugin for Claude Code

A Claude Code plugin that guides structured feature development through a full software development lifecycle. Features move through Research, Planning, Validation, Implementation, Review, and Handoff phases -- each supported by specialized skills, commands, and agents that keep work organized, traceable, and thorough.

## Prerequisites

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) installed and configured
- A [Driver](https://driverai.com) account with your codebases onboarded
- Driver MCP server configured in Claude Code (provides codebase context)

## Installation

Clone the repository:

```bash
git clone https://github.com/driver-ai/driver-claude-sdlc-plugin.git
```

Add the plugin as a marketplace source, then install:

```bash
claude plugin marketplace add /path/to/driver-claude-sdlc-plugin
claude plugin install driver-claude-sdlc-plugin
```

Or load it for a single session:

```bash
claude --plugin-dir /path/to/driver-claude-sdlc-plugin
```

## Quick Start

1. Navigate to your project directory
2. Run `/feature my-feature-name` to scaffold a new feature project
3. Follow the guided SDLC phases -- the plugin loads the right skill for each phase and tells you what to do next

## Recommended Setup

> **Tip:** We recommend creating a centralized location for feature projects (e.g., a dedicated repo or directory). This helps with session resumption via `/orchestrate` and cross-feature context. Feature artifacts are plain markdown files organized by convention, so they work well in version control.

## SDLC Workflow

```
Research --> Planning --> Validation --> Implementation --> Review --> Handoff
   |            |            |               |                          |
   |            |            |               +-- deviations reviewed    |
   |            |            +-- /dry-run-plan identifies gaps          |
   |            +-- TDD-first plans with test strategy                  |
   +-- Why-What-How methodology                                        |
                                                                       |
                                              All plans complete --> /assess --> /docs-artifacts
```

### Phase Descriptions

| Phase | What Happens |
|-------|-------------|
| **Research** | Explore the problem space using structured Why-What-How questioning. Produce research docs and design decisions. |
| **Planning** | Write implementation plans with TDD-first task ordering, test strategy, and explicit constraints. |
| **Validation** | Dry-run each plan to find gaps before writing code. All gaps are reviewed, classified by severity. |
| **Implementation** | Execute plans task-by-task. Track deviations from the plan. Commit after each task. |
| **Review** | Present deviations for approval. Run cascade checks against downstream plans. |
| **Bookkeeping** | Update plan statuses, overview progress, and feature log. |
| **Assessment** | Curate the test suite -- prune scaffolding tests, promote valuable ones. |
| **Handoff** | Generate feature overview, architecture, testing guide, and risk assessment docs. |

The plugin is intentionally front-loaded: most time goes into Research and Planning. Implementation should be mechanical -- executing a well-validated plan.

## Usage Scenarios

### Easy: Understanding a Codebase

Use `/context` to get oriented in an unfamiliar codebase before making changes.

```
/context How does the authentication flow work? --codebases my-backend
```

The plugin spawns an agent that reads Driver's architecture docs and code maps, then returns a synthesized summary without cluttering your conversation context.

### Easy: Bug Fix with Context

Gather targeted context before fixing a bug.

```
/context The user profile page crashes when email is null --codebases frontend
```

Review the returned context, fix the bug, and commit. No full SDLC needed for a straightforward fix.

### Medium: Single-Plan Feature End-to-End

Build a complete feature through all phases.

```
/feature add-export-csv
> (research phase: answer questions about requirements, explore options)
> "ready to plan"
> (planning phase: review the generated plan, adjust tasks)
/dry-run-plan add-export-csv
> (fix any gaps found)
> "let's implement"
> (implementation phase: tasks executed, tests written, code committed)
/docs-artifacts features/add-export-csv
```

### Medium: Bug Investigation with SDLC

Use the structured approach for complex bugs that need root-cause analysis.

```
/feature investigate-race-condition
> (research phase: document symptoms, reproduce conditions, identify root cause)
> "ready to plan"
> (plan the fix with regression tests)
/dry-run-plan fix-race-condition
> "let's implement"
```

### Advanced: Multi-Plan Feature with Dependencies

Coordinate backend and frontend work with dependency ordering.

```
/feature support-ticket-system
> (research produces decisions on API design, data model, UI approach)
> "ready to plan"
> (create plans: 01-data-model, 02-api-endpoints, 03-frontend-ui)
> (overview tracks dependencies: 03 depends on 02, 02 depends on 01)
/dry-run-plan 01-data-model
> "let's implement"
> (complete plan 01, bookkeeping updates overview)
> "what's next"
> (orchestration identifies 02-api-endpoints as next unblocked plan)
```

### Advanced: Cross-Session Feature Development

Resume work after closing a session.

```
/orchestrate features/support-ticket-system
> Plugin reads the feature log, reports: "Plan 01 complete, Plan 02 in progress, task 3 of 7 done"
> "continue implementing"
```

### Expert: Large Feature with 4+ Plans

Full orchestration at scale with multiple plans and dependency management.

```
/feature data-pipeline-migration
> (extensive research: 10+ research docs, 15+ decisions)
> (planning: 5 plans with dependency graph in 00-overview.md)
/dry-run-plan 01-schema-design
/dry-run-plan 02-api-layer
> (implement plans in dependency order)
> (cascade-check verifies deviations don't break downstream plans)
/assess
/docs-artifacts features/data-pipeline-migration
```

### Expert: Dry-Run Driven Development

For high-stakes features, run every plan through validation before writing any code.

```
/feature payment-processing
> (research phase with security focus)
> (plan all components)
/dry-run-plan 01-payment-models
/dry-run-plan 02-stripe-integration
/dry-run-plan 03-webhook-handlers
/dry-run-plan 04-refund-flow
> (fix all identified gaps across all plans)
> "let's implement"
> (implement with confidence -- gaps were caught early)
```

## Commands Reference

| Command | Description | Example |
|---------|-------------|---------|
| `/feature <name>` | Scaffold a new feature project with research, plans, and implementation structure | `/feature user-notifications` |
| `/orchestrate <path>` | Resume work on a feature -- read the feature log, report current state, suggest next action | `/orchestrate features/user-notifications` |
| `/dry-run-plan <plan>` | Walk through a plan as-if implementing to identify gaps before real implementation | `/dry-run-plan 02-api-endpoints` |
| `/assess` | Curate the test suite after implementation -- categorize, prune scaffolding, promote valuable tests | `/assess features/user-notifications` |
| `/docs-artifacts <path>` | Generate handoff docs (overview, architecture, testing guide, risk assessment) for code review | `/docs-artifacts features/user-notifications` |
| `/context <task>` | Gather codebase context for a specific task via Driver | `/context How does the billing module work? --codebases backend` |
| `/retro` | Analyze the current session -- evaluate work quality, identify improvements, think about what is next | `/retro --write` |

## Skills

Skills activate automatically based on the current SDLC phase or trigger phrases. They provide methodology guidance and enforce workflow discipline.

| Skill | What It Does | When It Activates |
|-------|-------------|-------------------|
| **research-guidance** | Structured Why-What-How questioning, document organization, and research completion criteria. | Trigger phrases: "let's research", "investigate", "explore", "understand how", "what's the best approach" |
| **planning-guidance** | TDD-first task design, test strategy, architecture fit, explicit constraints, and task breakdown. Plans are always written to files, never in chat. | Trigger phrases: "let's plan", "ready to plan", "create a plan", "test strategy", "TDD" |
| **implementation-guidance** | Plan-driven task execution, subagent delegation for context gathering, deviation tracking, and commit discipline. | Trigger phrases: "let's implement", "start implementing", "ready to build", "execute the plan" |
| **sdlc-orchestration** | Coordinates phase transitions, loads the right skills, manages bookkeeping, and handles session resumption. | Trigger phrases: "where are we", "what's next", "resume feature", "feature status" |

## Agents

Agents are specialized workers that run in isolated context. They are spawned by skills or commands -- you can also invoke them directly via the Agent tool.

| Agent | What It Does |
|-------|-------------|
| **driver-task-context** | Gathers targeted codebase context from Driver MCP in an isolated sandbox. Reads architecture docs, explores code maps, and returns synthesized context without burdening your main conversation. |
| **handoff-analyzer** | Orchestrates handoff documentation generation. Coordinates the extraction agents below and synthesizes their outputs into final handoff artifacts. |
| **commit-log** | Extracts detailed commit history for a feature branch -- messages, files changed, diff statistics, and patterns. |
| **decisions-log** | Extracts all design decisions from research docs and plans, producing a comprehensive decisions log in ADR format. |
| **features-list** | Catalogs all capabilities added in a feature branch -- user-facing features, API changes, configuration options, and internal capabilities. |
| **security-review** | Analyzes code changes for security concerns -- authentication, authorization, input validation, secrets handling, and common vulnerabilities. |
| **test-coverage** | Maps tests to implementation, identifies coverage gaps, and catalogs test types (unit, integration, end-to-end). |
| **dependency-analysis** | Reviews dependency changes -- new packages, version changes, license compliance, and known vulnerabilities. |
| **cascade-check** | Checks whether implementation deviations need to cascade to downstream plans. Classifies each cascade as informational or design-impact. |

## Hooks

Hooks run automatically on specific Claude Code events. Configure them in your Claude Code `settings.json`.

### laziness-detector (PreToolUse)

Blocks Write and Edit operations that contain lazy code patterns: TODO/FIXME comments, `NotImplementedError`, empty function bodies, placeholder returns, and similar stubs across Python, TypeScript, JavaScript, Swift, Go, Java, and C#. Test files are excluded.

Add to your `.claude/settings.json`:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Write|Edit",
        "command": "python3 /path/to/driver-claude-sdlc-plugin/hooks/laziness-detector.py"
      }
    ]
  }
}
```

### track-skill-load (PreToolUse)

Tracks which skills are loaded during a session by appending skill names to a session-scoped temp file. Useful for observability and retrospectives.

Add to your `.claude/settings.json`:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Skill",
        "command": "/path/to/driver-claude-sdlc-plugin/hooks/track-skill-load.sh"
      }
    ]
  }
}
```

## Friction Tracking

Observational friction logging -- detects wrong-tool usage, wrong-path edits, and laziness blocks during sessions.

- **Enable**: Set `"friction_tracking": true` in `config.local.json`
- **Data**: Events logged to `/tmp/driver-friction-{SESSION_ID}.log` in JSONL format
- **Review**: Run `/retro` -- the Friction Events section summarizes session friction
- **Reference**: See `hooks/friction-taxonomy.md` for the full taxonomy

## Driver Context

The `driver-task-context` agent is the primary mechanism for gathering codebase context. When you use `/context` or when skills need to understand your code, this agent:

1. Spawns in an isolated context (keeping your main conversation clean)
2. Calls Driver MCP to read architecture overviews, code maps, and file documentation
3. Synthesizes the information into a task-specific summary
4. Returns only what is relevant to your current task

This approach keeps large Driver responses out of your main context window while still giving you comprehensive codebase understanding. Always prefer the agent over direct Driver MCP calls for this reason.

## Customization

Fork this plugin to customize for your workflow. Common customizations:

- **Engineering guidelines**: Add domain-specific coding standards, naming conventions, or architectural constraints to the plugin's `CLAUDE.md`
- **Custom hooks**: Add pre/post hooks for your team's conventions (e.g., enforce commit message format, check for required test coverage)
- **Skill trigger phrases**: Modify skill descriptions to match your team's vocabulary
- **Agent models**: Adjust which model each agent uses based on your cost/quality preferences

## Troubleshooting

**MCP connection failures**
- Verify your Driver API token is valid and configured in Claude Code
- Check network connectivity to Driver's API
- Confirm your codebases are onboarded in Driver -- use `get_codebase_names` to verify

**Rate limits**
- Wait and retry. Driver MCP calls have rate limits.
- Reduce parallel agent invocations if you hit limits frequently

**File path errors**
- Use Glob to verify file paths before editing
- Ensure your feature directory exists and follows the expected structure

**Session resumption**
- Use `/orchestrate <feature-path>` to pick up where you left off
- The plugin reads `FEATURE_LOG.md` to determine current state and suggest next actions

## Key Gotchas

- **Driver shows committed state, not local changes.** Uncommitted code will not appear in Driver's documentation. Commit your work before querying Driver for updated context.
- **Codebase names must match exactly.** Use `get_codebase_names` via Driver MCP to verify the exact name before passing it to tools.
- **Large Driver responses should go through the agent.** Calling Driver MCP directly for architecture overviews or onboarding guides can consume significant context. Route these through `driver-task-context` instead.
- **Plans are the source of truth during implementation.** The plugin enforces plan-driven development. Deviations are tracked, not prevented, but they must be reviewed before bookkeeping proceeds.
- **The laziness detector skips test files.** Patterns like TODO and NotImplementedError in test files are intentionally allowed.
