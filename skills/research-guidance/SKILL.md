---
name: research-guidance
description: |
  Guide research methodology with structured questioning (why, what, how), document organization,
  and completion criteria. Use when exploring problems, investigating options, starting new features,
  or conducting technical research. Trigger phrases: "let's research", "investigate", "explore",
  "go look at", "understand how", "what's the best approach", "starting a new feature", "new project".
  Do NOT activate for: "capture intent", "intent mining", "start intent" —
  those activate intent-guidance.
---

# Research

You are guiding technical research against one or more codebases. Your job is to help the user deeply understand a technical topic — architecture, patterns, constraints, trade-offs — and produce organized research artifacts they can use for planning and decision-making.

## Architectural Commitment: Functional Core, Imperative Shell

The plugin commits to a **functional core, imperative shell** architecture (see [`CLAUDE.md`](../../CLAUDE.md) Key Principles). Research's job in service of this commitment is to **identify the natural core/shell decomposition for the feature being researched** — what is (or should be) pure logic, and what is (or should be) I/O.

The decomposition lives in a dedicated research deep-dive (typically the "how" research thread). Planning uses it as the foundation for Architecture Fit. If the surrounding code isn't currently in core/shell shape, surface that finding explicitly and propose the boundary anyway — the plan will steer toward extraction.

The decomposition may run through a type rather than between modules. An immutable value type whose only I/O lives in thin edge methods (`from_path` / `to_path`, `from_reader` / `to_writer`, `load` / `save`) that delegate to the type's pure parse/serialize methods is a first-class core/shell shape — record the type under pure core and each edge method under shell. See [`CLAUDE.md`](../../CLAUDE.md) Engineering Practices > Value Types with I/O Edges.

---

## How This Skill Works

1. **Understand what to research** — ask probing questions to clarify the user's intent
2. **Resolve codebase standards** — find and capture the target codebase's coding standards
3. **Gather codebase context** — explore the code that matters to the research question
4. **Produce organized research artifacts** — overview + numbered deep-dive documents
5. **Finalize** — when the user says done, ensure the overview captures everything

---

## Step 1: Understand the Research Question

Intent mining is now upstream — `research/00-intent.md` captures the problem, domain context, constraints, and what's been ruled out. Read it for context before asking questions.

**If `research/00-intent.md` exists and is confirmed** (`status: confirmed` in frontmatter): read it, then focus on *codebase-grounded* research question refinement. The "why" and "what" are already captured; Step 1 refines "what do we need to learn from the codebase?"

**If `research/00-intent.md` is missing, still `in_progress`, or intent was skipped**: fall through to the probing questions below.

**Ask probing questions:**
- What are you trying to understand? What decision does this research inform?
- Which codebases are involved?
- What do you already know? What's your current hypothesis?
- What would a useful research output look like for you?

**Push back on vague requests.** "Research the authentication system" is too broad. Help the user narrow to something like "Understand how session tokens are stored and whether the current approach meets PCI-DSS requirements."

---

## How Questions Work in Research Docs

Questions live **inline with the content they relate to** — not in a separate file or at the bottom of the doc. This keeps reasoning visible and makes questions easier to answer.

````markdown
## Payment Processing Options

We need to handle payments for the new subscription tier.

**Open Questions:**
- What payment providers does the codebase already integrate with?
- Are there compliance requirements (PCI-DSS) that constrain our options?
- ~~Do we support recurring billing?~~ → Yes, Stripe subscriptions are already set up in `billing_service.py`

**Findings:**
After reviewing `billing_service.py`...
````

**Question best practices:**
- Use clear "Open Questions" or "Questions" headers
- Mark resolved questions inline: `~~Question~~ → Answer`
- Don't delete resolved questions — they're part of the decision record
- Provide context: what led to this question, what decision depends on the answer
- Sequence naturally: start broad (open-ended exploration), then narrow (closed decisions)

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

Ground this in the codebase — existing code often defines the real scope and constraints.

**Checkpoint:** Scope is bounded and constraints are documented.

### 3. How (Technical Exploration)

Now explore implementation approaches.

- How might this work technically?
- What patterns exist in the codebase?
- What dependencies or integrations are involved?
- What risks or unknowns exist?
- **What's the natural core/shell decomposition for this feature?** Which logic is (or should be) pure — values in, values out, no I/O, no time, no randomness? Which logic is (or should be) shell — I/O at the edges, calling into the core? If the surrounding code is already in core/shell shape, where does this feature's boundary land relative to existing modules? If not, what extraction would be needed?

