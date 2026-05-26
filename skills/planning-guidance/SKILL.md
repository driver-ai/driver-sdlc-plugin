---
name: planning-guidance
description: |
  Guide planning methodology with functional-core / imperative-shell architecture, TDD-first task
  design, test strategy derived from architecture, explicit constraints, and task breakdown. Use
  when transitioning from research to planning phase.
  Trigger phrases: "let's plan", "ready to plan", "move to planning", "create a plan",
  "how should we implement", "test strategy", "what should I test", "TDD", "tests first",
  "core and shell", "pure functions".
---

# Planning

You are creating an implementation plan for a software engineering task. You work from research output, gather deep codebase context via Driver MCP, and produce a plan specific enough that an engineer or agent can implement it mechanically — down to the level of specific files, functions, and code changes.

## Architectural Commitment: Functional Core, Imperative Shell

**This is the load-bearing principle that shapes every plan.** See [`CLAUDE.md`](../../CLAUDE.md) Key Principles. Software produced through this plugin separates a **pure logical core** (functions taking values in and returning values out — no I/O, no time, no randomness, no mutable shared state) from a **thin imperative shell** that performs I/O and calls into the core.

The plan's job is to design code that has this shape. The test strategy is *derived* from the architecture — pure-core functions get unit tests with values in / values out (no mocks); shell functions get integration tests against real I/O. **If the plan would require a mock to test a "unit," the architecture is wrong and the plan must be re-shaped to extract a pure core.** When the surrounding code isn't in core/shell shape, the plan steers the feature toward extracting a pure core anyway — local mess from a clean extraction is preferred to a clean fit with an entangled neighbor.

---

## How This Skill Works

1. **Ingest research** — read the research output to understand findings and decisions (including any core/shell decomposition surfaced during research)
2. **Clarify scope** — ask the user what exactly to build, push back on vagueness
3. **Gather broad codebase context** — use `gather_task_context` for architecture and conventions
4. **Detail with primitive tools** — use `get_code_map`, `get_file_documentation`, `get_source_file` for specific file-level understanding
4.5. **Confirm approach** — present the core/shell decomposition, architecture, derived test strategy, scope, and sizing for user confirmation
5. **Write the plan** — environment, core/shell architecture, TDD-ordered task breakdown, acceptance criteria
6. **Self-review** — validate the plan against the actual codebase using Driver tools, including the core/shell boundary
7. **Approve** — user reviews, approves plan for implementation

---

## Step 1: Ingest Research

This skill assumes research has been done. Ask the user to point you to the research output folder.

**Read all research documents:**
- Start with `00-overview.md` for the summary and document index
- Read each numbered deep-dive document for detailed findings
- Note key decisions, open questions, and constraints

**Check for codebase standards:**
- Look for a research doc with a `## Standards Source` section (the codebase standards artifact from research)
- If found, read it — the Key Rules and Applicable Sections will be encoded as plan constraints in Step 5
- If not found, no codebase standards were discovered during research — proceed without standards constraints

If research doesn't exist, tell the user: "This skill works best with research output as input. Want to run the research skill first?"

---

## Step 2: Clarify Scope

With research context loaded, ask the user what they want to build.

