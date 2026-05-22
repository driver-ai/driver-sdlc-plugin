---
description: Per-plan test suite curation — runs after a plan's bookkeeping completes and before that plan's PR. Categorize, prune scaffolding, promote valuable tests, keep durable ones for the named plan.
argument-hint: <plan-name> [feature-path]
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, Agent
---

# /drvr:assess Command

Curate the test suite **for a single plan**, after that plan's bookkeeping completes and before that plan's PR opens. TDD naturally produces scaffolding tests that are valuable during construction but become maintenance burden afterward. This command evaluates the plan's tests, prunes what's no longer needed, promotes scaffolding that covers important behavior, and documents the decisions — so the PR ships with a curated, reviewable test suite.

**When uncertain, judge by shape — don't default.** If the test asserts **structure** (counts, enum membership, types, mock call sequences, internal state) → PRUNE. If it asserts **behavior** (inputs → outputs, error modes, contract boundaries) → KEEP. This is a pruning pass, not a purge — but tests that only mirror the implementation are exactly what it exists to remove. A blanket "when uncertain, KEEP" default lets scaffolding ship by inertia; the shape of the assertion is the signal.

This is the first step in the per-plan PR gate: `/drvr:assess <plan>` → `/drvr:docs-artifacts <plan>` → `/drvr:open-pr <plan>`. Do not skip steps.

---

## Step 1: Locate Feature, Resolve Plan, and Check Readiness

1. **Resolve feature path** — from argument, cwd, or parent directories (same as `/drvr:orchestrate`)
2. **Resolve target plan**:
   - If a plan name is provided as the first argument, use it (strip `.md` if present).
   - If no plan name is provided, scan `plans/00-overview.md` progress table for the lowest-numbered plan with status COMPLETE that does not yet have a per-plan assessment artifact (`assessment/<plan>-test-curation.md`) — that's the next plan in the gate. Tell the user: "No plan specified — defaulting to `<plan>` (next plan needing assessment)."
   - If no eligible plan is found: BLOCK. "No plans are awaiting per-plan assessment. Either all complete plans are already assessed, or no plan has reached COMPLETE. Run implementation first."
3. **Read `plans/00-overview.md`** — verify the target plan's status

### Readiness Check (Per-Plan)

- **Target plan status = COMPLETE** → proceed
- **Target plan status ≠ COMPLETE** → BLOCK. "Plan `<plan>` is not COMPLETE yet (current status: `<status>`). Per-plan assessment runs after bookkeeping. Complete implementation and bookkeeping first."
- **Other plans incomplete** → INFO only — that's expected in the stacked model. Earlier plans are assessed and PR'd before later plans are implemented.
- **Per-plan assessment artifact already exists for `<plan>`** → ask: "An assessment already exists at `assessment/<plan>-test-curation.md`. Overwrite, or update in place?"

---

## Step 2: Inventory the Plan's Test Suite

Identify test files **introduced or modified by THIS plan only**. Earlier plans were assessed in their own pass; later plans haven't been implemented.

