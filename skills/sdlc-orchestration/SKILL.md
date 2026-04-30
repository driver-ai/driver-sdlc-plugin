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
   - Phase detection resolves to **Assessment** (all plans COMPLETE, no `assessment/test-curation-*.md`) → suggest `/drvr:assess`
5. **Report current state:**

```
Feature: <name>
Progress: N/M plans complete
Current state: <what's in progress or what's next>
Last activity: <most recent artifact modified>
Codebase: <name> at <local-path> (on <base-branch>)
Test command: `<cmd>`
Next action: <suggestion based on state — if assessment phase, "Run /drvr:assess to curate the test suite before handoff">
```

**Graceful degradation**: if `plans/00-overview.md` has no `## Implementation Environment` section (legacy features, or overview not yet created), omit the `Codebase:` and `Test command:` lines. Do NOT emit placeholder values.

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

### Bookkeeping → Next Plan
After bookkeeping is complete:
- Read overview dependency graph
- Identify unblocked plans (all dependencies COMPLETE)
- Present: "Next unblocked plan is X. It [has a plan document / needs planning]."
- If multiple unblocked: "Two plans are unblocked: X and Y. Which to start?"
- If none unblocked: "No plans are currently unblocked."
- If all complete: "All plans complete. Run `/drvr:assess` to curate the test suite before handoff."

### All Complete → Assessment

When all plans are complete, the next step is test suite assessment — not handoff.

- "All plans complete. Next step: `/drvr:assess` to curate the test suite before handoff."
- `/drvr:assess` handles the workflow independently and updates the feature log when done
- After `/drvr:assess` completes, suggest `/drvr:docs-artifacts`
- Do NOT suggest `/drvr:docs-artifacts` until assessment is complete

**Mid-implementation assessment**: Users may invoke `/drvr:assess` before all plans are complete. This is allowed — `/drvr:assess` handles scoping and warnings internally. A partial assessment does not satisfy the mandatory pre-handoff requirement; the final assessment must cover all plans.

### Phase Detection: Assessment

- All plans COMPLETE in overview but no `assessment/test-curation-*.md` → phase is **Assessment**
- Assessment artifact exists that covers all plans (check Scope line) → phase is **Handoff**
- Partial assessment exists but plans remain → phase is still **Implementation**

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
| `/drvr:assess` | Assessment complete (with prune/keep/promote counts) |
| `sdlc-orchestration` | Bookkeeping complete, phase transitions |

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
- [/drvr:docs-artifacts](../../commands/docs-artifacts.md)
- [cascade-check](../../agents/cascade-check.md)
- [driver-task-context](../../agents/driver-task-context.md)