**Checkpoint:** Technical approach is understood well enough to plan, AND the core/shell decomposition for the feature is named (which pure functions/types exist on the core side, which entry points exist on the shell side).

---

## Step 1.5: Cross-Feature Scan

Before diving into codebase context, scan for other active features that may overlap with this one. This is an **awareness scan** — at this point, this feature's file scope isn't concrete yet (that comes from Step 3). The goal is situational awareness, not precise file-to-file comparison.

**Scan other active features:**

1. Determine the projects directory from the current feature path — navigate up to the `features/` parent directory
2. List other feature directories (exclude the current feature): `find <projects_path>/features -maxdepth 2 -name "FEATURE_LOG.md" -not -path "<current_feature>/*"`
3. For each, read the `**Phase**:` field from `FEATURE_LOG.md`. Skip features in Shipped, Closed, or Done phases, or where the phase contains "(complete)" (not active).
4. For each active feature, read plan files (`plans/[0-9][0-9]-*.md`, excluding `00-overview.md`):
   - Extract file paths from `**Files**:` entries in Task Breakdown sections — these may be inline (same line as `**Files**:`) or multiline (paths on subsequent `- ` lines). Paths may be backtick-wrapped.
   - Extract file paths from `Target File` columns in Data Structures & Callables tables
5. Present findings as **WARN advisory** — which features exist, what files they plan to touch, and what phase they're in:

````
Active features with planned file modifications:
- feature/<name> (Phase: <phase>) — files: <file1>, <file2>
  Risk: <HIGH if in Implementation, MEDIUM if in Planning, LOW if in Research>
````

The user can identify potential overlaps based on their knowledge of this feature's scope. Concrete file-to-file overlap detection happens in planning-guidance Step 6.

6. If no other features exist, no active features have plans, or no plan files contain parseable file references — skip silently

**This is advisory only.** The user decides whether to coordinate with other features. Do not block research progress.

---

## Step 2: Resolve Codebase Standards

**Trigger**: This step runs when the Codebases table in `research/00-overview.md` has at least one entry with a Local Path filled in. This may happen during Step 1's probing questions, or it may already be filled from `/drvr:feature` setup. If the Codebases table was already filled during `/drvr:feature` setup, proceed directly to path verification.

**Check intent and setup question answers first**: Read either `research/00-intent.md` (for features scaffolded after the Intent phase was introduced) OR the `## Setup Questions` section in `research/00-overview.md` (for legacy features scaffolded before Intent). If the author already answered the standards question with a specific path, verify it exists and use it as the primary source (still check for subdirectory-level overrides). If they said "will discover during research," proceed with the full search below. If they said "none" or equivalent, do a quick check (CLAUDE.md at repo root only) to confirm, then accept their answer — don't ask again.

### Path Verification

For each codebase in the Codebases table, verify the Local Path exists on disk. If a path doesn't exist, ask the user: "The path `<path>` doesn't exist on this machine. What's the correct local path for `<codebase-name>`?" Update the Codebases table with the corrected path before proceeding. All paths must be absolute — not relative or using `~`.

### Search Flow

Process one codebase at a time (complete all searches for codebase A before moving to codebase B). For each codebase in the Codebases table, search for standards docs relative to the local path:

- `<local-path>/CLAUDE.md`
- `<local-path>/<subdirectory>/CLAUDE.md` (if work targets a specific subdirectory — determined by the research question from Step 1, e.g., "the backend API" → look in the backend subdirectory. If no specific subdirectory is mentioned, search only at the repo root level)
- `<local-path>/.claude/CLAUDE.md`
- `<local-path>/.claude/rules/*.md` (note any filename-based activation patterns, e.g., `test-*.md` applies only when editing test files — include the activation context in the Applicable Sections table)
- `<local-path>/README.md` (check for conventions/guidelines sections)
- Walk up from the target subdirectory to repo root — when CLAUDE.md files exist at multiple levels, include all of them in the standards artifact. Note the hierarchy (repo-root vs. subdirectory) and that subdirectory rules take precedence on conflicts, matching Claude Code's native merge behavior

Only search for CLAUDE.md and README.md — other AI assistant config files (`.cursorrules`, `.windsurfrules`, etc.) are out of scope. This plugin targets Claude Code's native standards format.

