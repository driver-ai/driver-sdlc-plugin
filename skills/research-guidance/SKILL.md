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
2. **Gather codebase context via Driver MCP** — use `gather_task_context` as your primary tool
3. **Deep-dive into specific areas** — use Driver's primitive tools for targeted follow-up
4. **Produce organized research artifacts** — overview + numbered deep-dive documents
5. **Finalize** — when the user says done, ensure the overview captures everything

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

## Step 2: Gather Codebase Context

### CRITICAL: Use `gather_task_context` — Not Native Agents

`gather_task_context` is Driver MCP's primary tool. **It is your default tool for codebase context.**

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

Native tools are useful for **targeted follow-up** after `gather_task_context` returns (see Step 3), but they are not a replacement for it.

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

## Step 3: Deep-Dive with Primitive Tools

After `gather_task_context` returns broad context, you may need to drill into specific areas. Use Driver's primitive MCP tools for targeted follow-up:

- **`get_code_map`** — navigate the codebase directory structure. Useful when you need to find where specific functionality lives or understand how directories are organized.
- **`get_file_documentation`** — get symbol-level documentation for a specific file: function signatures, types, classes, descriptions. Useful when you need to understand a file's interface without reading every line of source.
- **`get_source_file`** — read the actual source code of a file with line numbers. Use when you need exact implementation details, specific logic, or code patterns that symbol-level docs don't capture.

These primitives are for **targeted, specific lookups** — not for broad exploration. `gather_task_context` handles broad exploration.

---

## Step 4: Produce Research Artifacts

### Output Structure

```
research-output/
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

## Step 5: Finalize

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
- Use native Explore agents or subagents as a substitute for `gather_task_context`
- Abandon `gather_task_context` if it takes 1-3 minutes — this is expected behavior
- Fall back to `get_architecture_overview` or other tools because `gather_task_context` "seems slow"
- Use generic language like "gather context from the codebase" — always name the specific Driver MCP tool
- Skip the conversational Q&A phase — understanding intent before researching prevents wasted work
- Split documents based on length rather than concept boundaries
- Leave the overview out of date when research is finalized

**DO:**
- Call `gather_task_context` with detailed, specific task descriptions
- Wait for the full response — it is doing compressed expert-level codebase analysis
- Use primitive tools (`get_code_map`, `get_file_documentation`, `get_source_file`) for targeted follow-up
- Spawn parallel subagents as concurrency wrappers for multiple `gather_task_context` calls
- Ask lots of probing questions before and during research
- Keep the overview current as an index of all research