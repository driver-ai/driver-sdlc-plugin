---
description: Per-plan test suite curation against the functional-core / imperative-shell commitment — runs after a plan's bookkeeping and before that plan's PR. Prune mock-heavy and implementation-detail tests, promote behavior coverage that needs a pure-core extraction, keep conforming tests for the named plan.
argument-hint: <plan-name> [feature-path]
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, Agent
---

# /drvr:assess Command

Curate the test suite **for a single plan**, after that plan's bookkeeping completes and before that plan's PR opens. This command evaluates the plan's tests against the plugin's architectural commitment — **functional core, imperative shell** (see [CLAUDE.md](../CLAUDE.md) Key Principles) — prunes tests that violate it, promotes tests that almost get it right, and keeps tests that already conform, so the PR ships with a curated, reviewable test suite.

Under that commitment, every test should fall into one of two shapes:
- **Pure-core unit test**: a function in the pure core, values in / values out, no mocks, no I/O, no time, no randomness.
- **Shell integration test**: a shell entry point, exercised against real I/O (test DB, tmpdir, fake-backed HTTP from recorded real calls). Mocks permitted only at justified boundaries — when the real collaborator is external (third-party API with no sandbox), expensive (real money per invocation), non-deterministic in ways you can't control (real wall clock for timing-sensitive tests), or absent in the test environment — and each mock must be named with its justification.

Tests that don't fit either shape — most commonly, "unit tests" that mock internal modules — are signals of a core/shell boundary problem. The default action is to prune them and surface the architecture fix, not to keep them as documentation of a broken seam.

**When uncertain, judge by shape — don't default to KEEP.** The historical "when uncertain, KEEP" guidance is reversed for two shapes: mock-on-internal-module tests → PRUNE or PROMOTE (never let them persist as KEEP); and tautological structural assertions (counts, enum membership, types, internal state that only mirror the implementation) → PRUNE. For unambiguously behavior-asserting tests with no mock concerns, KEEP remains the default. A blanket "when uncertain, KEEP" lets scaffolding ship by inertia; the shape of the assertion is the signal.

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
- **Tautological structural assertions** — the assertion mirrors the implementation by construction (an enum asserted to have exactly the three variants it lists; a class asserted to expose the N methods it defines; a config dict asserted to have the K keys of its literal). These pass iff the implementation is unchanged and catch no real bug — they only re-state the implementation in a different syntax.

### KEEP — Valuable long-term, already conforming

Strong KEEP signals:
- **Pure-core unit test, no mocks** — takes values in, asserts on the returned value. Reads as documentation of what the function does.
- **Shell integration test against real I/O** — exercises a shell entry point against a real test DB, tmpdir, or fake-backed HTTP from recorded real calls. Asserts an observable outcome.
- **Mock only at a justified boundary, with the justification named** — external (third-party with no sandbox), expensive (real money per invocation), non-deterministic in ways you can't control, or absent in the test environment. The mock is at the edge, not inside, and the test or plan documents which category it fits.
- **Reads as documentation** — a reader could use this test to understand what the code does without reading the implementation. This is the bar.
- **Tests a contract boundary** — public API, integration point, error handling, failure mode that the code explicitly handles.

### PROMOTE — Rewrite to conform

The test covers behavior worth keeping, but in a shape that violates the architecture. The fix is a rewrite, not a deletion. Two common cases:

