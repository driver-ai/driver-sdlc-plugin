---
description: Generate per-plan handoff docs (overview, architecture, testing guide, risks) for the PR body of a single plan. Runs after `/drvr:assess <plan>` and before `/drvr:open-pr <plan>`.
argument-hint: <plan-name> [process-artifacts-path] [codebase-paths...]
allowed-tools: Read, Write, Edit, Glob, Grep, Bash, Agent
---

# /drvr:docs-artifacts Command

Generate or update **per-plan** handoff documentation. Each plan ships as its own PR, with a self-contained PR body sourced from `driver-docs/<plan>/`. A reviewer who hasn't seen the rest of the stack should be able to understand what changed, why, how to verify it, and where this PR sits in the stack — all from this plan's docs.

This is the second step in the per-plan PR gate: `/drvr:assess <plan>` → **`/drvr:docs-artifacts <plan>`** → `/drvr:open-pr <plan>`.

## Artifacts Generated

| File | Purpose |
|------|---------|
| `driver-docs/<plan>/feature-overview.md` | PR body summary — what was built in THIS plan and why; includes stack context |
| `driver-docs/<plan>/architecture.md` | Technical design and decisions for this plan (ADR-style) |
| `driver-docs/<plan>/testing-guide.md` | QA verification steps for this plan |
| `driver-docs/<plan>/risk-assessment.md` | Dependencies, security, complexity concerns specific to this plan |

Additionally, the cross-plan rollup at `driver-docs/00-feature-overview.md` is updated to reflect this plan's status (created on first run, updated subsequently).

## Workflow

### Step 1: Parse Arguments and Resolve Plan

1. **Plan name** (required) — the plan to generate docs for. If not provided, scan `plans/00-overview.md` for the lowest-numbered plan with status COMPLETE that has a per-plan assessment artifact (`assessment/<plan>-test-curation.md`) but no `driver-docs/<plan>/` directory. Tell the user: "No plan specified — defaulting to `<plan>` (next plan needing handoff docs)."
2. **Process artifacts path** (optional) — Path to feature folder with research/, plans/. Default: cwd or detected feature root.
3. **Codebase paths** (optional) — Paths to codebases; if not provided, use current directory or codebase paths from research Codebases table.

Example invocations:
```
/drvr:docs-artifacts 01-token-store
/drvr:docs-artifacts 02-refresh-flow ./features/oauth-support
/drvr:docs-artifacts 01-foo ./features/oauth-support ~/work/driver/python-backend
```

### Step 2: Check Prerequisites (Per-Plan Gate)

