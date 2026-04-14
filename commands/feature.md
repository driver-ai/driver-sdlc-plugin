---
description: Start a new feature project with research, plans, and implementation structure
argument-hint: <project-name> [--prd <path>]
allowed-tools: Read, Write, Edit, Bash, Glob
---

# /feature Command

Create a new feature project and kick off the research phase.

## Workflow

### Step 1: Parse Arguments

Extract project name from arguments. If not provided, ask for it.

**Optional:** Check for `--prd <path>` flag. If provided, this PRD will be included as context in the research overview.

### Step 2: Check Configuration

Look for `config.local.json` in the plugin directory (`~/.claude/plugins/local/driver-claude-plugin/` or the installed plugin location).

If `config.local.json` doesn't exist, create it by asking:
1. "Where should I create feature projects? (e.g., ~/driver-projects)"

Save the response to `config.local.json`:
```json
{
  "projects_path": "<user's answer>",
  "friction_tracking": false
}
```

> Optional. When `true`, hooks log friction events for `/retro` analysis.

### Step 3: Create Folder Structure

Create the following structure at `{projects_path}/features/<project-name>/`:

```
<project-name>/
├── FEATURE_LOG.md
├── research/
│   └── 00-overview.md
├── plans/
├── dry-runs/
├── implementation/
├── assessment/
└── tests/
    └── results/
```

Note: `wireframes/` is created on-demand during research when UI exploration is needed — not scaffolded upfront.

### Step 4: Create FEATURE_LOG.md

Create the feature log that tracks lifecycle state and artifact history:

```markdown
# Feature Log: <Project Name>

## Current State
**Phase**: Research
**Active**: Setting up — answer Setup Questions in `research/00-overview.md`
**Last updated**: <today's date>

## Log

| Date | Event | Artifact |
|------|-------|----------|
| <today> | Feature created | `FEATURE_LOG.md` |
| <today> | Research started | `research/00-overview.md` |
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

_What problem are we solving? For whom?_

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

## Setup Questions

Answer these before diving into research:

- [ ] Which codebases are involved? (Driver codebase names + local paths)
- [ ] Which branches should we work on?
- [ ] What problem are we solving? (1-2 sentences)

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
2. Tell the user: "Please answer the Setup Questions in `research/00-overview.md`. Once answered, we'll begin research using the `research-guidance` skill."
3. Note that `/orchestrate <feature-path>` can be used to resume this feature in future sessions

### Step 7: Begin Research

Once the user answers the Setup Questions (provides codebases, branch, and problem statement):

1. Update `research/00-overview.md` with their answers
2. **Invoke the `research-guidance` skill** to drive the research phase — do NOT use ad-hoc Explore agents or manual research
3. The research-guidance skill handles structured questioning (Why-What-How), context gathering via Driver MCP, and artifact organization

## Notes

- The `/feature` command only handles scaffolding
- Research methodology is handled by the `research-guidance` skill
- Deep codebase context is handled by `driver-task-context` agent
- `FEATURE_LOG.md` tracks lifecycle state — each skill updates it at transitions
- Resume with `/orchestrate <feature-path>` in future sessions
- Config is stored per-user in `config.local.json` (gitignored)
- Use `--prd <path>` to include a PRD from product planning as context

## PRD Handoff from Product Planning

If a PRD exists from prior product planning, it can be passed to `/feature`:

```bash
/feature analytics --prd path/to/prd-analytics.md
```

This creates the feature project with the PRD content summarized in the research overview, providing context from product planning to engineering research.
