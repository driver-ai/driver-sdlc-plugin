---
description: Dry run a plan to identify gaps before implementation
argument-hint: "[plan-name]"
allowed-tools: Read, Write, Edit, Glob, Grep, Agent
---

# /drvr:dry-run-plan Command

Walk through a plan as if implementing it to identify gaps, missing context, and potential issues before actual implementation begins.

## Workflow

### Step 1: Locate the Plan

Find the plan file based on the argument:
- If `<plan-name>` provided: Look for `plans/<plan-name>.md` or `plans/*<plan-name>*.md`
- If no argument: Run **multi-plan mode** — validate all plans in parallel:
  1. Glob for all `plans/*.md` excluding `00-overview.md`
  2. If no plans found: `> "No plans found to validate."` and exit
  3. If only one plan found: run it directly in single-plan mode (no subagent overhead)
  4. For multiple plans: spawn one subagent per plan (using `Agent` tool). Each subagent's prompt must embed the full dry-run procedure:
     > "Read plan X at `plans/X.md`. Walk through each task checking: Files, Patterns, Tests, Dependencies, Edge cases, Context, Env vars, Dependency paths, File conventions, CLI compatibility, Platform. Classify gaps as LOW/MEDIUM/HIGH. Write results to `dry-runs/X-<date>.md` using the standard dry-run template."
  5. Each subagent writes its own `dry-runs/<plan-name>-<date>.md` result
  6. If a subagent fails (e.g., plan file is malformed), continue with remaining plans and report the failure in the convergence manifest
  7. `> "Found N plans (excluding overview). Running dry-run validation on all plans in parallel..."`
  8. After all subagents complete, proceed to Step 6 (Convergence Manifest)

### Step 2: Read the Plan

Read the full plan document and identify:
- All tasks in the Task Breakdown section
- Acceptance criteria
- Constraints
- Test strategy

### Step 3: Dry Run Each Task

For each task in the plan, walk through it as if implementing:

