# Driver SDLC Plugin for Claude Code

This plugin guides structured feature development through a phased SDLC lifecycle: Research, Planning, Validation, Implementation, Review, and Ship. It provides skills (always-on guidance), commands (user-invoked actions), and agents (spawnable specialists) that coordinate the process.

The user drives all decisions. The plugin suggests, organizes, and tracks -- but never acts autonomously.

---

## Project Structure

Running `/feature <name>` scaffolds this structure:

```
<feature>/
├── FEATURE_LOG.md           # Lifecycle state — phase transitions and artifact history
├── research/                # Problem exploration and design decisions
│   ├── 00-overview.md       # Research overview and open questions
│   ├── decisions/           # Standalone decision files (d01-*.md, d02-*.md)
│   └── NN-topic.md          # Individual research documents
├── plans/                   # Implementation plans
│   ├── 00-overview.md       # Multi-plan overview with dependency graph
│   └── NN-plan-name.md      # Individual plans with tasks and acceptance criteria
├── dry-runs/                # Plan validation results
├── implementation/          # Implementation logs per plan
│   └── <plan-name>/
│       ├── log.md           # Implementation log
│       ├── deviations/      # What diverged from the plan and why
│       └── learnings/       # Discoveries during implementation
├── assessment/              # Test suite curation results
├── tests/                   # Markdown test plans for LLM execution (optional)
│   └── results/             # Timestamped test results
├── wireframes/              # Single-page HTML wireframes for UI research (optional)
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
| `task` | `depends_on` | List of task paths this task depends on |
| `decision` | `topic` | What the decision is about |
| `decision` | `choice` | What was decided |
| `deviation` | `severity` | `low`, `medium`, or `high` |
| `deviation` | `task` | Source task that deviated |
| `plan` | `depends_on` | Plans that must complete first |
| `plan` | `blocks` | Plans that depend on this one |

---

## SDLC Lifecycle

Features follow a phased development lifecycle. Each phase has a dedicated skill or command that provides guidance.

```
/feature --> Research --> Planning --> Validation --> Implementation --> Review --> Bookkeeping --> Next Plan --> ...
                                                                                                       |
                                                                                          All plans complete
                                                                                                       |
                                                                                                       v
                                                                                  /assess --> /docs-artifacts --> Ship
```

### Phase-Skill Mapping

| Phase | Skill / Command | What It Does |
|-------|----------------|--------------|
| Research | `research-guidance` | Why-What-How methodology, structured questioning, document organization |
| Planning | `planning-guidance` | TDD-first task design, test strategy, architecture fit, task breakdown |
| Validation | `/dry-run-plan` | Walk through plan as-if implementing, severity-classified gap analysis |
| Implementation | `implementation-guidance` | Plan-driven task execution, subagent delegation, deviation tracking |
| Review | `sdlc-orchestration` | Present deviations for user approval before bookkeeping |
| Bookkeeping | `implementation-guidance` Step 4 | Update plan status, overview, cascade check |
| Transition | `sdlc-orchestration` | Identify next unblocked plan from dependency graph |
| Assessment | `/assess` | Curate test suite -- categorize, prune scaffolding, promote valuable tests |
| Handoff | `/docs-artifacts` | Generate feature overview, architecture, testing guide, risk assessment |
| Retro | `/retro` | Evaluate session quality, recurring patterns, improvement ideas |

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
- **Skills use the Driver CLI for state queries** -- `driver project status`, `driver project query`, etc. -- rather than manual file parsing.

---

## Available Components

### Commands

| Command | Description |
|---------|-------------|
| `/feature <name>` | Start a new feature project with research, plans, and implementation structure |
| `/orchestrate <path>` | Resume work on a feature -- read the feature log, report current state, suggest next action |
| `/dry-run-plan <plan>` | Dry run a plan to identify gaps before implementation |
| `/assess` | Curate the test suite after implementation -- categorize, prune scaffolding, promote valuable tests |
| `/docs-artifacts <path>` | Generate handoff docs (overview, architecture, testing guide, risks) for code review |
| `/context <task>` | Gather codebase context for a specific task via Driver MCP |
| `/retro` | Analyze current session -- evaluate work quality, identify improvements |

### Skills

| Skill | Description |
|-------|-------------|
| `driver-context-layer` | Optimal source code context gathering via Driver MCP. Invoked automatically at session start or when starting a new major task. |
| `research-guidance` | Guide research with structured questioning (why, what, how), document organization, and completion criteria. |
| `planning-guidance` | Guide planning with TDD-first task design, test strategy, architecture fit, and task breakdown. |
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

**Direct tools** (also available):
- `get_architecture_overview` -- complete architecture document for a codebase
- `get_llm_onboarding_guide` -- codebase orientation, navigation tips, conventions
- `get_code_map` -- navigate directory structure at any depth
- `get_file_documentation` -- symbol-level documentation from static analysis
- `get_source_file` -- read actual source code with line numbers
- `get_changelog` / `get_detailed_changelog` -- development history

Use `get_codebase_names` to discover which codebases are available.

---

## Engineering Best Practices

These practices apply to all implementation work guided by this plugin.

### Self-Documenting Code
- Clarity of intent is paramount -- code should reveal its purpose through structure and naming
- Use descriptive function and variable names instead of verbose comments
- Break complex logic into small, well-named helper functions that express intent
- Comments should explain *why*, not *what* -- if the code is clear, no comment is needed
- Do not remove existing code comments unless they are factually incorrect

### Function Naming
- Use clear, action-oriented names (e.g., `fetch_nodes_with_descriptions`, `build_tree_from_nodes`)
- Private functions should start with underscore
- Names should describe what they do, not how they do it

### Avoid Code Smells
- Replace inline comments with well-named functions
- Avoid deeply nested logic -- extract to helper functions
- Keep functions small (typically under 10-15 lines)
- DRY -- extract duplicated logic into helper functions

### Error Handling
- try/except blocks should be as narrow as possible
- Use descriptive error messages
- Handle edge cases explicitly

---

## Behavioral Rules

These rules govern how the plugin operates during all phases.

- **Verify file paths exist before editing** -- use Glob or find to confirm paths before making changes
- **Research existing codebase patterns before implementing** -- use Driver MCP to understand conventions
- **Run tests and verification before declaring any task complete** -- never mark done without confirmation
- **When a dry-run identifies gaps, fix ALL of them** -- do not skip any, regardless of severity
- **Use parallel agents for research, sequential for implementation** -- research can fan out, implementation must be ordered
- **Follow existing codebase patterns** -- ask the user before deviating from established conventions
