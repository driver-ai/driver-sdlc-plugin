---
name: sdlc-orchestration
description: |
  SDLC lifecycle orchestration for the drvr plugin. Coordinates phase transitions, loads the right skills,
  manages bookkeeping, and handles session resumption for feature projects.
  Trigger phrases: "returning to feature", "where are we", "what's next",
  "resume feature", "feature status".
  Do NOT activate for: "let's research", "create a plan", "implement plan X" —
  those are handled by their respective skills.
---

# SDLC Orchestration

You coordinate the feature development lifecycle. You know which phase we're in, ensure the right skill is active, manage transitions between phases, and handle session resumption.

## CRITICAL: User Controls All Decisions

You manage process, not decisions. Present information, suggest next steps, but the user decides:
- Whether to move to the next phase
- Whether deviations are acceptable or need rework
- Whether bookkeeping should proceed
- Which plan to work on next

"Next unblocked plan is 01b" is a suggestion. "Ready to implement?" is overstepping.

---

## Phase → Skill Mapping

See [CLAUDE.md Phase-Skill Mapping](../../CLAUDE.md#phase-skill-mapping) for the full phase-to-skill table with entry signals.

When you detect an entry signal, ensure the corresponding skill is active. If the user is in research and says "let's plan", acknowledge the transition and activate `drvr:planning-guidance`.

---

## Session Resumption

When a user returns to a feature ("returning to feature/X", "resume feature X", "where are we on X"):

1. **Locate the feature directory** — resolve the path to the feature project
2. **Read `plans/00-overview.md`** — progress table, dependency graph, gaps
3. **Check for uncommitted artifacts:**

   ### Check for Uncommitted Artifacts

   Before reporting state, check for uncommitted SDLC artifacts from a previous session:

   1. Run `git status --porcelain` in the feature directory, filtering for `.md` files in artifact directories (`research/`, `plans/`, `implementation/`, `assessment/`, `driver-docs/`, `dry-runs/`)
   2. Also check `FEATURE_LOG.md` and `DECISIONS.md`
   3. If uncommitted artifacts found: report what was found and commit them
   4. Commit message: `chore: Commit SDLC artifacts from previous session`
   5. Then proceed with normal state reporting

4. **Check for in-progress work:**
   - `research/00-intent.md` missing → phase is **Intent**. Suggest: "Intent has not been captured. Activate `intent-guidance` to start."
   - `research/00-intent.md` exists but `status: in_progress` (not confirmed) → phase is **Intent**. Suggest: "Intent is in progress. Resume `intent-guidance` to complete."
   - `research/00-intent.md` confirmed (or intent explicitly skipped per FEATURE_LOG) but no `research/NN-*.md` (except 00-* files) → phase is **Research (Why-What-How)**. Intent is complete, research proper hasn't started.
   - Implementation logs without a matching plan status header → implementation was in progress
   - Plan files without dry-run results → plan needs validation
   - Research docs with open questions → research may be incomplete
   - Plan with `status: approved` in frontmatter but task doc count < plan task count (or no `plans/<plan>/tasks/` directory) → phase is **Materialization**. Suggest: "Plan X is approved but not fully materialized. Activate `drvr:materialize-tasks`."
   - Phase detection resolves to **Per-Plan Assessment** for a specific plan (plan COMPLETE, no `assessment/<plan>-test-curation.md`) → suggest `/drvr:assess <plan>`
   - Phase detection resolves to a post-PR per-plan phase (PR Review, Revision, Merge, Verification) via FEATURE_LOG `*_<plan>` event scanning → see Phase Detection: Post-PR (Per Plan)
     - If a plan's most recent event is `pr_created_<plan>` or revision-related, check PR status via `gh pr view <URL>` (extract URL from FEATURE_LOG `pr_created_<plan>` event). If `gh pr view` fails (network, auth, or missing PR), report the failure and fall back to the FEATURE_LOG phase header — do not change the detected phase based on a failed check. Report current PR state per plan (open, approved, changes requested, merged, closed).
4.5. **Scan for cross-feature dependencies:**
   - Determine the projects directory from the current feature path (navigate up to `features/` parent)
   - Find other active features: `find <projects_path>/features -maxdepth 2 -name "FEATURE_LOG.md" -not -path "<current_feature>/*"` — filter to active (phase not Shipped, Closed, Done, and phase does not contain "(complete)")
   - Check two sources of cross-feature overlap:
     a. Read other features' `plans/00-overview.md` for `## Feature Dependencies` — look for rows referencing THIS feature
     b. Read other features' plan files (`plans/[0-9][0-9]-*.md`) for `**Files**:` entries (inline or multiline `- ` list format; paths may be backtick-wrapped) and `Target File` columns — compare against this feature's planned files
   - If dependencies found, include in the state report. If none, report "none detected"
   - **Advisory only** — do not block session resumption. Skip silently if no other features exist or projects path can't be determined.
5. **Report current state:**

```
Feature: <name>
Progress: N/M plans complete
Current state: <what's in progress or what's next>
Last activity: <most recent artifact modified>
Codebase: <name> at <local-path> (base: <base-branch>, feature: <feature-branch>)
Test command: `<cmd>`
Cross-feature dependencies: <summary or "none detected">
Next action: <suggestion based on state — if a plan is past bookkeeping but not past `/drvr:open-pr`, suggest the next per-plan gate step for that plan (assess → docs → open-pr)>
```

**Graceful degradation**: if `plans/00-overview.md` has no `## Implementation Environment` section (legacy features, or overview not yet created), omit the `Codebase:` and `Test command:` lines. Do NOT emit placeholder values. If the source (IE or Codebases) uses a single `Branch` column (legacy format), display as `(branch: <branch>)` instead of `(base: ..., feature: ...)`. Read branch values from whatever format the Implementation Environment uses — key-value pairs, table columns, or subsections. Do not prescribe a specific parsing format; the IE is free-form and varies across features.

**Multi-codebase**: if Implementation Environment lists multiple codebases, emit one `Codebase:` and `Test command:` line per codebase.

If no overview exists, check for `research/` and `plans/` directories to infer the phase.

---

## Transition Boundaries

### Scaffold → Intent

When `/drvr:feature` completes and FEATURE_LOG shows `Phase: Intent`:
- Activate `intent-guidance` if the user signals "capture intent" or any intent trigger
- If the user attempts to skip to research ("let's research") without capturing intent:
  WARN and prompt "Intent has not been captured. Activate `intent-guidance` first, or say
  'skip intent' (appropriate when intent is clear from external context — PRD, detailed ticket, prior discussion) to proceed anyway."

### Intent → Research

When the user signals "let's research" or any research trigger:
- **Check 1: Intent artifact exists** — Verify `research/00-intent.md` exists. If not:
  BLOCK. "Intent has not been captured. Activate `intent-guidance` first, or explicitly
  skip intent with 'skip intent' (appropriate when intent is clear from external context — PRD, detailed ticket, prior discussion)."
- **Check 2: Intent exit criteria met** — Read `research/00-intent.md`'s `## Exit Criteria`
  checklist. If any item is unchecked: WARN. "Intent exit criteria are not fully satisfied.
  Review `research/00-intent.md` before proceeding. Proceed anyway?"
- If the user said "skip intent" explicitly: note "Intent skipped at user direction" in
  FEATURE_LOG and proceed. No file is created.
- Activate `research-guidance`

### Research → Planning
When the user signals "let's plan" or "ready to plan":

**Open question scan** — Before transitioning, scan research docs for unresolved open questions:

1. Use Bash to list files matching `research/[0-9][0-9]-*.md` (e.g., `ls research/[0-9][0-9]-*.md`). After listing, exclude files named `00-overview.md` and `00-intent.md` from the list before scanning.
2. Count the matching files → N (total research docs scanned).
3. For each file, scan for ALL occurrences of BOTH question formats — a single file may have multiple question sections under different headings:
   - **Inline bold headers:** Lines starting with `**Open Questions` (handles suffix variants like `**Open Questions (for future research):**`). Also match lines starting with `**Questions:**`. The section extends to the next line that starts with `**` (bold header) or `##` (markdown header), or end of file. Under each, count lines starting with `- ` that do NOT contain `~~` (strikethrough = resolved).
   - **H2 headers:** Lines starting with `## Open Questions` (prefix match — handles suffix variants like `## Open Questions (for Planning)`). The section extends to the next `## ` header or end of file. Under each, count lines starting with `- ` that do NOT contain `~~` AND do NOT match `- [x]` or `- [X]` (checkbox = resolved).
4. If `research/00-overview.md` exists, scan it for `## Open Questions` section using prefix match (`## Open Questions` at line start). If the file does not exist, skip (count 0). If found, the section extends to the next `## ` header or end of file. Count lines starting with `- ` that do NOT contain `~~` AND do NOT match `- [x]` or `- [X]`.
5. Aggregate: M = total unresolved questions, X/Y = filenames containing them.
6. Report: "N research docs. M open questions remain in docs X, Y."
7. Edge cases: If N = 0 and M = 0: "No research docs found." If N > 0 and M = 0: "N research docs. No open questions." If N = 0 and M > 0: "No research docs found, but M open questions remain in X."
8. Known limitations: (a) only `- ` bullet-format questions are detected — research-guidance enforces this format, but older features using numbered lists or unbulleted prose require manual review. (b) The scanner has no fenced-code-block awareness — `## Open Questions` inside triple-backtick blocks would be matched. No real research files have this pattern at column 0, so the risk is theoretical.

This is informational — the user decides whether to proceed or resolve questions first.

- Activate `drvr:planning-guidance`

### Planning → Validation
When a plan is written:
- If the feature has an overview with interface contracts, run consumer validation: check whether downstream plans' assumptions match this plan's definitions
- Suggest: "Want to run `/drvr:dry-run-plan <name>`?"

### Validation → Materialization
When the plan is approved and ready for materialization:
- **Approval check** — Verify plan has `status: approved` in frontmatter. If not: this transition does not apply.
- **Approval staleness check** — If `approved_at` exists and the plan's `updated` field is a more recent date than `approved_at`, WARN: "Plan was modified after approval (approved: <date>, updated: <date>). Consider re-approving before materialization." This is advisory, not blocking — the user decides.
- **Dry-run verdict check** — Read the latest `dry-runs/<plan>-*.md` (sort by file modification time, most recent first — filename-based sorting is unreliable since dry-run files use inconsistent suffixes like `-deep`, `-round4`). Check the Verdict section. If "Needs plan updates first": WARN. "Dry-run verdict is not 'Ready for implementation'. Proceed anyway?" If no dry-run found: note "No dry-run found for this plan" (informational, not blocking).
- **Task doc completeness check** — Count `### Task N` sections in the plan's `## Task Breakdown`. Count `.md` files in `plans/<plan>/tasks/`. Three checks:
  1. **Count check**: If task doc count < plan task count: trigger materialization (partial). Report: "N of M task docs exist — triggering materialization to complete the remaining K."
  2. **Freshness check**: If task doc count equals plan task count, read `materialized_at` from any task doc and compare against the plan's `updated` date. If `materialized_at` predates `updated`: task docs are stale (plan was revised after materialization). Trigger re-materialization: "Task docs are stale (materialized before plan was last updated). Triggering re-materialization." materialize-tasks Step 4 handles this by preserving completed tasks and overwriting incomplete ones.
  3. **Complete and fresh**: If count matches AND task docs are fresh, skip to implementation.
- **Planning open questions check** — If `plans/00-overview.md` exists, read it and find the `## Open Questions` section (prefix match at line start — handles suffix variants). The section extends to the next `## ` header or end of file. Count unchecked items (`- [ ]`) — both `[x]` and `[X]` count as checked. If any unchecked items exist: WARN. "N open questions remain in the planning overview. Proceed anyway?" If `plans/00-overview.md` does not exist or has no `## Open Questions` section, skip this check silently.
- Activate `drvr:materialize-tasks`

### Materialization → Implementation
When materialization is complete:
- **Task doc gate** — Verify task docs exist in `plans/<plan>/tasks/` AND count matches plan task count. If count mismatch: BLOCK. "Task doc count (N) does not match plan task count (M). Re-run `materialize-tasks`."
- The user decides whether to proceed

### Implementation → Review Deviations
When implementation-guidance reports all tasks complete:
- **Present the deviation summary** from the implementation log
- Let the user review each deviation
- Ask: "Are these deviations acceptable, or would you like to go back and address any of them?"
- If the user wants changes → return to implementation for rework
- If the user approves → proceed to bookkeeping

### Review → Bookkeeping
After the user approves deviations, execute all bookkeeping steps automatically without pausing:
- Update plan status header (mark checkboxes, add Implementation Status)
- Update overview progress table
- Verify upstream plan commits — read the implementation log for commit hashes. For each, verify the commit exists locally via `git rev-parse --verify <hash>^{commit}`. If missing: WARN. "Commit `<hash>` not found in local git history — cascade-check results may be unreliable. Proceed?"
- Spawn [cascade-check](../../agents/cascade-check.md) agent to analyze whether deviations affect downstream plans
- Present cascade results to user (pause only if design-impact decisions are flagged)
- Commit bookkeeping: `"chore: Update plan status and overview for plan <name>"`

### Bookkeeping → Per-Plan PR Gate (REQUIRED)

After a plan's bookkeeping is complete, the plan must go through the per-plan PR gate before work begins on the next plan. The gate is sequential — each step depends on the previous, and you must surface the next step explicitly.

```
Plan <name> bookkeeping complete
  → /drvr:assess <plan>           (per-plan test curation; writes assessment/<plan>-test-curation.md)
  → [/drvr:review <plan>]         (optional — only if per-plan assessment found FAIL violations)
  → /drvr:docs-artifacts <plan>   (writes driver-docs/<plan>/* for the PR body)
  → /drvr:open-pr <plan>          (push Feature Branch, open PR with base = Base Branch from plan Environment)
  → THEN next unblocked plan
```

**Surface the gate step-by-step. Never collapse the chain into "all done — move to the next plan."** Each PR is self-contained for reviewers, and that depends on doing the per-plan assess/docs/open-pr work for *this* plan before context shifts.

### Per-Plan Assessment → Per-Plan Internal Review

After `/drvr:assess <plan>` completes:

**Detection:**
1. Read `assessment/<plan>-test-curation.md`
2. Find the `## Code Quality Review` section
3. Check for any rows with Status = FAIL

**If FAILs found:**
- "Plan `<plan>` assessment found N standards violations. Run `/drvr:review <plan>` to fix them before generating handoff docs."
- Advisory (WARN) — the user can skip to `/drvr:docs-artifacts <plan>` if they choose

**If no FAILs (or no Code Quality Review section):**
- "Plan `<plan>` assessment clean. Run `/drvr:docs-artifacts <plan>` to generate this plan's PR docs."

**If user skips review:**
- Do not re-suggest within this session. Proceed to per-plan handoff normally.

### Per-Plan Handoff → Per-Plan Open PR

After `/drvr:docs-artifacts <plan>` completes:

**Advisory:** "Plan `<plan>` handoff docs generated at `driver-docs/<plan>/`. Open this plan's PR with `/drvr:open-pr <plan>` — its base will be `<Base Branch>` from the plan's Environment."

### Per-Plan Open PR → Per-Plan PR Review

`/drvr:open-pr <plan>` handles this transition directly — it records a `pr_created_<plan>` event in FEATURE_LOG and sets the plan's status in the PR Stack table. "Open PR" is a transient command phase, not a persistent state.

### Per-Plan PR Open → Next Plan

After a plan's PR is created:

- Read overview's PR Stack and dependency graph
- Identify the next unblocked plan (all upstream plans named in its `depends_on` have their PRs open or merged — stacked branches only require the upstream branch to exist remotely; they do not require merge before downstream work starts)
- Present: "Plan `<plan>` PR opened (#N). Next unblocked plan is `<next>`. Its Base Branch is `<base>` (derived from its `depends_on`: feature parent if independent, or upstream plan's Feature Branch if dependent). It has [a plan document / needs planning]."
- If multiple unblocked: "Plans X and Y are both unblocked. They are independent of each other (`depends_on` is disjoint) — their PRs will be parallel against `<feature parent>`. Pick whichever to start with; the other can run in parallel or after."
- If unblocked plans depend on each other: list them in DAG order and note which is the branch-parent
- If none unblocked: "No plans are currently unblocked."
- If all plans have PRs open: "All plan PRs are open. Track merge status and ship."

**Mental model:** the PR landscape is a DAG of base relationships, not a linear stack. Plans 02 and 08 can be implemented in any order if they're independent — both will open PRs targeting the feature parent.

**Upstream-merged-first scenario:** if a downstream plan's upstream PR merges before the downstream PR opens, the upstream branch is usually deleted by GitHub. When `/drvr:open-pr` runs and finds the recorded Base Branch missing, it asks the user which branch to target instead. When suggesting the next plan, surface this proactively: "Plan `<next>`'s recorded Base Branch is `<upstream-branch>`. Upstream plan `<upstream>` has already merged — `/drvr:open-pr` will prompt for a replacement base when you run it (feature parent is the usual answer)."

### Per-Plan PR Review → Revision

When review comments on a plan's PR require code changes.

**Advisory:** "Make changes on `<Feature Branch>`, push, optionally re-run `/drvr:docs-artifacts <plan>` to update the PR docs."

After re-running `/drvr:docs-artifacts <plan>`, suggest updating the PR body with `gh pr edit <number> --body <new-body>` (read body from `driver-docs/<plan>/*`). This is a lightweight loop — no full implementation-guidance workflow.

**Stacked-PR caveat:** if a revision changes Plan N's interface in a way downstream plans depend on, surface that explicitly — downstream branches may need to be rebased or downstream plans updated. Use the cascade-check agent if the change is non-trivial.

### Per-Plan PR Review → Merge

When a plan's PR is approved and ready to merge. User reports approval or `gh pr view` shows approved status.

**Advisory:** "Plan `<plan>` PR approved. Merge when ready."

**Stacked-PR mechanic (surface only if downstream plan PRs are stacked on this branch):** When this PR merges, GitHub **retargets** any PR based on this branch onto this PR's base — it does *not* rebase the downstream branch. Whether the downstream also needs a manual rebase depends on the merge strategy:

- **Squash or rebase merge** → this plan's commits are rewritten under new SHAs. The downstream branch still carries the original commits, so its diff will show this plan's changes (duplicated) until it is rebased onto the new base. Tell the user to rebase the downstream branch before its PR is reviewed.
- **Merge commit** → the original SHAs are preserved on the base, so the retargeted downstream diff is already scoped to just that plan; no rebase needed.

Let the user perform any rebase — don't orchestrate it. If the interface itself changed (not just the base), see the Stacked-PR caveat under Revision and run cascade-check.

Record `pr_approved_<plan>` event in FEATURE_LOG. After merge: record `pr_merged_<plan>` event, advance this plan's status in the PR Stack table.

### Per-Plan Merge → Per-Plan Verification

After a plan's PR is merged.

**Advisory:** "Plan `<plan>` PR merged. Verify the change (deployment, integration, smoke test). When verified, record `verification_complete_<plan>`."

Verification is advisory/checklist-based — the plugin can't know what "verified" means for every team. For stacked PRs, verification often only matters for the final/bottom-of-stack plan, but earlier plans may have user-facing changes worth verifying independently.

### All Plan PRs Shipped → Feature Shipped

After every plan's PR is merged (and any verification users care about is done):

- Set feature phase to "Shipped"
- Suggest `/drvr:retro`
- Terminal state

### Any Post-PR → Closed

Alternate terminal state. User can say "close feature" or "abandon" at any post-PR phase (PR Review, Revision, Merge, Verification). Set phase to "Closed", record `feature_closed` event. Terminal.

This applies only to post-PR phases — pre-PR abandonment is informal (features are simply left inactive).

### Phase Detection: Per-Plan PR Gate

For each plan that has reached COMPLETE in the overview's progress table, evaluate the per-plan gate state in this order:

- Plan is COMPLETE, no `assessment/<plan>-test-curation.md` → phase is **Per-Plan Assessment** for `<plan>`. Suggest `/drvr:assess <plan>`.
- Per-plan assessment exists with FAIL violations in Code Quality Review, no `internal_review_complete_<plan>` in FEATURE_LOG → suggest **Per-Plan Internal Review** (`/drvr:review <plan>`).
- Per-plan assessment exists (clean, or `internal_review_complete_<plan>` logged), no `driver-docs/<plan>/` → phase is **Per-Plan Handoff** for `<plan>`. Suggest `/drvr:docs-artifacts <plan>`.
- `driver-docs/<plan>/` exists, no `pr_created_<plan>` in FEATURE_LOG → phase is **Per-Plan Open PR** for `<plan>`. Suggest `/drvr:open-pr <plan>`.
- `pr_created_<plan>` in FEATURE_LOG, PR still open (no `pr_merged_<plan>`) → phase is **Per-Plan PR Review** for `<plan>`.
- `pr_merged_<plan>` in FEATURE_LOG, no `verification_complete_<plan>` → phase is **Per-Plan Verification** for `<plan>`.

When evaluating multiple plans, the current focus is the lowest-numbered COMPLETE plan that has not yet reached `pr_created_<plan>` — that's the plan blocking the gate. Surface that one first; downstream plans cannot have PRs opened until upstream PRs are opened (their base branches don't exist remotely yet).