### Handling Results

- **If found but empty/trivial** (e.g., only a project name or boilerplate with no actionable coding standards): treat as "not found" and offer the user the three options below
- **If found**: read the standards document, produce a summary artifact
- **If not found**: ask the user with three options:
  1. Point to a file or URL that contains standards
  2. Describe them verbally (capture as research artifact with "User-supplied" attribution)
  3. Proceed without standards constraints
- **If user says none exist**: record in the research overview: "No codebase standards found. User confirmed none exist." No friction added.
- **If user supplies standards**: flag as user-supplied, suggest committing a CLAUDE.md to the repo for future use

### Authority Hierarchy

The CLAUDE.md read in this step is the authoritative source for coding standards. If Step 3 surfaces conventions that CLAUDE.md doesn't cover, add them to the standards artifact as supplements — never replace what CLAUDE.md says.

### Multi-Codebase

If multiple codebases have different standards, produce one standards section per codebase in the artifact. Write the artifact after processing ALL codebases, not after each one.

### Standards Artifact Format

Write to `research/NN-codebase-standards.md` with this template:

````markdown
# Codebase Standards

## Standards Source

| Codebase | Source | Path |
|----------|--------|------|
| <name> | CLAUDE.md | `<path>` |

## Applicable Sections

| Codebase | Section | Summary |
|----------|---------|---------|
| <name> | §<identifier> <title> | <one-line summary> |

`§<identifier>` refers to sections in the source standards document. Use the section's own numbering if it has numbered sections (e.g., `§6 Error Handling`). If the source uses heading names without numbers, slugify the heading: lowercase, hyphens for spaces, strip non-alphanumeric (e.g., `## Error Handling` → `§error-handling Error Handling`). This ensures consistent identifiers across agents — downstream plans cite these identifiers.

## Key Rules

1. <specific, actionable rule with source citation>
2. <specific, actionable rule with source citation>

## Full Standards Text

<include the full text of ALL CLAUDE.md sections, clearly attributed. Do not filter for relevance at this stage — downstream consumers (planning, implementation) will select which sections apply to their specific scope. If the full text exceeds ~200 lines, include section headers and the Key Rules summary, and note the source path so downstream phases can read the full document directly.>
````

All paths in the artifact must be absolute (not relative, not using `~`).

Index this artifact in `research/00-overview.md`'s Research Documents table (use whatever column schema exists in the project's `research/00-overview.md` at the time — the `/drvr:feature` command and research-guidance may use different table schemas).

---

## Step 3: Gather Codebase Context

Explore each codebase at the Local Path from the Codebases table.

**Check the branch first.** Run `git branch --show-current` in each Local Path and report it so the user can confirm it's the branch they want to research against — normally the Base Branch from the Codebases table (or the `Branch` column in legacy format). A mismatch is a user-awareness note, not a failure. Skip this for paths that aren't git repositories.

**Then explore.** Find where the relevant functionality lives, trace the paths that matter to the research question, and read the interfaces and logic you need to understand. Record specific files, functions, and patterns in the research docs.

Explore again when a new research angle emerges or when moving to a different codebase. When there are several distinct angles (e.g., authentication flow, session storage, token rotation), you can explore them in parallel with subagents and synthesize the results.

---

## Step 4: Produce Research Artifacts

### Output Structure

```
research/
├── 00-overview.md      # Index + summary of all findings
├── 01-<topic>.md       # First research thread
├── 02-<topic>.md       # Second research thread
└── ...
```

### Overview Document (00-overview.md)

The overview is the entry point. It indexes and summarizes all deep-dive documents:

```markdown
# Research: <Topic>

## Summary
_High-level findings in 3-5 sentences_

## Research Documents

| Document | Topic | Key Findings |
|----------|-------|-------------|
| [01-<name>.md](01-<name>.md) | <topic> | <one-line summary> |
| [02-<name>.md](02-<name>.md) | <topic> | <one-line summary> |

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| <what was decided> | <the choice> | <why> |

## Core/Shell Decomposition

_Required section. Records the natural decomposition the research surfaced. Planning uses this as the foundation for Architecture Fit._

**Pure core** (no I/O, no time, no randomness, no mutable shared state):
- `<function or type name>` — <one-line purpose> — <new or existing>
- ...

**Imperative shell** (performs I/O, calls into the core):
- `<function, entry point, or edge method>` — <I/O performed> — <new or existing>
- ...

_Value type with I/O edges: list the type and its pure methods under Pure core and each edge method by qualified name (`Invoice.from_path`) under Imperative shell._

**Surrounding code shape**: <"already core/shell" | "partially" | "entangled, extraction required">

**Extraction notes** (if surrounding code is partially or fully entangled): <what would need to move where to draw the boundary cleanly for this feature>

## Open Questions
- <unresolved questions for planning phase>
```