**Ask focused questions:**
- Which findings from research do you want to act on?
- What's the desired end state?
- What constraints exist? (timeline, compatibility, dependencies)
- What's explicitly out of scope?
- Are there cross-feature dependencies — other active features that may overlap with or depend on this work? (Check other features' plans for overlapping file targets.)

**Push back on scope creep.** If the user says "and also..." that's a signal to split into separate plans. Each plan should deliver one logical unit of work.

---

## Step 3: Gather Broad Codebase Context

### CRITICAL: Use `gather_task_context` — Not Native Agents

`gather_task_context` is Driver MCP's primary tool. **It is your default tool for codebase context.** (Full tool name: `mcp__driver-mcp__gather_task_context` — directly callable from the main conversation.)

**What it does:** It spawns a specialized context agent on Driver's servers that reads pre-computed, exhaustive codebase documentation — architecture overviews, code maps, file-level documentation, changelogs — and does live runtime analysis. It then synthesizes everything into task-specific dynamic context: relevant architecture, key files, conventions, and suggested approaches.

**How to call it for planning:** Provide a task description focused on what you're about to plan. Include architectural concerns and testing patterns.

```
Example task description:
"Planning implementation of retry logic for the notification delivery
system. Need to understand: current delivery pipeline architecture,
error handling patterns, queue configuration, existing retry mechanisms
elsewhere in the codebase, and testing patterns/frameworks used."
```

**It takes 1-3 minutes. This is expected and normal.** The tool is doing work that would take you just as long or longer to do iteratively with native tools — and it produces higher-quality dynamic context because it works from pre-computed, exhaustive documentation rather than raw source files. Wait for the full response.

### CRITICAL: Do NOT Substitute Native Agents

**Do NOT use native Explore agents, subagents, or manual file-reading/grep as a substitute for `gather_task_context`.** These native tools work from raw source only. `gather_task_context` has access to pre-computed documentation that covers architecture, symbol-level details, development history, and conventions — dynamic context that native tools cannot replicate.

Native tools are useful for **targeted follow-up** after `gather_task_context` returns (see Step 4), but they are not a replacement for it.

### Running Multiple Calls in Parallel

When you need context from multiple angles (e.g., architecture AND testing patterns), spawn native subagents as concurrency wrappers. Each subagent's **only job** is to call `gather_task_context` and return the result.

**This is the one correct use of native subagents in this skill.** The subagent is a concurrency wrapper — it does NOT do its own codebase exploration.

| Pattern | What the subagent does | Correct? |
|---------|----------------------|----------|
| **Substitution** | Its own file reading, grep, exploration — bypassing Driver | No |
| **Parallelism wrapper** | Calls `gather_task_context` with a specific task description, returns the result | Yes |

**Example:** You need architecture context and testing patterns for the same feature. Spawn two subagents, each calling `gather_task_context` with a different focused task description. Collect both results before writing the plan.

---

## Step 4: Detail with Primitive Driver MCP Tools

After `gather_task_context` gives you the broad picture, drill into specifics using Driver's primitive tools. **This step is essential for reaching code-level plan specificity.**

### `get_code_map`
Navigate codebase structure. Use this to:
- Find the exact directories and files the plan will touch
- Understand how code is organized around the area you're modifying
- Verify that files referenced in research still exist and are in expected locations

### `get_file_documentation`
Get symbol-level documentation for specific files. Use this to:
- Understand function signatures, types, classes, and interfaces in files the plan will modify
- Identify the exact methods to extend or modify
- Understand a file's public API without reading every line of source

### `get_source_file`
Read the actual source code. Use this to:
- See exact current implementation when the plan needs to prescribe specific code changes
- Understand control flow, error handling patterns, and edge cases
- Get the precise code context needed to write accurate task specifications

**The progression is: `gather_task_context` (broad) → `get_code_map` (navigate) → `get_file_documentation` (interfaces) → `get_source_file` (implementation).** You won't always need all four, but the plan should be specific enough that you've used at least the first three.

---

## Step 4.5: Confirm Approach

Before writing the plan, present your proposed direction to the user. At this point you have all the codebase context from Steps 3–4 but haven't committed to a plan structure.

**Present a summary covering:**

1. **Core/shell decomposition** — what's the pure logical core for this feature (no I/O, no time, no randomness), and what's the imperative shell that performs I/O and calls into it? Name the candidate pure functions/types and the shell entry points. If the surrounding code makes a clean extraction hard, say so explicitly and propose the extraction anyway — the plugin steers toward purity, it doesn't accommodate entanglement.
2. **Architecture approach** — which existing patterns to follow, key files to modify, integration strategy. Note where the core/shell boundary lands relative to existing files.
3. **Derived test strategy** — testing follows from the architecture, not the other way around. Pure-core functions get unit tests (values in, values out, no mocks). Shell functions get integration tests against real I/O. Name the framework and fixture-sourcing approach. If you find yourself proposing a mock for anything other than a system boundary (external API, DB at unit level, time, randomness), stop — that's a signal the core/shell boundary needs to move.
4. **Scope adjustments** — anything surfaced during context gathering that wasn't in the original Step 2 scope (additions or exclusions)
5. **Plan sizing** — estimated task count, single plan vs. split, and rationale

**Format:**

> Here's my planning direction:
>
> - **Core/shell decomposition**: [pure core: <functions/types>; shell: <I/O entry points>]
> - **Architecture**: [summary of approach, key patterns, files, where the boundary lands]
> - **Test strategy** (derived): [unit tests for pure-core values-in/values-out; integration tests for shell against real I/O; framework; fixture sourcing]
> - **Scope changes**: [any additions/exclusions discovered during context gathering, or "none"]
> - **Sizing**: [N tasks, single plan / split rationale]
>
> Does this look right? (Say "looks good" to proceed, or tell me what to change.)

**If the user confirms** ("looks good", "yes", "proceed"): append confirmed choices to `DECISIONS.md` using the entry template in the Decision Logging section below, then proceed to Step 5. Step 4.5 decisions capture the broad direction (which pattern to follow, which framework, single vs. split). Specific design decisions with rejected alternatives are logged during Step 7 — do not duplicate.

**If the user requests changes**: adjust the proposed direction and re-present. Do not proceed to Step 5 until the user confirms.

**Skipping**: If the user says "skip" or moves directly to "write the plan", respect that — the checkpoint is advisory, not a gate. Note "Step 4.5 skipped at user direction" and proceed.

---

## Step 5: Write the Plan

## CRITICAL: Write Plans to Files

**NEVER write plan content in chat.** Always write to `plans/*.md`.

### Output Structure

```
plans/
├── 00-overview.md      # Index (only if multiple plans)
├── 01-<name>.md        # The plan
└── ...                 # Additional plans if needed (usually just 1)
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

### Multi-Plan Overview

For features that span multiple plans, create `plans/00-overview.md` as the central coordination document.

**When to create an overview:**
- Feature will have 2+ plans
- Multiple codebases or components are involved
- Plans have dependencies on each other

**Overview template:**

````markdown
# <Feature Name> — Planning Overview

## Status
**Phase**: Planning
**Last Updated**: <date>

### Progress
| Plan | Status | Tests | Key Artifact |
|------|--------|-------|-------------|
| 01 <name> | NOT STARTED | — | <what it delivers> |
| 02 <name> | NOT STARTED | — | <what it delivers> |

## Implementation Environment

_Capture the environment information that implementation needs: codebase paths, base/feature branches,
test commands, and any other environment details relevant to this feature. Materialize-tasks
reads this section to hydrate task docs so sub-agents arrive pre-loaded._

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

## Feature Dependencies
_Known overlaps or dependencies with other active features. Populated during research (Step 1.5)
and updated during planning (Step 6 self-review). Advisory only — user decides whether to coordinate._

| Feature | Relation | Overlap | Status |
|---------|----------|---------|--------|
| _none discovered_ | | | |
````

#### Fill In Implementation Environment

When creating `plans/00-overview.md`, populate the Implementation Environment section with
the environment details sub-agents will need: codebase paths, base branch (for Driver MCP context and merge target), feature branch (for local implementation), test commands, and anything else relevant. Pull from research Codebases and codebase
CLAUDE.md as starting points, then confirm with the user.

#### Populate Environment

When writing each plan, populate the `## Environment` section. Source values from: the research Codebases table (`research/00-overview.md` `## Codebases`), the codebase's CLAUDE.md, and Driver context gathered in Steps 3–4. Confirm values with the user. For multi-plan features, the per-plan Environment section may duplicate values from the overview's Implementation Environment — this is intentional (each plan is self-contained for materialize-tasks).

#### Interface Contracts Are Critical

The interface contracts section prevents the most expensive planning failure: discovering during implementation that Plan B's assumptions don't match Plan A's definitions. Define contracts explicitly when writing each plan.

#### Consumer Validation

After writing a plan, check whether downstream plans are compatible:

1. Read the overview's dependency graph — find plans that depend on this one
2. For each downstream plan that already exists as a document:
   - Compare interface contracts: does THIS plan's definition match what the downstream plan assumes?
   - Flag mismatches: "Plan 01b assumes a 7-method interface. Plan 01a defines 4 methods."
3. If no downstream plans exist yet, note what the interface contract is so future plans can develop against it

This catches interface design problems during planning (free to fix) rather than during implementation (expensive refactor).

### Plan Document Template

<!-- The template block uses a four-backtick outer fence so nested three-backtick code
     snippets inside tasks don't terminate it prematurely. -->

````markdown
# Plan: <name>

## Environment

| Field | Value |
|-------|-------|
| Codebase | <name> |
| Path | `<absolute path>` |
| Base Branch | `<branch>` |
| Feature Branch | `<branch>` |
| Test Command | `<command>` |
| Key Directories | `<dir1>`, `<dir2>` |
| Standards Doc | `<path to CLAUDE.md or equivalent>` |

## Context
_Summary from research — problem statement, scope, key decisions_

## Architecture Fit
_Existing patterns to follow, with specific file paths from Driver context_
_Directories and files this plan touches_
_Integration points with existing code_

### Core/Shell Decomposition

_This subsection is required. The plan must explicitly name what's pure-core and what's shell._

**Pure core** (no I/O, no time, no randomness, no mutable shared state — functions taking values in, returning values out):
- `<function or type name>` at `<file>` — <one-line purpose>
- ...

**Imperative shell** (performs I/O, calls into the core):
- `<function or entry point>` at `<file>` — <I/O performed: HTTP / DB / filesystem / time / random / etc.>
- ...

**Boundary notes:** <Where does the seam land relative to existing files? Is the surrounding code already in core/shell shape, partially, or not at all? If the boundary cuts through an existing entangled module, name the extraction explicitly.>

## Data Structures & Callables

_Interface-level design decisions: the data structures (with their typed fields) and
callable signatures (with full argument names, types, and return types) this plan
introduces or modifies. The types ARE the design — they connect data structures to
callables and let reviewers assess whether the interfaces are right without reading
implementation logic. Each item here has a corresponding inline snippet (`#### Snippet:`)
in its Owning Task — the snippet is the primary artifact, flowing through materialization
into the task doc that sub-agents execute against. This section is the scannable index;
the per-task snippets are the source of truth._

_Snippets must show the full signature — not just the function name, but every argument
with its name and type, plus the return type. For data structures, show every field with
its type. Elide method bodies with `...` when only the interface matters; include the body
when the logic itself is a design decision worth reviewing (e.g., a retry formula, a
validation pipeline, a state machine)._

_Calibrate coverage per plan: for a plan with significant API surface, this may be every
type and method. For targeted changes, list only the signatures that represent design
decisions. For plans with no code-surface changes, leave subsections empty with a note._

_Language-agnostic: use the codebase's native idioms. Kind values adapt per language
(`class`, `struct`, `dataclass`, `typed_dict`, `pydantic_model`, `enum`, `interface`,
`protocol`, `trait`, `type_alias`, `function`, `method`, etc.). For untyped languages,
show argument names and document expected shapes in brief comments. The codebase CLAUDE.md
defines idioms; when absent, use the language's most natural form._

### Added

| Kind | Name | Target File | Owning Task | Notes |
|------|------|-------------|-------------|-------|

### Modified

| Kind | Name | Target File | Owning Task | Operation |
|------|------|-------------|-------------|-----------|

### Removed

| Kind | Name | Target File | Owning Task | Rationale |
|------|------|-------------|-------------|-----------|

## Acceptance Criteria
- [ ] Criterion 1 (specific, testable)
- [ ] Criterion 2

## Test Strategy

_The test strategy is derived from the Core/Shell Decomposition above, not designed independently. Pure-core functions get unit tests (values in, values out, no mocks). Shell functions get integration tests against real I/O. If any test below would need a mock to exercise the unit, the core/shell boundary is wrong — return to Architecture Fit and re-extract._

### Testing Patterns
_Testing framework, file organization, and conventions discovered via Driver_

### Unit Tests (pure-core)
_One test per pure-core function listed above. Each test takes values in, asserts on the returned value. No mocks, no I/O, no time, no randomness — if you reach for any of those, the function isn't pure, fix it._

- [ ] Test: `<test_name>` — `<pure-core function>` with `<input>` returns `<output>`

### Integration Tests (shell)
_One test per shell entry point. Exercises real I/O against a real dependency (real test DB, real HTTP fake-backed by recorded fixtures from real calls, real filesystem in a tmpdir, etc.). Mocks only at hard external system boundaries that cannot be exercised in test (third-party APIs without sandboxes; cost-bearing services)._

- [ ] Test: `<test_name>` — `<shell entry point>` against `<real dependency>`, verifies `<observable outcome>`

## Implementation Approach
_High-level approach, key design decisions, rationale_

## Scope
**In scope (explicitly requested):** ...
**In scope (surfaced during planning):** ...
**Out of scope (deferred):** ...

## Constraints
- **Functional core, imperative shell** (always present, sourced from plugin CLAUDE.md): Pure-core functions take values in and return values out — no I/O, no time, no randomness, no mutable shared state, no internal mocks. Shell functions perform I/O and call into the core. If a test would require a mock to exercise the "unit," the architecture is wrong — extract a pure core. Mocks are permitted only at hard external boundaries (third-party APIs without sandboxes, cost-bearing services, hardware that doesn't exist in test).
- <additional constraints from codebase standards artifact, with source citations — omit if no standards artifact>
- <specific, actionable constraints — not generic advice>

## Task Breakdown

### Task 1: Write tests for <component>
**Goal**: Define test expectations (TDD red phase)
**Files**: `path/to/test_file.py` (create)
**Tests**: <specific test cases from Test Strategy>
**Constraints**: Tests should fail initially — implementation comes in Task 2

### Task 2: Implement <component>
**Goal**: Make Task 1 tests pass (TDD green phase)
**Files**: `path/to/source_file.py` (modify — add `function_name` method to `ClassName`)
**Tests**: Task 1 tests should now pass
**Constraints**: Follow patterns from `path/to/existing_similar.py`

#### Snippet: NotificationRetryPolicy (new)

```python
@dataclass(frozen=True)
class NotificationRetryPolicy:
    max_attempts: int
    base_delay_seconds: float
    jitter_ratio: float = 0.1

    def delay_for(self, attempt: int) -> float:
        """Return the delay in seconds for the given attempt (1-indexed)."""
        ...
```

_Language note: in a Go codebase this would be a struct + method receiver; in TypeScript an interface + class; in Rust a struct + impl. The codebase CLAUDE.md defines idioms._
````

### TDD Task Ordering

**Always order test tasks before implementation tasks.**

```
WRONG:
  Task 1: Implement retry logic
  Task 2: Write tests for retry logic

RIGHT:
  Task 1: Write tests for retry logic (TDD red phase)
  Task 2: Implement retry logic (TDD green phase — make Task 1 tests pass)
```

### Code-Level Specificity

Each task must prescribe concrete changes — not hand-wavy descriptions:

**Too vague:** "Implement the notification handler"

**Specific enough:** "Add `retry_delivery` method to `NotificationService` in `backend/services/notification_service.py`. Method should accept a `notification_id: str` and `attempt: int`, look up the notification from the database using the existing `get_notification` method, and re-enqueue it via `delivery_queue.enqueue()` with exponential backoff. Follow the retry pattern in `backend/services/email_service.py:retry_send`."

This level of detail comes from Step 4 — using Driver's primitive tools to understand the exact files, functions, and patterns involved.

### Explicit Constraints

Be specific. Generic advice is not a constraint.

**Always-present constraint:** The functional core / imperative shell rule (see CLAUDE.md Key Principles) is encoded as the first constraint in every plan, with the canonical wording shown in the Plan Document Template above. This is not optional — it appears even when the plan's surrounding code isn't in core/shell shape today, because the plan steers toward extraction.

**Encode codebase standards as constraints:**
If a codebase standards artifact exists from research, encode each applicable standard as a plan constraint. Standards-derived constraints follow the same format as other constraints — the source citation is the only difference. Use the standard's own language and cite the source:

| Good Constraint (from standards) | Bad Constraint |
|----------------------------------|---------------|
| "§6: try/except blocks must be as narrow as possible. Source: driver/backend/CLAUDE.md" | "Follow good error handling practices" |
| "§4: Prefer Pydantic models over raw dicts for structured data. Source: driver/backend/CLAUDE.md" | "Use appropriate data structures" |
| "§8: Separate I/O from logic for testability. Source: driver/backend/CLAUDE.md" | "Write testable code" |

| Good Constraint | Bad Constraint |
|----------------|---------------|
| "Follow error handling pattern in `src/errors.ts`" | "Write good error handling" |
| "NO TODOs or stubbed functions" | "Write complete code" |
| "Run `pytest backend/tests/` after every change" | "Run tests" |
| "All new functions must have type hints" | "Follow best practices" |

### Testing Methodology

Testing is a planning concern, but it is **derivative of the architecture**, not an independent design exercise. The Core/Shell Decomposition determines what tests exist and how they're written. This subsection codifies the rules.

#### Two Test Kinds, Determined by Code Location

| Kind | What it covers | How it's written |
|------|---------------|------------------|
| **Pure-core unit test** | A function in the pure core | Values in, asserted value out. No mocks. No I/O. No time. No randomness. |
| **Shell integration test** | A shell entry point | Real I/O against a real dependency (test DB, tmpdir, fake-backed HTTP, etc.). Mocks only at hard external boundaries that cannot be exercised in test. |

There is no "unit test with a mock." If a test needs a mock to test a "unit," the code being tested is shell code mislabeled as core, or the core has been written with I/O entangled in it. Fix the architecture; do not add the mock.

There is no test-pyramid ratio to tune. The ratio of unit to integration tests is dictated by where the core/shell boundary lands in the code — it is not a knob.

#### No Coverage Quotas

This plugin does not set numeric coverage targets. Coverage quotas reliably produce filler tests written to hit a number rather than to document behavior. Instead:

- **Every pure-core function gets at least one test** that documents its input/output contract. More tests for branches, edge cases, and error returns as the function's behavior warrants.
- **Every shell entry point gets at least one happy-path integration test** and additional tests for failure modes that the code handles explicitly.
- **A test is worth keeping only if a reader can use it to understand what the code does.** If the test reads as noise — long mock setup, opaque assertions, brittle to refactors — it should not be written in the first place.

#### Mocking Rules

**Mock only at hard external boundaries that cannot be exercised in test:**
- Third-party APIs without a sandbox or recording mechanism
- Cost-bearing services (paid APIs, send-real-money endpoints)
- Hardware that doesn't exist in the test environment

**Do not mock:**
- Internal modules of any kind — if you'd need to mock them, the core/shell boundary is in the wrong place
- The database — use a real test DB
- Time, randomness, environment — pure-core code shouldn't reach for these; shell code can take them as injected values, and integration tests pass fixed values
- HTTP to services you control — use a real local instance or recorded fixtures from real calls

**If you find yourself proposing a mock and it doesn't fit the "hard external boundary" rule, stop. The plan is wrong, not the test. Return to Architecture Fit, find the missing seam, extract the pure core, and re-derive the tests.**

#### Test Lifecycle — No "Scaffolding" Category

Earlier versions of this plugin distinguished "scaffolding" tests (write freely, prune later) from "durable" tests. That framing is removed. Under functional core / imperative shell, every test should be durable by construction:

- A pure-core unit test asserts an input/output contract that should survive any internal refactor. It is durable.
- A shell integration test asserts an observable I/O outcome that should survive shell refactors. It is durable.
- A test that's "just scaffolding" — asserts internal call sequences, mock interactions, or implementation details — should not be written. Its existence is a signal the boundary is wrong.

`/drvr:assess` still runs, but its job is not "prune the scaffolding you wrote freely." Its job is to catch tests that slipped through with mocks or implementation-detail assertions and either prune them (architecture failure to fix in a follow-up) or rewrite them to assert behavior through the boundary.

#### Fixture Sourcing

Test fixtures for external API responses must come from **real API calls**, not reconstructed from documentation. Documentation-sourced fixtures encode incorrect assumptions about response structure.

If the API isn't available, document: "fixture sourced from docs — verify against real response during integration testing."

Fixtures for shell integration tests against your own services (DB, internal HTTP, filesystem) should use the real dependency directly — no fixtures needed.

#### Test Specificity in Plans

Each test case must have enough detail for a subagent to write it, AND must read as documentation of what the code does:

**Too vague:** "Test: user authentication works"

**Vague + mock-heavy (rejected — also a sign of a boundary problem):** "Test: `LoginService.login` with mocked `UserRepository` and mocked `TokenIssuer` and mocked `Clock` calls them in the right order"

**Good (pure-core):** "Test: `verify_credentials(stored_hash, candidate_password)` returns `True` when bcrypt matches, `False` otherwise"

**Good (shell integration):** "Test: `POST /auth/login` with valid credentials against a real test DB and a real `TokenIssuer` returns 200 with a JWT whose `user_id` claim matches the DB user"

### Commit After Writing

Commit the plan to the projects repo:

```
git add plans/ FEATURE_LOG.md && git commit -m "chore: Plan created — <plan name>"
```

---

## Step 6: Self-Review

After drafting the plan, validate it against the actual codebase. **This step is required, not optional.**

### Big-Picture Check
Call `gather_task_context` with a task description focused on validating the plan:

```
Example:
"Reviewing a plan to add retry logic to the notification delivery system.
Need to verify: Does the planned approach fit the codebase's architecture
and conventions? Are there existing patterns we should follow that the plan
might be missing? Any concerns about the approach?"
```

### Specific Checks
Use primitive tools to verify concrete plan details:

- **`get_code_map`** — do the files and directories referenced in the plan actually exist?
- **`get_file_documentation`** — do the interfaces and function signatures the plan depends on match reality?
- **`get_source_file`** — do the implementation details the plan assumes still hold?

### Local Validation

Driver MCP shows committed state, not local changes. After the remote checks above, verify plan assumptions against local state:

1. **File existence** — for each file in the plan's Task Breakdown, verify it exists locally at the stated path using `Glob` or `ls`. Flag files that exist in Driver but not locally (renamed? deleted?) or that exist locally but not in Driver (new? uncommitted?).
2. **Interface check** — for key functions or classes the plan modifies or depends on, read the local version and compare against what Driver's `get_file_documentation` reported. If signatures differ, update the plan to match local state.
3. **Uncommitted changes** — run `git status --short` in the target codebase for files the plan touches. If there are local modifications, note them: the plan should be based on local state, not Driver's committed version.

If research was conducted in the same session and included local validation, focus this check on files specific to the plan's Task Breakdown (not the full codebase). If planning runs in a new session, do the full check.

When divergence is found, update the plan to match local reality. Note the divergence in the self-review report.

### Report Findings
Tell the user what you found:
- Confirmed: what matches
- Discrepancies: what doesn't match (with specifics)
- Suggestions: adjustments to the plan based on what you discovered

Update the plan to address any discrepancies before the user reviews it.

### Core/Shell Boundary Self-Review

Before any other self-review check, verify the plan's core/shell decomposition holds:

1. **Pure-core items are actually pure** — for every function/type listed under "Pure core" in Architecture Fit, walk through what its body would need to do. If the body would need to read from disk, hit a network, read the clock, read randomness, mutate shared state, or call a shell function, it isn't pure. Either move it to the shell or split out the pure piece.
2. **Shell items don't carry hidden logic** — for every function/type listed under "Imperative shell," check that the substantive logic has been pulled into the core. The shell should be thin: receive I/O input → call into core → write I/O output. If the shell function has branching, calculation, or state machinery, extract it.
3. **Every Unit Test in Test Strategy maps to a pure-core item** — and asserts values-in/values-out with no mocks. If any unit test would need a mock, the architecture is wrong.
4. **Every Integration Test in Test Strategy maps to a shell item** — and exercises real I/O against a real dependency (or a hard-external-boundary mock per the rules above).
5. **No test in the plan uses mocks for internal modules** — internal mocks are a boundary failure, not a testing choice.

If any of these checks fail, **update the plan**, not the check. Return to Architecture Fit, re-extract the core, and re-derive the Test Strategy. Report the change in the self-review summary.

### Data Structures & Callables Self-Review

After drafting, verify:

1. **Rollup exists** — the plan has a `## Data Structures & Callables` section with Added / Modified / Removed sub-sections (empty sub-sections are fine; absent section is not).
2. **Rollup↔snippet consistency** — every row in Added and Modified has a corresponding inline snippet (`#### Snippet:`) inside its Owning Task. Every inline snippet has a matching rollup row. No orphans in either direction.
3. **Signature drift on modified items** — for each Modified row, use `get_file_documentation` on the target file and verify the snippet signature matches the current codebase signature. If drifted, update the plan to match reality, OR mark the signature change as intentional in the Constraints section (breaking change).
4. **Collision check on added items** — for each Added row, verify the name does not already exist in the target file (`get_file_documentation`).

### Cross-Feature File Overlap Check

After validating the plan against the codebase, check for cross-feature file overlap:

1. Determine the projects directory from the current feature path (navigate up to `features/` parent)
2. Find other active features: `find <projects_path>/features -maxdepth 2 -name "FEATURE_LOG.md" -not -path "<current_feature>/*"` — filter to active (phase not Shipped, Closed, Done, and phase does not contain "(complete)")
3. For each active feature, read `plans/[0-9][0-9]-*.md` (excluding `00-overview.md`):
   - Extract file paths from `**Files**:` entries in Task Breakdown — these may be inline (same line) or multiline (paths on subsequent `- ` lines). Paths may be backtick-wrapped.
   - Extract file paths from `Target File` columns in Data Structures & Callables tables
4. Compare against THIS plan's `## Task Breakdown` file paths
5. If overlaps found, report as **WARN advisory**:

````
Cross-feature file overlap detected:
- feature/<name> (Phase: <phase>) — overlapping files: <file1>, <file2>
````

6. If overlaps found and `plans/00-overview.md` exists, update its `## Feature Dependencies` table
7. If no overlaps or no other active features — note "No cross-feature overlaps detected" and continue

---

## Step 7: Approve

> **Returning to approve a prior-session plan?** If the plan was written in a prior session and the user is returning to approve, skip Steps 1-6. Read the existing plan, verify it's current (check `updated` date), and proceed with the approval flow below.

Present the plan to the user for review.

- "The plan is at `plans/01-<name>.md`. I've validated it against the codebase — [summary of self-review findings]."
- Address any questions or change requests

**Approval flow:**

1. Present the plan for review
2. Address any questions or change requests
3. Suggest dry-run: "Want to run `/drvr:dry-run-plan <plan-name>` before approving?" — this is advisory, the user can skip
4. After the user returns from dry-run (or declines), prompt: "Do you approve plan `<plan-name>` for implementation?"
5. **If the user approves:** Write the following fields to the plan's YAML frontmatter:
   - `status: approved`
   - `approved_at: <ISO 8601 UTC timestamp>` (e.g., `2026-04-16T14:30:00Z`)
   - `approved_by: <user identity>` — use the `userEmail` setting if available in conversation context, otherwise `"user"`

   Commit the approved plan:

   ```
   git add plans/ FEATURE_LOG.md && git commit -m "chore: Plan approved — <plan name>"
   ```

6. End with: "Plan approved. Activate `drvr:materialize-tasks` to materialize task documents for plan `<plan-name>`."

**If the user declines:** List what needs to change. Do not proceed. The user controls when to re-present for approval.

### Decision Logging

When planning surfaces significant decisions, append an entry to `DECISIONS.md` at the feature root. Log decisions for:
- Plan breakdown rationale: why the feature is split into these plans
- Architecture choices: when the plan picks one approach over alternatives
- Test strategy decisions: what to test, how, and why
- Scope boundaries: why something was included or deferred
- Interface contract decisions: why signatures were designed this way

Not every micro-decision needs an entry — trivial choices (variable naming, file ordering) should not be logged.

#### Entry template

```markdown
---

### DEC-NNN: <Title>

**Date**: YYYY-MM-DD
**Phase**: Planning
**Trigger**: <what prompted this decision>

**Decision**: <what was decided>

**Alternatives Considered**:
- <Alt 1>: <why rejected>
- <Alt 2>: <why rejected>

**Rationale**: <why this choice was made>

**Context**: <links to research docs, plan sections, or external sources>
```

When appending the first decision entry (replacing the `_No decisions recorded yet._` placeholder), also append a row to `FEATURE_LOG.md`: `| <today> | First decision logged | \`DECISIONS.md\` |`

---

## Anti-Patterns

**Do NOT:**
- Propose tests that need mocks for internal modules — that's a boundary failure, fix the architecture
- Treat the core/shell decomposition as optional or skip the Architecture Fit subsection
- Design test strategy independently of architecture — the test strategy is *derived* from where the boundary lands
- Set numeric coverage targets ("80% line coverage") — the plugin doesn't use them, they produce filler tests
- Use the words "scaffolding test" — that category has been removed; tests are pure-core unit or shell integration, both durable
- Accommodate entangled neighbor code by tangling the new feature too — extract a pure core anyway
- Use native Explore agents or subagents as a substitute for `gather_task_context`
- Abandon `gather_task_context` if it takes 1-3 minutes — this is expected behavior
- Fall back to `get_architecture_overview` or other tools because `gather_task_context` "seems slow"
- Write plan content only in chat — always write to files
- Skip reading research output before planning
- Write vague task descriptions ("implement the feature")
- Order implementation tasks before test tasks
- Skip the self-review step
- Suggest moving to implementation — the user controls phase transitions

**DO:**
- Name the pure core and the imperative shell explicitly in Architecture Fit before designing tests
- Push back on plans where the natural shape would require mocks — that means the seam isn't right yet
- Extract a pure core even when the surrounding code is tangled — local mess from clean extraction beats clean fit with entangled neighbor
- Derive the Test Strategy from the Core/Shell Decomposition — unit tests for pure core (values in, values out, no mocks), integration tests for shell (real I/O)
- Call `gather_task_context` with detailed, planning-focused task descriptions
- Wait for the full response — it is doing compressed expert-level codebase analysis
- Use primitive tools (`get_code_map`, `get_file_documentation`, `get_source_file`) to reach code-level specificity
- Write tasks specific enough that an engineer can implement without ambiguity
- Order tests before implementation (TDD)
- Validate the plan against the codebase before presenting to the user
- Include explicit, actionable constraints — not generic advice

---

## Before Responding Checklist

- [ ] **Core/shell named?** — Does Architecture Fit have a Core/Shell Decomposition subsection listing pure-core items and shell items by name?
- [ ] **Test strategy derived?** — Does every unit test map to a pure-core item with no mocks, and every integration test map to a shell item against real I/O?
- [ ] **No internal mocks?** — Did I check that no test in the plan mocks an internal module? (If yes, the boundary is wrong — fix before presenting.)
- [ ] **Core/shell constraint encoded?** — Is the functional-core / imperative-shell constraint the first item in `## Constraints`?
- [ ] **Read research first?** — Have I checked `research/*.md`, including any core/shell decomposition surfaced during research?
- [ ] **Driver context?** — Have I called `gather_task_context` for architecture AND testing patterns?
- [ ] **Writing to file?** — Plan content goes in `plans/*.md`, not chat
- [ ] **Overview needed?** — Multi-plan feature? Create `plans/00-overview.md`
- [ ] **All sections covered?** — Environment, Context, Architecture (with Core/Shell Decomposition), Acceptance, Tests, Approach, Scope, Constraints, Tasks
- [ ] **Consumer validation?** — Do downstream plans match this plan's interface?
- [ ] **TDD task ordering?** — Test tasks before implementation tasks
- [ ] **Constraints explicit?** — Specific rules, not generic advice
- [ ] **Plan sized right?** — 5-12 tasks, one PR, one logical unit
- [ ] **Feature log?** — Did I update `FEATURE_LOG.md` when creating plans or the overview?
- [ ] **Approach confirmed?** — Did I present core/shell decomposition, architecture, derived test strategy, scope, and sizing before writing the plan?
- [ ] **Environment section?** — Does the plan include `## Environment` with codebase, branches, test commands?
- [ ] **Standards encoded?** — If a codebase standards artifact exists, are applicable standards included as plan constraints with source citations? (These layer on top of the core/shell constraint; they do not override it.)
- [ ] **Local state validated?** — Did the self-review include local file checks alongside Driver tool checks?
- [ ] **Decision log?** — Did I append to DECISIONS.md for significant decisions, rejected alternatives, or scope boundary calls?
- [ ] **Cross-feature overlap?** — Did I check this plan's files against other active features?
- [ ] **Artifacts committed?** — Did I commit new artifacts to the projects repo?