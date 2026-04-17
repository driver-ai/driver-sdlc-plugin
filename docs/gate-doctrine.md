# Gate Doctrine: Process Invariants vs User Decisions

## Process Invariant

A fact about the SDLC process that must be true for the next phase to function correctly. When violated: hard gate (BLOCK with remediation text). Cannot be overridden by interpretation or user preference.

Examples: task docs exist before implementation starts, assessment ran before handoff docs, plan is approved before materialization.

## User Decision

A judgment the user makes about scope, approach, quality trade-offs, or whether to proceed despite a warning. When surfaced: soft advisory (inform, let user decide). The system presents information; the user controls the outcome.

Examples: whether to run a dry-run, whether a deviation is acceptable, whether to split a plan.

## Anti-Patterns

### Pattern A: Prose-Only Invariant Protection

A process invariant is documented as prose ("always do X", "after the user approves") but no mechanism refuses to proceed when violated. The invariant is advisory, not enforced.

Example: the materialization step said "after the user approves the plan" but nothing verified approval had occurred. A plan could be finalized without tasks ever being materialized.

### Pattern B: Explicit Fallback Bypasses Gate

A hard gate exists (e.g., BLOCK on missing task docs), but a nearby code path provides an explicit fallback that degrades gracefully instead of blocking. The fallback undermines the gate.

Example: implementation-guidance Step 1 had a "plan-extraction mode" fallback when task docs were missing, directly contradicting Phase 1.1's BLOCK for the same condition.

### Pattern C: Guard in One Caller, Not All

A validation check exists in one entry point but not others. Direct invocation of the callee bypasses the guard entirely.

Example: the "don't handoff before assessment" check lived only in sdlc-orchestration prose. Direct invocation of `/drvr:docs-artifacts` bypassed it.

## Rules

- **No silent fallbacks** for process invariants. If a process invariant is violated, the system must BLOCK with remediation text. Graceful degradation is for runtime errors, not missing process steps.
- **Guards live in the callee** when the callee has the required access. When the callee cannot check (e.g., no tool access), duplicate the guard across all callers.
- **Hard gates state remediation** — a BLOCK says what is wrong AND how to fix it. "Missing task docs" is insufficient; "Missing task docs. Return to planning-guidance to approve, then run materialize-tasks" is correct.