### Phase Detection: Post-PR (Per Plan)

Post-PR phases use **event-driven detection** (scanning FEATURE_LOG for markers), distinct from the artifact-driven pattern used for pre-PR phases. Event-driven detection takes precedence over artifact-based detection when post-PR events exist in FEATURE_LOG. Pre-PR phases continue to use artifact-based detection exclusively.

**Per-plan event detection:** Each plan has its own event lineage (`pr_created_<plan>`, `pr_merged_<plan>`, etc.). Scan FEATURE_LOG for the most recent event for each plan.

**Feature-level rollup:**
- All plans have `pr_merged_<plan>` (and any team-relevant `verification_complete_<plan>` logged) → phase is **Shipped**
- `feature_closed` in FEATURE_LOG → phase is **Closed**
- When multiple status events exist for the same plan (e.g., multiple revision cycles), the most recent takes precedence.

**Canonical event names for FEATURE_LOG entries (per-plan suffix where applicable):**

| Event | Meaning | Source |
|-------|---------|--------|
| `assessment_complete_<plan>` | Per-plan test curation complete | `/drvr:assess` |
| `internal_review_complete_<plan>` | Per-plan standards review complete | `/drvr:review` |
| `handoff_docs_<plan>` | Per-plan PR docs generated | `/drvr:docs-artifacts` |
| `pr_created_<plan>` | Plan PR opened | `/drvr:open-pr` |
| `pr_approved_<plan>` | Plan PR approved by reviewer | sdlc-orchestration |
| `pr_merged_<plan>` | Plan PR merged to its Base Branch | sdlc-orchestration |
| `verification_complete_<plan>` | Post-merge verification for plan passed | sdlc-orchestration |
| `feature_shipped` | All plan PRs merged, feature shipped | sdlc-orchestration |
| `feature_closed` | Feature abandoned/closed | sdlc-orchestration |

