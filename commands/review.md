---
description: Run internal standards review before PR — check code against standards, verify acceptance criteria and test coverage, auto-fix violations
argument-hint: [feature-path]
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, Agent
---

# /drvr:review Command

Run an internal standards review after assessment and before opening a PR. This command checks implementation code against codebase standards, verifies acceptance criteria from plans are met, and confirms test coverage. Standards violations can be auto-fixed; unmet criteria and missing tests are presented as manual action items.

**Gate doctrine**: This command is advisory. Orchestration suggests it after `/drvr:assess`, but the user can skip directly to `/drvr:docs-artifacts`.

**User controls all fix decisions** — the command proposes fixes, the user approves or declines.

---

## Step 1: Locate Feature

1. **If argument provided**: Use it as the feature path
2. **Else scan cwd**: Look for `FEATURE_LOG.md` in the current directory
3. **Scan parent directories**: Check up to 3 levels up for `FEATURE_LOG.md`
4. Read `FEATURE_LOG.md` to confirm feature exists and get the feature name

---

## Step 2: Check Prerequisites

Run these checks in order. BLOCK and SKIP gates stop or skip the command; WARN gates allow continuation with reduced scope.

1. **Assessment artifact** — Glob for `assessment/test-curation-*.md`.
   - If no matches: **BLOCK**: "Assessment has not been run. Run `/drvr:assess` first."
   - If multiple matches: use the most recent (highest date in filename).

2. **Standards violations** — Read the assessment artifact, find `## Code Quality Review` section.
   - If section absent or all rows PASS: **SKIP**: "Assessment found no standards violations. This review step is not needed — proceed to `/drvr:docs-artifacts`."
   - If FAIL rows exist, also check for "acknowledged" or "accepted as-is" notes:
     - If ALL FAIL violations were user-accepted: **SKIP**: "All standards violations were accepted by user during assessment. This review step is not needed — proceed to `/drvr:docs-artifacts`."
     - If SOME were accepted and SOME approved for fixing: proceed with only the approved-for-fixing violations.

3. **Standards artifact** — Scan `research/` for the codebase standards artifact (file containing `## Standards Source` or `## Key Rules`).
   - If missing: **WARN**: "No standards artifact found. Review will check acceptance criteria and test coverage only."

4. **Environment** — Read `plans/00-overview.md` `## Implementation Environment` for codebase path, base branch, feature branch, test command. Fall back to per-plan `## Environment` sections.

---

## Step 3: Identify Scope

1. Get list of changed files from the codebase directory: `git diff --name-only {base_branch}...{feature_branch}`
   - If no changed files: **SKIP**: "No changed files found between base and feature branch. Nothing to review." Exit.
2. Read all plan documents to collect acceptance criteria and test strategies
3. Read standards artifact if it exists

---

## Step 4: Spawn Standards-Review Agent

Spawn a `standards-review` agent (via Agent tool, `subagent_type: "drvr:standards-review"`) with:

- Codebase path
- Feature branch
- Base branch
- Standards artifact path (or note that none exists)
- List of changed files
- Plan paths for acceptance criteria and test strategy

Wait for the agent to return structured findings covering:
- Standards compliance checks per file
- Acceptance criteria verification per plan
- Test coverage analysis

---

## Step 5: Present Findings

Parse agent output into three categories:

| Category | Source | Auto-fixable? |
|----------|--------|---------------|
| **Standards Compliance** | Agent checks against standards artifact | Yes (Step 6) |
| **Acceptance Criteria** | Agent checks against plan criteria | No (manual) |
| **Test Coverage** | Agent checks against plan test strategy | No (manual) |

Present summary: "Internal review found N standards violations, M unmet criteria, P missing tests."

### Decision tree

- **If no findings in any category**: Append to FEATURE_LOG.md: `| <date> | Internal review complete — 0 violations found | — |`. Report: "Internal review passed — all standards met, criteria satisfied, tests present. Proceed to `/drvr:docs-artifacts`." Exit (skip Steps 6-7, proceed to Step 9).

- **If only UNMET/MISSING (no standards FAILs)**: Present manual action items. Skip Steps 6-7. Proceed to Step 8. Ask user: "These require manual action. Address them now, or proceed to `/drvr:docs-artifacts`?"

- **If standards FAILs found**: Present findings by category. Show each FAIL with its agent-proposed fix. Ask user: "Apply standards fixes? (Or review individually: 'show details')" UNMET/MISSING items listed separately as manual action items.

---

## Step 6: Apply Approved Fixes

All file edits and git operations execute in the **codebase directory** (from Environment section), not the feature project directory.

**Strategy: batch-then-isolate.** Track every file modified by fixes.

1. Record the fix file list from agent findings
2. Apply all approved fixes
3. Run test command once to verify no regressions
4. If tests pass: commit: `git commit -m "fix: Address N standards violations (internal review)"`
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
| Standards only | `\| <date> \| Internal review complete — N standards violations found, M fixed \| — \|` |
| Mixed | `\| <date> \| Internal review complete — N standards violations fixed, M criteria unmet, P tests missing \| — \|` |
| All regressions | `\| <date> \| Internal review complete — N standards violations found, 0 fixed (all caused regressions) \| — \|` |
| No FAILs | `\| <date> \| Internal review complete — M criteria unmet, P tests missing (manual action items) \| — \|` |

The log entry MUST contain the substring `Internal review complete` for phase detection.

---

## Step 9: Suggest Next Step

"Internal review complete. Run `/drvr:docs-artifacts` to generate handoff documentation."
