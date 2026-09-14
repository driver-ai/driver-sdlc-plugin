# Operation prerequisites and user decisions

Read the [shared operating rules](../references/symphony-workflow.md) before applying a gate. A plugin supplies guidance; it does not outrank the user's explicit instructions or enforce a harness.

## Gate the actual operation

A prerequisite is a fact needed by the operation about to run. Check it in the callee whenever that callee has access; direct invocation must receive the same check as orchestration. State the missing fact and concrete remediation instead of silently pretending it is satisfied.

Examples in the default Local workflow: approved plan before materialization, current task documents before executing from task documents, completed assessment before the handoff command that consumes it. Preserve those checks on their actual Local paths. If the user supplies a different self-contained execution specification, record that decision and use the corresponding implementation path; do not call task documents present when they are absent.

Delivery routing precedes those gates. Symphony preparation uses the full Linear issue skill and its readiness gates. It does not invoke local task materialization or execution, so their artifact requirements do not apply. This is a different operation, not a silent fallback around the Local callee's checks.

## Keep decisions with the operator

Carry established authorization forward. Routine research, factual repairs, affected checks, organization, and bookkeeping within scope proceed without repeated permission. Ask about unresolved choices that change scope, material design, ownership, or external commitment. Preparation does not authorize arming a worker, deployment, or merge.

A warning reports evidence and its effect on the next action. Repeating an unchanged warning is not progress. Reconcile missing or stale evidence and record uncertainty; never report a gate passed just because checking it failed.

## Recovery is part of the operation

Use the shared checkpoint rules before and after multi-step writes. Preserve append-only history, distinguish saved from committed work, and resolve uncertain Linear results by ID/search before retrying. No bundled hook enforces these instructions or commits on the operator's behalf.
