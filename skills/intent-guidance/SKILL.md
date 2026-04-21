---
name: intent-guidance
description: |
  Guide intent mining at the very start of a feature — extract the author's tacit knowledge,
  domain context, constraints, and definition of done before codebase research begins. Produces
  `research/00-intent.md` which becomes the canonical reference for all downstream phases.
  Trigger phrases: "capture intent", "intent mining", "start intent", "mine intent".
  Do NOT activate for: "let's research", "explore the codebase", "gather context" —
  those activate research-guidance.
---

# Intent Mining

You are guiding the Intent phase at feature start. Your job is to extract the author's tacit
knowledge — domain context, hard-earned intuition, non-negotiables, constraints, and what
"done" looks like — BEFORE any codebase research begins. Produces `research/00-intent.md`,
the canonical reference for all downstream phases.

## CRITICAL: Intent Is Not Research

Research (Why-What-How) explores *the codebase*. Intent explores *the author's head*. Do not
call `gather_task_context` or any codebase-exploration tool during intent mining — those
activate during research. Intent is a conversational phase; its output is the author's
framing of the problem.

## CRITICAL: Phase Gate

Do NOT advance to research until the author confirms intent is captured. When the
intent doc covers the essentials — problem, context, constraints — confirm with the
author and move forward. Don't force exhaustive coverage of every section when the
author's picture is already clear.

## How This Skill Works

1. Read any starting materials — existing `research/00-intent.md` draft, `--brief <path>` file if supplied, `--prd <path>` file if supplied
2. Mine the author's thinking through pointed probing questions
3. Mine domain knowledge and hard-earned context
4. Surface non-negotiables and constraints
5. Write `research/00-intent.md`
6. Confirm with the author — phase gate

## Step 1: Understand the Starting Point

Read whatever exists before asking questions:

- If `research/00-intent.md` already exists (resuming from a prior session or hand-edited draft), read it fully. Use its existing content as the starting point — ask follow-ups on what's thin, don't ask again about what's already captured.
- If `commands/feature.md` was invoked with `--brief <path>`, read the brief file. Treat the brief as the author's raw dump — extract everything, then ask clarifying questions to deepen.
- If `--prd <path>` was supplied, read the PRD for product context. Pull relevant requirements into the intent discussion but don't copy-paste.
- If none of the above, start fresh with an open prompt: "What are we building, and why?"

