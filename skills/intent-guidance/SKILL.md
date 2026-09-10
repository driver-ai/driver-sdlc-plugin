---
name: intent-guidance
description: |
  Guide intent mining at the very start of a feature — extract the author's tacit knowledge,
  domain context, constraints, and definition of done before codebase research begins. Captures
  intent in the established local feature artifacts or Linear operator document.
  Trigger phrases: "capture intent", "intent mining", "start intent", "mine intent".
  Do NOT activate for: "let's research", "explore the codebase", "gather context" —
  those activate research-guidance.
---

# Intent Mining

## Entry: Delivery, Authority, and Organization

Read [Symphony workflow](../../references/symphony-workflow.md) and
[Linear organization](../../references/linear-organization.md) before choosing an artifact
or applying phase prerequisites. Their authority, durable-record, checkpoint, and recovery
rules apply to both delivery paths below.

Record **Delivery: Symphony** for an established request to prepare Symphony worker work,
or **Delivery: Local** for local implementation. Use explicit task context; the repository
name does not select delivery. Intent can proceed while delivery is unresolved. Clarify
before choosing an execution path or publishing an execution contract.

### Meaningful Intent Challenge

Challenge assumptions that could change the outcome: is the stated problem supported,
what is the smallest useful result, can an existing mechanism do the job, and what would
make this work unnecessary or unsuccessful? Surface one or a few consequential tensions
from the actual context, including duplicate sources of truth, premature abstraction,
or a costly mechanism without an observed need. Explain the tradeoff and record the
resolution. Do not impose an interview quota or relitigate settled intent without new evidence.

### Symphony or Unresolved Delivery

1. Read the established intent, current summary, relevant decisions, and recent history.
   Reuse context already supplied. Read known Linear records or source documents as needed
   to recover context and organize the work; substantive technical investigation belongs
   in research. Do not invoke Driver MCP or a Driver-backed agent.
2. Capture the problem, why now, desired outcome, domain context, constraints, exclusions,
   definition of done, and the author's key notes. Ask only for material missing information.
   Apply the meaningful challenge above while preserving the author's voice.
3. Keep scope and placement provisional where appropriate. Search/reuse the smallest useful
   Linear home using the organization reference. Capture tangents and deferrals with their
   origin, value, deferral reason, destination or uncertainty, and revisit condition.
   Creating an Initiative or Project is not an intent prerequisite.
4. Save working intent in the canonical home: existing local feature artifacts remain in
   use; Linear-native work uses the operator document's working intent section, Current
   State, Decisions, and append-only Activity Log. Reuse an already durable plan/log rather
   than create another editable record. Follow the shared checkpoint/recovery rules.
5. Reflect the agreed intent and unresolved decisions to the user. Continue to research
   when it is within the existing request; ask only for a material decision still needed.
   Record the actual next action and any pending save/synchronization.

This completes the intent procedure for Symphony or unresolved delivery. Do not continue
into the Local artifact procedure below.

## Local Intent Procedure

The remaining sections apply to **Delivery: Local**. Shared authority and safe bookkeeping
still apply; an explicit user instruction takes precedence over these plugin defaults.

You are guiding the Intent phase at feature start. Your job is to get the author talking
about what they want to build and why, then capture it in `research/00-intent.md`. This
doc becomes the canonical reference for all downstream phases.

Intent is brief. The value is the artifact — getting the author's thinking on paper — not
an exhaustive interview. Get in, capture intent, get out.

## CRITICAL: Intent Is Not Research

Research (Why-What-How) investigates the technical problem. Intent captures the author's
framing. Read existing intent, briefs, decisions, and known organization records to recover
context without making the author repeat it. Defer substantive codebase investigation to
research; intent does not require `gather_task_context` or another technical context agent.

## CRITICAL: Smooth Transition to Research

Intent should flow naturally into research, not feel like a gate. When the author's intent
is clear — even if brief — confirm and transition. Don't block the flow with rounds of
probing questions when the author wants to move on.

## How This Skill Works

1. Check for existing content, then get the author talking
2. Capture their intent — conversationally
3. Write `research/00-intent.md`
4. Confirm and transition to research

## Step 1: Get the Author Talking

**The best intent comes from the author just expressing it.** Start with "What are we
building, and why?" and let them talk. Dictation, stream of consciousness, rough
notes — all work. The richer the initial dump, the fewer follow-ups needed.

Check for existing content first:

- **`research/00-intent.md` already exists** — read it. If `status: confirmed`, intent is
  already done; tell the author and suggest moving to research. If `status: in_progress`,
  use existing content as the starting point.
- **`--brief` or `--prd` was supplied** — read the file for context. Extract intent from
  it, present what you captured, and ask if there's anything to add.
- **Nothing exists** — start fresh: "What are we building, and why?"

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
5. If research is already authorized, record the transition and continue. Otherwise report
   that intent is captured and research is the next available phase.

Apply the meaningful intent challenge above before treating an unresolved material
assumption as confirmed. Save and commit only owned artifact changes using the shared
checkpoint rules; report a pending save or commit honestly.

## Anti-Patterns

**Do NOT:**
- Turn intent into a technical investigation; context recovery and organization reads are allowed
- Run the author through a long questionnaire — get them talking, capture what they say
- Block the flow when the author wants to move to research
- Treat an unresolved material intent decision as confirmed; existing confirmation need not be repeated

**DO:**
- Get in, capture intent, get out — this phase should be brief
- Preserve the author's raw voice verbatim
- Let the author express intent in their own words before asking follow-ups
- Transition smoothly to research when intent is clear

## Before Responding Checklist

- [ ] **Author's voice captured?** — Are their key notes preserved without inventing quotes?
- [ ] **Meaningful challenge?** — Are consequential assumptions and their resolutions visible?
- [ ] **Key areas covered?** — Problem, context, constraints, ruled-out?
- [ ] **Not blocking?** — Am I letting the author move on when they're ready?
- [ ] **FEATURE_LOG updated?** — Did I record the transition at Step 4?
