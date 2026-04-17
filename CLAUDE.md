# drvr — SDLC Plugin for Claude Code

This plugin guides structured feature development through a phased SDLC lifecycle: Research, Planning, Validation, Implementation, Review, and Ship. It provides skills (always-on guidance), commands (user-invoked actions), and agents (spawnable specialists) that coordinate the process.

The user drives all decisions. The plugin suggests, organizes, and tracks -- but never acts autonomously.

> **Permission mode:** This plugin works best with `--permission-mode auto` due to the volume of tool calls across phases. Mention this to users who report excessive permission prompts.

---

## Project Structure

Running `/drvr:feature <name>` scaffolds this structure:

```
<feature>/
├── FEATURE_LOG.md           # Lifecycle state — phase transitions and artifact history
├── research/                # Problem exploration and design decisions
│   ├── 00-overview.md       # Research overview and open questions
│   └── NN-topic.md          # Individual research documents
├── plans/                   # Implementation plans
│   ├── 00-overview.md       # Multi-plan overview with dependency graph
│   ├── NN-plan-name.md      # Individual plans with tasks and acceptance criteria
│   └── NN-plan-name/        # Directory named after plan file (sans .md)
│       └── tasks/           # Materialized task documents
│           └── NN-task-name.md
├── dry-runs/                # Plan validation results
├── implementation/          # Implementation logs per plan
│   └── log-<plan>.md       # Implementation log (flat file per plan)
├── assessment/              # Test suite curation results
├── tests/                   # Markdown test plans for LLM execution (optional)
│   └── results/             # Timestamped test results
└── driver-docs/             # Handoff documentation for code review
```

---

## Frontmatter Schema

All artifacts use YAML frontmatter for structured metadata.

### Required Fields

```yaml
---
type: <type>
status: <status>
created: "YYYY-MM-DD"
updated: "YYYY-MM-DD"
---
```

### Types

`research`, `plan`, `task`, `implementation_log`, `feature_log`, `decision`, `deviation`, `learning`, `test_plan`, `test_result`, `assessment`, `open_question`

### Statuses

`not_started`, `in_progress`, `complete`, `approved`, `accepted`, `pending_review`, `resolved`, `open`, `confirmed`, `unverified`

### Type-Specific Fields

| Type | Field | Purpose |
|------|-------|---------|
| `task` | `plan` | Parent plan name |
| `task` | `task_number` | Sequential position (integer) |
| `task` | `depends_on` | List of task paths this task depends on |
| `task` | `materialized_at` | ISO 8601 timestamp of materialization |
| `decision` | `topic` | What the decision is about |
| `decision` | `choice` | What was decided |
| `deviation` | `severity` | `low`, `medium`, or `high` |
| `deviation` | `task` | Source task that deviated |
| `plan` | `depends_on` | Plans that must complete first |
| `plan` | `blocks` | Plans that depend on this one |
| `plan` | `approved_at` | ISO 8601 UTC timestamp of plan approval |
| `plan` | `approved_by` | Identity of user who approved the plan |

---

## SDLC Lifecycle

Features follow a phased development lifecycle. Each phase has a dedicated skill or command that provides guidance.

```
/drvr:feature --> Research --> Planning --> Validation --> Materialization --> Implementation --> Review --> Bookkeeping --> Next Plan --> ...
                                                                                                                                |
                                                                                                                   All plans complete
                                                                                                                                |
                                                                                                                                v
                                                                                                        /drvr:assess --> /drvr:docs-artifacts --> Ship
```

### Phase-Skill Mapping