1. Verify process artifacts path exists and contains plans/
2. Verify the target plan file exists: `plans/<plan>.md` (status: COMPLETE)
3. Verify each codebase path is a git repository
4. Check that Driver MCP is available (required)
5. **Per-plan assessment check** — BLOCK if `assessment/<plan>-test-curation.md` does not exist. "Per-plan assessment for `<plan>` has not been completed. Run `/drvr:assess <plan>` first — handoff docs depend on a curated test suite."
6. **Plan status check** — Read `plans/<plan>.md` frontmatter. BLOCK if `status` is not `complete` (or the plan's section in `plans/00-overview.md` is not COMPLETE). "Plan `<plan>` is not marked complete. Complete implementation + bookkeeping, then assess, before generating handoff docs."
7. Detect if `driver-docs/<plan>/` directory exists (determines create vs update mode)

If Driver MCP is unavailable:
```
Error: Driver MCP is required for /drvr:docs-artifacts.
Please ensure Driver MCP server is running.
```

### Step 3: Determine Mode

| Condition | Mode |
|-----------|------|
| No `driver-docs/<plan>/` folder | **Create** - Generate all per-plan artifacts from scratch |
| `driver-docs/<plan>/` exists | **Update** - Diff-based update of changed sections (e.g., after PR revision) |

### Step 3.5: Resolve Driver Codebase Names

Before spawning the analyzer, resolve Driver codebase names so the analyzer can use Driver MCP tools:

1. Read `research/00-overview.md` from the feature's process artifacts
2. Find the Codebases table and extract the "Driver Name" column values
3. If no Codebases table exists, check `FEATURE_LOG.md` or ask the user for Driver codebase names

### Step 4: Spawn Handoff Analyzer Agent (Per-Plan Scope)

Use the Agent tool to spawn the `handoff-analyzer` agent, scoped to THIS plan:

```
Prepare per-plan handoff documentation:
- Plan: {plan-name}
- Plan file: {process_artifacts_path}/plans/{plan-name}.md
- Implementation log: {process_artifacts_path}/implementation/log-{plan-name}.md
- Per-plan assessment: {process_artifacts_path}/assessment/{plan-name}-test-curation.md
- Process artifacts (read-only context): {process_artifacts_path}/research/, plans/00-overview.md, DECISIONS.md
- Codebases:
  - {codebase_path_1}
  - {codebase_path_2}
- Driver codebase names: {driver_name_1}, {driver_name_2}
- Plan Environment (from plans/{plan-name}.md):
  - Base Branch: {base_branch}
  - Feature Branch: {feature_branch}
- Mode: {create|update}
```

The analyzer must:
- Scope all analysis to changes between Base Branch and Feature Branch — `git diff Base Branch...Feature Branch` (or HEAD if Feature Branch checked out)
- Read this plan's `## Context`, `## Architecture Fit`, `## Data Structures & Callables`, `## Test Strategy` as primary sources
- Read implementation log for actual deviations/decisions for this plan
- Read research artifacts and DECISIONS.md for upstream context (cross-plan motivation, prior decisions)
- Read `plans/00-overview.md` for stack position (this plan's row in PR Stack, prior/next plan names)
- Query Driver MCP for architecture and patterns relevant to changed files only
- Return structured content where each artifact's "feature-overview.md" includes a self-contained PR body — feature context, this plan's purpose, stack position, and links to upstream/downstream plans

### Step 5: Write Per-Plan Artifacts

Using the analyzer's output, write each artifact to `driver-docs/<plan>/`:

**For Create mode:**
- Create `driver-docs/<plan>/` folder
- Write all 4 artifact files using the structured content
- Update or create `driver-docs/00-feature-overview.md` cross-plan rollup (add this plan's row to the PR/plan list)

**For Update mode:**
- Read existing per-plan artifacts
- Compare analyzer output to existing content
- Update sections that have changed
- Preserve manually-added content where possible
- Update "Last Updated" timestamp
- Update the cross-plan rollup to reflect any status changes

### Step 6: Confirm Completion and Surface Next Gate Step

Report what was created/updated:

```
Created driver-docs/01-token-store/ in features/oauth-support/:
- feature-overview.md (PR body — self-contained with stack context)
- architecture.md
- testing-guide.md
- risk-assessment.md
Updated driver-docs/00-feature-overview.md (cross-plan rollup)

Sources:
- Plan: plans/01-token-store.md
- Implementation log: implementation/log-01-token-store.md
- Per-plan assessment: assessment/01-token-store-test-curation.md
- Diff scope: amark/oauth/01-token-store ← main (Base Branch)
- Files analyzed: 7 changed files across 4 commits
```

Or for updates:
```
Updated driver-docs/01-token-store/ in features/oauth-support/:
- architecture.md: Updated Components, Design Decisions sections
- risk-assessment.md: Added new dependency (zod)
- feature-overview.md: No changes needed
- testing-guide.md: No changes needed
```

Update `FEATURE_LOG.md` with the per-plan event:
`| <date> | Handoff docs generated for plan <plan> (handoff_docs_<plan>) | driver-docs/<plan>/ |`

Commit the handoff documentation:

```
git add driver-docs/<plan>/ driver-docs/00-feature-overview.md FEATURE_LOG.md && git commit -m "chore: Handoff docs for plan <plan>"
```

**Surface the next gate step explicitly:**

> "Plan `<plan>` handoff docs ready at `driver-docs/<plan>/`. Final gate step: `/drvr:open-pr <plan>` — this will push Feature Branch `<feature_branch>` and open a PR targeting `<base_branch>`."

## Artifact Templates (Per-Plan)

Each plan's docs must be **self-contained** — a reviewer who hasn't read other PRs in the feature should be able to evaluate this PR. Include feature context, plan purpose, and stack position in every per-plan `feature-overview.md`.

### `driver-docs/<plan>/feature-overview.md` (becomes the PR body)

```markdown
# {Plan Name} — Part of {Feature Name}

> Plan: `{plan}` · Last Updated: {date}

## Stack Position

- **Base branch**: `{base_branch}` (this PR targets `{base_branch}`)
- **Feature branch**: `{feature_branch}` (this PR's head)
- **Depends on**: {list of upstream plans by name + PR link if known, or "none — this PR is independent against the feature parent"}
- **Enables**: {list of downstream plans by name that will stack on this PR, or "—"}
- **Cross-plan rollup**: [driver-docs/00-feature-overview.md](../00-feature-overview.md)

## Feature Context (1–2 paragraphs)

_What the overall {Feature Name} feature is solving. Why it exists. Carry just enough context that a reviewer who's never seen this feature can evaluate this PR. Pulled from research/00-intent.md and DECISIONS.md, summarized._

## What This Plan Delivers

{2–3 sentence description scoped to THIS plan — not the whole feature}

## What Changed in This PR

- {User-facing or system-facing change 1 — specific to this plan}
- {Change 2}

## Key Files in This PR

| File | Purpose |
|------|---------|
| `{path}` | {description} |

_Only files modified by this plan's commits (`git diff {base_branch}...{feature_branch}`). Files touched by upstream plans appear in their PR, not this one._

## How to Verify

- See [Testing Guide](./testing-guide.md)
- Plan acceptance criteria: {N criteria, all met — see `plans/{plan}.md` `## Acceptance Criteria`}

## Related

- [Architecture](./architecture.md)
- [Testing Guide](./testing-guide.md)
- [Risk Assessment](./risk-assessment.md)
- [Cross-plan overview](../00-feature-overview.md)
- Upstream PRs: {list with #N links, or "—"}
- Downstream plans (not yet PR'd): {list of plan names, or "—"}
```

### `driver-docs/<plan>/architecture.md`

```markdown
# Architecture: {Plan Name}

> Plan: `{plan}` · Last Updated: {date}

## Overview

{Brief technical summary scoped to this plan's changes}

## Functional Core, Imperative Shell

This feature was designed around the plugin's functional-core / imperative-shell commitment (see plugin CLAUDE.md). Reviewers should verify the boundary is intact in the diff.

**Pure core** (no I/O, no time, no randomness, no mutable shared state — values in, values out):

| Item | File | Purpose | Tested by |
|------|------|---------|-----------|
| `{function or type}` | `{path}` | {one-line} | `{test file/name}` (values in / values out, no mocks) |

**Imperative shell** (performs I/O, calls into the core):

| Item | File | I/O performed | Tested by |
|------|------|---------------|-----------|
| `{entry point}` | `{path}` | {HTTP / DB / filesystem / time / random / etc.} | `{integration test file/name}` (real I/O) |

**Mocks used in tests, with justification**: {list every mock, with the hard-external-boundary justification — third-party API without sandbox, cost-bearing service, hardware absent in test. If no mocks: "None."}

**Architecture follow-ups identified during assessment**: {if any §FCIS findings were left as follow-up work rather than fixed before merge, list them with proposed extraction. If none: "None."}

## Components Touched

### {Component Name}

- **Location**: `{path}`
- **Responsibility**: {what it does}
- **Change in this plan**: {added/modified/removed}
- **Key Files**: {list}

## Design Decisions (This Plan)

### Decision: {Topic}

- **Context**: {What prompted this decision in the scope of this plan}
- **Decision**: {What was chosen}
- **Rationale**: {Why}
- **Alternatives**: {What was rejected and why}

_Pull from `plans/{plan}.md` and `DECISIONS.md` entries with `**Phase**: Planning` or `**Phase**: Implementation` referencing this plan._

## Data Flow

{Description of how data moves through the changes in this PR}

## Patterns

- **Follows**: {existing patterns matched in this plan}
- **Introduces**: {new patterns added in this plan, if any}
- **Deviates from**: {precedents intentionally not followed; cite reason}

## Integration Points

- {System}: {how the changes in this PR interact}

## Interfaces Affecting Downstream Plans

_For features with downstream plans that depend on this one — what interfaces does this PR expose that the next plans build against? Pull from `plans/00-overview.md` `## Interface Contracts Between Plans`._
```

### `driver-docs/<plan>/testing-guide.md`

```markdown
# Testing Guide: {Plan Name}

> Plan: `{plan}` · Last Updated: {date}

## Prerequisites

- [ ] {Environment requirement}
- [ ] {Test data requirement}
- [ ] {Account/role requirement}
- [ ] Checked out branch `{feature_branch}` (this PR's head)

## Automated Tests

- Test command: `{test_command from plan Environment}`
- Tests added in this plan: {N tests across M files — link to per-plan assessment artifact for curation details}
- Run: `{test_command}` — all should pass

## Manual Test Scenarios

### Scenario: {Happy Path}

**Steps**:
1. {Step 1}
2. {Step 2}

**Expected Result**: {What should happen}

### Scenario: {Error Case}

**Steps**:
1. {Step 1}

**Expected Result**: {Error behavior}

## Edge Cases

- [ ] **{Edge case}**: {How to test} → {Expected result}

## What This Guide Does NOT Cover

_Scenarios that belong to upstream PRs (already verified there) or downstream plans (not yet shipped). Naming them helps the reviewer know where verification responsibility lies._

## Known Limitations

- **{Limitation}**: {Reason, follow-up plan if any}
```

### `driver-docs/<plan>/risk-assessment.md`

```markdown
# Risk Assessment: {Plan Name}

> Plan: `{plan}` · Last Updated: {date}

## Summary

| Risk Area | Level | Notes |
|-----------|-------|-------|
| Dependencies | {Low/Medium/High} | {note} |
| Security | {Low/Medium/High} | {note} |
| Performance | {Low/Medium/High} | {note} |
| Breaking Changes | {Low/Medium/High} | {note} |
| Stack Risk | {Low/Medium/High} | {risk of merging out of order, rebase cost if upstream changes} |

## New Dependencies (Introduced by THIS Plan)

| Package | Purpose | License | Weekly Downloads | Notes |
|---------|---------|---------|------------------|-------|
| `{package}` | {why} | {license} | {downloads} | {concerns} |

_Dependencies introduced by upstream PRs are documented in their risk-assessment.md — not duplicated here._

## Security Considerations

- [ ] **{Concern}**: {Description, mitigation}

## Performance Impact

- **{Area}**: {Details}

## Breaking Changes

- **{Change}**: {Migration path, timeline, blast radius}

## Complexity Hotspots

| File | Changes | Notes |
|------|---------|-------|
| `{path}` | +{lines} | {why notable} |

## Downstream Impacts (Within This Feature)

- **{Plan Y}**: {How a change here would ripple — if Plan Y is stacked on this PR}

## Downstream Impacts (Outside This Feature)

- **{System/Feature}**: {How affected}
```

### `driver-docs/00-feature-overview.md` (Cross-Plan Rollup)

```markdown
# Feature: {Feature Name} — Cross-Plan Overview

> Last Updated: {date}

## Summary

{2–3 sentence description of the feature as a whole}

## PR Stack

| Plan | depends_on | Base Branch | PR | Status |
|------|------------|-------------|-----|--------|
| 01 <name> | — | `<feature parent>` | #N | Merged |
| 02 <name> | [01] | `<prefix>/01-<slug>` | #M | Open |
| 03 <name> | — | `<feature parent>` | — | Pending |

## Per-Plan Docs

- [Plan 01 — {name}](./01-{slug}/feature-overview.md)
- [Plan 02 — {name}](./02-{slug}/feature-overview.md)
- ...

## Why This Feature

_Pulled from `research/00-intent.md`. The single source for "why are we building this" that all plan PRs link back to._

## Decisions Log

_Pointer to `DECISIONS.md` — append-only decisions made across the feature._
```

## Notes

- All artifacts include "Last Updated" timestamp and `Plan: {plan}` so they're attributable
- Per-plan `feature-overview.md` becomes the PR body — it MUST be self-contained for a reviewer who hasn't read other PRs
- Stack Position section is mandatory in every per-plan `feature-overview.md`
- Diff scope is always per-plan: `{base_branch}...{feature_branch}`. Don't include files touched only by upstream PRs.
- Risk Assessment levels (Low/Medium/High) are for quick scanning
- Architecture uses ADR (Architecture Decision Record) format for decisions
- Testing Guide is QA-focused, step-by-step, and names which scenarios belong to upstream/downstream PRs
- The cross-plan rollup `driver-docs/00-feature-overview.md` is the single feature-wide narrative, linked from every PR body
