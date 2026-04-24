---
description: Start a new feature project with research, plans, and implementation structure
argument-hint: <project-name> [--prd <path>] [--brief <path>]
allowed-tools: Read, Write, Edit, Bash, Glob
---

# /drvr:feature Command

Create a new feature project with research, plans, and implementation structure.

## Workflow

### Step 1: Parse Arguments

Extract project name from arguments. If not provided, ask for it.

**Optional flags:**
- `--prd <path>` — PRD from product planning, included as context in the research overview.
- `--brief <path>` — Author's pre-written brief or detailed ticket. Captured in FEATURE_LOG; `intent-guidance` Step 1 reads it as the conversational starting point. If the path is supplied but the file doesn't exist, WARN and proceed without it.

### Step 2: Check Configuration

Read `~/.driver/config.json` and use the `projects_path` value to determine where feature projects are created.

If `~/.driver/config.json` doesn't exist or doesn't have a `projects_path`:
> "No projects directory is configured. Run `/drvr:setup` first to set up your projects directory."

Stop here — do not create config or ask for the path. `/drvr:setup` owns that configuration.

### Step 3: Create Folder Structure

Create the following structure at `{projects_path}/features/<project-name>/`:

```
<project-name>/
├── FEATURE_LOG.md
├── research/
│   ├── 00-intent.md
│   └── 00-overview.md
├── plans/
├── dry-runs/
├── implementation/
├── assessment/
└── tests/
    └── results/
```

**Scaffold `research/00-intent.md`** using this template (skip if file already exists with `status: confirmed`):

```markdown
---
type: research
status: in_progress
created: "<today's date>"
updated: "<today's date>"
---

# Intent: <Project Name>

## Status

**Phase**: Intent
**Last Updated**: <today's date>

## Starting Materials

- Brief: <path from --brief, or "none">
- PRD: <path from --prd, or "none">

## Why Now

_What triggered this feature? What happens if we don't solve it? — fill in during intent mining_

## The Problem

_What problem are we solving? Who experiences it? What does the bad path look like today? — fill in during intent mining_

## Desired End State

_What does "done" look like? — fill in during intent mining_

## Author's Domain Context

_Domain knowledge: mental model of the system, intuition on approach, likely gotchas, unwritten rules, how users actually use it, broader vision. Problem history: prior attempts, incidents, adjacent features, undocumented context, code already examined. Don't self-censor. — fill in during intent mining_

## Non-Negotiables

_What must be true of the solution? What should definitely NOT happen? — fill in during intent mining_

## Constraints

_Timeline, compatibility, performance, team — fill in during intent mining_

## What's Been Ruled Out

_Approaches already considered and rejected, with reasoning — fill in during intent mining_

## Definition of Done

_How will we know the feature is shipped? Acceptance bar? — fill in during intent mining_

## Decisions Captured During Intent

| Decision | Choice | Rationale |
|----------|--------|-----------|
| _none yet_ | | |

## References

- _tickets, Slack threads, prior features, PRDs — fill in during intent mining_

## Raw Author Notes

_Verbatim capture of the author's thinking — filled in during intent mining_

## Exit Criteria

- [ ] Problem, why-now, and desired end state are clear
- [ ] Author's key context and constraints are captured
- [ ] Anything already ruled out is documented (prevents re-litigation)
```

Note: `wireframes/` is created on-demand during research when UI exploration is needed — not scaffolded upfront.

### Step 4: Create FEATURE_LOG.md

Create the feature log that tracks lifecycle state and artifact history:

```markdown
# Feature Log: <Project Name>

## Current State
**Phase**: Intent
**Active**: Capture intent — say "capture intent" to activate `intent-guidance`
**Last updated**: <today's date>

## Log

| Date | Event | Artifact |
|------|-------|----------|
| <today> | Feature created | `FEATURE_LOG.md` |
| <today> | Intent started | `research/00-intent.md` |
```

### Step 5: Create research/00-overview.md

Create the research overview. If `--prd <path>` was provided, include a PRD Reference section.

```markdown
# <Project Name>

## Status

**Phase**: Research
**Last Updated**: <today's date>

---

## PRD Reference

_Only include this section if --prd flag was provided_

**Source PRD:** `<path from --prd flag>`

_Read the PRD and summarize the key requirements here._

---

## Problem Statement

_See `research/00-intent.md` for full problem framing and author's domain context._

---

## Scope

**In Scope:**
- _TBD_

**Out of Scope:**
- _TBD_

---

## Codebases

| Name | Local Path | Driver Name | Branch |
|------|------------|-------------|--------|
| _TBD_ | _TBD_ | _TBD_ | _TBD_ |

---

## Research Documents

| Document | Contents |
|----------|----------|
| _None yet_ | |

---

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| _None yet_ | | |
```

### Step 6: Confirm and Guide

After creating the structure:

1. Confirm what was created
2. Tell the user: "Next: capture intent. Say 'capture intent' to activate `intent-guidance`,
   or invoke `/drvr:feature <name> --brief <path>` if you have a pre-written brief or detailed
   ticket. When substantive external content exists, intent-guidance takes a lighter path —
   it mines the content, presents what it captured, and asks if there's anything to add. Intent
   produces `research/00-intent.md` and gates entry into research."
3. Note that `/drvr:orchestrate <feature-path>` can be used to resume this feature in future sessions

## Notes

- The `/drvr:feature` command only handles scaffolding
- Research methodology is handled by the `research-guidance` skill
- Deep codebase context is handled by `driver-task-context` agent
- `FEATURE_LOG.md` tracks lifecycle state — each skill updates it at transitions
- Resume with `/drvr:orchestrate <feature-path>` in future sessions
- Config is stored per-user in `~/.driver/config.json`
- Use `--prd <path>` to include a PRD from product planning as context
- Use `--brief <path>` to pass a pre-written brief or detailed ticket for intent mining

## PRD Handoff from Product Planning

If a PRD exists from prior product planning, it can be passed to `/drvr:feature`:

```bash
/drvr:feature analytics --prd path/to/prd-analytics.md
```

This creates the feature project with the PRD content summarized in the research overview, providing context from product planning to engineering research.
