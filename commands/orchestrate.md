---
description: Resume work on a feature project — read the feature log, report current state, suggest next action
argument-hint: <feature-path>
allowed-tools: Read, Write, Edit, Glob, Grep, Agent
---

# /drvr:orchestrate Command

Resume work on an existing feature project.

## Locate Feature

1. **If argument provided**: Use it as the feature path (e.g., `features/support-ticket-analysis`)
2. **Else scan cwd**: Look for `FEATURE_LOG.md` in the current directory
3. **Scan parent directories**: Check up to 3 levels up for `FEATURE_LOG.md`
4. **Ask user**: "I can't find a feature project. Which directory should I use?"

Once located, activate the `drvr:sdlc-orchestration` skill for session resumption — it handles reading the feature log, reporting state, and suggesting next actions.
