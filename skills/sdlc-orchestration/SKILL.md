---
name: sdlc-orchestration
description: |
  SDLC lifecycle orchestration. Coordinates phase transitions, loads the right skills,
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

When you detect an entry signal, ensure the corresponding skill is active. If the user is in research and says "let's plan", acknowledge the transition and activate planning-guidance.

---

## Session Resumption

When a user returns to a feature ("returning to feature/X", "resume feature X", "where are we on X"):

1. **Locate the feature directory** — resolve the path to the feature project
2. **Read `plans/00-overview.md`** — progress table, dependency graph, gaps
3. **Check for in-progress work:**
   - Implementation logs without a matching plan status header → implementation was in progress
   - Plan files without dry-run results → plan needs validation
   - Research docs with open questions → research may be incomplete
4. **Report current state:**

```
Feature: <name>
Progress: N/M plans complete
Current state: <what's in progress or what's next>
Last activity: <most recent artifact modified>
Next action: <suggestion based on state>
```

If no overview exists, check for `research/` and `plans/` directories to infer the phase.

---

## Transition Boundaries

### Research → Planning
When the user signals "let's plan" or "ready to plan":
- Report research status: "N research docs. M open questions remain in docs X, Y."
- This is informational — the user decides whether to proceed or resolve questions first
- Activate `planning-guidance`

### Planning → Validation
When a plan is written:
- If the feature has an overview with interface contracts, run consumer validation: check whether downstream plans' assumptions match this plan's definitions
- Suggest: "Want to run `/dry-run-plan <name>`?"

### Validation → Implementation
When the user wants to implement:
- Check if a dry-run exists for the plan. If not, note: "No dry-run found for this plan."
- The user decides whether to proceed without one

### Implementation → Review Deviations
When implementation-guidance reports all tasks complete:
- **Present the deviation summary** from the implementation log
- Let the user review each deviation
- Ask: "Are these deviations acceptable, or would you like to go back and address any of them?"
- If the user wants changes → return to implementation for rework
- If the user approves → proceed to bookkeeping

### Review → Bookkeeping
After the user approves deviations:
- Update plan status header (mark checkboxes, add Implementation Status)
- Update overview progress table
- Spawn [cascade-check](../../agents/cascade-check.md) agent to analyze whether deviations affect downstream plans
- Present cascade results to user
- Commit bookkeeping: `"chore: Update plan status and overview for plan <name>"`

### Bookkeeping → Next Plan
After bookkeeping is complete:
- Read overview dependency graph
- Identify unblocked plans (all dependencies COMPLETE)
- Present: "Next unblocked plan is X. It [has a plan document / needs planning]."
- If multiple unblocked: "Two plans are unblocked: X and Y. Which to start?"
- If none unblocked: "No plans are currently unblocked."
- If all complete: "All plans complete. Run `/assess` to curate the test suite before handoff."

### All Complete → Assessment

When all plans are complete, the next step is test suite assessment — not handoff.

- "All plans complete. Next step: `/assess` to curate the test suite before handoff."
- `/assess` handles the workflow independently and updates the feature log when done
- After `/assess` completes, suggest `/docs-artifacts`
- Do NOT suggest `/docs-artifacts` until assessment is complete

**Mid-implementation assessment**: Users may invoke `/assess` before all plans are complete. This is allowed — `/assess` handles scoping and warnings internally. A partial assessment does not satisfy the mandatory pre-handoff requirement; the final assessment must cover all plans.

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

When a loop occurs, note: "Going back to [phase] because [reason]."

---

## Feature Log

`FEATURE_LOG.md` at the feature root is the source of truth for lifecycle state. It tracks phase transitions and artifact creation — not individual task completions or research questions (those live in their respective files).

### When to Update the Log

Each skill appends to the log at transition moments:

| Skill | Events to Log |
|-------|--------------|
| `/feature` | Feature created, research started |
| `research-guidance` | Research doc created, wireframe created |
| `planning-guidance` | Planning started, overview created, plan created |
| `/dry-run-plan` | Dry-run completed (with gap count and verdict) |
| `implementation-guidance` | Implementation started, implementation complete (with test count) |
| `/assess` | Assessment complete (with prune/keep/promote counts) |
| `sdlc-orchestration` | Bookkeeping complete, phase transitions |

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

## Related

- [/feature](../../commands/feature.md) — create a new feature project
- [/orchestrate](../../commands/orchestrate.md) — resume an existing feature
- [research-guidance](../research-guidance/SKILL.md)
- [planning-guidance](../planning-guidance/SKILL.md)
- [implementation-guidance](../implementation-guidance/SKILL.md)
- [/dry-run-plan](../../commands/dry-run-plan.md)
- [/assess](../../commands/assess.md)
- [/docs-artifacts](../../commands/docs-artifacts.md)
- [cascade-check](../../agents/cascade-check.md)
- [driver-task-context](../../agents/driver-task-context.md)
