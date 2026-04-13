---
description: Dry run a plan to identify gaps before implementation
argument-hint: <plan-name>
allowed-tools: Read, Write, Edit, Glob, Grep, mcp__driver-mcp__*
---

# /dry-run-plan Command

Walk through a plan as if implementing it to identify gaps, missing context, and potential issues before actual implementation begins.

## Workflow

### Step 1: Locate the Plan

Find the plan file based on the argument:
- If `<plan-name>` provided: Look for `plans/<plan-name>.md` or `plans/*<plan-name>*.md`
- If no argument: List available plans in `plans/` and ask which to dry run

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

### Step 6: Present Gaps and Offer to Fix

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

## Notes

- Results are written to `dry-runs/` for the historical record
- Be thorough — the goal is to catch issues BEFORE implementation
- Present ALL gaps to the user for review, regardless of severity
- The user decides which gaps to fix — don't auto-apply fixes
- Severity helps prioritize review, not skip it
