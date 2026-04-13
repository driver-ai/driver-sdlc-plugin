---
description: Resume work on a feature project — read the feature log, report current state, suggest next action
argument-hint: <feature-path>
allowed-tools: Read, Write, Edit, Glob, Grep, Agent
---

# /orchestrate Command

Resume work on an existing feature project. Reads the feature log to determine where you left off and suggests the next action.

## Step 1: Locate Feature

1. **If argument provided**: Use it as the feature path (e.g., `features/support-ticket-analysis`)
2. **Else scan cwd**: Look for `FEATURE_LOG.md` in the current directory
3. **Scan parent directories**: Check up to 3 levels up for `FEATURE_LOG.md`
4. **Ask user**: "I can't find a feature project. Which directory should I use?"

## Step 2: Read Feature Log

Read `FEATURE_LOG.md` at the feature root. The "Current State" section tells you:
- **Phase** — Research, Planning, Validation, Implementation, Assessment, or Done
- **Active** — which plan or research topic is in progress
- **Last updated** — when the log was last written

The log table below shows the full history of transitions and artifacts.

If `FEATURE_LOG.md` doesn't exist, check for `research/` and `plans/` directories to infer the phase. Suggest creating the log: "This feature doesn't have a FEATURE_LOG.md. Want me to create one based on what I see?"

## Step 3: Report Current State

Present the state to the user:

```
Feature: <name>
Phase: <current phase>
Active: <what's in progress>
Progress: N/M plans complete (if overview exists)
Last activity: <most recent log entry>
```

If an overview exists at `plans/00-overview.md`, include the progress table.

## Step 4: Suggest Next Action

Based on the current phase, suggest what to do:

| Phase | Suggestion |
|-------|-----------|
| Research | "Research is active. Last doc created: <X>. Continue exploring or say 'let's plan' when ready." |
| Planning | "Planning is active. Last plan created: <X>. Continue writing plans or dry-run when ready." |
| Validation | "Plan <X> was dry-run. Review the results at `dry-runs/<file>`." |
| Implementation | "Plan <X> is being implemented. Check `implementation/log-<X>.md` for progress." |
| Assessment | "All plans complete. Run `/assess` to curate the test suite before handoff." |
| Done | "Assessment complete. Run `/docs-artifacts` for handoff documentation." |

If the phase is between activities (e.g., a plan was just completed but the next hasn't started), use the overview's dependency graph to identify the next unblocked plan:
- "Plan 01a is complete. Next unblocked: 01b. It has a plan document."
- "Two plans are unblocked: 03 and 05. Which to start?"

The user decides what to do — you suggest, they choose.

### Phase Detection: Assessment

- All plans COMPLETE in overview but no `assessment/test-curation-*.md` → phase is **Assessment**
- Assessment artifact exists that covers all plans (check Scope line) → phase is **Done**
- Partial assessment exists but plans remain → phase is still **Implementation**

---

## Notes

- The feature log is the source of truth for lifecycle state — not inferred from artifacts
- Each phase-specific skill updates the log at transitions (see [sdlc-orchestration](../skills/sdlc-orchestration/SKILL.md))
- For boundary detection rules and transition guidance, see the orchestration skill
- If the feature log is out of date, offer to update it based on current artifacts
