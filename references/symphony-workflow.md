# Symphony preparation and shared operating rules

Read this file and [Linear organization](linear-organization.md) on entry to any drvr phase. They define delivery routing, authority, durable records, and recovery once; phase skills supply the method. drvr is operator guidance. It does not run a polling loop, dispatch workers, or enforce a harness.

## Select delivery before execution

Record `Delivery: Symphony` or `Delivery: Local` in the current durable record from the user's stated outcome and established context. Symphony means preparing work for a Symphony worker; Local means implementation managed in the current task. A repository's name, installed connector, or issue's team is not a delivery selector. Building Symphony itself can be Local work.

If delivery is unresolved, record that uncertainty and continue useful intent and research. Ask only when the answer changes the next action, and resolve it before task materialization, implementation, or handoff. An explicit change of delivery is a recorded decision; it does not require moving or duplicating the artifacts.

- **Symphony:** use the Symphony branch at the beginning of each skill or command, then return. Do not fall through into Local setup, `.driver` configuration, Driver MCP discovery/retrieval, task-document scaffolding, or local execution gates. Use direct repository, git, GitHub, web, and Linear access. Do not invoke Driver indirectly through `driver-task-context`, `cascade-check`, `handoff-analyzer`, or other legacy agents. For an affected-artifact check, inspect the relevant source, recorded commits, plans, and Linear relations directly.
- **Local:** retain the existing phase methods and actual operation prerequisites. Load the full callee before using it. A check required to perform an operation still belongs in that callee; an unrelated Local prerequisite does not gate Symphony preparation. Explicit user instructions take precedence over plugin defaults, including the choice of self-contained execution specifications.

The Symphony terminal preparation step is the full [Linear issue skill](../skills/linear-issue/SKILL.md). Preparing issues does not authorize running their implementation locally or assigning/delegating them to a worker.

## Symphony executable review plans