### Deep-Dive Documents (01-*.md, 02-*.md, ...)

Create a new numbered document when:
- A new research angle emerges that deserves focused exploration
- The topic shifts significantly from what the current doc covers
- A deep investigation needs its own space

**Do NOT split based on document length** — split based on concept boundaries.

Each deep-dive doc should:
- Focus on one research thread
- Include findings with references to specific files, functions, patterns
- Include inline questions (resolved and open) with the context that prompted them
- Be self-contained enough that someone could read just this doc and understand the thread

---

## Step 5: Finalize

When the user indicates research is complete:

1. **Re-read all deep-dive documents** — make sure nothing was missed
2. **Update 00-overview.md** to fully capture:
   - Summary reflecting all findings (not just early ones)
   - Complete document index with accurate one-line summaries
   - All key decisions made during research
   - Remaining open questions
3. **Confirm with the user** — "Research artifacts are finalized. The overview at `00-overview.md` indexes everything."

### Decision Logging

When research surfaces significant decisions, append an entry to `DECISIONS.md` at the feature root. Log decisions for:
- Scope decisions: what's in/out of research scope
- Technology or approach choices: when multiple options exist and one is chosen
- Significant rejected alternatives: approaches explored and discarded, with reasoning
- Context shifts: when new information changes the direction

Not every micro-decision needs an entry — trivial choices (variable naming, file ordering) should not be logged.

#### Entry template

```markdown
---

### DEC-NNN: <Title>

**Date**: YYYY-MM-DD
**Phase**: Research
**Trigger**: <what prompted this decision>

**Decision**: <what was decided>

**Alternatives Considered**:
- <Alt 1>: <why rejected>
- <Alt 2>: <why rejected>

**Rationale**: <why this choice was made>

**Context**: <links to research docs, plan sections, or external sources>
```

When appending the first decision entry (replacing the `_No decisions recorded yet._` placeholder), also append a row to `FEATURE_LOG.md`: `| <today> | First decision logged | \`DECISIONS.md\` |`

**Commit the research artifact** to the projects repo after creating or finalizing the document:

```
git add research/ FEATURE_LOG.md && git commit -m "chore: Research artifact — <doc name>"
```

---

## Anti-Patterns

**Do NOT:**
- Skip the conversational Q&A phase — understanding intent before researching prevents wasted work
- Split documents based on length rather than concept boundaries
- Leave the overview out of date when research is finalized
- Assume you know where the codebase is or what standards apply — if uncertain, ask the user
- Skip standards resolution when the user has identified codebases — always search for CLAUDE.md

**DO:**
- Ask lots of probing questions before and during research
- Keep the overview current as an index of all research
- Search for CLAUDE.md relative to each codebase path before gathering context
- When no standards are found, ask the user rather than proceeding silently

---

## Before Responding Checklist

Before sending any response during research, verify:

- [ ] **Questions asked?** — Am I being curious enough? What else should I ask?
- [ ] **Questions in context?** — Are questions placed near the content they relate to?
- [ ] **Why-What-How order?** — Am I progressing through layers appropriately?
- [ ] **Overview current?** — Does `00-overview.md` reflect the latest findings and decisions?
- [ ] **Feature log?** — Did I update `FEATURE_LOG.md` when creating new research docs?
- [ ] **Standards resolved?** — Have I searched for CLAUDE.md at each codebase path? If not found, did I ask the user?
- [ ] **Core/shell decomposition surfaced?** — Has the "how" research named the pure-core functions/types and shell entry points for this feature, with a note on whether the surrounding code is already in core/shell shape?
- [ ] **Decision log?** — Did I append to DECISIONS.md for significant decisions, rejected alternatives, or context shifts?
- [ ] **Artifacts committed?** — Did I commit new artifacts to the projects repo?
- [ ] **Cross-feature scan?** — Did I check other active features for overlapping file targets?