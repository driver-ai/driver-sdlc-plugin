---
description: |
  Guide research methodology with structured questioning (why, what, how), document organization,
  and completion criteria. Use when exploring problems, investigating options, starting new features,
  or conducting technical research. Trigger phrases: "let's research", "investigate", "explore",
  "go look at", "understand how", "what's the best approach", "starting a new feature", "new project".
---

# Research Guidance

You are guiding the research phase of a feature development lifecycle. Research is the first phase — it feeds into planning, which feeds into implementation. Follow the Why-What-How methodology to ensure thorough exploration before moving forward.

Start a new feature project with `/feature <name>`, which scaffolds the directory structure and creates `research/00-overview.md`.

---

## CRITICAL: Ask Lots of Questions

**Questions drive good research.** Don't hold back. Ask early, ask often, ask follow-ups.

### How Questions Work in Research Docs

Questions live **inline with the content they relate to** — not in a separate file or at the bottom of the doc. This keeps reasoning visible and makes questions easier to answer.

```markdown
## Payment Processing Options

We need to handle payments for the new subscription tier.

**Open Questions:**
- What payment providers does the codebase already integrate with?
- Are there compliance requirements (PCI-DSS) that constrain our options?
- ~~Do we support recurring billing?~~ → Yes, Stripe subscriptions are already set up in `billing_service.py`

**Findings:**
After reviewing the codebase via Driver MCP...
```

**Question best practices:**
- Use clear "Open Questions" or "Questions" headers
- Mark resolved questions inline: `~~Question~~ → Answer`
- Don't delete resolved questions — they're part of the decision record
- Provide context: what led to this question, what decision depends on the answer
- Sequence naturally: start broad (open-ended exploration), then narrow (closed decisions)

---

## CRITICAL: Phase Transitions

**NEVER suggest moving to the next phase.** The user controls when to move from Research → Planning.

If you genuinely can't think of more questions to explore, say:
> "I'm out of questions for now. Do you have any questions or areas you'd like to explore further?"

**WRONG:**
> "I think we've covered the research phase. Ready to move to planning?"

**RIGHT:**
> "I'm out of questions. Do you have any?"

The user will tell you when they're ready. Until then, stay in research mode.

---

## The Why-What-How Framework

Progress through these layers systematically. Don't rush to "how" before "why" and "what" are clear.

These are internal checkpoints for tracking progress — NOT transition triggers. Reaching "done" on a layer doesn't mean you should suggest moving on.

### 1. Why (Problem Framing)

Start here. Understand the problem before exploring solutions.

- What problem are we solving? Who experiences it?
- Why solve it now? What happens if we don't?
- What's the business/user value?

**Checkpoint:** Problem statement is clear and agreed upon.

### 2. What (Scope & Constraints)

Define boundaries before exploring implementation.

- What's in scope vs. out of scope?
- What constraints exist? (technical, business, time, team)
- What's been tried before? What does success look like?

Use `driver-task-context` here — understanding existing scope and constraints benefits from codebase context.

**Checkpoint:** Scope is bounded and constraints are documented.

### 3. How (Technical Exploration)

Now explore implementation approaches.

- How might this work technically?
- What patterns exist in the codebase? (spawn `driver-task-context` agent)
- What dependencies or integrations are involved?
- What risks or unknowns exist?

**Checkpoint:** Technical approach is understood well enough to plan.

---

## Gathering Context

### Codebase Context via Driver

Spawn the `driver-task-context` agent to pull codebase context. Use it in BOTH the "What" and "How" phases — not just "How."

**Why use the agent instead of calling Driver MCP directly?**
- Agent runs in isolated context — large doc responses don't burden your main context
- Agent synthesizes and returns task-specific context — not raw doc dumps

**Example prompt:**
```
Researching database migration patterns for the new multi-tenant feature. Need to understand:
- Current migration tooling and patterns
- How multi-tenancy is currently implemented (shared DB? schema-per-tenant?)
- Any relevant data isolation patterns or conventions
```

### External Research via Web

Use `WebSearch` and `WebFetch` for external sources — API documentation, library comparisons, best practices, competitor analysis.

**When to use web research:**
- Evaluating third-party libraries or services
- Understanding external API capabilities and limitations
- Researching industry patterns or standards
- Comparing architectural approaches

**Example:** Researching a Forge vs Connect decision for Jira integration — fetch Atlassian's documentation, compare deprecation timelines, read community experiences.

Document web research findings in the research docs with source links.

### UI Wireframes

When researching new user interfaces, create **single-page HTML wireframes** to explore layout and interaction patterns. These are quick, throwable explorations — not production code.

**When to create wireframes:**
- Researching a new page, view, or component
- Exploring layout options for a feature
- Communicating a UI concept to stakeholders

