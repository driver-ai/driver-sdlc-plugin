---
description: Run a plan's internal standards review before its PR — check code against standards, verify acceptance criteria and test coverage, auto-fix violations
argument-hint: <plan-name> [feature-path]
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, Agent
---

# /drvr:review Command

Run an internal standards review **for a single plan**, after that plan's assessment and before its PR opens. This is the optional second step in the per-plan PR gate: `/drvr:assess <plan>` → `[/drvr:review <plan>]` → `/drvr:docs-artifacts <plan>` → `/drvr:open-pr <plan>`.

This command delegates to the [standards-review](../agents/standards-review.md) agent, which checks these layers of standards:

1. **§FCIS — functional core / imperative shell** (plugin commitment, always runs)
2. **§self-standing — code stands on its own** (plugin commitment, always runs): comments explain the non-obvious *why*, never reference SDLC/process artifacts (task numbers, deviation/decision IDs, plan/gap names)
3. **Codebase-specific standards** (only if a standards artifact exists from research)

It also verifies acceptance criteria from plans are met and confirms test coverage. Standards violations can be auto-fixed; unmet criteria and missing tests are presented as manual action items.

**Gate doctrine**: This command is advisory. Orchestration suggests it when `/drvr:assess <plan>` found FAIL violations, but the user can skip directly to `/drvr:docs-artifacts <plan>`. Unlike the rest of the per-plan gate, this step is optional.

**User controls all fix decisions** — the command proposes fixes, the user approves or declines.

---

## Step 1: Locate Feature and Resolve Plan

1. **Resolve feature path** — from the `[feature-path]` argument, cwd, or up to 3 parent directories, by locating `FEATURE_LOG.md`. Read it to confirm the feature exists and get its name.
2. **Resolve target plan**:
   - If a plan name is provided as the first argument, use it (strip `.md` if present).
   - If no plan name is provided, scan `plans/00-overview.md` for the lowest-numbered plan that has a per-plan assessment artifact (`assessment/<plan>-test-curation.md`) but no `driver-docs/<plan>/` directory — that's the plan currently sitting in the gate. Tell the user: "No plan specified — defaulting to `<plan>` (next plan needing review)."
   - If no eligible plan is found: **BLOCK**. "No plan is awaiting internal review. Either no plan has been assessed yet, or every assessed plan already has handoff docs. Run `/drvr:assess <plan>` first."

---

## Step 2: Check Prerequisites

Run these checks in order. BLOCK and SKIP gates stop or skip the command; WARN gates allow continuation with reduced scope.

1. **Per-plan assessment artifact** — Read `assessment/<plan>-test-curation.md`.
   - If missing: **BLOCK**: "Per-plan assessment for `<plan>` has not been run. Run `/drvr:assess <plan>` first." If a feature-wide `assessment/test-curation-<date>.md` exists instead, this feature was scaffolded under 1.1.0 — see [/drvr:setup](setup.md) → **In-Flight Features (1.1.0 → 1.2.0)** before continuing.

2. **Standards violations** — Read the assessment artifact, find `## Code Quality Review` section.
   - If section absent or all rows PASS: **SKIP**: "Assessment found no standards violations for `<plan>`. This review step is not needed — proceed to `/drvr:docs-artifacts <plan>`."
   - If FAIL rows exist, also check for "acknowledged" or "accepted as-is" notes:
     - If ALL FAIL violations were user-accepted: **SKIP**: "All standards violations for `<plan>` were accepted by user during assessment. This review step is not needed — proceed to `/drvr:docs-artifacts <plan>`."
     - If SOME were accepted and SOME approved for fixing: proceed with only the approved-for-fixing violations.

3. **Standards artifact** — Scan `research/` for the codebase standards artifact (file containing `## Standards Source` or `## Key Rules`).
   - If missing: **WARN**: "No codebase standards artifact found. The review will still run the always-on plugin checks — §FCIS (functional core / imperative shell) and §self-standing (code stands on its own) — plus acceptance criteria and test coverage. Codebase-specific rules will be skipped."

4. **Environment** — Read the target plan's own `## Environment` section in `plans/<plan>.md` for codebase path, Base Branch, Feature Branch, and test command. In the per-plan PR model each plan carries its own branch pair — the Base Branch is the feature parent for independent plans, or the upstream plan's Feature Branch for dependent ones. Fall back to `plans/00-overview.md` `## Implementation Environment` only for legacy single-branch features.

---

## Step 3: Identify Scope

Scope is **this plan only** — earlier plans were reviewed in their own pass, and later plans aren't implemented yet.

1. Get the list of changed files from the codebase directory using the target plan's branch pair: `git diff --name-only {base_branch}...{feature_branch}`
   - If no changed files: **SKIP**: "No changed files found between `<base_branch>` and `<feature_branch>`. Nothing to review for `<plan>`." Exit.
