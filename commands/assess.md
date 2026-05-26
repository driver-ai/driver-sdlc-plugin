---
description: Curate the test suite after implementation against the functional-core / imperative-shell commitment — prune mock-heavy and implementation-detail tests, promote behavior coverage that needs a pure-core extraction, keep conforming tests
argument-hint: [feature-path]
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, Agent
---

# /drvr:assess Command

Curate the test suite after all plans are implemented. This command evaluates every test against the plugin's architectural commitment — **functional core, imperative shell** (see [CLAUDE.md](../CLAUDE.md) Key Principles) — prunes tests that violate it, promotes tests that almost get it right, and keeps tests that already conform.

Under that commitment, every test should fall into one of two shapes:
- **Pure-core unit test**: a function in the pure core, values in / values out, no mocks, no I/O, no time, no randomness.
- **Shell integration test**: a shell entry point, exercised against real I/O (test DB, tmpdir, fake-backed HTTP from recorded real calls). Mocks only at hard external boundaries that cannot be exercised in test (third-party APIs without sandboxes, cost-bearing services, hardware absent in test).

Tests that don't fit either shape — most commonly, "unit tests" that mock internal modules — are signals of a core/shell boundary problem. The default action is to prune them and surface the architecture fix, not to keep them as documentation of a broken seam.

**Bias toward pruning mock-heavy tests.** This is a curation pass with a strong architectural opinion. The historical "when uncertain, KEEP" guidance is reversed for mock-on-internal-module tests: **when uncertain about a mock-heavy test, PRUNE or PROMOTE — do not let it persist as KEEP**. For unambiguously behavior-asserting tests with no mock concerns, KEEP remains the default.

---

## Step 1: Locate Feature and Check Readiness

1. **Resolve feature path** — from argument, cwd, or parent directories (same as `/drvr:orchestrate`)
2. **Read `plans/00-overview.md`** — check the progress table for plan statuses

### Readiness Check

- **All plans COMPLETE** → proceed normally (standard case)
- **Some plans incomplete** → warn:

> "Plans X, Y are still in progress. Tests from completed plans may still be load-bearing for remaining work. Proceeding will scope assessment to tests from completed plans only."

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

Evaluate each test against the core/shell rules. The categories:

### PRUNE — Remove after assessment

The test is a symptom of a boundary problem, has no future use, and shouldn't survive curation. Either the architecture is wrong (a follow-up will fix it) or the test never asserted anything load-bearing.

Strong PRUNE signals:
- **Mocks an internal module** — the test asserts behavior of something the codebase owns by mocking its collaborators. This is the strongest PRUNE signal. If the covered behavior is important, the right fix is to extract a pure core and write a real unit test against it; the mock-based test should not survive in the meantime.
- **Asserts exact mock call signatures** (`.toHaveBeenCalledWith(exact, args)` on internal methods) — tests the call sequence, not the outcome.
- **Tests pure wiring with no behavioral assertion** — "this constructor was called" type tests.
- **Setup longer than the test itself** — visible symptom of over-mocking; the seams are wrong.
- **Tests implementation details** — private method calls, internal state inspection, class-internal collaborator interactions.
- **Breaks on any refactor without catching real bugs** — coupled to structure, not behavior.
- **Duplicates coverage from a behavior-asserting test** — the behavioral one is the keeper.

### KEEP — Valuable long-term, already conforming

Strong KEEP signals:
- **Pure-core unit test, no mocks** — takes values in, asserts on the returned value. Reads as documentation of what the function does.
- **Shell integration test against real I/O** — exercises a shell entry point against a real test DB, tmpdir, or fake-backed HTTP from recorded real calls. Asserts an observable outcome.
- **Mock only at a hard external boundary** — third-party API without sandbox, cost-bearing service, hardware not present in test. The mock is at the edge, not inside.
- **Reads as documentation** — a reader could use this test to understand what the code does without reading the implementation. This is the bar.
- **Tests a contract boundary** — public API, integration point, error handling, failure mode that the code explicitly handles.

### PROMOTE — Rewrite to conform

The test covers behavior worth keeping, but in a shape that violates the architecture. The fix is a rewrite, not a deletion. Two common cases:

- **Mock-heavy test of internal logic that could be tested through a pure-core extraction.** Rewrite: extract the pure core (record as a follow-up architecture task if it's nontrivial), then assert values-in / values-out against the extracted function with no mocks.
- **Implementation-detail test that should be a behavioral test through the public interface.** Rewrite: assert the observable outcome rather than the internal call sequence.

PROMOTE is a stronger signal than PRUNE that there's architecture work to follow up on. Surface it.

**Key constraint (revised):** A mock-heavy test that is the only coverage for an important edge case becomes **PROMOTE**, not KEEP. Keeping it as-is preserves a boundary failure indefinitely; promoting it forces the extract-and-rewrite that should have happened in the first place. The follow-up is tracked in the assessment report.

The historical guidance "when uncertain, KEEP" is reversed for mock-heavy tests: **when uncertain about a mock-heavy test, PROMOTE.** For tests with no mocks against internal modules, KEEP-when-uncertain still applies.

---

## Step 4: Code Quality Review

This step always runs the **core/shell boundary check** (independent of any codebase standards artifact), then layers codebase-specific standards on top if a standards artifact exists.

### 4a: Core/Shell Boundary Check (always runs)

Audit the implementation files for violations of the functional-core / imperative-shell commitment. This check runs whether or not the codebase has its own CLAUDE.md — the commitment comes from the plugin, not the codebase's standards.

For each implementation file, classify the code into pure-core and shell sections (using the plan's Architecture Fit > Core/Shell Decomposition as the authoritative classification). Then flag:

- **I/O bleeding into pure-core code** — a function classified as core that reaches for the filesystem, network, database, time, randomness, or mutable shared state. FAIL.
- **Substantive logic in a shell function** — a function classified as shell that contains branching, calculation, or state machinery that should have been extracted into the core. FAIL.
- **Internal-module mocking in tests** — already surfaced as PRUNE/PROMOTE in Step 3; mirror those here as architecture findings.
- **Pure-core functions never called from the shell** — dead pure code suggests the boundary was drawn but not wired up. WARN.

Record findings in the compliance table with `Standard: §FCIS Core/shell boundary` and the specific violation.

For each FAIL, suggest a concrete fix: which logic to extract, which I/O to push outward, which test to rewrite.

### 4b: Codebase Standards Review (only if standards artifact exists)

If a codebase standards artifact exists (`research/NN-codebase-standards.md`), review implementation code against the documented standards.

**If no standards artifact exists, skip 4b entirely. 4a still runs.**

1. **Read the standards artifact** — get the Applicable Sections and Key Rules
2. **Identify implementation files** — from the implementation logs, identify all source files modified or created. If implementation logs don't enumerate all files, fall back to `git diff --name-only <base-branch>...HEAD` to identify modified files.
3. **For each applicable standard**, check whether each implementation file complies. Only check standards relevant to the file's type and content — skip standards that clearly don't apply (e.g., don't check Python error handling standards against CSS files, don't check data structure standards against test files). The table should contain only rows where the standard is applicable — omit N/A combinations:
   - Read the file
   - Compare against the standard's requirements
   - Classify as PASS (compliant) or FAIL (violation found)
4. **For each FAIL**, note the specific violation and suggest a fix

Build a compliance table (rows from 4a and 4b combined):

| File | Standard | Status | Detail |
|------|----------|--------|--------|
| `path/to/core.py` | §FCIS Core/shell boundary | FAIL | `compute_total` is classified as core but reads from DB on line 18 — extract DB read into shell, pass values into compute_total |
| `path/to/shell.py` | §FCIS Core/shell boundary | FAIL | `handle_request` contains discount calculation logic — extract into core function `apply_discount(items, coupon) -> total` |
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
| PRUNE | N | Delete — mock-heavy, implementation-detail, or boundary-failure test |
| PROMOTE | N | Rewrite — behavior worth keeping, needs pure-core extraction to test cleanly |
| KEEP | N | No change — already conforms to core/shell rules |
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
**Reason**: <why this fails core/shell — mocks an internal module / tests implementation details / is shell wiring with no behavioral assertion / etc.>
**Risk**: <what we lose — usually "none, covered by <other test>"; if this was the only coverage for an important behavior, this should be PROMOTE not PRUNE>

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

_Always includes the core/shell boundary check (§FCIS). Codebase-specific standards rows are added only if a standards artifact exists._

**Core/shell boundary source**: plugin CLAUDE.md, Key Principles
**Codebase standards source** (if applicable): `research/NN-codebase-standards.md`

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

After completion, suggest: "Assessment complete. Run `/drvr:docs-artifacts` for handoff documentation."

---

## Notes

- This command is mandatory before `/drvr:docs-artifacts` — the orchestrator enforces this
- Users can run `/drvr:assess` mid-implementation, but a partial assessment doesn't satisfy the pre-handoff requirement
- **Uncertainty default depends on the test shape:** For mock-on-internal-module tests, default to PRUNE or PROMOTE — leaving them as KEEP perpetuates a boundary failure. For tests with no internal mocks, default to KEEP — losing real coverage is worse than carrying a marginal test.
- The §FCIS core/shell boundary check in Step 4a runs regardless of whether the codebase has its own standards artifact — it comes from the plugin's commitment, not the codebase's
- The assessment report persists as documentation of test curation decisions and as a record of architecture follow-ups identified
- For phase detection rules, see [/drvr:orchestrate](orchestrate.md) and [sdlc-orchestration](../skills/sdlc-orchestration/SKILL.md)
