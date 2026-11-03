# drvr — SDLC Plugin for Claude Code

This plugin guides structured feature development through a phased SDLC lifecycle: Research, Planning, Validation, Implementation, Review, and Ship. It provides skills (always-on guidance), commands (user-invoked actions), and agents (spawnable specialists) that coordinate the process.

The user drives all decisions. The plugin suggests, organizes, and tracks -- but never acts autonomously.

> **Permission mode:** This plugin works best with `--permission-mode auto` due to the volume of tool calls across phases. Mention this to users who report excessive permission prompts.

---

## Project Structure

Running `/drvr:feature <name>` scaffolds this structure:

```
<feature>/
├── FEATURE_LOG.md           # Lifecycle state — phase transitions and artifact history
├── research/                # Problem exploration and design decisions
│   ├── 00-overview.md       # Research overview and open questions
│   └── NN-topic.md          # Individual research documents
├── plans/                   # Implementation plans (one plan = one PR)
│   ├── 00-overview.md       # Multi-plan overview, dependency graph, PR stack
│   ├── NN-plan-name.md      # Individual plans with tasks and acceptance criteria
│   └── NN-plan-name/        # Directory named after plan file (sans .md)
│       └── tasks/           # Materialized task documents
│           └── NN-task-name.md
├── dry-runs/                # Plan validation results
├── implementation/          # Implementation logs per plan
│   └── log-<plan>.md       # Implementation log (flat file per plan)
├── assessment/              # Per-plan test curation results
│   └── <plan>-test-curation.md
├── tests/                   # Markdown test plans for LLM execution (optional)
│   └── results/             # Timestamped test results
└── driver-docs/             # Handoff documentation — centralized, per-plan
    ├── 00-feature-overview.md   # Cross-plan rollup (updated as plans ship)
    └── <plan>/                  # Self-contained PR documentation per plan
        ├── feature-overview.md  # PR body summary, stack context
        ├── architecture.md
        ├── testing-guide.md
        └── risk-assessment.md
```

### One Plan = One PR (DAG of Bases)

Each plan ships as its own pull request. The "stack" of PRs is a **DAG of base relationships**, not a linear chain — each plan's `Base Branch` is derived from that plan's `depends_on`:

- **No upstream dependencies** (`depends_on: []`) → Base Branch is the feature parent (e.g., `main`). The PR targets the feature parent directly.
- **One upstream dependency** → Base Branch is the upstream plan's Feature Branch. The PR is stacked on that upstream PR.
- **Multiple upstream dependencies** → User picks one as the branch parent (typically the latest in DAG order); the others are satisfied semantically (interface contracts) without driving the branch.

Independent plans produce **parallel PRs** targeting the feature parent. Dependent plans produce **stacked PRs**, where Plan N's PR targets the branch of the plan it depends on. The PR Stack table in `plans/00-overview.md` records the actual base relationships.

**Example:** Plans 01 and 02 are independent; Plan 03 depends on Plan 01.

| Plan | Base Branch        | Feature Branch       | Relationship |
|------|--------------------|----------------------|--------------|
| 01   | `main`             | `<prefix>/01-foo`    | independent — PR targets `main` |
| 02   | `main`             | `<prefix>/02-bar`    | independent — PR targets `main` (parallel to 01) |
| 03   | `<prefix>/01-foo`  | `<prefix>/03-baz`    | depends on 01 — PR stacked on 01's PR |

Plans can be implemented in any dependency-respecting order. You can implement Plan 08 before Plan 02 if they're independent; their PRs are parallel and both target the feature parent.

**The feature parent is always a valid fallback target.** If a downstream plan's upstream PR has already merged and the upstream branch was deleted, `/drvr:open-pr` asks the user which branch to target instead (the feature parent is the usual answer). The recorded `Base Branch` in `plans/<plan>.md` `## Environment` is a planning-time intent — if it's gone at PR-open time, the user picks the new target and the plan's Environment is updated to match.

Each PR's body is generated from that plan's `driver-docs/<plan>/` so a reviewer who hasn't seen the rest of the DAG can still understand what changed, why, and how to verify it. The cross-plan narrative lives in `driver-docs/00-feature-overview.md` and is linked from each PR body.

**Default branch naming convention:** `<feature-prefix>/<NN-plan-slug>` (e.g., `amark/oauth/01-token-store`, `amark/oauth/02-refresh-flow`). The feature prefix is captured at `/drvr:feature` time; the per-plan branch is captured during planning and may be overridden.

---