`<plan>` is the plan filename without `.md` (e.g., `01-token-store`).

---

## Loop Handling

The lifecycle is not linear. These backward transitions are normal:

| Loop | When It Happens | What to Do |
|------|----------------|------------|
| Validation → Planning | Dry-run found gaps | User reviews gaps, fixes plan |
| Implementation → Rework | User rejects a deviation | Return to implementation to fix |
| Implementation → Research | Unknown discovered during implementation | Research the unknown, update plan |
| Bookkeeping → Planning | Cascade affects a downstream plan | User updates the downstream plan |
| Next Plan → Research | Next plan needs research first | Start research for new topic |
| Planning → Research | Planning surfaces unanswered question | Research the question first |
| Materialization → Planning | materialize-tasks blocks on gaps or missing codebase | Fix plan, re-approve |
| Implementation → Materialization | Pre-flight finds stale task docs | Re-materialize affected tasks |
| Research → Intent | Gap surfaced that requires re-mining intent | Resume `intent-guidance`, update `00-intent.md` |
| Per-plan PR Review → Revision | Review comments on plan PR require code changes | Make changes on plan's Feature Branch, push, optionally re-run `/drvr:docs-artifacts <plan>` and update PR body |
| Per-plan Revision → PR Review | Changes pushed, awaiting re-review | Check PR status on next resumption |
| Per-plan PR Review → Implementation | Review surfaces significant issue | Return to implementation (or planning) for THIS plan. PR remains open as discussion thread. On return after rework, update PR body via `gh pr edit`. |
| Per-plan Verification → Implementation | Verification fails | Debug issue, fix in place on plan's Feature Branch or split into a follow-up plan/PR |
| Plan N PR Review → Plan M Rebase | Upstream PR (Plan N) revised with interface change | Rebase Plan M+ branches on the updated upstream; re-run cascade-check if interfaces changed |

