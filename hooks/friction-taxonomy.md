# Friction Taxonomy

Reference document for friction types detected by hooks and analyzed by `/retro`.

| Type | Description | Cost | Tier |
|------|-------------|------|------|
| wrong_tool | Used wrong tool for the task | 2 | MEDIUM |
| wrong_approach | Chose custom solution over existing pattern | 5 | HIGH |
| skipped_skill | Should have loaded a skill but didn't | 3 | MEDIUM |
| false_completion | Claimed task done before verification | 4 | HIGH |
| wrong_path | Edited/created file at wrong location | 2 | MEDIUM |
| silent_failure | Error occurred but wasn't surfaced | 3 | MEDIUM |
| phase_violation | Performed action belonging to different phase | 4 | HIGH |
| infrastructure | Build/test/tool failure not related to code | 1 | LOW |
| scope_creep | Work outside the plan scope | 3 | HIGH |
| context_pollution | Loaded irrelevant context, wasted context window | 2 | LOW |

## Cost Tiers

- **HIGH** (cost 3-5): wrong_approach, false_completion, phase_violation, scope_creep — wastes full implementation rounds
- **MEDIUM** (cost 2-3): wrong_tool, skipped_skill, wrong_path, silent_failure — wastes partial work
- **LOW** (cost 1-2): infrastructure, context_pollution — minor delays
