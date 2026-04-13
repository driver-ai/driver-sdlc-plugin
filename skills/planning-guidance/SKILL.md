---
name: planning-guidance
description: |
  Guide planning methodology with TDD-first task design, test strategy, architecture fit, explicit
  constraints, and task breakdown. Use when transitioning from research to planning phase.
  Trigger phrases: "let's plan", "ready to plan", "move to planning", "create a plan",
  "how should we implement", "test strategy", "what should I test", "TDD", "tests first".
---

# Planning Guidance

You are guiding the planning phase for a feature development lifecycle. Plans should be thorough enough to make implementation mechanical — good planning prevents wasted code, missed requirements, and agent laziness.

Planning includes test strategy and TDD methodology. Tests are a planning concern — they shape task ordering, acceptance criteria, and how each task is specified.

---

## CRITICAL: Write Plans to Files

**NEVER write plan content in chat.** Always write to `plans/*.md`.

### Before Creating Any Plan:

1. **Read research context** — Check `research/*.md` for prior exploration and resolved decisions
2. **Pull architecture AND testing patterns** — Spawn `driver-task-context` agent (see below)
3. **Create plan file** — Write to `plans/01-<name>.md` (or next available number)
4. **Tell the user** — "I've created a plan at `plans/01-<name>.md`. Please review."

---

## CRITICAL: Phase Transitions

**NEVER suggest moving to implementation.** The user controls when to move from Planning → Implementation.

When the plan feels complete, say:
> "The plan is ready for your review. Let me know if you have questions or want changes."

The ONE exception: you may suggest a dry-run, since dry-runs happen within planning:
> "Want to run `/dry-run-plan <name>` before implementation?"

---

## Before Planning: Read Research Context

Always start by reading existing research:

1. **Check for research docs** — `research/*.md`
2. **Review decisions made** — Look for resolved questions (marked with `~~Question~~ → Answer`)
3. **Check for wireframes** — `wireframes/*.html` if UI is involved
4. **Summarize in plan** — The Context section should reference research findings

If research doesn't exist or is incomplete, note this and ask if the user wants to do research first.

---

## Pull Architecture AND Testing Patterns via Driver

Before planning, spawn the `driver-task-context` agent to gather BOTH architecture patterns and testing conventions in a single call.

**Why the agent instead of direct MCP calls?**
- Agent runs in isolated context — large doc responses don't burden your main context
- Agent synthesizes and returns task-specific context — not raw doc dumps

**Example prompt:**
```
Planning implementation for [feature]. Need to understand:
- Current architecture patterns and conventions
- Files/directories that will be touched
- Existing patterns to follow for consistency
- Testing framework, file organization, fixture catalog, mocking patterns
- How to run tests (commands, configuration)
```

Also check if Driver has a **Testing Strategy Guide** for the codebase. If available, follow the codebase's established testing patterns exactly.

---

## Planning Overview for Multi-Plan Features

For features that span multiple plans, create `plans/00-overview.md` as the central coordination document. This is the most important planning artifact for non-trivial features.

### When to Create an Overview

- Feature will have 2+ plans
- Multiple codebases or components are involved
- Plans have dependencies on each other

### What the Overview Contains

```markdown
# <Feature Name> — Planning Overview

## Status
**Phase**: Planning
**Last Updated**: <date>

### Progress
| Plan | Status | Tests | Key Artifact |
|------|--------|-------|-------------|
| 01 <name> | NOT STARTED | — | <what it delivers> |
| 02 <name> | NOT STARTED | — | <what it delivers> |

## Planning Strategy
_Why the feature is broken into these plans, what order, what the rationale is_

## Dependency Graph
_ASCII diagram showing which plans depend on which_

## Interface Contracts Between Plans
_Key seams between plans — method signatures, data models, API routes, config_
_Each plan defines its interface; downstream plans develop against it_

## Gaps to Address in Downstream Plans
_Surfaced during implementation — deviations that affect other plans_

## Open Questions
- [ ] <unresolved decisions>
```

### Interface Contracts Are Critical

The interface contracts section prevents the most expensive planning failure: discovering during implementation that Plan B's assumptions don't match Plan A's definitions. Define contracts explicitly when writing each plan.

---

## Consumer Validation

After writing a plan, check whether downstream plans are compatible:

