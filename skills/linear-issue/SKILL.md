---
name: linear-issue
description: |
  Write or rewrite one Linear issue so that a Symphony worker can complete it unattended in one pull request and a human can review the result. Use once a plan exists: "write the Linear issue", "turn this plan into an issue", "create the issue for this plan", "rewrite SYM-NN", "is SYM-NN ready to arm". Used by the operator, never by the worker. Harness-neutral: any agent that can read this file and reach Linear can follow it.
---

# Linear issue

## What this is for

Symphony is a runtime that polls one Linear project for issues delegated to Driver Symphony (assigned to it in Linear's picker, which keeps a person as the assignee) that sit in an active state, clones the target repository into a fresh workspace, and hands each issue to a coding agent, the worker. The worker has no conversation history and no access to anything outside the repository and the issue. Its prompt is the body of the `WORKFLOW.md` selected for that Symphony deployment with the issue's title and description pasted in. It plans, implements, validates, opens one pull request, and reports on the issue. A human reviews the PR and moves the issue on. Another human, the operator, prepares the issue, does what the worker cannot (repository settings, secrets, deployments), and arms it: assigns it to Driver Symphony and moves it to Todo. Symphony dispatches nothing else.

An issue here is therefore not a note to a teammate. It is the complete specification of one PR's worth of work for an agent that cannot ask questions, plus what the reviewer needs to judge the result. Everything the worker needs is in the issue or in the repository. Everything `WORKFLOW.md` already tells the worker stays out of the issue.

## When to use it

- A plan exists, in the conversation, in a file, or as an existing issue that needs rewriting, and the work fits one pull request.
- Not for arming, not for reviewing, not for changing `WORKFLOW.md`. Those are separate acts.

## Inputs

1. The plan: whatever document or conversation decided what to build and how. Research notes behind it are transient; only verified facts survive into the issue, and anything of lasting value is landed in the repository by a task of the issue.
2. The Linear target: resolve the team, project, milestone if applicable, and dependencies from the established effort and current Linear records. Do not infer the destination from the plugin repository.
3. The relevant Symphony `WORKFLOW.md`, resolved from the established deployment or repository reference. It is an external input, not a file bundled with drvr. Its clone configuration names the target repository; its prompt names the PR base branch and the rules the worker already receives. Record the source and revision, and distinguish source configuration from a verified deployed version.
4. Access to Linear: a Linear MCP server, or the GraphQL API at `https://api.linear.app/graphql` with an API key. Access to the target repository for direct verification: `gh`, `git`, or a clone. This preparation skill does not require or invoke Driver MCP.

## Procedure

### 1. Read the harness

Read the resolved `WORKFLOW.md` end to end. If it is unavailable or its relationship to the effective deployment is unknown, identify that limit before claiming the issue is ready. It has a YAML front matter (tracker, workspace, hooks, agent, and coding-agent settings) and a prompt body. Write down what the body already tells the worker: where the repository is cloned, branch naming, PR base, how to reach Linear, the sections of its workpad (the single Linear comment it keeps current while it works), when to move an issue to Blocked, how to validate, and host limits and available services/tools. None of that goes into the issue. The workpad sections matter for one reason: the issue must give each of them something to hold.

### 2. Verify every fact

For each path, command, setting, branch, version, or external state the plan names, check it against the target repository at its base branch (`gh api`, `git ls-tree`, a clone) or against the live system. Record each fact under `## Research` with the date and how it was verified. Anything you could not verify is written as an assumption in its own sentence. A worker that meets a wrong fact either guesses or stops; in Symphony's first live run a vague ticket cost four attempts before it produced a PR.

### 3. Compose

Fill the template below.

- Title: an imperative verb and one outcome, at most 70 characters, no issue identifiers.
- One issue is one pull request. Work that needs several reviewable PRs becomes several issues chained with blocking relations; Symphony does not dispatch a Todo issue while any issue that blocks it is still open, so the chain runs in order by itself.
- Split tasks by actor. Operator tasks before arming and after merge are explicit so the worker never attempts them; operator work that must happen between two worker PRs is its own issue in the state Manual Work that blocks the next worker issue, because the worker never enters Manual Work. Operator tasks are checklists (`- [ ]` items) of single actions in order, sub-lettered when one step has several actions, with the expected result on the item and contingencies as their own "Only if ..." items: the operator ticks them in Linear while working. Each worker task has Goal, Tests, Constraints, and Files, in that order; each Files entry names the exact change. Files comes last because Linear folds any line that follows a bullet list into that list, and a Files entry is often a list.
- Acceptance criteria are checkboxes a reviewer can verify from the PR and the workpad without asking anyone.
- Validation lists the exact commands and expected results, and names what the host cannot run so the worker records it instead of failing. The worker treats this section as mandatory. Prefer checks that leave the working tree clean: `python3 -m py_compile` writes a `__pycache__` directory the worker then has to delete before committing; `python3 -c 'import ast, sys; ast.parse(open(sys.argv[1]).read())' <file>` checks the syntax and writes nothing.
- Anything the worker must copy verbatim into a file, down to a single line or a comment, goes in a fenced code block, never in quoted prose. Linear rewrites prose when the issue is saved: a bare URL becomes link syntax, an issue identifier becomes a mention, nested backticks and some quotation marks change; the worker copies what it sees. Fenced blocks arrive byte for byte, except that Linear drops blank lines at the end of a fence, so say "followed by one blank line" in words.
- Dependencies are Linear relations, never prose in the issue.
- Never write Linear's closing words (fixes, closes, resolves followed by an issue identifier) anywhere in the issue. The worker copies issue text into commits and PR bodies, and Linear would close issues on merge.
- A change to code, rather than to a document or a prompt, also gets the optional sections described under the template.

### 4. Self-review

Apply the gates below. Fix every BLOCK before writing anything to Linear.

### 5. Write to Linear

Create or update the issue with the description, project, and milestone: `issueCreate` or `issueUpdate`, or the equivalent tool of the Linear MCP server in use. A new issue starts in state Backlog with no label; a rewrite keeps its state and labels. Add relations with `issueRelationCreate` of type `blocks`. If the milestone description lists an order, insert the issue there.

### 6. Report

Return the issue URL, the operator tasks that must be done before arming, and the arming step. Do not arm.

After the run, read the worker's Confusions in the workpad. A confusion is an ambiguity the worker had to resolve on its own; when the same kind appears twice, the issue template or this file changes.

## Issue template

````markdown
## Context
Why this issue exists: the observed problem, dated, with links to the evidence (workpads, PRs, runs).

## Research (YYYY-MM-DD)
* Verified facts, each with how it was verified. Observed and assumed are separate sentences.

## Decision
The approach chosen. Each rejected alternative in one line with the reason.

## Scope
In scope: ...
Out of scope: ...

## Tasks

Operator, before arming (never the worker):

- [ ] 1. ...

Symphony worker, one PR:

### Task 1: <name>
**Goal**: <what done looks like for this task>
**Tests**: <tests to write or run; "none" for a document or prompt change>
**Constraints**: <specific and sourced; "change nothing else"; what the worker must not touch>
**Files**: `path` (create | modify: the exact change; text the worker copies verbatim goes in a fenced block, like this)

```text
<the exact line or block the worker inserts>
```

Operator, after merge (tick each as done; keep the order):

- [ ] 1a. <one action, with the expected result>
- [ ] 1b. Only if <condition>: <the contingency>

## Acceptance criteria
- [ ] Observable by the reviewer from the PR or the workpad.

## Validation
Exact commands and expected results. What is not runnable on the host, and how to record it.

## Constraints
Cross-cutting rules with their source (a file, a decision, a runtime fact).

Standards: `<path the worker reads>`
Type: <who does what, one line>
````

The `Standards:` line names the file with the coding rules for the target repository, such as `AGENTS.md` at the repository root or a `CLAUDE.md` in the changed directory. The current worker reads `AGENTS.md` on its own.

Optional sections for code changes, placed after `## Scope` in this order:

- `## Architecture fit`: the existing patterns to follow, with file paths, then `### Core and shell`. The core is the pure part of the change: functions that take values in and return values out, with no I/O, clock, randomness, or shared mutable state. The shell is the thin layer that performs I/O and calls the core. Name which new or changed functions are which, or state that the change is shell-only and why. This lets the worker test the core directly and the shell against real dependencies.
- `## Data structures & callables`: tables of Added, Modified, and Removed items with kind, name, target file, owning task, and notes.
- `## Test strategy`: unit tests on the core and integration tests on the shell, each named with its input and expected output. Name every test double and why it is justified: the real collaborator is external, expensive, non-deterministic, or absent from the test environment.

## From a plan document

Plans arrive in many shapes. Map their sections like this. The drvr planning plugin used at Driver produces plans with exactly these section names; other plans map by meaning.

| Plan section | Where it goes in the issue |
|---|---|
| Environment: codebase, local path, base branch, feature branch | Not copied. `WORKFLOW.md` owns them. |
| Environment: test command | `## Validation` |
| Environment: standards document | The `Standards:` line |
| Context or problem statement | `## Context`; verified findings go to `## Research` |
| Decisions | `## Decision` |
| Architecture fit, core and shell decomposition | `## Architecture fit` |
| Data structures and callables | `## Data structures & callables` |
| Acceptance criteria | `## Acceptance criteria` |
| Test strategy | `## Test strategy`; its commands go to `## Validation` |
| Scope | `## Scope` |
| Constraints | `## Constraints` |
| Task breakdown | Worker tasks, with Goal, Files, Tests, Constraints copied verbatim |
| Open questions, unresolved review findings | Resolve before writing. An open question in an issue is a BLOCK. |

## Gates

BLOCK, each with its remedy:

- An acceptance criterion a reviewer cannot verify from the PR or the workpad. Rewrite it as something observable.
- A path, command, or setting that was not verified against the base branch or the live system. Verify it, or mark it an assumption.
- Text that repeats a `WORKFLOW.md` rule (branch, PR base, workpad, state transitions, blocked behavior). Delete it. If the rule is wrong, change `WORKFLOW.md` through its own issue.
- A worker task that depends on an operator task not yet done. List the operator task under "before arming" and say so in the report.
- A link to a local file path or to an uncommitted document. Inline the fact, or land the document in the repository first.
- An open question or an unresolved alternative. Decide, or send the plan back.
- Closing words followed by an issue identifier anywhere in the text.
- More than one pull request's worth of work. Split into issues and chain them with blocking relations.

WARN:

- A code change without a `## Validation` section.
- A worker task without a Files entry.
- A research bullet without a date or a verification method.
- Quoted prose that the worker is told to copy into a file. Move it into a fenced code block.
- An operator step that is not a checklist item, or one item that bundles several actions.

## Worked example

SYM-34, https://linear.app/driver-ai/issue/SYM-34, the first issue written in this structure.

## Where this file lives

The canonical source is `skills/linear-issue/SKILL.md` in `driver-ai/driver-sdlc-plugin`, bundled with drvr as `drvr:linear-issue`. The Symphony repository retains a forwarding entry for its existing local skill paths. Read this full file when entering through that compatibility path; do not maintain another issue template there.

Migrated from `driver-ai/symphony`, revision `bed063d8d7be6677a18e5eb37083833ff90dc33a`, path `skills/linear-issue/SKILL.md`. The Symphony release ships the worker's `.codex/skills/linear` skill, not this operator preparation skill. Any agent with the required source and Linear access can read and use this file.
