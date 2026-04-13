---
description: Analyze current session — evaluate work quality, identify improvements, think about what's next
argument-hint: [--write]
allowed-tools: Read, Write, Edit, Bash, Glob, Grep
---

# /driver-retro Command

Reflect on the current session. Evaluate work quality, identify systemic improvements, and think creatively about what's next — for the workflow, the plugin, and the product.

## Workflow

### Step 1: Check for --write flag

If arguments contain `--write`, skip the interactive discussion (Steps 6-7) and write directly.

### Step 2: Gather Context

Read these before analyzing:

1. **FEATURE_LOG.md** — if the session was on a feature, read the log for full lifecycle context
2. **Previous retros** — scan `retrospectives/INDEX.md` for recurring patterns
3. **MEMORY.md** — check `~/.claude/projects/-Users-adamtilton/memory/MEMORY.md` to avoid suggesting things already captured
4. **Plugin manifest** — `~/.claude-plugin/plugin.json` for available skills/agents/commands

### Step 3: Identify what happened

Determine:
- What SDLC phase was this session in? (Check FEATURE_LOG.md if available)
- What was it trying to accomplish?
- Did it achieve its goal?
- If the session spanned multiple phases, note each transition

**Context compaction note**: If the conversation was compacted, note which portions are missing from your analysis.

Phase signals:

| Phase | Signals |
|-------|---------|
| Research | `/feature`, `research-guidance`, writing to `research/*.md`, web/code exploration |
| Planning | `planning-guidance`, writing to `plans/*.md`, `/dry-run-plan` |
| Implementation | Code edits, test writing, git commits, `implementation-guidance` |
| Handoff | `/docs-artifacts`, writing to `driver-docs/` |
| Mixed | Multiple unrelated tasks, general Q&A |

### Step 4: Evaluate work quality

Evaluate artifacts against the phase-specific criteria below. Read the actual files — don't guess from conversation summaries.

### Step 5: Think forward

This is the most important step. Go beyond "what happened" to "what should happen next."

**Pattern Analysis** — Read `retrospectives/INDEX.md`. Are the same gaps appearing across sessions? Recurring gaps = systemic issues that need skill/command changes, not one-off fixes.

**Artifact Value** — The feature creates research docs, plans, dry-runs, implementation logs, wireframes, test plans. For each artifact type produced in this session, ask:
- Is this artifact being used to its full potential?
- Could it serve a downstream purpose? (Research → blog post, plan → Linear tickets, implementation log → onboarding doc, wireframe → design spec)
- Is the format optimized for both human and LLM consumption?

**Workflow Innovation** — Think outside the current workflow:
- What manual steps could become skills, commands, or agents?
- What integrations would make this more powerful? (Linear, Notion, GitHub, Slack)
- What visualization would help? (Dependency graphs, progress dashboards, diff views)
- What would make this workflow valuable to other teams or as a marketplace plugin?

**Product Thinking** — The SDLC orchestration is itself a product:
- What would the ideal user experience look like?
- Where is the friction that a product (app, tool, integration) could solve?
- What would a marketplace version of this plugin need?
- How could the markdown artifacts become interactive (web UI, dashboards)?

### Step 6: Present the analysis

Present the retrospective using the output template below. This is a draft for discussion — do NOT write to a file yet.

### Step 7: Discuss with user

The user may push back, add context, or ask to expand sections. Revise as needed. When the user says "write it" or "looks good" — proceed to Step 8.

### Step 8: Write the retro

1. Write to: `retrospectives/YYYY-MM-DD-<short-id>.md`
   - Use today's date and first 6 chars of session ID
2. Append one row to `retrospectives/INDEX.md`

INDEX.md row format:
```
| <YYYY-MM-DD> | <short-id> | <phase> | <summary under 100 chars> | <top suggestion> |
```

---

## Phase-Specific Evaluation

### Research Phase

**Structure & Method**:
- Why → What → How progression followed?
- Questions inline with content, resolved questions preserved?
- `00-overview.md` effective as entry point?
- Driver MCP and web research used where appropriate?
- Wireframes created for UI research?

