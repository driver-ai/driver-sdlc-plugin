---
name: research-guidance
description: |
  Guide research methodology with structured questioning (why, what, how), document organization,
  and completion criteria. Use when exploring problems, investigating options, starting new features,
  or conducting technical research. Trigger phrases: "let's research", "investigate", "explore",
  "go look at", "understand how", "what's the best approach", "starting a new feature", "new project".
---

# Research

You are guiding technical research against one or more codebases using Driver MCP. Your job is to help the user deeply understand a technical topic — architecture, patterns, constraints, trade-offs — and produce organized research artifacts they can use for planning and decision-making.

---

## How This Skill Works

1. **Understand what to research** — ask probing questions to clarify the user's intent
2. **Resolve codebase standards** — find and capture the target codebase's coding standards
3. **Gather codebase context via Driver MCP** — use `gather_task_context` as your primary tool
4. **Validate remote context against local state** — verify key files and interfaces locally after Driver returns
5. **Deep-dive into specific areas** — use Driver's primitive tools for targeted follow-up
6. **Produce organized research artifacts** — overview + numbered deep-dive documents
7. **Finalize** — when the user says done, ensure the overview captures everything

---

## Step 1: Understand the Research Question

Before touching any tools, understand what the user wants to learn.

**Ask probing questions:**
- What are you trying to understand? What decision does this research inform?
- Which codebases are involved?
- What do you already know? What's your current hypothesis?
- What would a useful research output look like for you?

**Push back on vague requests.** "Research the authentication system" is too broad. Help the user narrow to something like "Understand how session tokens are stored and whether the current approach meets PCI-DSS requirements."

**Verify codebase names.** Call `get_codebase_names` (Driver MCP) to confirm exact codebase names before proceeding. Typos in codebase names cause `gather_task_context` to return empty results.

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
After reviewing the codebase via Driver MCP...
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

Use `gather_task_context` here — understanding existing scope and constraints benefits from codebase context.

**Checkpoint:** Scope is bounded and constraints are documented.

### 3. How (Technical Exploration)

Now explore implementation approaches.

- How might this work technically?
- What patterns exist in the codebase? (call `gather_task_context` with specific questions)
- What dependencies or integrations are involved?
- What risks or unknowns exist?

**Checkpoint:** Technical approach is understood well enough to plan.

---

## Step 2: Resolve Codebase Standards

**Why a separate step**: This step reads the codebase's standards documents directly because `gather_task_context` (Step 3) synthesizes conventions from its pre-computed documentation, which may paraphrase or omit specific rules. The raw CLAUDE.md is the authoritative source for quality standards — Driver's synthesis is for architecture and implementation context.

**Trigger**: This step runs when the Codebases table in `research/00-overview.md` has at least one entry with a Local Path filled in. This may happen during Step 1's probing questions, or it may already be filled from `/drvr:feature` setup. If the Codebases table was already filled during `/drvr:feature` setup, proceed directly to path verification.

**Check setup question answer first**: Read the Setup Questions section in `research/00-overview.md`. If the user already answered the standards question with a specific path, verify it exists and use it as the primary source (still check for subdirectory-level overrides). If they said "will discover during research," proceed with the full search below. If they said "none" or equivalent, do a quick check (CLAUDE.md at repo root only) to confirm, then accept their answer — don't ask again.

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

**Note on native file reading**: Reading standards documents at known paths (CLAUDE.md, README.md) is a direct file lookup, not a substitute for `gather_task_context`. The prohibition in Step 3 against native file-reading applies to broad codebase exploration for research context, not targeted reads of specific files at known paths.

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

The local CLAUDE.md read in this step is the authoritative source for coding standards. If `gather_task_context` (Step 3) later returns conventions or standards information that supplements this, note the supplement but do not overwrite CLAUDE.md content with Driver-synthesized conventions. Update the standards artifact only to add genuinely new information — not to replace what was read directly from CLAUDE.md.

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

### CRITICAL: Use `gather_task_context` — Not Native Agents

`gather_task_context` is Driver MCP's primary tool. **It is your default tool for codebase context.** (Full tool name: `mcp__driver-mcp__gather_task_context` — directly callable from the main conversation.)

**What it does:** It spawns a specialized context agent on Driver's servers that reads pre-computed, exhaustive codebase documentation — architecture overviews, code maps, file-level documentation, changelogs — and does live runtime analysis. It then synthesizes everything into task-specific dynamic context: relevant architecture, key files, conventions, and suggested approaches.