1. **Files**: Do I know exactly which files to create/modify?
2. **Patterns**: Do I understand the existing patterns to follow?
3. **Tests**: Are the test cases specific enough to write?
4. **Dependencies**: Are there hidden dependencies on other tasks?
5. **Edge cases**: What could go wrong that isn't covered?
6. **Context**: Is any context missing that I'd need during implementation?
7. **Env vars**: Are there environment variables that must be set? Will they persist across shell sessions?
8. **Dependency paths**: Do file paths and import references use correct extensions and conventions?
9. **File conventions**: Do new file names follow the project's naming conventions?
10. **CLI compatibility**: Do referenced CLI commands and flags exist in the expected versions?
11. **Platform**: Are there platform-specific assumptions (e.g., bash version, OS utilities)?
12. **Standards**: If a codebase standards artifact exists (search the feature's `research/` directory for a file containing `## Standards Source`), do the plan's constraints cover the applicable standards for this task's files? Match the artifact's Applicable Sections against the task's file paths. (Check once per unique file-type group — if multiple tasks touch the same language/framework, check once and reference that finding for the others.)
13. **Concreteness**: Does the plan have a `## Data Structures & Callables` section? If present, does each rollup row have a corresponding inline snippet in its Owning Task? For modified items, do the snippet signatures match the current codebase (use `get_file_documentation` for verification)? For plans with minimal code surface or that predate this rule (no section at all), downgrade to MEDIUM and note the reason.

Classify each gap found using the severity criteria below.

### Step 4: Check Architecture Fit

If the plan modifies source code or references codebase patterns, spawn the `driver-task-context` agent to verify accuracy:

```
Dry running a plan for <feature>. Need to verify:
- Do the referenced files/directories exist?
- Are the patterns referenced in the plan accurate?
- Any architectural concerns with this approach?

Plan references these files: <list from plan>
Plan references these patterns: <list from plan>
```

Skip this step if the plan only modifies project management files (markdown, config).

### Step 5: Write Dry Run Results

Write findings to `dry-runs/<plan-name>-<YYYY-MM-DD>.md`. If the `dry-runs/` directory doesn't exist, create it.

The gap table column order is canonical — follow it exactly:

```markdown
# Dry Run: <plan-name>

**Date**: <date>
**Plan**: `plans/<plan-name>.md`

## Gaps Found

| # | Task | Gap Type | Severity | Description | Suggested Fix |
|---|------|----------|----------|-------------|---------------|
| 1 | Task 1 | Missing context | MEDIUM | ... | ... |
| 2 | Task 2 | Stale reference | LOW | ... | ... |

## Architecture Concerns

- ...

## Missing Edge Cases

- ...

## Verdict

- [ ] Ready for implementation
- [ ] Needs plan updates first

**If needs updates, list by priority:**
1. [HIGH] <must-fix items>
2. [MEDIUM] <should-fix items>
3. [LOW] <nice-to-fix items>
```

### Step 6: Convergence Manifest (multi-plan mode only)

After all individual dry-runs complete in multi-plan mode, synthesize results into a convergence manifest.

#### Cross-Plan Interface Validation

Read `plans/00-overview.md` Interface Contracts section. If no `00-overview.md` exists or no Interface Contracts section is found, skip cross-plan interface validation and note "No interface contracts defined" in the convergence manifest.

For each contract, verify both sides define consistent interfaces:
- Method/function signatures match
- Data models/types are compatible
- API routes/endpoints agree
- Config keys/env vars are consistent

Severity: HIGH for signature mismatches, MEDIUM for naming inconsistencies, LOW for documentation gaps.

#### Write Convergence Manifest

Write to `dry-runs/convergence-manifest-<YYYY-MM-DD>.md`. If a manifest already exists for today's date, append a sequence number: `convergence-manifest-<date>-2.md`.

```markdown
# Convergence Manifest

**Date**: <date>
**Plans validated**: <list>

## Per-Plan Summary

| Plan | Gaps | HIGH | MEDIUM | LOW | Verdict |
|------|------|------|--------|-----|---------|

## Cross-Plan Interface Issues

| Plans | Issue | Severity | Description |

## Overall Verdict

- [ ] All plans ready for implementation
- [ ] Plans need updates first (see gaps above)
```

Check the "All plans ready" box only if every individual plan's verdict is "Ready for implementation" AND no HIGH-severity cross-plan interface issues were found.

Present the manifest to the user.

### Step 7: Present Gaps and Offer to Fix

Present the results to the user, organized by severity (HIGH first). The user reviews all gaps — even LOW severity gaps may trigger insights about missed requirements.

After the user has reviewed:
> "Would you like me to update the plan to address these gaps?"

If the user approves fixes:
1. Apply the agreed fixes to the plan file
2. Mark fixed gaps as `[FIXED]` in the dry-run results (prepend to Description)
3. Commit: `git commit -m "fix: Address dry-run gaps for plan <name>"`

If the user wants to re-validate after fixes:
> "Want to re-run the dry-run to verify the fixes?"

---

## Severity Classification

Use these criteria when assigning severity to each gap:

| Severity | Criteria | Examples |
|----------|----------|----------|
| **LOW** | Mechanical fix — one correct answer | Stale file reference, typo in pattern name, outdated method name |
| **MEDIUM** | Clear addition needed | Missing constraint, missing edge case, adding a test case |
| **HIGH** | Design decision — multiple valid approaches | Interface choice, architecture pattern, scope change, trade-off |

## Gap Types to Watch For

Default severities are starting points — override based on the specific gap.

| Gap Type | What to Look For | Default Severity |
|----------|------------------|------------------|
| **Missing context** | Task references something not defined elsewhere | MEDIUM |
| **Unclear patterns** | "Follow existing pattern" without specifying which | MEDIUM |
| **Hidden dependencies** | Task assumes something from another task that isn't explicit | MEDIUM |
| **Missing edge cases** | Happy path only, no error handling specified | MEDIUM |
| **Ambiguous acceptance** | Criteria that can't be objectively verified | HIGH |
| **Stale references** | Files or patterns that don't exist in codebase | LOW |
| **Missing tests** | Implementation task without corresponding test task | MEDIUM |
| **Constraint gaps** | Generic constraints instead of specific rules | MEDIUM |
| **Standards coverage** | Codebase standards artifact exists but plan constraints don't reference applicable standards sections | MEDIUM |
| **Env var persistence** | Required env var not set, or won't persist across sessions | MEDIUM |
| **Dependency path mismatch** | Import or file reference uses wrong extension or path | LOW |
| **File naming convention** | New file doesn't follow project naming pattern | LOW |
| **CLI flag incompatibility** | Referenced command flag doesn't exist or changed between versions | MEDIUM |
| **Platform assumption** | Code assumes platform-specific behavior (bash version, OS utilities) | MEDIUM |
| **Missing concreteness rollup** | Plan has no `## Data Structures & Callables` section | HIGH (MEDIUM if plan has minimal code surface or predates rule) |
| **Rollup/snippet mismatch** | Rollup lists an item but no inline snippet in Owning Task (or vice versa) | MEDIUM |
| **Signature drift on modification** | Plan modifies an existing callable; snippet signature doesn't match codebase | HIGH |
| **Collision on addition** | Plan adds a name that already exists in the target file | HIGH |

## Notes

- Results are written to `dry-runs/` for the historical record
- Be thorough — the goal is to catch issues BEFORE implementation
- Present ALL gaps to the user for review, regardless of severity
- The user decides which gaps to fix — don't auto-apply fixes
- Severity helps prioritize review, not skip it