## Frontmatter Schema

All artifacts use YAML frontmatter for structured metadata.

### Required Fields

```yaml
---
type: <type>
status: <status>
created: "YYYY-MM-DD"
updated: "YYYY-MM-DD"
---
```

### Types

`research`, `plan`, `task`, `implementation_log`, `feature_log`, `decision`, `deviation`, `learning`, `test_plan`, `test_result`, `assessment`, `open_question`

### Statuses

`not_started`, `in_progress`, `complete`, `approved`, `accepted`, `pending_review`, `resolved`, `open`, `confirmed`, `unverified`

### Type-Specific Fields

| Type | Field | Purpose |
|------|-------|---------|
| `task` | `plan` | Parent plan name |
| `task` | `task_number` | Sequential position (integer) |
| `task` | `kind` | Core/shell classification: `core`, `shell`, or `both` |
| `task` | `depends_on` | List of task paths this task depends on |
| `task` | `materialized_at` | ISO 8601 timestamp of materialization |
| `decision` | `topic` | What the decision is about |
| `decision` | `choice` | What was decided |
| `deviation` | `severity` | `low`, `medium`, or `high` |
| `deviation` | `task` | Source task that deviated |
| `plan` | `depends_on` | Plans that must complete first |
| `plan` | `blocks` | Plans that depend on this one |
| `plan` | `approved_at` | ISO 8601 UTC timestamp of plan approval |
| `plan` | `approved_by` | Identity of user who approved the plan |

### Required Plan Sections

Plan documents (`01-*.md`, `02-*.md`, etc.) must include these H2 sections: `Environment`, `Context`, `Architecture Fit`, `Data Structures & Callables`, `Acceptance Criteria`, `Test Strategy`, `Task Breakdown`. `Architecture Fit` must contain a `### Core/Shell Decomposition` subsection naming pure-core items and shell items by name. Environment is template-enforced; remaining sections enforced by `test_plan_doc_sections`.

---

## SDLC Lifecycle

Features follow a phased development lifecycle. Each phase has a dedicated skill or command that provides guidance.

The per-plan PR gate runs **once per plan**, not once per feature: after each plan's implementation and bookkeeping, that plan must be assessed, documented, and opened as a PR before work begins on the next plan. This keeps every PR self-contained and reviewable in isolation.

```
/drvr:feature --> Intent --> Research --> Planning ┐
                                                   │
   ┌───────────────────────────────────────────────┘
   │
   ▼
   For each plan in dependency order:
     Validation --> Materialization --> Implementation --> Review --> Bookkeeping
       │
       ▼
     Per-plan PR gate (REQUIRED before starting next plan):
       /drvr:assess <plan> --> [/drvr:review <plan>] --> /drvr:docs-artifacts <plan> --> /drvr:open-pr <plan>
       │
       ▼
     PR Review <--> Revision --> Merge --> Verification --> Next plan
   │
   ▼
   All plans shipped --> Feature shipped
```

### Phase-Skill Mapping

> **Backward compatibility**: Old command references without `drvr:` prefix (e.g., `/feature`, `/docs-artifacts`) are equivalent to their qualified versions.