**How to call it:** Provide a detailed task description and codebase names. The richer your description, the better the context you get back.

```
Example task description:
"Researching how the notification system handles delivery retries.
Need to understand: retry logic, failure modes, queue architecture,
and how delivery status is tracked. Codebase: my-backend"
```

**It takes 1-3 minutes. This is expected and normal.** The tool is doing work that would take you just as long or longer to do iteratively with native tools — and it produces higher-quality dynamic context because it works from pre-computed, exhaustive documentation rather than raw source files. Wait for the full response.

### CRITICAL: Do NOT Substitute Native Agents

**Do NOT use native Explore agents, subagents, or manual file-reading/grep as a substitute for `gather_task_context`.** These native tools work from raw source only. `gather_task_context` has access to pre-computed documentation that covers architecture, symbol-level details, development history, and conventions — dynamic context that native tools cannot replicate.

Native tools are useful for **targeted follow-up** after `gather_task_context` returns (see Step 5), but they are not a replacement for it.

### When to Call `gather_task_context`

Use your judgment. Not every user answer needs to trigger a call. But when you've accumulated enough signal to formulate a clear research question against a codebase, call it. Specifically:

- **After clarifying the research question** — your first call, with a broad task description
- **When a new research angle emerges** — a follow-up call with a more focused description
- **When exploring a different codebase** — each codebase may need its own call

### Running Multiple Calls in Parallel

When you have multiple distinct research angles to explore, you can run `gather_task_context` calls concurrently by spawning native subagents. Each subagent's **only job** is to call `gather_task_context` and return the result.

**This is the one correct use of native subagents in this skill.** The subagent is a concurrency wrapper — it does NOT do its own codebase exploration.

| Pattern | What the subagent does | Correct? |
|---------|----------------------|----------|
| **Substitution** | Its own file reading, grep, exploration — bypassing Driver | No |
| **Parallelism wrapper** | Calls `gather_task_context` with a specific task description, returns the result | Yes |

**Example:** You've identified three research angles — authentication flow, session storage, and token rotation. Spawn three subagents, each calling `gather_task_context` with a different focused task description. Collect all results and synthesize.

---

## Step 4: Validate Remote Context Against Local State

This step runs immediately after `gather_task_context` returns. It's a lightweight local validation — not a full codebase scan.

For each codebase in the Codebases table, run these commands in the directory specified by its Local Path column:

- **Branch check**: run `git branch --show-current` in the target codebase's Local Path directory. Report the current branch so the user can confirm they're on the right one. If the Codebases table has a Branch column entry, compare against it. If different, note: "Local branch is `<branch>`, Codebases table specifies `<expected>`. You may need to switch branches before implementation." This is a user-awareness check, not a validation failure.
- **Key file existence**: for files that `gather_task_context` referenced as architecturally important, verify they exist locally at the stated paths using `ls` or `Glob`. Flag any that are missing locally — they may have been renamed or deleted.
- **Uncommitted changes**: run `git status --short` in the target codebase's Local Path directory. If there are uncommitted changes to files that `gather_task_context` referenced in its response, note them: "Local file `<path>` has uncommitted changes — Driver's documentation may not reflect the current state of this file."
- **Not a git repo**: if the Local Path is not a git repository (`git rev-parse --git-dir` fails), skip branch check and uncommitted changes. Note: "Codebase at `<path>` is not a git repo — skipping git-based validation."
- **If divergence found**: report it inline in the research doc, note which findings from `gather_task_context` may be affected. Use local state as ground truth when the two conflict.
- **If no divergence**: note "Local state validated against Driver context — no divergence found" and continue.

This step should be quick — a few git commands and targeted file checks. Do not re-read the entire codebase; that's what `gather_task_context` already did.

---

## Step 5: Deep-Dive with Primitive Tools

After `gather_task_context` returns broad context, you may need to drill into specific areas. Use Driver's primitive MCP tools for targeted follow-up:

- **`get_code_map`** — navigate the codebase directory structure. Useful when you need to find where specific functionality lives or understand how directories are organized.
- **`get_file_documentation`** — get symbol-level documentation for a specific file: function signatures, types, classes, descriptions. Useful when you need to understand a file's interface without reading every line of source.
- **`get_source_file`** — read the actual source code of a file with line numbers. Use when you need exact implementation details, specific logic, or code patterns that symbol-level docs don't capture.