**Planning Readiness** — could someone start writing a plan from these artifacts?
- Problem statement clear?
- Key decisions made (not "TBD")?
- Trade-offs explored with evidence?
- Scope boundaries defined?

### Planning Phase

**Plan Quality**:
- Research context read first?
- Architecture patterns from Driver used?
- Constraints explicit and specific?
- Task breakdown granular enough for subagents?
- Test strategy with specific test cases?
- TDD task ordering (tests before implementation)?

**Implementation Readiness** — could someone implement without asking questions?
- Overview created for multi-plan features?
- Interface contracts defined between plans?
- Consumer validation run on downstream plans?
- `/dry-run-plan` run and gaps addressed?

### Implementation Phase

- TDD followed? Tests before implementation?
- Commits at task boundaries?
- Implementation log maintained?
- Deviations tracked and reviewed?
- Bookkeeping completed (plan status, overview, cascade check)?
- FEATURE_LOG.md updated?

### Mixed / Ad-hoc

- Should any work be formalized into a feature project?
- Were there repeated patterns suggesting a workflow that needs structure?

---

## Writing Style

Follow Simplified Technical English (STE):

- No subjective qualities ("robust", "comprehensive", "elegant")
- No speculative language ("likely", "probably", "might")
- Action verbs first. "Invoked at line 12" not "The skill was invoked at line 12"
- No self-referential preamble ("In this retro...", "After analyzing...")
- Reference file paths, content, decisions — not abstractions

**Usefulness test**: Specific enough to act on AND concise enough to consume quickly.

**Brevity tiers**:
- INDEX.md: single sentence, under 100 chars
- Observations: one line — file ref + fact + implication
- Suggestions: exact change, no explanation unless non-obvious
- Empty sections: "Nothing to add."

---

## Output Template

```markdown
# Session Retro: <YYYY-MM-DD HH:MM>

**Session ID:** <session_id>
**Working Directory:** <cwd>
**Phase:** <Research | Planning | Implementation | Handoff | Mixed>
**Feature:** <feature name, if applicable>
**Goal:** <1 sentence>
**Outcome:** <1 sentence>

---

## Work Quality

<Evaluate artifacts against phase criteria. Reference specific files. What's strong? What's missing? What blocks the next phase?>

## Orchestration

<Did skills/agents/commands help? What should have fired but didn't (cite the specific moment)? Was FEATURE_LOG.md maintained?>

## Recurring Patterns

<Check INDEX.md for patterns across sessions. Same gap appearing 3+ times = systemic issue. "Gap X appeared in retros from <dates> — this is a pattern, not an incident.">

## Artifact Opportunities

<For each artifact type produced: could it serve a downstream purpose? Research → blog posts? Plans → tickets? Logs → onboarding? Be specific about which artifacts and how.>

## Innovation Ideas

<Think outside the current workflow. New skills, integrations, visualizations, product ideas. What would make this dramatically better, not incrementally better?>

## Suggestions

### For the Plugin
- [ ] <specific skill/agent/command change>

### For the Workflow
- [ ] <specific process change>

### For the Product
- [ ] <bigger ideas — marketplace, apps, integrations>

### For MEMORY.md
- [ ] <exact addition with section reference>
```

Use "Nothing to add." for any section with no actionable observations.

---

## Anti-Patterns

1. **Don't produce tool frequency tables.** Only mention tool usage when it impacted work quality.
2. **Don't summarize what happened.** Evaluate quality and push forward.
3. **Don't pad empty sections.** "Nothing to add." is correct.
4. **Don't suggest things already in MEMORY.md.** Check first.
5. **Don't flag "missing skills" without a concrete moment.** Cite when it would have changed behavior.
6. **Don't play it safe.** The innovation section should contain ideas that feel ambitious. "Build a web dashboard for feature progress" is better than "consider adding a progress command."
7. **Don't ignore previous retros.** Recurring patterns are the highest-signal findings.

## Constraints

- Do NOT modify MEMORY.md. Only recommend changes in suggestions.
- Do NOT modify any files except writing the retro and appending to INDEX.md.
- Do NOT create any other files.
