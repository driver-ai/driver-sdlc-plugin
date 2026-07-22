---
description: Open a pull request for a single plan, using that plan's driver-docs/<plan>/ artifacts as the PR body. Final step of the per-plan PR gate (after /drvr:assess and /drvr:docs-artifacts).
argument-hint: <plan-name> [feature-path]
allowed-tools: Read, Write, Edit, Bash, Glob, Grep
---

# Open Per-Plan PR

Open a stacked pull request for a single plan. The PR's base is read from that plan's `## Environment` (derived from `depends_on`: feature parent if independent, upstream plan's Feature Branch if dependent). The PR body is composed from `driver-docs/<plan>/`, which must already exist from `/drvr:docs-artifacts <plan>`.

This is the final step in the per-plan PR gate: `/drvr:assess <plan>` → `/drvr:docs-artifacts <plan>` → **`/drvr:open-pr <plan>`**.

### Step 1: Locate Feature and Resolve Plan

1. **Plan name** (required) — the first argument. If absent, scan `plans/00-overview.md` for the lowest-numbered plan with status COMPLETE that has a per-plan assessment AND a per-plan `driver-docs/<plan>/` directory AND no `pr_created_<plan>` event in `FEATURE_LOG.md` — that's the next plan needing a PR. Tell the user: "No plan specified — defaulting to `<plan>` (next plan needing a PR)."
2. **Feature path** — if provided as second arg, use it. Else scan cwd, then up to 3 parent directories, for `FEATURE_LOG.md`.
3. Read `FEATURE_LOG.md` to confirm feature exists and get the feature name.

### Step 2: Check Prerequisites (Per-Plan Gate)

Run these prerequisite checks in order. Each is a hard gate — stop on first failure.

1. **GitHub CLI authentication** — Run `gh auth status`:
   - If it fails: **BLOCK**: "GitHub CLI is not installed or not authenticated. Run `gh auth login` first."

2. **Per-plan handoff documentation** — Check if `driver-docs/<plan>/` directory exists in the feature project:
   - If missing: **BLOCK**: "Per-plan handoff documentation for `<plan>` has not been generated. Run `/drvr:docs-artifacts <plan>` first."

3. **Per-plan assessment artifact** — Check `assessment/<plan>-test-curation.md`:
   - If missing: **BLOCK**: "Per-plan assessment for `<plan>` is missing. Run `/drvr:assess <plan>` first — the per-plan PR gate is assess → docs → open-pr." If a feature-wide `assessment/test-curation-<date>.md` exists instead, this feature predates 1.2.0 — see [/drvr:setup](setup.md) → **In-Flight Features (1.1.0 → 1.2.0)**.

4. **Plan Environment** — Read `plans/<plan>.md` `## Environment` section to get:
   - Codebase path
   - **Base Branch** (this PR's target — derived from plan's `depends_on`: feature parent if independent; upstream plan's Feature Branch if dependent)
   - **Feature Branch** (this PR's head — this plan's branch)
   - **CRITICAL:** Do NOT default the Base Branch to a feature-wide value. Read it from the plan's own Environment.

5. **Confirm Base Branch exists** — Verify the recorded Base Branch exists on the remote: `git ls-remote --heads origin <base-branch>`.

   - **Exists** → proceed with `<base-branch>` as recorded.
   - **Missing** → ask the user which branch to target:

     > "Recorded Base Branch `<base-branch>` no longer exists on the remote (likely because the upstream PR was merged and the branch was deleted). Which branch should this PR target instead? Common choice: `<feature-parent>` (the feature parent)."

     Wait for the user's answer. Use whatever branch they provide as the effective base. If they pick the feature parent and the Feature Branch needs a rebase to keep the diff scoped to this plan only, tell them — but let them handle the rebase, don't orchestrate it.

   If the user picks a different branch than recorded, update `plans/<plan>.md` `## Environment` Base Branch to match and update the PR Stack row in `plans/00-overview.md`.

6. **Existing PR check** — Run `gh pr list --head <feature-branch> --base <effective-base-branch> --state open --json url,number` from the codebase directory:
   - If a PR already exists: Report the existing PR URL and ask: "PR #N already exists for branch `<feature-branch>` → `<effective-base-branch>`. Update its body with current driver-docs/<plan>/, or skip PR creation?"
     - **Update**: Read driver-docs/<plan>/, compose body (Step 3-4), run `gh pr edit <number> --body <body>`, then skip to Step 6.
     - **Skip**: Exit with existing PR URL.

### Step 3: Read Per-Plan Driver-Docs Artifacts

Read these files from `driver-docs/<plan>/`:

1. `driver-docs/<plan>/feature-overview.md` — primary source of PR body
2. `driver-docs/<plan>/architecture.md`
3. `driver-docs/<plan>/testing-guide.md`
4. `driver-docs/<plan>/risk-assessment.md`

If any are missing, compose from what exists and WARN — do not BLOCK. A partial PR body is better than no PR.

Also read `driver-docs/00-feature-overview.md` (cross-plan rollup) to include a link in the PR body.

### Step 4: Compose Per-Plan PR

1. **Title**: Prefix with the plan number for stack legibility — e.g., `[<plan-prefix>] <short summary from feature-overview Summary section>`. Under 70 characters total. Examples:
   - `[01-token-store] Add OAuth token persistence layer`
   - `[02-refresh-flow] Implement refresh token rotation`
2. **Body**: Compose from `driver-docs/<plan>/` with these sections in this order:
   - `## Stack Position` — copy the Stack Position section from `feature-overview.md` verbatim. This is what makes the PR self-contained for the reviewer.
   - `## Feature Context` — copy the Feature Context section.
   - `## What This Plan Delivers` — from feature-overview.
   - `## What Changed in This PR` — from feature-overview.
   - `## Architecture` — condensed highlights from `architecture.md` (Overview, Components Touched, Key Design Decisions).
   - `## Test Plan` — from `testing-guide.md` (Automated Tests + Manual Test Scenarios).
   - `## Risks` — from `risk-assessment.md` (Summary table + significant items).
   - `## Related` — links to: cross-plan overview, upstream PRs (if any, from Stack Position), per-plan docs in the repo.

The PR body **must be self-contained**. A reviewer who has not seen other PRs in this feature should be able to evaluate the change.

### Step 5: Push and Create Per-Plan PR

**Run git and gh commands from the codebase directory** (read Path from the plan's `## Environment`).

1. Ensure current branch is `<feature-branch>`. If not, BLOCK and tell the user to check out the correct branch.
2. Ensure branch is pushed: `git push -u origin <feature-branch>`.
3. Create PR: `gh pr create --base <effective-base-branch> --head <feature-branch> --title <title> --body <body>`
4. Capture the PR URL from output.
5. Do NOT update FEATURE_LOG or other artifacts until PR creation is confirmed successful.

**Stack note:** if `<effective-base-branch>` is an upstream plan's still-live Feature Branch, this PR shows only THIS plan's commits in the diff view (GitHub computes the diff against the base). Reviewers will not see upstream PR changes mixed in — that's the point of stacking. When the upstream PR later merges, GitHub **retargets** this PR onto the upstream's base but does not rebase this branch; if the upstream was squash- or rebase-merged, rebase this branch onto the new base to keep the diff scoped (see sdlc-orchestration → Per-Plan PR Review → Merge).

### Step 6: Update Per-Plan Artifacts

**Return to the feature project directory** for SDLC artifact updates.

1. Update `driver-docs/<plan>/feature-overview.md` Related section: replace any `[PR #{number}]({link})` placeholder with the actual PR URL.
2. Update `driver-docs/00-feature-overview.md` PR Stack table: set this plan's row PR column to the new URL and Status to "Open".
3. Update `plans/00-overview.md` PR Stack table similarly.
4. Update `FEATURE_LOG.md`:
   - Append per-plan event row: `| <date> | PR opened for plan <plan> — pr_created_<plan> <URL> | driver-docs/<plan>/ |`

### Step 7: Commit and Surface Next Step

1. Commit SDLC artifact updates: `"chore: PR opened for plan <plan> — <URL>"`
2. Report the PR URL to the user
3. Surface the next step explicitly based on the dependency graph:
   - **If another plan is unblocked**: "Plan `<plan>` PR opened (`<URL>`). Next unblocked plan is `<next>` (Base Branch: `<next-base>`). Begin its cycle when ready: validation → materialization → implementation → bookkeeping → assess → docs → open-pr."
   - **If all plans now have open PRs**: "All plan PRs are open. Track merge status; run `/drvr:retro` after the feature ships."
   - **If this plan's PR has downstream plans waiting**: "Downstream plans `<list>` were waiting on this branch to exist remotely — they are now unblocked."