1. **Implementation log** (primary) — read `implementation/log-<plan>.md`. Extract test files from "Files" and "Actual" sections of each task.
2. **Plan document** (supplement) — read the plan's `## Test Strategy` section for the full list of planned test files. Cross-reference with the log to catch any tests added during implementation that weren't in the original plan.
3. **Git diff** (verification) — read the plan's `## Environment` for Base Branch and Feature Branch, then run `git diff --name-only <Base Branch>...<Feature Branch> -- '*.test.*' '*.spec.*' '*_test.*' '**/test_*' '**/tests/**'` (or against HEAD if the Feature Branch is currently checked out) to catch anything the log missed. The Base Branch is the prior plan's Feature Branch (or feature parent for Plan 01), which scopes the diff to THIS plan's changes only.
4. **Read each test file** alongside its corresponding implementation file

Build an inventory:
```
| Test File | Test Count | Implementation File | From Task |
```

If you discover tests from earlier plans in the diff (because the Feature Branch contains commits from prior plans you haven't filtered out), exclude them — those were assessed previously.

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
- **Tautological structural assertions** — the assertion mirrors the implementation by construction. Example: a test that asserts an enum has exactly three variants when the enum itself lists those three variants; a test that asserts a class exposes N methods when those methods are the class definition; a test that asserts a config dict has K keys when those keys are the dict literal. These tests pass iff the implementation is unchanged and catch no real bug — they only re-state the implementation in a different syntax.

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

**Key constraint**: A test that is the only coverage for an important **behavior** — even if implemented through mocks or with awkward setup — stays (KEEP, or PROMOTE if it tests behavior through implementation details). What does *not* qualify: tests whose only "coverage" is structural (the enum still has these three variants, the class still has these methods, the config still has these keys). Structural-only coverage is tautology, not coverage. The goal is removing tests that mirror the implementation, while preserving tests that catch real bugs.

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

Write to `assessment/<plan>-test-curation.md` (per-plan filename — one assessment artifact per plan):

```markdown
# Test Suite Assessment — Plan `<plan>`

**Feature**: <name>
**Plan**: `<plan>`
**Date**: <YYYY-MM-DD>
**Scope**: Tests introduced or modified by plan `<plan>`

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
- A **promoted** test was rewritten incorrectly and now fails → fix the rewrite (the common case)
- A test that wasn't pruned now fails because it depended on a pruned test's setup, fixtures, or shared state → extract the shared setup into an explicit fixture; do not restore the pruned test (the dependency was the bug)
- Unrelated regression slipped in via the curation commit → revert and redo the curation in a clean tree
- Pre-existing failure unrelated to assess → address separately

Note: a deleted test cannot fail. "Tests fail after pruning" is never a signal that the pruned test should be restored — it's a signal about the surviving tests or the rewrite. If you suspect a real behavior is now uncovered, that's a code-review/coverage concern, not a test-suite signal, and the fix is a new behavioral test rather than restoring the scaffolding.

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

If `plans/00-overview.md` exists, update the target plan's row in the progress table with assessment results (or add a notes column):

```
| 01-foo | COMPLETE | <N> tests (pruned <X>, promoted <Y>, kept <Z>) | <key artifact> |
```

Also update the PR Stack table row for this plan to reflect "ASSESSED" status (the next step is `/drvr:docs-artifacts <plan>`).

---

## Step 10: Update Feature Log, Commit, and Surface Next Gate Step

1. Update `FEATURE_LOG.md`:
   - Append event row (with standards):
     `| <date> | Assessment complete for plan <plan> — pruned <X>, promoted <Y>, kept <Z>, standards: <N pass, M fail> (assessment_complete_<plan>) | assessment/<plan>-test-curation.md |`
   - Append event row (without standards — use when no standards artifact exists):
     `| <date> | Assessment complete for plan <plan> — pruned <X>, promoted <Y>, kept <Z> (assessment_complete_<plan>) | assessment/<plan>-test-curation.md |`
2. Commit bookkeeping: `"chore: Assessment complete for plan <plan> — pruned <X>, promoted <Y>, kept <Z>"`

After completion, surface the next gate step explicitly:

- **If standards FAIL violations found**: "Plan `<plan>` assessment found N standards violations. Run `/drvr:review <plan>` to fix them, then `/drvr:docs-artifacts <plan>`, then `/drvr:open-pr <plan>`."
- **If clean**: "Plan `<plan>` assessment complete. Next gate step: `/drvr:docs-artifacts <plan>` to generate this plan's PR docs. After that: `/drvr:open-pr <plan>` to open the PR (base: `<Base Branch>` from the plan's Environment)."

---

## Notes

- This command is mandatory before `/drvr:docs-artifacts <plan>` — the per-plan PR gate enforces it
- One assessment artifact per plan: `assessment/<plan>-test-curation.md`
- Scope is per-plan — assess only tests introduced or modified by THIS plan
- When uncertain about a test, judge by what it asserts: structural / implementation-mirroring (enum membership, method counts, mock call shapes, internal state) → PRUNE; behavioral (inputs → outputs, error modes, contract boundaries) → KEEP. A blanket "default to KEEP" lets scaffolding ship by inertia, which defeats the assess phase's purpose.
- Tautological structural assertions (e.g., "the enum has three variants" against a three-variant enum literal) are the canonical PRUNE case — they pass iff the implementation is unchanged and catch no real bug.
- The assessment report persists as documentation of test curation decisions for that plan
- For phase detection rules, see [/drvr:orchestrate](orchestrate.md) and [sdlc-orchestration](../skills/sdlc-orchestration/SKILL.md)