When a loop occurs, note: "Going back to [phase] because [reason]."

---

## Feature Log

`FEATURE_LOG.md` at the feature root is the source of truth for lifecycle state. It tracks phase transitions and artifact creation — not individual task completions or research questions (those live in their respective files).

### When to Update the Log

Each skill appends to the log at transition moments:

| Skill | Events to Log |
|-------|--------------|
| `/drvr:feature` | Feature created, research started |
| `intent-guidance` | Intent started, Intent captured, Intent skipped (if applicable) |
| `research-guidance` | Research doc created, wireframe created |
| `planning-guidance` | Planning started, overview created, plan created |
| `/drvr:dry-run-plan` | Dry-run completed (with gap count and verdict) |
| `materialize-tasks` | Tasks materialized (with task count and codebase target) |
| `implementation-guidance` | Implementation started, implementation complete (with test count) |
| `/drvr:assess` | Per-plan assessment complete (event: `assessment_complete_<plan>`, with prune/keep/promote counts) |
| `/drvr:review` | Per-plan internal review complete (event: `internal_review_complete_<plan>`, with violation/fix counts) |
| `/drvr:docs-artifacts` | Per-plan handoff docs generated (event: `handoff_docs_<plan>`) |
| `/drvr:open-pr` | Per-plan PR opened (event: `pr_created_<plan>`, with URL) |
| `sdlc-orchestration` | Per-plan bookkeeping complete, per-plan PR status changes (`pr_approved_<plan>`, `pr_merged_<plan>`, `verification_complete_<plan>`), feature shipped, feature closed |

