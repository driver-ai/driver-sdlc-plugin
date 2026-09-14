# Organize work as it becomes clear

Use this during intent, research, planning, and resumption, not just when writing execution issues. Pair it with [the shared operating rules](symphony-workflow.md) for authority, canonical records, and uncertain writes.

## Start with the work

Capture the desired outcome, why it matters, current scope, and unresolved questions. The user need not first choose Initiative, Project, or Issue. Read the known Linear links and search relevant team/project records for existing work before creating anything. Inspect promising matches and existing relations; a matching word is not enough to merge work.

Choose the smallest useful organization:

| Shape of the work | Default home |
| --- | --- |
| One independently reviewable change | Issue; use the team's backlog if no project fits |
| A coordinated outcome requiring several issues/PRs | Existing relevant project, or a new project when that coordination has value |
| A strategic outcome coordinating several projects | Relevant initiative, only when that broader relationship is established |
| Ambiguous early exploration | Existing durable working record; defer the hierarchy decision until evidence warrants it |

Do not manufacture a project, initiative, milestone, parent issue, priority, owner, date, or label to fill a template. Resolve the correct team from established ownership. If ownership/destination is unclear, keep a named pending item and ask before assigning it arbitrarily. A plugin source repository does not determine a work item's team or worker target repository.

## Revisit organization at useful boundaries

Reconsider when intent changes, research uncovers independent work, a plan grows beyond one reviewable PR, or a dependency becomes clear. Explain the organization in plain language: what stays in scope, what moves, and where to resume each deferred item.

- Reuse and update the matching issue/project before adding another.
- Split independently reviewable changes; keep each Symphony worker issue to one PR and make it self-contained with the full Linear issue skill.
- Promote coordination when multiple issues need a shared outcome. Retain existing issue IDs/history and relate them to the project; do not replace them just to change hierarchy.
- Use native blocking relations for true prerequisites. Use related links for context. Parent/sub-issue organization does not imply execution order.
- Keep team/project ownership and operator-versus-worker responsibilities visible. Split manual work from worker execution when their actors or delivery differ.
- Make routine organization changes within existing authority; surface material scope, ownership, or strategic changes for a decision. Do not force an unrelated tangent into the active project.

## Defer without losing work

Capture a tangent before resuming the main task. Search for duplicates, then append to an existing backlog item or create one in the established destination when authorized. Keep it small; a backlog capture does not need a worker-ready implementation specification.

Include:

- **Problem and value:** what was noticed and why addressing it could matter.
- **Origin:** the source issue/project, research finding, conversation decision, or repository evidence that surfaced it.
- **Reason deferred:** why it is outside the present outcome or not worth doing now.
- **Destination:** a verified issue/project/team link, or an explicit unresolved destination in the durable record.
- **Revisit condition:** the evidence, dependency, user need, or event that would justify resuming it; do not invent a deadline.

Record the destination URL/ID in the source activity log. If unresolved, retain enough detail to retrieve and route it later. Never say an item is in the backlog when only a local pending draft exists. Preserve uncertain write outcomes and reconcile by ID/search before retrying.

## Keep execution unarmed

Organization and preparation do not arm workers. New prepared issues start in Backlog, with no labels or worker delegate unless separately authorized. Preserve current state, labels, assignee, and delegate on routine rewrites; do not alter them to make a preparation checklist look complete.

Before rewriting an issue that a worker may be executing, inspect its live state and workpad. Treat an active specification change as rework requiring coordination through the deployment's established rework path. Do not silently replace the worker's instructions or write an operator log into its Workpad.

Use native Linear relations and fields as the live source of truth. Working notes explain rationale and append history; they do not become a shadow tracker.