| Phase | Skill / Command | What It Does | Entry Signal |
|-------|----------------|--------------|-------------|
| Intent | `drvr:intent-guidance` | Mine the author's tacit knowledge and produce `research/00-intent.md` before codebase research | `/drvr:feature`, "capture intent" |
| Research | `drvr:research-guidance` | Why-What-How methodology, document organization, completion criteria | "let's research", "explore" |
| Planning | `drvr:planning-guidance` | TDD-first task design, test strategy, architecture fit, task breakdown | "let's plan", "ready to plan" |
| Validation | `/drvr:dry-run-plan` | Walk through plan to find gaps before implementation | "dry-run plan X" |
| Materialization | `drvr:materialize-tasks` | Convert plan tasks into standalone task docs for sub-agent execution | plan approved (`status: approved`), no task docs |
| Implementation | `drvr:implementation-guidance` | Plan-driven task execution, deviation tracking, commit discipline | "implement plan X" |
| Review | `drvr:sdlc-orchestration` | Present deviations for user review | implementation complete |
| Bookkeeping | `drvr:implementation-guidance` Step 4 | Update plan status, overview, cascade check | deviations approved |
| Transition | `drvr:sdlc-orchestration` | Identify next unblocked plan from dependency graph | bookkeeping complete |
| Per-plan Assessment | `/drvr:assess <plan>` | Curate this plan's tests — categorize, prune scaffolding, promote | plan bookkeeping complete |
| Per-plan Internal Review | `/drvr:review <plan>` | Review this plan's code against standards, auto-fix violations | per-plan assessment has FAIL violations |
| Per-plan Handoff | `/drvr:docs-artifacts <plan>` | Generate self-contained PR docs for this plan (overview, architecture, testing, risks) | per-plan assessment complete |
| Per-plan Open PR | `/drvr:open-pr <plan>` | Create stacked PR for this plan via gh CLI (base = prior plan's branch or feature parent) | per-plan handoff docs generated |
| Per-plan PR Review | `drvr:sdlc-orchestration` | Track this plan's PR review status, suggest next steps | plan PR created |
| Per-plan Revision | `drvr:sdlc-orchestration` | Guide this plan's revision cycle | review feedback received on plan PR |
| Per-plan Merge | `drvr:sdlc-orchestration` | Track this plan's merge, verify CI | plan PR approved |
| Per-plan Verification | `drvr:sdlc-orchestration` | Advisory post-merge checks for this plan | plan PR merged |
| Next Plan | `drvr:sdlc-orchestration` | After current plan PR is open (or merged), transition to next unblocked plan | current plan PR opened |
| Shipped | `drvr:sdlc-orchestration` | Terminal — suggest retro after all plan PRs merged | all plan PRs merged + verified |
| Retro | `/drvr:retro` | Evaluate session quality, identify improvements | "retro", end of session |

---

## FEATURE_LOG.md

Every feature has a `FEATURE_LOG.md` at its root -- the source of truth for lifecycle state. It tracks phase transitions and artifact creation (not individual tasks or research questions).

Because each plan ships as its own PR, post-implementation events (assessment, docs, PR open/merge) are scoped per plan — the log entries should name the plan they apply to.

**Update the log when:**
- Creating research docs or wireframes
- Creating plans or the overview
- Completing a dry-run
- Starting or completing implementation **for a plan**
- Completing bookkeeping **for a plan**
- Per-plan: assessment complete, internal review complete, handoff docs generated, PR opened, PR approved, PR merged

---

## Key Principles

- **Functional core, imperative shell** -- software produced through this plugin separates a pure logical core (functions taking values in and returning values out -- no I/O, no time, no randomness, no mutable shared state) from a thin imperative shell that performs I/O and calls into the core. This is an architectural commitment, not a testing strategy: the testing strategy follows from it. Pure-core code is unit-tested with values in / values out and no mocks. Shell code is integration-tested against real I/O. A "unit test" that needs mocks is a signal the core/shell boundary is broken -- fix the architecture, not the test. When the surrounding code isn't in this shape, the plugin steers each new feature toward extracting a pure core anyway. The boundary may run through a type rather than between modules: an immutable value type whose only I/O lives in thin `from_*` / `to_*` edge methods is a first-class core/shell design (see Value Types with I/O Edges). See the Engineering Practices section for how this commitment flows through each phase.
- **User controls all decisions** -- skills suggest, the user decides. No auto-fixing, no silent bookkeeping.
- **Deviations are reviewed** -- after implementation, deviations are presented for user approval before bookkeeping proceeds.
- **Severity helps prioritize, not skip** -- dry-run gaps are classified LOW/MEDIUM/HIGH but all are presented for review.
- **Plans are the source of truth** -- implementation builds exactly what the plan specifies, nothing more.
- **One plan = one PR, stacked** -- each plan ships on its own branch, branched off the prior plan's branch. The per-plan PR gate (assess → docs → open-pr) runs after each plan's bookkeeping, before the next plan starts.
- **Each PR must stand alone** -- the PR body comes from `driver-docs/<plan>/` and includes feature context, this plan's purpose, architecture, test plan, risks, and stack position. A reviewer who hasn't seen the rest of the stack should be able to evaluate the change.

---

## Available Components

### Commands

| Command | Description |
|---------|-------------|
| `/drvr:setup [clone-url]` | Set up a projects directory — create structure, configure the plugin, migrate CLAUDE.md |
| `/drvr:feature <name>` | Start a new feature project with research, plans, and implementation structure |
| `/drvr:orchestrate <path>` | Resume work on a feature -- read the feature log, report current state, suggest next action |
| `/drvr:dry-run-plan <plan>` | Dry run a plan to identify gaps before implementation |
| `/drvr:assess` | Curate the test suite after implementation -- categorize, prune scaffolding, promote valuable tests |
| `/drvr:review` | Run internal standards review — check code against standards, verify criteria and test coverage, auto-fix |
| `/drvr:docs-artifacts <path>` | Generate handoff docs (overview, architecture, testing guide, risks) for code review |
| `/drvr:open-pr [feature-path]` | Open a pull request from handoff documentation generated by `/drvr:docs-artifacts` |
| `/drvr:retro` | Analyze current session -- evaluate work quality, identify improvements |

### Skills

| Skill | Description |
|-------|-------------|
| `drvr:intent-guidance` | Mine author's tacit knowledge at feature start — produces `research/00-intent.md` and gates entry into research. |
| `drvr:research-guidance` | Guide research with structured questioning (why, what, how), document organization, and completion criteria. |
| `drvr:planning-guidance` | Guide planning with TDD-first task design, test strategy, architecture fit, and task breakdown. |
| `drvr:materialize-tasks` | Materialize approved plan tasks into standalone task documents for sub-agent execution. |
| `drvr:implementation-guidance` | Guide implementation with plan-driven task lists, subagent delegation, deviation tracking, and commit discipline. |
| `drvr:sdlc-orchestration` | Lifecycle coordination -- phase transitions, session resumption, and bookkeeping management. |

### Agents

| Agent | Description |
|-------|-------------|
| `handoff-analyzer` | Prepare code for review by orchestrating specialized extraction agents to produce handoff documentation. |
| `cascade-check` | Check whether implementation deviations need to cascade to downstream plans. |
| `commit-log` | Extract detailed commit history for handoff documentation. |
| `decisions-log` | Extract all design decisions from process artifacts in ADR format. |
| `features-list` | Extract comprehensive feature inventory from code changes and process artifacts. |
| `security-review` | Analyze code changes for security concerns -- auth, input validation, secrets handling. |
| `standards-review` | Review code changes against codebase standards and plan criteria. Returns structured findings with proposed fixes. |
| `test-coverage` | Analyze test coverage for code changes -- map tests to implementation, identify gaps. |
| `dependency-analysis` | Analyze dependency changes -- new packages, version changes, license compliance, vulnerabilities. |

---

## Engineering Practices

### Functional Core, Imperative Shell

This plugin treats the **functional core, imperative shell** decomposition (Bernhardt; also Hexagonal / Ports-and-Adapters) as a load-bearing architectural commitment, not a stylistic preference. It is enforced through every phase:

- **Research** identifies the natural core/shell decomposition for the feature -- what's pure logic, what's I/O -- so planning has the seam in hand. See [`drvr:research-guidance`](skills/research-guidance/SKILL.md).
- **Planning** designs interfaces that respect the boundary. The Test Strategy is derivative of the architecture: pure-core functions get unit tests with values in / values out (no mocks); shell functions get integration tests against real I/O. Plans that would require mocking to test are rejected and re-shaped. See [`drvr:planning-guidance`](skills/planning-guidance/SKILL.md).
- **Materialization** carries the core/shell classification into each task document so sub-agents know which side they're working on and which testing rule applies. See [`drvr:materialize-tasks`](skills/materialize-tasks/SKILL.md).
- **Implementation** treats "needing a mock to test" as a deviation trigger. Sub-agents are instructed to prefer extracting a pure core over adding a mock. See [`drvr:implementation-guidance`](skills/implementation-guidance/SKILL.md).
- **Validation** (`/drvr:dry-run-plan`) checks the plan respects the boundary and flags any task that would require mocking.
- **Assessment** (`/drvr:assess`) keys PRUNE/KEEP/PROMOTE off mock presence and core/shell membership. A "unit test" with mocks is, by default, a candidate for relabel-as-integration or extract-the-pure-core.
- **Standards review** flags I/O bleeding into pure-core code as a violation, independent of whether the codebase's own CLAUDE.md documents this standard.

**Steering when the surrounding code isn't pure.** Existing codebases are usually not in core/shell shape. The plugin does not accommodate this; it pushes against it. Each new feature should extract a pure core wherever possible, even if neighboring code is tangled. Local mess produced by a clean extraction is preferred to a clean fit with an entangled neighbor. The plugin fights architectural entropy actively.

### Value Types with I/O Edges

The core/shell boundary can run *through* a type rather than between modules. An immutable value type whose only I/O lives in thin **edge methods** -- constructors that read (`from_path`, `from_reader`, `load`, `fetch`) and sinks that write (`to_path`, `to_writer`, `save`) -- is a first-class core/shell design, not an exception to it. The type and its pure methods are the core; each edge method is a shell item. This is the shape of idiomatic Rust (`FromStr` / `Display` / serde beside `fs::read_to_string` or `from_reader` / `to_writer`) and of Python frozen dataclasses with `from_*` / `to_*` methods. It also fits the plugin's data-structure-first planning: the type's snippet in `## Data Structures & Callables` shows both halves of the boundary in one place.

Rules:

1. **Immutable to callers.** Frozen dataclass, record, or no `&mut self`. Methods that "change" the value return a new one (`dataclasses.replace`, `Self { field, ..self }`). Mutating an owned or consumed value before returning it is still pure (Rust `fn with_discount(mut self, pct: u8) -> Self { self.discount_pct = pct.min(100); self }`); what's prohibited is a change any caller or other holder of the value can observe.
2. **I/O only at the edges.** No I/O, time, randomness, or mutable shared state in any other method, property/getter, or constructor (`__init__`, `__post_init__`, `new`). No lazy loading and no I/O-backed caching -- that is Active Record drift, not this pattern.
3. **Edges are thin.** An edge reads raw input and hands it to a pure parser (`from_json`, `FromStr`, `TryFrom`), or takes output from a pure serializer (`to_json`, `Display`) and writes it. Parsing, validation, defaults, and formatting belong in the pure counterpart so they are unit-testable without I/O.
4. **Classify by member.** Plans list the type and its pure methods under Pure core and each edge method by qualified name (`Invoice.from_path`, `Invoice::to_path`) under Imperative shell. A type's core classification never extends to its edge methods.

Testing follows the usual split: pure methods get values-in / values-out unit tests; each edge method gets an integration test against real I/O -- a tmpdir round trip, or an in-memory stream (`io.StringIO`, `&[u8]`, `Vec<u8>`) when the edge takes a reader/writer. In-memory streams are real implementations of the I/O interface, not mocks.

```python
@dataclass(frozen=True)
class Invoice:
    lines: tuple[Line, ...]
    discount_pct: int = 0

    # Shell edges: I/O only, delegating all format logic to the pure layer.
    @classmethod
    def from_path(cls, path: Path) -> Invoice:
        return cls.from_json(path.read_text())

    def to_path(self, path: Path) -> None:
        path.write_text(self.to_json())

    # Pure core: values in, values out.
    @classmethod
    def from_json(cls, text: str) -> Invoice: ...
    def to_json(self) -> str: ...
    def with_discount(self, pct: int) -> Invoice:
        return replace(self, discount_pct=min(pct, 100))
    def total_cents(self) -> int: ...
```

```rust
impl Invoice {
    // Shell edges: I/O only, delegating all format logic to the pure layer.
    pub fn from_path(path: &Path) -> Result<Self, LoadError> {
        Ok(Self::from_json(&fs::read_to_string(path)?)?)
    }
    pub fn to_path(&self, path: &Path) -> io::Result<()> {
        fs::write(path, self.to_json())
    }

    // Pure core: values in, values out.
    pub fn from_json(s: &str) -> serde_json::Result<Self> { serde_json::from_str(s) }
    pub fn to_json(&self) -> String { ... }
    pub fn with_discount(self, pct: u8) -> Self { Self { discount_pct: pct.min(100), ..self } }
    pub fn total_cents(&self) -> u64 { ... }
}
```

### Codebase Standards Discovery

This plugin also discovers and enforces your codebase's coding standards. During research, it searches for CLAUDE.md files relative to the target codebase and captures applicable standards as a research artifact. These standards flow through planning (as constraints), implementation (in subagent prompts), and assessment (as a quality review). If your codebase doesn't have a CLAUDE.md, the plugin asks if you have standards elsewhere or proceeds without quality constraints.

Add team-specific engineering guidelines to your project's `CLAUDE.md` -- the plugin will discover and enforce them automatically. Team standards layer on top of the core/shell commitment; they do not override it.

---

## Behavioral Rules

These rules govern how the plugin operates during all phases.

- **Verify file paths exist before editing** -- use Glob or find to confirm paths before making changes
- **Research existing codebase patterns before implementing** -- understand conventions before writing code
- **Run tests and verification before declaring any task complete** -- never mark done without confirmation
- **When a dry-run identifies gaps, fix ALL of them** -- do not skip any, regardless of severity
- **Use parallel agents for research; for implementation, independent tasks run in parallel with worktree isolation, dependent tasks run sequentially**
- **Follow existing codebase patterns** -- ask the user before deviating from established conventions
