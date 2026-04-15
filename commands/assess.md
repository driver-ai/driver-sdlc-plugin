---
description: Curate the test suite after implementation — categorize, prune scaffolding, promote valuable tests, keep durable ones
argument-hint: [feature-path]
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, Agent
---

# /assess Command

Curate the test suite after all plans are implemented. TDD naturally produces scaffolding tests that are valuable during construction but become maintenance burden afterward. This command evaluates every test, prunes what's no longer needed, promotes scaffolding that covers important behavior, and documents the decisions.

**When uncertain, KEEP. This is a pruning pass, not a purge.**

---

## Step 1: Locate Feature and Check Readiness

1. **Resolve feature path** — from argument, cwd, or parent directories (same as `/orchestrate`)
2. **Read `plans/00-overview.md`** — check the progress table for plan statuses

### Readiness Check

- **All plans COMPLETE** → proceed normally (standard case)
- **Some plans incomplete** → warn:

> "Plans X, Y are still in progress. Scaffolding from completed plans may still be load-bearing for remaining work. Proceeding will scope assessment to tests from completed plans only."

  User confirms or declines. If partial: scope analysis to tests from completed plans only. Note scope in report: `"Scope: Plans 01a, 01b (plans 02, 03 pending)"`

- The mandatory pre-handoff assessment still requires all plans complete — a partial mid-implementation assessment doesn't satisfy it

---

## Step 2: Inventory the Test Suite

Identify all test files across the feature:

1. **Implementation logs** (primary) — read `implementation/log-*.md` for each completed plan. Logs track every file touched per task with commit hashes. Extract test files from the "Files" and "Actual" sections.
2. **Plan documents** (supplement) — read each plan's `## Test Strategy` section for the full list of planned test files. Cross-reference with logs to catch any tests added during implementation that weren't in the original plan.
3. **Git diff** (verification) — if a feature branch exists, `git diff --name-only <base-branch>...HEAD -- '*.test.*' '*.spec.*' '*_test.*' '**/test_*' '**/tests/**'` to catch anything the logs missed.
4. **Read each test file** alongside its corresponding implementation file

Build an inventory:
```
| Test File | Test Count | Implementation File | From Plan |
```

If scoped to specific plans (partial assessment), only include tests from those plans.

---

## Step 3: Categorize Each Test

Evaluate each test using judgment. The categories:

### PRUNE — Remove after assessment

Signals:
- Asserts exact mock call signatures (`.toHaveBeenCalledWith(exact, args)` on internal methods)
- Tests pure wiring with no behavioral assertion
- Breaks on any refactor without catching real bugs
- Setup is longer than the test itself
- Duplicates coverage from a behavioral test
- Tests implementation details (private method calls, internal state)

### KEEP — Valuable long-term

Signals:
- Asserts observable behavior (inputs → outputs)
- Only coverage for an important edge case
- Tests a contract boundary (API, public interface, integration point)
- Would catch a real bug on regression
- Tests error handling or failure modes

### PROMOTE — Rewrite to assert behavior

Signals:
- Covers important behavior but tests it through implementation details
- Scaffolding that validates something worth keeping, but the wrong way
- Could be rewritten to assert the same behavior through the public interface

**Key constraint**: A mock-heavy test that is the only coverage for an important edge case stays (KEEP, not PRUNE). The goal is removing tests that cost more to maintain than the bugs they'd catch.

---

## Step 4: Code Quality Review

If a codebase standards artifact exists (`research/NN-codebase-standards.md`), review implementation code against the documented standards.

**If no standards artifact exists, skip this step entirely.**

1. **Read the standards artifact** — get the Applicable Sections and Key Rules
2. **Identify implementation files** — from the implementation logs, identify all source files modified or created. If implementation logs don't enumerate all files, fall back to `git diff --name-only <base-branch>...HEAD` to identify modified files.
3. **For each applicable standard**, check whether each implementation file complies. Only check standards relevant to the file's type and content — skip standards that clearly don't apply (e.g., don't check Python error handling standards against CSS files, don't check data structure standards against test files). The table should contain only rows where the standard is applicable — omit N/A combinations:
   - Read the file
   - Compare against the standard's requirements
   - Classify as PASS (compliant) or FAIL (violation found)
4. **For each FAIL**, note the specific violation and suggest a fix

Build a compliance table:

| File | Standard | Status | Detail |
|------|----------|--------|--------|
| `path/to/file.py` | §6 Error handling | PASS | Narrow try/except used |
| `path/to/file.py` | §4 Data structures | FAIL | Uses raw dict on line 42, should be Pydantic model |

This review is **advisory** — present violations organized by severity. The user decides which to address:
- **If user wants fixes**: track them as follow-up work items. Standards fixes are NOT executed during assessment (unlike test pruning/promotion, which has dedicated execution steps). Record approved fixes in the assessment report as "Standards fixes approved — to be addressed before handoff."
- **If user declines**: note in the report as "Standards violations acknowledged — user accepted as-is."
- The user can review all at once, by category, or individually.