- **Mock-heavy test of internal logic that could be tested through a pure-core extraction.** Rewrite: extract the pure core (record as a follow-up architecture task if it's nontrivial), then assert values-in / values-out against the extracted function with no mocks.
- **Implementation-detail test that should be a behavioral test through the public interface.** Rewrite: assert the observable outcome rather than the internal call sequence.

PROMOTE is a stronger signal than PRUNE that there's architecture work to follow up on. Surface it.

**Key constraint (revised):** A mock-heavy test that is the only coverage for an important edge case becomes **PROMOTE**, not KEEP — keeping it as-is preserves a boundary failure indefinitely; promoting it forces the extract-and-rewrite that should have happened in the first place (the follow-up is tracked in the assessment report). What does *not* qualify for KEEP or PROMOTE at all is structural-only "coverage" — a test whose only assertion mirrors the implementation (the enum still has these three variants, the class still has these methods, the config still has these keys). Structural-only coverage is tautology, not coverage; it's a PRUNE.

The historical guidance "when uncertain, KEEP" is reversed for mock-heavy tests: **when uncertain about a mock-heavy test, PROMOTE.** For tests with no mocks against internal modules, KEEP-when-uncertain still applies.

---

## Step 4: Code Quality Review

This step always runs the **core/shell boundary check** (independent of any codebase standards artifact), then layers codebase-specific standards on top if a standards artifact exists.

### 4a: Core/Shell Boundary Check (always runs)

Audit the implementation files for violations of the functional-core / imperative-shell commitment. This check runs whether or not the codebase has its own CLAUDE.md — the commitment comes from the plugin, not the codebase's standards.

**Verdicts**: each row is PASS, FAIL, or **N/A** (decomposition genuinely doesn't apply — trivial routing, framework-mandated shape, or shell-only feature per the plan). N/A rows are recorded but don't contribute to FAIL counts and don't trigger fix workflows.

For each implementation file, classify the code into pure-core and shell sections (using the plan's Architecture Fit > Core/Shell Decomposition as the authoritative classification — if the plan declared shell-only, apply only the shell rules and mark pure-core checks N/A). Then flag:

- **I/O bleeding into pure-core code** — a function classified as core that reaches for the filesystem, network, database, time, randomness, or mutable shared state. FAIL.
- **Substantive logic in a shell function** — a function classified as shell that contains branching, calculation, or state machinery that should have been extracted into the core. FAIL. **Exception (N/A)**: routing/dispatch branching that IS the feature in a shell-only plan; framework-mandated shape (e.g., a Django view's required structure) where extraction would produce a single-line wrapper with no behavior of its own.
- **Internal-module mocking in tests** — already surfaced as PRUNE/PROMOTE in Step 3; mirror those here as architecture findings. **Exception (N/A)**: a mock whose justification fits the Mocking Rules (external / expensive / non-deterministic / absent) and is documented in the test or plan.
- **Pure-core functions never called from the shell** — dead pure code suggests the boundary was drawn but not wired up. WARN.

Record findings in the compliance table with `Standard: §FCIS Core/shell boundary` and the specific violation or N/A reason.

For each FAIL, suggest a concrete fix: which logic to extract, which I/O to push outward, which test to rewrite. For each N/A, briefly note why it's N/A (one line — "shell-only plan, routing dispatch", "mock of LLM client — justified as expensive in tests") so reviewers can audit the exceptions.

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
| `path/to/routes.py` | §FCIS Core/shell boundary | N/A | Shell-only plan, routing dispatch — branching IS the feature |
| `tests/test_llm.py` | §FCIS Core/shell boundary | N/A | Mock of `LLMClient` — justified as expensive (real calls cost money per invocation) |
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
- **Uncertainty default depends on the test's shape.** For mock-on-internal-module tests, default to PRUNE or PROMOTE — leaving them as KEEP perpetuates a boundary failure. For tautological structural assertions (enum membership, method counts, mock call shapes, internal state that mirror the implementation) → PRUNE; the canonical case is "the enum has three variants" against a three-variant enum literal, which passes iff the implementation is unchanged and catches no real bug. For behavior-asserting tests with no internal mocks, default to KEEP — losing real coverage is worse than carrying a marginal test.
- The §FCIS core/shell boundary check in Step 4a runs regardless of whether the codebase has its own standards artifact — it comes from the plugin's commitment, not the codebase's
- The assessment report persists as documentation of test curation decisions for that plan and as a record of architecture follow-ups identified
- For phase detection rules, see [/drvr:orchestrate](orchestrate.md) and [sdlc-orchestration](../skills/sdlc-orchestration/SKILL.md)