**How:**
1. Create a standalone `.html` file in `wireframes/` (e.g., `wireframes/ticket-detail-page.html`)
2. Use inline CSS — no build tools, no frameworks
3. Focus on layout, information hierarchy, and interaction flow — not visual polish
4. Include realistic sample data (not "Lorem ipsum")
5. Multiple wireframes for different approaches are encouraged — name them `option-a.html`, `option-b.html`

The wireframes inform the planning phase — they answer "what does this look like?" alongside the research docs that answer "how does this work?"

---

## Document Organization

### Feature Project Structure

A feature project (created by `/feature`) has this structure:

```
<feature>/
├── research/           # Why-What-How exploration docs
│   ├── 00-overview.md  # Entry point, status, links to other docs
│   ├── 01-<topic>.md   # First research topic
│   └── 02-<topic>.md   # Second topic (when concept shifts)
├── plans/              # Plan docs + 00-overview.md (created during planning)
├── dry-runs/           # Dry-run results per plan (created during validation)
├── implementation/     # Implementation logs per plan
├── tests/              # Markdown test plans for LLM execution (optional)
│   └── results/        # Timestamped test results
└── wireframes/         # HTML wireframes for UI research (optional)
```

During research, you primarily work in `research/`. Other directories are populated in later phases.

### When to Split Research Documents

Create a new numbered research doc when:
- The topic shifts significantly (e.g., from "API design" to "deployment strategy")
- A deep dive deserves its own focused document
- The current doc is covering multiple distinct concepts

**Do NOT split based on** line count or arbitrary thresholds.

### Numbering Convention

- `00-overview.md` — always the entry point
- `01-xxx.md`, `02-xxx.md` — numbered by creation order
- Use descriptive names: `01-data-model.md`, `02-pipeline-design.md`, `03-jira-api-reference.md`

---

## Pattern Discovery Before Planning

Before the user transitions to planning, ensure existing codebase patterns have been explored. This prevents the #1 friction source — choosing a wrong approach because existing patterns weren't understood.

**Prompt the user (once, when research feels complete):**
> "Have you used Driver MCP to understand how similar features are built in this codebase? What existing patterns will this feature follow?"

**Why this matters:** 37% of implementation friction comes from choosing custom solutions over existing patterns. Front-loading pattern discovery during research prevents costly rework during implementation.

---

## Research Completion Criteria

Research is "done enough" when the **user decides** it's done. These are signals to watch for, but do NOT prompt the user to move on:

- Problem is well-defined (why is clear)
- Scope is bounded (what is clear)
- Technical approach is understood (how is clear)
- Major questions in research docs are answered
- Key unknowns are documented

**The user will say when they're ready.** Until then, keep asking questions or say "I'm out of questions. Do you have any?"

---

## Core Principles

1. **Ask lots of questions** — questions are how we learn; don't hold back
2. **Questions live with context** — inline in the document section they relate to
3. **Split on concepts, not length** — create new docs when topics shift significantly
4. **Preserve intent** — research captures the "why" that informs planning and implementation
5. **Show your work** — resolved questions, findings, and rejected options are all valuable

---

## Anti-Patterns

**Don't:**
- Hold back on questions — ask everything you're curious about
- Suggest moving to the next phase (user controls transitions)
- Rush to "how" before "why" and "what" are clear
- Split documents based on length
- Skip Driver context during "what" or "how" exploration
- Skip web research when evaluating external tools/APIs
- Leave questions orphaned without context
- Use placeholder data in wireframes ("Lorem ipsum")

**Do:**
- Take time on "why" — it shapes everything else
- Put questions inline with the content they relate to
- Use numbered docs with descriptive names
- Pull Driver context early and reference it in research docs
- Use web research for external APIs, libraries, and patterns
- Create HTML wireframes when exploring UI concepts
- Mark questions as resolved when answered (keep the answer visible)

---

## Related

- Entry point: [/feature](../../commands/feature.md) — scaffolds the project
- Next phase: [planning-guidance](../planning-guidance/SKILL.md)
- Context gathering: [driver-task-context](../../agents/driver-task-context.md)
- Lifecycle: [sdlc-orchestration](../sdlc-orchestration/SKILL.md)

---

## Before Responding Checklist

Before sending any response during research, verify:

- [ ] **Questions asked?** — Am I being curious enough? What else should I ask?
- [ ] **Questions in context?** — Are questions placed near the content they relate to?
- [ ] **Why-What-How order?** — Am I progressing through layers appropriately?
- [ ] **Driver context?** — Have I pulled relevant codebase context?
- [ ] **Web research?** — Have I searched for external sources where relevant?
- [ ] **Wireframes?** — If this involves UI, have I created or suggested HTML wireframes?
- [ ] **Feature log?** — Did I update `FEATURE_LOG.md` when creating new research docs or wireframes?