---

## Step 5: Write Assessment Report

Write to `assessment/test-curation-<YYYY-MM-DD>.md`:

```markdown
# Test Suite Assessment

**Feature**: <name>
**Date**: <YYYY-MM-DD>
**Scope**: All plans | Plans 01a, 01b (plans 02, 03 pending)

## Summary

| Category | Count | Action |
|----------|-------|--------|
| PRUNE | N | Delete — scaffolding, no longer needed |
| PROMOTE | N | Rewrite — valuable behavior, wrong approach |
| KEEP | N | No change — durable tests |
| **Total** | **N** | |

## Coverage Impact

- Current test count: N
- After pruning: N (−X)
- After promotion: N (rewritten, not removed)
- Estimated coverage change: <analysis>

---

## PRUNE

Tests recommended for removal.

### <test-file>:<test-name>
**Reason**: <why this is scaffolding>
**Risk**: <what we lose — usually "none, covered by <other test>">

---

## PROMOTE

Tests to rewrite from implementation-detail assertions to behavioral assertions.

### <test-file>:<test-name>
**Current**: <what it tests now>
**Rewrite to**: <what it should assert instead>

---

## KEEP

Durable tests — no changes needed.

### Summary by file
| Test File | Tests Kept | Coverage |
|-----------|-----------|----------|
| ... | ... | ... |

## Code Quality Review

_Only include if a codebase standards artifact exists_

**Standards source**: `research/NN-codebase-standards.md`

| File | Standard | Status | Detail |
|------|----------|--------|--------|
```

---

## Step 6: Present Findings

Present to the user in this order:

1. **Summary table** — overall test counts
2. **PRUNE list** — what will be removed and why
3. **PROMOTE list** — what will be rewritten and how
4. **KEEP summary** — confirmation that the rest stays
5. **Code Quality Review** — standards compliance findings (if applicable). User approves or declines fixes using the same flow as test curation (all at once, by category, or individually).

The user can approve:
- **All at once** — "Looks good, proceed"
- **By category** — "Approve prunes, skip promotions for now"
- **Individually** — "Keep test X, prune the rest"

---

## Step 7: Execute Approved Changes

For approved changes:

1. **Delete pruned tests** — remove the test cases (or entire files if all tests in the file are pruned)
2. **Rewrite promoted tests** — change assertions from implementation details to behavioral assertions
3. **Run full test suite** — verify nothing is broken
4. **Commit** — `"refactor: Curate test suite — pruned <X>, promoted <Y>"`

If tests fail after changes, investigate:
- A pruned test was the only coverage for a real behavior → restore it as KEEP
- A promoted test needs adjustment → fix the rewrite
- Unrelated failure → address separately

---

## Step 8: Update Report with Outcomes

Update the assessment report to mark each test's actual outcome:

| Outcome | Meaning |
|---------|---------|
| PRUNED | Deleted as approved |
| PROMOTED | Rewritten as approved |
| KEPT | Durable test, no change |
| KEPT (override) | User overrode PRUNE/PROMOTE recommendation |
| SKIPPED | User declined the change |

This makes the report the permanent record of decisions, not just proposals.

---

## Step 9: Update Overview

If `plans/00-overview.md` exists, add an Assessment row to the progress table:

```
| Assessment | COMPLETE | pruned <X>, promoted <Y>, kept <Z> | assessment/test-curation-<date>.md |
```

---

## Step 10: Update Feature Log and Commit

1. Update `FEATURE_LOG.md`:
   - Set phase → Handoff
   - Append event row (with standards):
     `| <date> | Assessment complete — pruned <X>, promoted <Y>, kept <Z>, standards: <N pass, M fail> | assessment/test-curation-<date>.md |`
   - Append event row (without standards — use when no standards artifact exists):
     `| <date> | Assessment complete — pruned <X>, promoted <Y>, kept <Z> | assessment/test-curation-<date>.md |`
2. Commit bookkeeping: `"chore: Assessment complete — pruned <X>, promoted <Y>, kept <Z>"`

After completion, suggest: "Assessment complete. Run `/docs-artifacts` for handoff documentation."

---

## Notes

- This command is mandatory before `/docs-artifacts` — the orchestrator enforces this
- Users can run `/assess` mid-implementation, but a partial assessment doesn't satisfy the pre-handoff requirement
- When uncertain about a test, default to KEEP — false positives (keeping unnecessary tests) are cheaper than false negatives (losing important coverage)
- The assessment report persists as documentation of test curation decisions
- For phase detection rules, see [/orchestrate](orchestrate.md) and [sdlc-orchestration](../skills/sdlc-orchestration/SKILL.md)
