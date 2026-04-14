---
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

---

## The Planning Workflow

Planning follows 7 steps, then a finalize section. Execute them in order.

---

## Step 1: Ingest Research

Always start by reading existing research:

1. **Check for research docs** — `research/*.md`
2. **Review decisions made** — Look for resolved questions (marked with `~~Question~~ → Answer`) and standalone decision artifacts in `research/decisions/`
3. **Check for wireframes** — `wireframes/*.html` if UI is involved
4. **Summarize in plan** — The Context section should reference research findings

If research doesn't exist or is incomplete, note this and ask if the user wants to do research first.

---

## Step 2: Clarify Scope

With research context loaded, ask the user what they want to build. Don't start writing a plan until scope is clear.

**Ask focused questions:**
- Which findings from research do you want to act on?
- What's the desired end state?
- What constraints exist? (timeline, compatibility, dependencies)
- What's explicitly out of scope?

**Push back on scope creep.** If the user says "and also..." that's a signal to split into separate plans. Each plan should deliver one logical unit of work.

**Push back on vague scope.** "Build the notification system" is too broad. Help the user narrow to something like "Add retry logic to the existing delivery pipeline with exponential backoff and a dead-letter queue."

---

## Step 3: Gather Broad Context

Spawn the `driver-task-context` agent to gather BOTH architecture patterns and testing conventions in a single call.

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

## Step 4: Detail with Primitive Tools

After `driver-task-context` gives you the broad picture, drill into specifics using Driver MCP primitives directly. **This step is what makes plans code-level specific instead of hand-wavy.**

The progression:
1. **`driver-task-context`** (Step 3) — broad architecture, conventions, testing patterns
2. **`get_code_map`** — find the exact directories and files the plan will touch, verify structure
3. **`get_file_documentation`** — understand function signatures, types, interfaces in files the plan will modify
4. **`get_source_file`** — see exact current implementation when the plan needs to prescribe specific code changes

You won't always need all four levels. But the plan should be specific enough that you've used at least the first two.

**When to use each:**
- `get_code_map` — "Where does the notification code live? What's in `services/`?"
- `get_file_documentation` — "What methods does `NotificationService` expose? What's the interface?"
- `get_source_file` — "How does the existing `retry_send` method work? I need to prescribe a similar pattern."

**Codebase name verification:** If calling Driver primitives directly, verify codebase names first with `get_codebase_names`. The `driver-task-context` agent handles this automatically.

---

## Step 5: Write the Plan

**Create plan file** — Write to `plans/01-<name>.md` (or next available number).

### Plan Document Structure

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

### Plan Sizing

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

### Testing Methodology

Testing is a planning concern. The test strategy shapes task ordering and acceptance criteria.

#### Tests First (TDD)

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

#### Test Pyramid

| Type | Typical Ratio | Purpose |
|------|---------------|---------|
| **Unit** | 70% | Business logic, pure functions |
| **Integration** | 20% | Component interactions, API contracts |
| **E2E** | 10% | Critical user journeys |

Adjust per project: API-heavy → more integration; UI-heavy → more e2e; library → more unit.

#### Coverage Targets

| Code Type | Target |
|-----------|--------|
| Business logic | 100% |
| API contracts | 100% |
| Edge cases / error handling | 90%+ |
| Critical user paths | E2E covered |
| Utilities / helpers | 80%+ |
| Glue code / wiring | Lower priority |

#### Mocking Boundaries

**Mock:** External APIs, database (in unit tests), time/date, random values.
**Don't mock:** The code under test, internal modules, simple data structures.
**Over-mocking signal:** Test setup is longer than the test itself.

#### Test Lifecycle

Not all TDD tests are permanent. Some are **scaffolding** — they help you build (verify wiring, assert mock call sequences, confirm implementation details). Others are **durable** — they help you maintain (assert observable behavior, test contracts, cover edge cases).

During planning, design both kinds deliberately:
- Scaffolding tests validate that components are wired correctly during construction
- Durable tests validate behavior that should survive refactoring
- Coverage targets (above) apply to durable tests — scaffolding tests don't count toward long-term coverage

After all plans are implemented, the test suite is curated via `/assess`. Plan accordingly: write scaffolding tests freely during TDD, knowing they'll be evaluated later.

#### Fixture Sourcing

Test fixtures for external API responses must come from **real API calls**, not reconstructed from documentation. Documentation-sourced fixtures can encode incorrect assumptions about response structure.

If the API isn't available, document: "fixture sourced from docs — verify against real response during integration testing."

#### Test Specificity in Plans

Each test case must have enough detail for a subagent to write it:

**Too vague:** "Test: user authentication works"

**Good:** "Test: `login_with_valid_credentials_returns_token` — POST `/auth/login` with valid credentials returns 200 with JWT containing `user_id` claim"

