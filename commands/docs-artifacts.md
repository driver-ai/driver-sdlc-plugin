---
description: Generate handoff docs (overview, architecture, testing guide, risks) from your feature's research, plans, and code changes. Use after implementation is complete, before opening a PR or requesting code review.
argument-hint: <process-artifacts-path> [codebase-paths...]
allowed-tools: Read, Write, Edit, Glob, Grep, Bash, Agent
---

# /docs-artifacts Command

Generate or update handoff documentation for the Handoff phase of the SDLC workflow.

## Artifacts Generated

| File | Purpose |
|------|---------|
| `driver-docs/feature-overview.md` | Entry point - what was built and why |
| `driver-docs/architecture.md` | Technical design and decisions (ADR-style) |
| `driver-docs/testing-guide.md` | QA verification steps |
| `driver-docs/risk-assessment.md` | Dependencies, security, complexity concerns |

## Workflow

### Step 1: Parse Arguments

Extract from arguments:
- **Process artifacts path** (required) — Path to feature folder with research/, plans/
- **Codebase paths** (optional) — Paths to codebases; if not provided, use current directory

Example invocations:
```
/docs-artifacts ./features/oauth-support ~/work/driver/python-backend ~/work/driver/webapp-frontend
/docs-artifacts ./features/search-improvements
```

### Step 2: Check Prerequisites

1. Verify process artifacts path exists and contains research/ or plans/
2. Verify each codebase path is a git repository
3. Check that Driver MCP is available (required)
4. Detect if `driver-docs/` folder exists in the feature folder (determines create vs update mode)

If Driver MCP is unavailable:
```
Error: Driver MCP is required for /docs-artifacts.
Please ensure Driver MCP server is running.
```

### Step 3: Determine Mode

| Condition | Mode |
|-----------|------|
| No `driver-docs/` folder in feature | **Create** - Generate all artifacts from scratch |
| `driver-docs/` exists in feature | **Update** - Diff-based update of changed sections |

### Step 3.5: Resolve Driver Codebase Names

Before spawning the analyzer, resolve Driver codebase names so the analyzer can use Driver MCP tools:

1. Read `research/00-overview.md` from the feature's process artifacts
2. Find the Codebases table and extract the "Driver Name" column values
3. If no Codebases table exists, check `FEATURE_LOG.md` or ask the user for Driver codebase names

### Step 4: Spawn Handoff Analyzer Agent

Use the Agent tool to spawn the `handoff-analyzer` agent:

```
Prepare handoff documentation:
- Process artifacts: {process_artifacts_path}
- Codebases:
  - {codebase_path_1}
  - {codebase_path_2}
- Driver codebase names: {driver_name_1}, {driver_name_2}
- Mode: {create|update}
```

The analyzer will:
- Read process artifacts for intent, decisions, scope
- Gather git context per codebase (branch, commits, changed files)
- Query Driver MCP for architecture and patterns
- Return structured content for each artifact

### Step 5: Write Artifacts

Using the analyzer's output, write each artifact to the feature's `driver-docs/` folder:

**For Create mode:**
- Create `driver-docs/` folder
- Write all 4 artifact files using the structured content

**For Update mode:**
- Read existing artifacts
- Compare analyzer output to existing content
- Update sections that have changed
- Preserve manually-added content where possible
- Update "Last Updated" timestamp

### Step 6: Confirm Completion

Report what was created/updated:

```
Created driver-docs/ in features/oauth-support/:
- feature-overview.md
- architecture.md
- testing-guide.md
- risk-assessment.md

Sources:
- Process artifacts: features/oauth-support/research/, plans/
- Codebases: python-backend (feature/oauth), webapp-frontend (feature/oauth)
- Files analyzed: 23 changed files across 8 commits
```

Or for updates:
```
Updated driver-docs/ in features/oauth-support/:
- architecture.md: Updated Components, Design Decisions sections
- risk-assessment.md: Added new dependency (zod)
- feature-overview.md: No changes needed
- testing-guide.md: No changes needed
```

## Artifact Templates

### feature-overview.md

```markdown
# Feature: {Feature Name}

> Last Updated: {date}

## Summary

{2-3 sentence description}

## Problem

{What problem this solves, for whom}

## What Changed

- {User-facing change 1}
- {User-facing change 2}

## Key Files

| File | Purpose |
|------|---------|
| `{path}` | {description} |

## Related

- [Architecture](./architecture.md)
- [Testing Guide](./testing-guide.md)
- [Risk Assessment](./risk-assessment.md)
- [PR #{number}]({link})
```

### architecture.md

```markdown
# Architecture: {Feature Name}

> Last Updated: {date}

## Overview

{Brief technical summary}

## Components

### {Component Name}

- **Location**: `{path}`
- **Responsibility**: {what it does}
- **Key Files**: {list}

## Design Decisions

### Decision: {Topic}

- **Context**: {What prompted this decision}
- **Decision**: {What we chose}
- **Rationale**: {Why}
- **Alternatives**: {What we didn't choose and why}

## Data Flow

{Description or diagram of how data moves}

## Patterns

- **Follows**: {existing patterns used}
- **Introduced**: {new patterns, if any}

## Integration Points

- {System}: {how it connects}
```

### testing-guide.md

```markdown
# Testing Guide: {Feature Name}

> Last Updated: {date}

## Prerequisites

- [ ] {Environment requirement}
- [ ] {Test data requirement}
- [ ] {Account/role requirement}

## Test Scenarios

### Scenario: {Happy Path Name}

**Steps**:
1. {Step 1}
2. {Step 2}
3. {Step 3}

**Expected Result**: {What should happen}

### Scenario: {Error Case Name}

**Steps**:
1. {Step 1}

**Expected Result**: {Error behavior}

## Edge Cases

- [ ] **{Edge case}**: {How to test} → {Expected result}

## Known Limitations

- **{Limitation}**: {Reason, planned fix if any}
```

### risk-assessment.md

```markdown
# Risk Assessment: {Feature Name}

> Last Updated: {date}

## Summary

| Risk Area | Level | Notes |
|-----------|-------|-------|
| Dependencies | {Low/Medium/High} | {note} |
| Security | {Low/Medium/High} | {note} |
| Performance | {Low/Medium/High} | {note} |
| Breaking Changes | {Low/Medium/High} | {note} |

## New Dependencies

| Package | Purpose | License | Weekly Downloads | Notes |
|---------|---------|---------|------------------|-------|
| `{package}` | {why} | {license} | {downloads} | {concerns} |

## Security Considerations

- [ ] **{Concern}**: {Description, mitigation}

## Performance Impact

- **{Area}**: {Details}

## Breaking Changes

- **{Change}**: {Migration path, timeline}

## Complexity Hotspots

| File | Changes | Notes |
|------|---------|-------|
| `{path}` | +{lines} | {why notable} |

## Downstream Impacts

- **{System/Feature}**: {How affected}
```

## Notes

- All artifacts include "Last Updated" timestamp
- Feature Overview links to other artifacts for navigation
- Risk Assessment uses Low/Medium/High levels for quick scanning
- Architecture uses ADR (Architecture Decision Record) format for decisions
- Testing Guide is QA-focused with step-by-step verification