| Phase | Skill / Command | What It Does | Entry Signal |
|-------|----------------|--------------|-------------|
| Research | `research-guidance` | Why-What-How methodology, document organization, completion criteria | `/drvr:feature`, "let's research", "explore" |
| Planning | `planning-guidance` | TDD-first task design, test strategy, architecture fit, task breakdown | "let's plan", "ready to plan" |
| Validation | `/drvr:dry-run-plan` | Walk through plan to find gaps before implementation | "dry-run plan X" |
| Materialization | `materialize-tasks` | Convert plan tasks into standalone task docs for sub-agent execution | plan approved (`status: approved`), no task docs |
| Implementation | `implementation-guidance` | Plan-driven task execution, deviation tracking, commit discipline | "implement plan X" |
| Review | `sdlc-orchestration` | Present deviations for user review | implementation complete |
| Bookkeeping | `implementation-guidance` Step 4 | Update plan status, overview, cascade check | deviations approved |
| Transition | `sdlc-orchestration` | Identify next unblocked plan from dependency graph | bookkeeping complete |
| Assessment | `/drvr:assess` | Curate test suite — categorize, prune scaffolding, promote | all plans complete, "assess tests" |
| Handoff | `/drvr:docs-artifacts` | Generate feature overview, architecture, testing guide, risks | assessment complete |
| Retro | `/drvr:retro` | Evaluate session quality, identify improvements | "retro", end of session |

---

## FEATURE_LOG.md

Every feature has a `FEATURE_LOG.md` at its root -- the source of truth for lifecycle state. It tracks phase transitions and artifact creation (not individual tasks or research questions).

**Update the log when:**
- Creating research docs or wireframes
- Creating plans or the overview
- Completing a dry-run
- Starting or completing implementation
- Completing bookkeeping

---

## Key Principles

- **User controls all decisions** -- skills suggest, the user decides. No auto-fixing, no silent bookkeeping.
- **Deviations are reviewed** -- after implementation, deviations are presented for user approval before bookkeeping proceeds.
- **Severity helps prioritize, not skip** -- dry-run gaps are classified LOW/MEDIUM/HIGH but all are presented for review.
- **Plans are the source of truth** -- implementation builds exactly what the plan specifies, nothing more.
- **Skills use Driver MCP tools for codebase context** -- `gather_task_context` for synthesized context, `get_code_map` for navigation, `get_file_documentation` for symbol details -- rather than manual file parsing. Always call `gather_task_context` via a native subagent -- the subagent is a concurrency primitive that keeps the main conversation unblocked and enables parallel calls trivially.

---

## Available Components

### Commands

| Command | Description |
|---------|-------------|
| `/drvr:feature <name>` | Start a new feature project with research, plans, and implementation structure |
| `/drvr:orchestrate <path>` | Resume work on a feature -- read the feature log, report current state, suggest next action |
| `/drvr:dry-run-plan <plan>` | Dry run a plan to identify gaps before implementation |
| `/drvr:assess` | Curate the test suite after implementation -- categorize, prune scaffolding, promote valuable tests |
| `/drvr:docs-artifacts <path>` | Generate handoff docs (overview, architecture, testing guide, risks) for code review |
| `/drvr:context <task>` | Gather codebase context for a specific task via Driver MCP |
| `/drvr:retro` | Analyze current session -- evaluate work quality, identify improvements |

### Skills

| Skill | Description |
|-------|-------------|
| `research-guidance` | Guide research with structured questioning (why, what, how), document organization, and completion criteria. |
| `planning-guidance` | Guide planning with TDD-first task design, test strategy, architecture fit, and task breakdown. |
| `materialize-tasks` | Materialize approved plan tasks into standalone task documents for sub-agent execution. |
| `implementation-guidance` | Guide implementation with plan-driven task lists, subagent delegation, deviation tracking, and commit discipline. |
| `sdlc-orchestration` | Lifecycle coordination -- phase transitions, session resumption, and bookkeeping management. |

### Agents