### Explicit Constraints Prevent Agent Laziness

| Constraint | Prevents |
|------------|----------|
| "NO TODOs or stubbed functions" | Incomplete implementations |
| "Run tests after every change" | Breaking changes going unnoticed |
| "Follow patterns from `<specific file>`" | Inconsistent code style |
| "All error cases must be handled" | Missing error handling |

Be specific. "Write good code" is not a constraint. "Follow the error handling pattern in `src/errors.ts`" is.

### Scope: Surface Unknown Unknowns

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

### Code-Level Specificity

Each task must prescribe concrete changes — not hand-wavy descriptions. This level of detail comes from Step 4 (using Driver primitives to understand the exact files, functions, and patterns).

**Too vague:** "Implement the notification handler"

**Specific enough:** "Add `retry_delivery` method to `NotificationService` in `backend/services/notification_service.py`. Method should accept a `notification_id: str` and `attempt: int`, look up the notification from the database using the existing `get_notification` method, and re-enqueue it via `delivery_queue.enqueue()` with exponential backoff. Follow the retry pattern in `backend/services/email_service.py:retry_send`."

### Task Specs for Subagents

Each task must be specific enough for a subagent to execute without ambiguity:

- **Clear, single goal** — one deliverable per task
- **Specific files** — which files to create or modify
- **Test references** — which tests verify completion
- **Explicit constraints** — copied from the plan, not summarized
- **TDD ordering** — test tasks before implementation tasks

---

## Step 6: Self-Review

After writing the plan, validate it against the actual codebase. **This step is required, not optional.** It catches stale references and incorrect assumptions before the user sees the plan.

### Big-Picture Check

Spawn `driver-task-context` with a validation-focused prompt:

```
Reviewing a plan to add [feature]. Need to verify:
- Does the planned approach fit the codebase's architecture and conventions?
- Are there existing patterns we should follow that the plan might be missing?
- Any concerns about the approach?
```

### Specific Checks

Use Driver primitives to verify concrete plan details:

- **`get_code_map`** — do the files and directories referenced in the plan actually exist?
- **`get_file_documentation`** — do the interfaces and function signatures the plan depends on match reality?
- **`get_source_file`** — do the implementation details the plan assumes still hold?

### Report and Fix

After self-review:
1. **Confirmed** — what matches the plan's assumptions
2. **Discrepancies** — what doesn't match (with specifics)
3. **Suggestions** — adjustments to the plan based on what you discovered

Update the plan to address any discrepancies before presenting to the user.

---

## Step 7: Validate (Dry-Run Loop)

After the user reviews the plan and approves the direction, run validation automatically. Say: **"Plan direction approved. Running validation..."**

The dry-run loop walks through the plan as if implementing it, surfaces gaps, fixes them, and repeats until no new gaps appear. This is the most leverage-positive activity in planning — gaps caught here cost minutes; gaps caught during implementation cost hours.

### The Loop

Each iteration has two passes:

**1. Mechanical pass** — walk each task checking:
- Do I know exactly which files to create/modify?
- Do I understand the existing patterns to follow?
- Are test cases specific enough to write?
- Are there hidden dependencies on other tasks?
- What edge cases could go wrong that aren't covered?
- Is any context missing that I'd need during implementation?

**2. Judgment pass** — apply the 7 critic checks (below) against the plan and tasks.

**3. Classify gaps** by severity:

| Severity | Criteria | Examples |
|----------|----------|----------|
| **LOW** | Mechanical fix — one correct answer | Stale file reference, typo in pattern name, outdated method name |
| **MEDIUM** | Clear addition needed | Missing constraint, missing edge case, adding a test case |
| **HIGH** | Design decision — multiple valid approaches | Interface choice, architecture pattern, scope change |

**4. Apply fixes per severity:**
- **LOW**: auto-fix in plan, note what changed
- **MEDIUM**: fix and surface to user for confirmation. If user rejects, mark as "accepted risk" — it doesn't count as a new gap in subsequent iterations.
- **HIGH**: stop loop, present to user for design input. After user provides input and fix is applied, resume from the next iteration number.

**5. Write/update** findings to `dry-runs/<plan-name>-<date>.md`. The same file is updated each iteration. The gap table reflects current state. Include an iteration history section:

```markdown
## Iteration History
- Iteration 1: N gaps found (X LOW, Y MEDIUM, Z HIGH)
- Iteration 2: M gaps found, K fixed from previous iteration
- Iteration 3: Converged — no new gaps
```

**6. Check convergence:** Compare the gap list against the previous iteration. A gap is "not new" if the same task + same gap type + same description (or a fix for it) appeared previously. If all gaps were already present or fixed, the loop has converged. **Maximum 3 iterations.**

### Critic Judgment Checks

Apply these 7 checks during the judgment pass:

1. **Missing context** — For each task, can a fresh agent execute it without going back to research docs? If a task references "the existing migration pattern" without pointing to a concrete file/function, that's a gap.

2. **Unclear instructions** — Read each task step. Do you know exactly which file, which function, which line range to edit? "Update the handler" without a specific handler name is a gap.

3. **Missing edge cases** — For each behavioral change, what fails? Empty input, max size, concurrent access, partial failure? If the plan doesn't address them, gap.

4. **Hidden dependencies** — Does any task assume another task's output without declaring it? Does any task touch a file another task also touches without coordination? Flag it.

5. **Test specificity** — Each test in the plan: concrete assertion or vague goal? "Test that pagination works" is vague; "Test that `fetch_page(0, 10)` returns 10 items and `fetch_page(1, 10)` returns items 11-20" is specific. Flag the vague ones.

6. **Architecture concerns** — Does the plan introduce a pattern that diverges from existing conventions? Does it add coupling that will be hard to undo? These are **HIGH severity** — they require user input.

7. **Scope understatement** — Does any task touch more files than it claims? A 1-line API change might force 5 call-site updates. If the task says "update X" but implementation will touch 5 files, flag it.

### Stopping Criteria

- **Convergence:** zero new gaps → done. Plan is validated.
- **Cap:** 3 iterations max → stop, present remaining gaps to user. The plan likely needs restructuring, not more iteration.
- **HIGH gap:** stop, present design question to user. Do not auto-fix HIGH gaps.

### After Validation

> "Plan validated after N iteration(s). M gaps found and fixed. The plan is ready for your review."

Note: `/dry-run-plan` remains available for manual re-runs after plan edits.

---

## Finalize

**NEVER suggest moving to implementation.** The user controls when to move from Planning → Implementation.

After validation completes, present the plan:
> "The plan is ready for your review. Let me know if you have questions or want changes."

The user will tell you when they're ready to implement. Until then, stay in planning mode.

---

## Multi-Plan Coordination

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

### Consumer Validation

After writing a plan, check whether downstream plans are compatible:

1. Read the overview's dependency graph — find plans that depend on this one
2. For each downstream plan that already exists as a document:
   - Compare interface contracts: does THIS plan's definition match what the downstream plan assumes?
   - Flag mismatches: "Plan 01b assumes a 7-method interface. Plan 01a defines 4 methods."
3. If no downstream plans exist yet, note what the interface contract is so future plans can develop against it

This catches interface design problems during planning (free to fix) rather than during implementation (expensive refactor).

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
- Use native Explore agents as a substitute for `driver-task-context` — they lack pre-computed documentation
- Skip the self-review step (Step 6) — always validate plan against codebase before presenting
- Skip the automatic dry-run validation (Step 7)
- Write vague task descriptions without code-level specificity (Step 4 enables this)
- Auto-fix HIGH severity gaps — these require user input

**Do:**
- Read research context before planning
- Spawn `driver-task-context` for architecture AND testing patterns
- Use Driver primitives (`get_code_map`, `get_file_documentation`, `get_source_file`) to reach code-level specificity
- Write plans to `plans/*.md`
- Create `plans/00-overview.md` for multi-plan features
- Define interface contracts between plans
- Run consumer validation after writing a plan
- Include explicit, specific constraints
- Order test tasks before implementation tasks
- Self-review the plan against the codebase before presenting to user
- Run the dry-run validation loop automatically after user approves plan direction
- Create standalone decision artifacts for choices that arise during planning (in `research/decisions/`)

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

- [ ] **Read research first?** — Have I checked `research/*.md`, `research/decisions/`, and `wireframes/`?
- [ ] **Pulled Driver context?** — Architecture AND testing patterns via `driver-task-context`?
- [ ] **Primitive tools used?** — Did I drill into specific files/interfaces with `get_code_map`, `get_file_documentation`, `get_source_file`?
- [ ] **Writing to file?** — Plan content goes in `plans/*.md`, not chat
- [ ] **Overview needed?** — Multi-plan feature? Create `plans/00-overview.md`
- [ ] **All sections covered?** — Context, Architecture, Acceptance, Tests, Approach, Scope, Constraints, Tasks
- [ ] **Code-level specificity?** — Are task descriptions specific to file, function, and pattern?
- [ ] **Consumer validation?** — Do downstream plans match this plan's interface?
- [ ] **TDD task ordering?** — Test tasks before implementation tasks
- [ ] **Constraints explicit?** — Specific rules, not generic advice
- [ ] **Plan sized right?** — 5-12 tasks, one PR, one logical unit
- [ ] **Self-reviewed?** — Did I validate the plan against the codebase (Step 6)?
- [ ] **Dry-run passed?** — Did the automatic validation converge (Step 7)?
- [ ] **Feature log?** — Did I update `FEATURE_LOG.md` when creating plans or the overview?