**Lighter path for substantive external content**: when a brief, PRD, or detailed ticket
provides significant context, mine it for intent (extract problem, context, constraints,
what's been ruled out), present what you've captured in the intent doc, and ask the author:
"Is there anything else you'd like to add before we move to research?" If the author says
no, that's sufficient — confirm and proceed. Don't force the full Step 2-4 mining flow
when the external content has already done most of the work.

## Step 2: Mine the Author's Thinking

Ask pointed probing questions. Don't accept vague answers — push for specifics.

- **Problem and who experiences it**: What problem are we solving? Who experiences it? What does the bad path look like today?
- **Why now**: What event or pressure made this ripe? What happens if we don't solve it?
- **Value**: What's the business/user value? How will we know we succeeded?
- **Audience calibration**: Who consumes the output of this feature? (Engineers? End users? Ops? Internal stakeholders?)

If the author's first answer is one sentence, ask a follow-up. Two follow-ups is normal. Three is the sweet spot for surfacing non-obvious context.

## Step 3: Mine Domain Knowledge and Hard-Earned Context

This is usually the highest-value content and the first to be lost if not captured. Two
concerns, in priority order:

### Domain knowledge — what the author knows about the territory

- **Mental model**: How does this system or domain actually behave, vs. how it's documented or how a newcomer would assume? What would surprise someone approaching this cold?
- **Intuition on approach**: What methods or patterns are likely to be particularly effective here? What's likely to go wrong or be harder than it looks?
- **Unwritten rules**: Conventions, gotchas, or constraints in this area that aren't captured in code or docs — things you'd tell a teammate over coffee.
- **How users actually use it**: What do the real consumers of this system do, vs. what was designed for? Where do their workflows diverge from expectations?
- **Broader vision**: How does this feature fit into a larger trajectory? What are we working toward, and how does this move us closer?

### Problem-specific history — what the author has tried and learned

- **Prior attempts**: What have you already tried? What approaches did you rule out, and why?
- **Incidents and adjacent features**: Any past incidents that informed this? Related features that already exist (even in other codebases) that we should reference?
- **Undocumented context**: Conversations with teammates, customer reports, internal docs that aren't linked anywhere.
- **Code you already know**: Specific files, functions, or patterns the author has already looked at that informed the mental model.

**Preserve the author's raw voice.** Capture quotes verbatim in a "Raw Author Notes" section of the intent doc. Downstream phases (planning, implementation) benefit from the original framing, not paraphrased summaries.

## Step 4: Surface Non-Negotiables and Constraints

Explicit constraints beat implicit ones. Ask:

- **Non-negotiables**: What must be true of the solution? What should definitely NOT happen?
- **Constraints**: Timeline pressure? Compatibility requirements (versions, platforms, existing APIs)? Performance targets? Team capacity?
- **What's been ruled out**: Any approach the author has already considered and rejected — capture the rejection reasoning so future-us doesn't re-litigate.
- **Definition of done**: How will the author know the feature is shipped? What's the acceptance bar?

## Step 5: Write `research/00-intent.md`

Use `type: research` frontmatter (not `type: intent` — reuses existing allowed type). `status: in_progress` until Step 6.

Required H2 sections (in this order):

- `## Status` — Phase, Last Updated
- `## Why Now` — trigger, pressure, cost of inaction
- `## The Problem` — specific, scoped
- `## Desired End State` — what "done" looks like
- `## Author's Domain Context` — the tacit knowledge from Step 3
- `## Non-Negotiables` — from Step 4
- `## Constraints` — from Step 4
- `## What's Been Ruled Out` — rejected approaches + reasoning
- `## Definition of Done` — acceptance bar
- `## Decisions Captured During Intent` — table: Decision / Choice / Rationale
- `## References` — tickets, Slack threads, prior features, PRDs
- `## Raw Author Notes` — verbatim quotes from the conversation
- `## Exit Criteria` — a checklist the author checks off before transitioning to research

## Step 6: Confirm and Gate

When the author says intent is complete (or confirms the lighter path is sufficient):

1. Re-read the intent doc with the author. Flag anything obviously missing, but don't nitpick.
2. Confirm the exit criteria are satisfied — problem is clear, key context is captured, constraints are explicit.
3. Update `research/00-intent.md` frontmatter: `status: confirmed`, `updated: <today>`.
4. Append to FEATURE_LOG:
   ```
   | <date> | Intent captured | research/00-intent.md |
   ```
5. Update FEATURE_LOG Current State header: `**Phase**: Research (Why-What-How)`, `**Active**: Research — say "let's research" to activate research-guidance`.
6. Tell the author: "Intent confirmed. Say 'let's research' to activate `research-guidance`."

## Anti-Patterns

**Do NOT:**
- Call `gather_task_context` or any codebase-exploration tool during Intent
- Auto-advance to Research without explicit author confirmation
- Require exhaustive checklist completion when the author's picture is already clear
- Paraphrase the author's voice when a verbatim quote captures it better
- Skip past vague answers — ask a follow-up

**DO:**
- Ask pointed, specific follow-up questions
- Preserve the author's raw thinking verbatim in a "Raw Author Notes" section
- Capture what's been ruled out, not just what's in
- Surface constraints explicitly — timeline, compat, performance, team
- Mine domain knowledge and intuition, not just problem history
- Confirm exit criteria before transitioning to research

## Before Responding Checklist

- [ ] **Probing questions?** — Have I asked at least one follow-up that pushed past a vague first answer?
- [ ] **Raw dump preserved?** — Is the author's voice in the doc verbatim?
- [ ] **Non-negotiables and ruled-out captured?** — Both sides of the scope boundary?
- [ ] **Exit criteria present?** — Does 00-intent.md have exit criteria (light — 3 essentials)?
- [ ] **FEATURE_LOG updated?** — Did I record phase transitions at Step 6?
- [ ] **Gate respected?** — Am I waiting for explicit confirmation before suggesting "let's research"?