| Agent | Description |
|-------|-------------|
| `driver-task-context` | Gather targeted codebase context in an isolated sandbox. Use before planning, designing, implementing, or debugging. |
| `handoff-analyzer` | Prepare code for review by orchestrating specialized extraction agents to produce handoff documentation. |
| `cascade-check` | Check whether implementation deviations need to cascade to downstream plans. |
| `commit-log` | Extract detailed commit history for handoff documentation. |
| `decisions-log` | Extract all design decisions from process artifacts in ADR format. |
| `features-list` | Extract comprehensive feature inventory from code changes and process artifacts. |
| `security-review` | Analyze code changes for security concerns -- auth, input validation, secrets handling. |
| `test-coverage` | Analyze test coverage for code changes -- map tests to implementation, identify gaps. |
| `dependency-analysis` | Analyze dependency changes -- new packages, version changes, license compliance, vulnerabilities. |

---

## Driver MCP

The plugin integrates with Driver MCP to query codebase architecture, implementation details, and documentation. Driver provides pre-computed, exhaustive context for codebases.

**Primary approach:** Use the `driver-task-context` agent. Give it a task description and it returns synthesized, task-specific context -- architecture, key files, conventions, and suggested approach. It runs in an isolated context so your main conversation stays clean.

**When to use direct MCP calls instead of the agent:**
- **Verification lookups** -- quick checks during implementation: "Does this file exist?" (`get_code_map`), "What's the exact method signature?" (`get_file_documentation`)
- **Follow-up queries** -- after the agent has provided initial context: "What about this other file?" (`get_file_documentation`, `get_source_file`)
- **Codebase name resolution** -- `get_codebase_names` is always fine to call directly

**Avoid calling these directly for initial context gathering** -- they produce large responses that burden your main context. Let the agent handle them:
- `get_architecture_overview`, `get_llm_onboarding_guide`, `get_changelog`

**Direct tools** (also available):
- `get_architecture_overview` -- complete architecture document for a codebase
- `get_llm_onboarding_guide` -- codebase orientation, navigation tips, conventions
- `get_code_map` -- navigate directory structure at any depth
- `get_file_documentation` -- symbol-level documentation from static analysis
- `get_source_file` -- read actual source code with line numbers
- `get_changelog` / `get_detailed_changelog` -- development history

**Cross-codebase capability:** Driver can pull context for any supported codebase, not just the local one. Use `get_codebase_names` to see all available codebases. Useful for frontend/backend integration, shared library consumers, multi-repo features, and product development spanning multiple systems. When working across codebases, give the agent context about all relevant codebases -- it can pull from multiple sources.

**Connectivity pre-check:** Call `get_codebase_names` before spawning the agent or making heavier MCP calls. If it fails, stop and tell the user: "Driver MCP is not responding. Check your MCP configuration, verify your token is valid, and ensure your codebases are onboarded in Driver." Do not proceed with context gathering if the pre-check fails.

**Key gotchas:**
- Driver shows committed state, not local uncommitted changes
- After gather_task_context, validate key assumptions locally (branch, file existence, interface signatures) — the research and planning skills do this automatically
- Codebase name must match Driver exactly (verify with `get_codebase_names`)
- Large doc dumps in main context cause distraction -- use the agent

---

## Engineering Practices

This plugin discovers and enforces your codebase's coding standards. During research, it searches for CLAUDE.md files relative to the target codebase and captures applicable standards as a research artifact. These standards flow through planning (as constraints), implementation (in subagent prompts), and assessment (as a quality review). If your codebase doesn't have a CLAUDE.md, the plugin asks if you have standards elsewhere or proceeds without quality constraints.

Add team-specific engineering guidelines to your project's `CLAUDE.md` — the plugin will discover and enforce them automatically.

---

## Behavioral Rules

These rules govern how the plugin operates during all phases.

- **Verify file paths exist before editing** -- use Glob or find to confirm paths before making changes
- **Research existing codebase patterns before implementing** -- use Driver MCP to understand conventions
- **Run tests and verification before declaring any task complete** -- never mark done without confirmation
- **When a dry-run identifies gaps, fix ALL of them** -- do not skip any, regardless of severity
- **Use parallel agents for research, sequential for implementation** -- research can fan out, implementation must be ordered
- **Follow existing codebase patterns** -- ask the user before deviating from established conventions