1. Read the overview's dependency graph — find plans that depend on this one
2. For each downstream plan that already exists as a document:
   - Compare interface contracts: does THIS plan's definition match what the downstream plan assumes?
   - Flag mismatches: "Plan 01b assumes a 7-method interface. Plan 01a defines 4 methods."
3. If no downstream plans exist yet, note what the interface contract is so future plans can develop against it

This catches interface design problems during planning (free to fix) rather than during implementation (expensive refactor).

---

## Plan Document Structure

Every plan should follow this structure:

```markdown
# Plan: <name>

## Context
_Summary from research — problem statement, scope, key decisions_

## Architecture Fit
_Existing patterns to follow (with file paths from Driver context)_
_Directories/files this feature touches_
_Integration points with existing code_

## Acceptance Criteria
- [ ] Criterion 1 (specific, testable)
- [ ] Criterion 2

## Test Strategy
### Unit Tests
- [ ] Test: <description> — verifies <behavior>
### Integration Tests
- [ ] Test: <description> — verifies <behavior>

## Implementation Approach
_High-level approach, key design decisions, dependencies between components_

## Scope
**In scope (explicitly requested):** ...
**In scope (surfaced during planning):** ...
**Out of scope (deferred):** ...

## Constraints
- NO TODOs or stubbed functions
- Run tests after every change
- Follow existing patterns from <specific files>

## Task Breakdown
### Task 1: Write tests for <component>
**Goal**: Define test expectations (TDD red phase)
**Files**: Files to create
**Tests**: Specific test cases from Test Strategy
**Constraints**: Task-specific rules

### Task 2: Implement <component>
**Goal**: Make Task 1 tests pass (TDD green phase)
**Files**: Files to create or modify
**Tests**: Task 1 tests should now pass
**Constraints**: Task-specific rules
```

---

## Plan Sizing

Each plan should produce **one reviewable PR**. Signals a plan is well-sized:

- **5-12 tasks** — fewer means tasks are too broad for subagents; more means the plan should be split
- **One logical unit of work** — a plan delivers one capability that can be tested independently
- **Focused scope** — if explaining the plan requires "and also..." it should be two plans

**Split when:**
- The PR would be too large to review (>500 lines of real code, not counting tests)
- Tasks have no dependencies on each other (parallel tracks = separate plans)
- Different codebases are involved (one plan per codebase, unless tightly coupled)

**Don't split when:**
- Tasks are sequential and tightly coupled (test + implement pairs)
- The feature only makes sense as a whole (splitting would create a broken intermediate state)

---

## Testing Methodology

Testing is a planning concern. The test strategy shapes task ordering and acceptance criteria.

### Tests First (TDD)

**ALWAYS order test tasks before implementation tasks.**

```
WRONG:
  Task 1: Implement user authentication
  Task 2: Write tests for authentication

RIGHT:
  Task 1: Write tests for user authentication (TDD red phase)
  Task 2: Implement user authentication (TDD green phase — make tests pass)
```

Adjacent test+implementation pairs should reference each other. The test task says "tests should fail initially"; the implementation task says "Task N tests should now pass."

### Test Pyramid

| Type | Typical Ratio | Purpose |
|------|---------------|---------|
| **Unit** | 70% | Business logic, pure functions |
| **Integration** | 20% | Component interactions, API contracts |
| **E2E** | 10% | Critical user journeys |

Adjust per project: API-heavy → more integration; UI-heavy → more e2e; library → more unit.

### Coverage Targets

| Code Type | Target |
|-----------|--------|
| Business logic | 100% |
| API contracts | 100% |
| Edge cases / error handling | 90%+ |
| Critical user paths | E2E covered |
| Utilities / helpers | 80%+ |
| Glue code / wiring | Lower priority |

### Mocking Boundaries

**Mock:** External APIs, database (in unit tests), time/date, random values.
**Don't mock:** The code under test, internal modules, simple data structures.
**Over-mocking signal:** Test setup is longer than the test itself.

### Test Lifecycle

Not all TDD tests are permanent. Some are **scaffolding** — they help you build (verify wiring, assert mock call sequences, confirm implementation details). Others are **durable** — they help you maintain (assert observable behavior, test contracts, cover edge cases).

During planning, design both kinds deliberately:
- Scaffolding tests validate that components are wired correctly during construction
- Durable tests validate behavior that should survive refactoring
- Coverage targets (above) apply to durable tests — scaffolding tests don't count toward long-term coverage

