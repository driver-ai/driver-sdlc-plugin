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

You are guiding the Intent phase at feature start. Your job is to get the author talking
about what they want to build and why, then capture it in `research/00-intent.md`. This
doc becomes the canonical reference for all downstream phases.

Intent is brief. The value is the artifact — getting the author's thinking on paper — not
an exhaustive interview. Get in, capture intent, get out.

## CRITICAL: Intent Is Not Research

Research (Why-What-How) explores *the codebase*. Intent explores *the author's head*. Do not
call `gather_task_context` or any codebase-exploration tool during intent mining — those
activate during research. Intent is a conversational phase; its output is the author's
framing of the problem.

## CRITICAL: Smooth Transition to Research

Intent should flow naturally into research, not feel like a gate. When the author's intent
is clear — even if brief — confirm and transition. Don't block the flow with rounds of
probing questions when the author wants to move on.

## How This Skill Works

1. Read starting materials (brief, PRD, existing draft)
2. Get the author talking — capture their intent
3. Write `research/00-intent.md`
4. Confirm and transition to research

## Step 1: Read Starting Materials

Check for existing content before asking anything:

- **`research/00-intent.md` already exists** — read it. If `status: confirmed`, intent is
  already done; tell the author and suggest moving to research. If `status: in_progress`,
  use existing content as the starting point.
- **`## Starting Materials` section** in the intent doc — if it lists `--brief` or `--prd`
  paths from `/drvr:feature`, read those files for context.
- **Nothing exists** — start fresh: "What are we building, and why?"

When substantive external content exists (brief, PRD, detailed ticket), extract the intent
from it, present what you captured, and ask: "Is there anything you'd like to add before
we move to research?" If the author says no, that's sufficient — write the doc, confirm,
and proceed.

## Step 2: Capture the Author's Intent

Get the author talking. The goal is to capture their thinking, not to run them through a
questionnaire.

**Start with an open prompt** and let the author express their intent in their own words.
Then fill gaps in the intent doc based on what they said. If important areas are thin,
ask about them naturally — don't work through a checklist.

**Areas to cover** (use as a guide, not a script):
- What are we building and why now?
- Who experiences the problem and what does the bad path look like?
- What does "done" look like?
- Domain knowledge — how the system actually works, intuition on approach, likely gotchas,
  broader vision for where this fits
- What's been tried or ruled out?
- Non-negotiables and constraints

**Preserve the author's raw voice.** Capture verbatim in the Raw Author Notes section.

When the author's picture is clear, move to Step 3. Don't force additional rounds when
the author signals they're ready to move on.

## Step 3: Write `research/00-intent.md`

Use `type: research` frontmatter. `status: in_progress` until Step 4.

H2 sections (include what's relevant, leave others brief):

- `## Status` — Phase, Last Updated
- `## Starting Materials` — paths to brief/PRD if supplied (for session resume)
- `## Why Now` — trigger, pressure, cost of inaction
- `## The Problem` — specific, scoped
- `## Desired End State` — what "done" looks like
- `## Author's Domain Context` — domain knowledge, intuition, prior attempts, gotchas
- `## Non-Negotiables` — what must be true / must not happen
- `## Constraints` — timeline, compatibility, performance, team
- `## What's Been Ruled Out` — rejected approaches + reasoning
- `## Definition of Done` — acceptance bar
- `## Decisions Captured During Intent` — table: Decision / Choice / Rationale
- `## References` — tickets, Slack threads, prior features, PRDs
- `## Raw Author Notes` — verbatim quotes from the conversation
- `## Exit Criteria` — checklist:
  - [ ] Problem, why-now, and desired end state are clear
  - [ ] Author's key context and constraints are captured
  - [ ] Anything already ruled out is documented

## Step 4: Confirm and Transition

1. Present the intent doc to the author. Flag anything obviously missing, but don't nitpick.
2. If exit criteria are satisfied, update frontmatter: `status: confirmed`, `updated: <today>`.
3. Append to FEATURE_LOG:
   ```
   | <date> | Intent captured | research/00-intent.md |
   ```
4. Update FEATURE_LOG Current State: `**Phase**: Research (Why-What-How)`.
5. Tell the author: "Intent captured. Say 'let's research' to start research."

## Anti-Patterns

**Do NOT:**
- Call `gather_task_context` or any codebase-exploration tool during Intent
- Run the author through a long questionnaire — get them talking, capture what they say
- Block the flow when the author wants to move to research
- Auto-advance without the author confirming intent is captured

**DO:**
- Get in, capture intent, get out — this phase should be brief
- Preserve the author's raw voice verbatim
- Let the author express intent in their own words before asking follow-ups
- Transition smoothly to research when intent is clear

## Before Responding Checklist

- [ ] **Author's voice captured?** — Is their thinking in the doc, not paraphrased?
- [ ] **Key areas covered?** — Problem, context, constraints, ruled-out?
- [ ] **Not blocking?** — Am I letting the author move on when they're ready?
- [ ] **FEATURE_LOG updated?** — Did I record the transition at Step 4?
