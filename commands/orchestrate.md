---
description: Resume evolving Symphony work or a Local feature from its durable records
argument-hint: <Linear link, work description, or feature-path>
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, Agent, Skill
---

# /drvr:orchestrate Command

## Resolve Delivery and Durable Home

Read the [operating contract](../references/symphony-workflow.md) and
[Linear organization rules](../references/linear-organization.md). Use the explicit
request and existing task record to select delivery; a repository name is insufficient.
Prior authorization and decisions persist across resumption. If delivery is unresolved,
continue useful intent/research and clarify before an execution path is selected.

### Delivery: Symphony

1. Accept an issue, project, initiative, existing artifact path, or description of the
   work. Resolve provided IDs/links and search relevant existing records before creating
   anything. Do not force a hierarchy selection or require a Local feature directory.
2. Reuse the existing local plan/log if this work already has one. Otherwise locate the
   Linear working record holding Current State, Working Notes for intent/research/plan,
   Decisions, and append-only Activity Log. It may be the existing issue for a small
   effort or an operator document for substantial research and cross-issue history.
   If it does not exist, use the Symphony path in `/drvr:feature` to establish the
   smallest useful home; do not duplicate a durable direct-issue preparation plan/log
   or create a project just to host a document. No `.driver` setup is needed.
3. Reconcile the latest log with current source/commit evidence and native Linear
   fields. Check previously attempted writes by returned ID or a scoped search before
   retrying. Leave ambiguous outcomes pending; never recreate an entity solely because
   a previous response was interrupted. Inspect inherited dirt without committing it.
4. Report the current objective, canonical home, completed/uncertain work, captured
   deferrals, and next authorized action. Keep deferred work linked to its origin and
   revisit condition. Append corrections and recovery outcomes rather than rewriting
   history. A temporary local draft remains pending sync until reconciliation succeeds.
5. Activate `drvr:sdlc-orchestration` with this context. Continue authorized phase work
   using its Symphony route, including the complete `drvr:linear-issue` skill for a
   handoff. Do not invoke Local task-doc execution gates, Driver agents, or worker
   dispatch as a side effect of resumption.

Return after handing off this context. The remaining lookup applies only to the
**Delivery: Local** feature-directory workflow.

## Delivery: Local — Locate Feature

1. **If argument provided**: Use it as the feature path (e.g., `features/support-ticket-analysis`)
2. **Else scan cwd**: Look for `FEATURE_LOG.md` in the current directory
3. **Scan parent directories**: Check up to 3 levels up for `FEATURE_LOG.md`
4. **Ask user**: "I can't find a feature project. Which directory should I use?"

Once located, activate the `drvr:sdlc-orchestration` skill for session resumption — it handles reading the feature log, reporting state, and suggesting next actions.

Resume from verified records and source state. Do not auto-commit discovered artifacts
or replay an interrupted write without establishing ownership and its actual outcome.