After all plans are implemented, the test suite is curated via `/assess`. Plan accordingly: write scaffolding tests freely during TDD, knowing they'll be evaluated later.

### Fixture Sourcing

Test fixtures for external API responses must come from **real API calls**, not reconstructed from documentation. Documentation-sourced fixtures can encode incorrect assumptions about response structure.

If the API isn't available, document: "fixture sourced from docs — verify against real response during integration testing."

### Test Specificity in Plans

Each test case must have enough detail for a subagent to write it:

**Too vague:** "Test: user authentication works"

**Good:** "Test: `login_with_valid_credentials_returns_token` — POST `/auth/login` with valid credentials returns 200 with JWT containing `user_id` claim"

---

## Explicit Constraints Prevent Agent Laziness

| Constraint | Prevents |
|------------|----------|
| "NO TODOs or stubbed functions" | Incomplete implementations |
| "Run tests after every change" | Breaking changes going unnoticed |
| "Follow patterns from `<specific file>`" | Inconsistent code style |
| "All error cases must be handled" | Missing error handling |

Be specific. "Write good code" is not a constraint. "Follow the error handling pattern in `src/errors.ts`" is.

---

## Scope: Surface Unknown Unknowns

Good planning reveals what the user didn't think to ask for:

- **Error handling** — What happens when the API returns 500?
- **Edge cases** — Empty states, maximum limits, concurrent access
- **Dependencies** — Will this break anything? What needs to change together?
- **Security** — Authentication, authorization, input validation
- **Performance** — Will this scale? N+1 queries? Caching?
- **UI wireframes** — If the plan involves new UI, reference wireframes from `wireframes/`. If none exist, note that wireframes should be created before implementation.

Document scope explicitly in the plan:

```markdown
## Scope
**In scope (explicitly requested):** ...
**In scope (surfaced during planning):** ...
**Out of scope (deferred):** ...
```

---

## Task Specs for Subagents

Each task must be specific enough for a subagent to execute without ambiguity:

- **Clear, single goal** — one deliverable per task
- **Specific files** — which files to create or modify
- **Test references** — which tests verify completion
- **Explicit constraints** — copied from the plan, not summarized
- **TDD ordering** — test tasks before implementation tasks

---

## Anti-Patterns

**Don't:**
- Write plan content in chat (write to files)
- Suggest moving to implementation (user controls transitions)
- Skip reading research context first
- Skip Driver context for architecture AND testing patterns
- Leave constraints vague or generic
- Create tasks too broad for subagents
- Order implementation before tests
- Write vague test cases ("test that it works")
- Skip fixture sourcing considerations for external API tests
- Forget the overview for multi-plan features

**Do:**
- Read research context before planning
- Spawn `driver-task-context` for architecture AND testing patterns
- Write plans to `plans/*.md`
- Create `plans/00-overview.md` for multi-plan features
- Define interface contracts between plans
- Run consumer validation after writing a plan
- Include explicit, specific constraints
- Order test tasks before implementation tasks
- Suggest `/dry-run-plan` when the plan feels complete

---

## Related

- Entry point: [/feature](../../commands/feature.md)
- Previous phase: [research-guidance](../research-guidance/SKILL.md)
- Validation: [/dry-run-plan](../../commands/dry-run-plan.md)
- Next phase: [implementation-guidance](../implementation-guidance/SKILL.md)
- Context gathering: [driver-task-context](../../agents/driver-task-context.md)
- Lifecycle: [sdlc-orchestration](../sdlc-orchestration/SKILL.md)

---

## Before Responding Checklist

- [ ] **Read research first?** — Have I checked `research/*.md` and `wireframes/`?
- [ ] **Pulled Driver context?** — Architecture AND testing patterns?
- [ ] **Writing to file?** — Plan content goes in `plans/*.md`, not chat
- [ ] **Overview needed?** — Multi-plan feature? Create `plans/00-overview.md`
- [ ] **All sections covered?** — Context, Architecture, Acceptance, Tests, Approach, Scope, Constraints, Tasks
- [ ] **Consumer validation?** — Do downstream plans match this plan's interface?
- [ ] **TDD task ordering?** — Test tasks before implementation tasks
- [ ] **Constraints explicit?** — Specific rules, not generic advice
- [ ] **Plan sized right?** — 5-12 tasks, one PR, one logical unit
- [ ] **Feature log?** — Did I update `FEATURE_LOG.md` when creating plans or the overview?