2. Read `plans/<plan>.md` to collect this plan's acceptance criteria and test strategy — not the whole plan set
3. Read standards artifact if it exists

---

## Step 4: Spawn Standards-Review Agent

Spawn a `standards-review` agent (via Agent tool, `subagent_type: "drvr:standards-review"`) with:

- Codebase path
- This plan's Feature Branch
- This plan's Base Branch
- Standards artifact path (or note that none exists)
- List of changed files
- The target plan's path (`plans/<plan>.md`) for acceptance criteria and test strategy — pass this plan only

Wait for the agent to return structured findings covering:
- Standards compliance checks per file
- Acceptance criteria verification per plan
- Test coverage analysis

---

## Step 5: Present Findings

Parse agent output into three categories:

| Category | Source | Auto-fixable? |
|----------|--------|---------------|
| **Standards Compliance** | Agent checks against §FCIS (always) + §self-standing (always) + codebase standards (if artifact present). Rows are tagged `§FCIS`, `§self-standing`, or the codebase standard's name in the Standard column. | Yes for `§self-standing` rows (comment edits — no behavior change) and codebase-standard rows; `§FCIS` rows usually require architectural extraction and should be presented for user judgment rather than auto-fixed. |
| **Acceptance Criteria** | Agent checks against plan criteria | No (manual) |
| **Test Coverage** | Agent checks against plan test strategy | No (manual) |

Present summary: "Internal review of `<plan>` found N standards violations, M unmet criteria, P missing tests."

### Decision tree

- **If no findings in any category**: Append to FEATURE_LOG.md: `| <date> | Internal review complete for plan <plan> — 0 violations found (internal_review_complete_<plan>) | — |`. Report: "Internal review passed for `<plan>` — all standards met, criteria satisfied, tests present. Proceed to `/drvr:docs-artifacts <plan>`." Exit (skip Steps 6-7, proceed to Step 9).

- **If only UNMET/MISSING (no standards FAILs)**: Present manual action items. Skip Steps 6-7. Proceed to Step 8. Ask user: "These require manual action. Address them now, or proceed to `/drvr:docs-artifacts <plan>`?"

- **If standards FAILs found**: Present findings by category. Show each FAIL with its agent-proposed fix. Ask user: "Apply standards fixes? (Or review individually: 'show details')" UNMET/MISSING items listed separately as manual action items.

---

## Step 6: Apply Approved Fixes

All file edits and git operations execute in the **codebase directory** (from the plan's Environment section), not the feature project directory. Fixes are committed on this plan's Feature Branch — the same branch its PR will be opened from.

**Strategy: batch-then-isolate.** Track every file modified by fixes.

1. Record the fix file list from agent findings
2. Apply all approved fixes
3. Run test command once to verify no regressions
4. If tests pass: commit: `git commit -m "fix: Address N standards violations in <plan> (internal review)"`
5. If tests fail: revert only fix files (`git checkout -- <file1> <file2> ...` — NOT `git checkout -- .`). Then re-apply one fix at a time, testing each. Keep passing fixes, skip failing ones.
   - If any survived: commit surviving fixes
   - If 0 survived: skip commit, report all regressions

---

## Step 7: Re-Verify

- Skip if 0 fixes were applied
- Quick re-check of only fixed files against violated standards
- Report any remaining violations

---

## Step 8: Update Feature Log

Append to `FEATURE_LOG.md` with counts per category (only include non-zero categories):

| Scenario | Log Entry |
|----------|-----------|
| Standards only | `\| <date> \| Internal review complete for plan <plan> — N standards violations found, M fixed (internal_review_complete_<plan>) \| — \|` |
| Mixed | `\| <date> \| Internal review complete for plan <plan> — N standards violations fixed, M criteria unmet, P tests missing (internal_review_complete_<plan>) \| — \|` |
| All regressions | `\| <date> \| Internal review complete for plan <plan> — N standards violations found, 0 fixed (all caused regressions) (internal_review_complete_<plan>) \| — \|` |
| No FAILs | `\| <date> \| Internal review complete for plan <plan> — M criteria unmet, P tests missing (manual action items) (internal_review_complete_<plan>) \| — \|` |

The log entry MUST contain the event token `internal_review_complete_<plan>` — that's what [sdlc-orchestration](../skills/sdlc-orchestration/SKILL.md) reads to tell a reviewed plan from an unreviewed one. The token is per-plan because each plan passes through this gate separately.

---

## Step 9: Suggest Next Step

"Internal review complete for `<plan>`. Run `/drvr:docs-artifacts <plan>` to generate this plan's handoff documentation, then `/drvr:open-pr <plan>` to open its PR against `<Base Branch>`."