For Symphony handoffs, planning selects exactly one `general` reviewer and adds specialists
only for concrete risks in the proposed change. Every selected role needs a nonempty reason.
Supported specialists are `correctness`, `security`, `conventions`, `design` and `tests`.
The issue's role/reason list is the execution input; surrounding prose cannot change it.
Use the [issue template](../skills/linear-issue/SKILL.md#issue-template) to carry that selection.
This contract does not replace the Local review workflow.

The consumer owns the schema and its validation. The contract landed in
[`driver-ai/symphony` at `42d55dd`](https://github.com/driver-ai/symphony/blob/42d55dd0899d8ee5c4992b8b9c7a3dbd7a6d8265/README.md#independent-review):
exactly one H2 `Review plan` section outside Markdown fences, containing one `json` fence.
The object has only `schema_version: 1`, a positive integer `revision`, and a nonempty
`reviewers` array of unique `role`/`reason` objects, including exactly one `general`.
Duplicate keys, unknown fields, unsupported roles and malformed or ambiguous blocks fail
validation. Keep illustrative complete plans inside longer outer fences so they cannot
be mistaken for an issue's authoritative section.

Resolve the consumer revision from the established deployment record and record the source
revision used for validation. A verified consumer source checkout can validate a draft
before deployment; source availability is not proof of the installed runtime, workflow,
method or configuration. Verify compatibility with the effective installed policy before
arming. If the validator or that deployment evidence is unavailable, record the remaining
preparation gate; do not substitute a plugin parser or infer a default plan.

From that Symphony checkout, validate the complete description saved as `ISSUE.md`:

```sh
python3 deploy/host/review-run.py --validate-plan ISSUE.md
```

This read-only command needs no credentials, makes no network/provider calls and creates
no run state. Success returns normalized `plan` data and `plan_hash`; failure exits nonzero.
Record the returned revision/hash and command/source revision in the canonical preparation
record. Do not hand-compute the hash. Validate the draft before saving, then validate the
complete description read back from Linear and compare the normalized plan and hash.
Correct any unexplained difference and repeat read-back before declaring the handoff ready.

Start a new plan at revision 1; preserve an existing plan's revision when its selection is
unchanged. A change to roles or reasons uses a higher revision, records the reason in the
existing decision log, and follows existing planning authority. The worker may
request a revision but cannot silently add, omit or substitute reviewers. A changed source
head can require a new run of the same selection without a new scope approval; it does
not change allowance, round limits or other installed policy. The review-plan JSON never supplies
models, effort, permissions, spending limits or commands to launch reviewers.

The runner executes the selected reviewers and owns run identity, receipts and accounting.
The runtime owns guarded handoff. Complete CI and substantive notes before final review;
during the evidence freeze, publish the exact generated evidence before guarded handoff.
Workers stop at In Review. Human GitHub merge, Linear completion, and deployment retain
their separate authority. Preparation neither launches reviews nor delegates the issue.

## Carry authority forward

Read the user's current request and recorded decisions before asking for approval. Authorization persists across phase changes and resumed sessions. Within the authorized outcome, continue routine research, organization, factual repairs, related validation, bookkeeping, and phase transitions. Report material findings and actual changes; do not ask again whether to fix a known factual error or repeat its affected check.

Ask when an unresolved choice changes the outcome, scope, material tradeoff, ownership, or external commitment. Worker arming/dispatch, deployment, and merge require their own applicable authority; preparation alone grants none. Continue independent authorized work while a necessary answer is pending. Treat suggestions and inferred preferences as proposals, not approvals.

Challenge intent in proportion to the stakes: is this the right problem, what would disprove the proposed need, what existing capability could solve it, and what is the smallest useful result? Surface evidence and tradeoffs without inventing objections or requiring an adversarial ceremony for every edit.

## Use one durable home

First locate the effort's existing intent, plan, decisions, and activity record. Reuse their canonical home and link it from Linear. Existing feature files remain canonical; do not copy their mutable contents into a new operator document. A self-contained execution issue is a deliberate handoff, not a second working plan to maintain in parallel.

For work starting in Linear without durable working artifacts, search for an existing operator document associated with the effort. Reuse it, or create one when substantial research or cross-issue history needs a home. Resolve its attachment from the established effort and available document capabilities; do not create a project merely to host a document. A small single-issue effort can keep these sections in its existing issue until the worker handoff requires the issue template. Use:

```markdown
## Current State
Delivery: <Symphony | Local | unresolved>
Outcome, current phase, canonical references, established authority,
next action, and pending decisions or writes.

## Working Notes
Intent, research, and plan as needed; source/revision evidence and uncertainties.

## Decisions
Dated choices, rationale, scope, and who authorized material choices.

## Activity Log
Append dated meaningful actions, attempts, outcomes, and next checkpoints.
```

Keep `Current State` and working notes current. Append to Decisions and Activity Log; corrections are new entries referencing the earlier observation. With local feature artifacts, use `FEATURE_LOG.md`, `DECISIONS.md`, and the existing phase/implementation logs for their established roles. Do not record every tool call. Record meaningful findings, transitions, deferrals, repairs, writes, verification outcomes, and resumption points.

Linear's native team, project, parent, state, assignee, delegate, labels, and dependency fields are authoritative for current organization. Logs are dated observations. Do not restore an old field value just because history names it.

If the canonical home cannot be written, save a named local draft with its intended destination and `pending sync` status. Report its path. It is a recovery draft, not a competing canonical home; reconcile and mark it synchronized once the destination becomes available.

## Checkpoint meaningful work

Before a multi-step external change, record the intended changes and known entity IDs in the durable home. After each meaningful result, record returned IDs/URLs, verified outcome or uncertainty, and the next unfinished step. If a request's outcome is unknown, record `pending verification` rather than success or failure.

For local artifacts, save at useful work boundaries, then review ownership and commit the work that belongs to this task:

```bash
git status --short
git diff -- <owned-paths>
git diff --cached -- <owned-paths>
git add -- <owned-paths>
git commit --only -m "<meaningful checkpoint>" -- <owned-paths>
```

`<owned-paths>` means the reviewed exact files, not a whole feature/repository by default. `--only` excludes unrelated staged paths but includes all working changes in the named files: when a file mixes user and agent changes, isolate the task's hunks or use a separate checkout before committing. Never stage or commit unknown dirty artifacts merely because they are Markdown or found on resumption. Preserve unrelated staged work. Record the resulting commit; if a save or commit fails, distinguish saved, committed, and pending work accurately.

The bundled hooks are disabled. No session-end hook will save, commit, or reconstruct these records.

## Resume and repair

Read Current State and recent appended activity, then verify relevant live Linear entities, source revisions, branch/diff state, and recorded commits. A summary is a navigation aid, not proof of current state. Reconcile contradictions as dated corrections. Retain verified upstream commit checks when assessing downstream effects; if a commit cannot be resolved, report the evidence limit and inspect what is available instead of claiming the check passed.

Before retrying an uncertain Linear create/update, fetch by returned ID or search within the known team/project using the recorded title and intent. Resume missing steps on the existing entity. Do not blindly create a duplicate after a timeout. If several candidates remain plausible, leave the write pending and request the missing decision while continuing unrelated work.

Repair clear factual, path, reference, and consistency errors in authorized artifacts, update the affected downstream assumptions, and repeat only the checks those changes affect. Repeated unchanged failures are evidence of a blocker or a wrong assumption; do not loop indefinitely or keep requesting approval for the same repair.

## Evidence and pragmatic engineering

Record source location, branch/revision, date, and relevant local changes for claims that drive a plan. Distinguish observed facts, inferences, assumptions, and unknown deployed state. A checked-in `WORKFLOW.md` proves source configuration; it does not prove which revision is deployed.

Apply KISS, DRY, and YAGNI: reuse established capabilities, keep one owner for each mutable fact, prefer the smallest coherent change, and defer unrelated improvements with a retrieval path. Functional-core/imperative-shell reasoning is useful when logic and I/O exist. Do not invent a pure core, abstraction layer, test framework, or fixture program for a prose/configuration change. Choose verification that can expose a meaningful failure; for this plugin, package/skill/reference checks and feedback from normal use are the initial strategy.