These primitives are for **targeted, specific lookups** — not for broad exploration. `gather_task_context` handles broad exploration.

---

## Step 6: Produce Research Artifacts

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

## Step 7: Finalize

When the user indicates research is complete:

1. **Re-read all deep-dive documents** — make sure nothing was missed
2. **Update 00-overview.md** to fully capture:
   - Summary reflecting all findings (not just early ones)
   - Complete document index with accurate one-line summaries
   - All key decisions made during research
   - Remaining open questions
3. **Confirm with the user** — "Research artifacts are finalized. The overview at `00-overview.md` indexes everything."

---

## Anti-Patterns

**Do NOT:**
- **Edit files in target codebases during research, even when the user asks.** Research produces artifacts in `research/` only. Target-codebase changes must be captured as plan tasks (or research amendments that name a future task) for the implementation phase. See "Handling Direct Edit Requests During Research" below.
- Use native Explore agents or subagents as a substitute for `gather_task_context`
- Abandon `gather_task_context` if it takes 1-3 minutes — this is expected behavior
- Fall back to `get_architecture_overview` or other tools because `gather_task_context` "seems slow"
- Use generic language like "gather context from the codebase" — always name the specific Driver MCP tool
- Skip the conversational Q&A phase — understanding intent before researching prevents wasted work
- Split documents based on length rather than concept boundaries
- Leave the overview out of date when research is finalized
- Assume you know where the codebase is or what standards apply — if uncertain, ask the user
- Skip standards resolution when the user has identified codebases — always search for CLAUDE.md
- Trust Driver context without local validation — Driver shows committed state, not local uncommitted changes

### Handling Direct Edit Requests During Research

Users often react to a research finding by giving an imperative instruction — "fix this in globals.css", "remove that code path", "update the Button variant." The instruction is clear and the change may seem trivial. **Do not execute it.**

Research's output is the task spec, not the code change. Reactive edits during research bypass planning, dry-run validation, and task materialization — reintroducing the failure modes the SDLC is designed to prevent. This is also true when the user invokes Auto mode: Auto mode does not authorize phase-skipping.

**Correct response** when the user asks for a target-codebase edit during research:
1. Pause. Do not execute the edit.
2. Respond: "I can capture this as an amendment to the research (as a named task for Phase N), or hold it for planning. Which do you want?"
3. If they confirm the amendment, update the research docs to specify the change, its blast radius, and which phase should implement it. Do not touch target code.
4. If they want the edit executed anyway as an out-of-band implementation step, ask them to explicitly confirm phase-skipping. Only then proceed, and log the deviation in the feature log.

**Exception — research artifacts and plugin/project config files are editable during research.** You may edit:
- Files inside `features/<name>/` (research docs, FEATURE_LOG.md)
- The SDLC projects directory's own CLAUDE.md (policy updates)
- The drvr-sdlc-plugin's own files (skill prompts, hooks, templates)

These are not "target codebases" — they are the SDLC authoring substrate. The restriction applies to the codebases under research, named in `research/00-overview.md`'s Codebases table.

**DO:**
- Call `gather_task_context` with detailed, specific task descriptions
- Wait for the full response — it is doing compressed expert-level codebase analysis
- Use primitive tools (`get_code_map`, `get_file_documentation`, `get_source_file`) for targeted follow-up
- Spawn parallel subagents as concurrency wrappers for multiple `gather_task_context` calls
- Ask lots of probing questions before and during research
- Keep the overview current as an index of all research
- Search for CLAUDE.md relative to each codebase path before gathering context
- When no standards are found, ask the user rather than proceeding silently
- After gather_task_context returns, validate key files and branch locally before building on the findings

---

## Before Responding Checklist

Before sending any response during research, verify:

- [ ] **Questions asked?** — Am I being curious enough? What else should I ask?
- [ ] **Questions in context?** — Are questions placed near the content they relate to?
- [ ] **Why-What-How order?** — Am I progressing through layers appropriately?
- [ ] **Driver context?** — Have I called `gather_task_context` where relevant?
- [ ] **Overview current?** — Does `00-overview.md` reflect the latest findings and decisions?
- [ ] **Feature log?** — Did I update `FEATURE_LOG.md` when creating new research docs?
- [ ] **Standards resolved?** — Have I searched for CLAUDE.md at each codebase path? If not found, did I ask the user?
- [ ] **Local state validated?** — After gather_task_context, did I check branch, key file existence, and uncommitted changes locally?