Additionally, all skills that make significant decisions should append to `DECISIONS.md` at the feature root — see individual skill checklists for decision-logging triggers.

### Log Entry Format

Append a row to the log table:
```markdown
| <YYYY-MM-DD> | <event description> | `<artifact path>` |
```

Update the "Current State" header to reflect the new phase and active work.

---

## Graceful Degradation

- **No `FEATURE_LOG.md`** → check for `research/` and `plans/` directories to infer phase. Offer to create the log.
- **No `plans/00-overview.md`** → phase detection only. Skip transition suggestions and cascade checks.
- **No `research/` directory** → skip research completeness checks
- **Feature doesn't follow standard structure** → describe what you see, ask user to clarify
- **No projects directory** → skip cross-feature scan, omit `Cross-feature dependencies:` line

---

## Before Responding Checklist

- [ ] **Feature log?** — Did I update FEATURE_LOG.md for phase transitions?
- [ ] **Decision log?** — For phase transition decisions (proceeding despite open questions, skipping phases), did I append to DECISIONS.md?

---

## Related

- [/drvr:feature](../../commands/feature.md) — create a new feature project
- [/drvr:orchestrate](../../commands/orchestrate.md) — resume an existing feature
- [research-guidance](../research-guidance/SKILL.md)
- [planning-guidance](../planning-guidance/SKILL.md)
- [materialize-tasks](../materialize-tasks/SKILL.md)
- [implementation-guidance](../implementation-guidance/SKILL.md)
- [/drvr:dry-run-plan](../../commands/dry-run-plan.md)
- [/drvr:assess](../../commands/assess.md)
- [/drvr:review](../../commands/review.md)
- [/drvr:docs-artifacts](../../commands/docs-artifacts.md)
- [cascade-check](../../agents/cascade-check.md)
- [driver-task-context](../../agents/driver-task-context.md)
