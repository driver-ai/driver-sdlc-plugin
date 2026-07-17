---
name: drvr
description: |
  Run drvr SDLC workflows in Codex. Use when the user asks for drvr setup, feature creation,
  orchestration, context, plan dry-runs, assessment, review, handoff docs, pull requests, or a
  retrospective. Also activates for Claude-style aliases such as "/drvr:setup", "/drvr:feature",
  "/drvr:orchestrate", "/drvr:context", "/drvr:dry-run-plan", "/drvr:assess", "/drvr:review",
  "/drvr:docs-artifacts", "/drvr:open-pr", and "/drvr:retro" when they are typed in Codex.
---

# drvr for Codex

Route the requested drvr workflow to its canonical command document. This skill is the Codex
compatibility layer for the command-oriented surface of the plugin; the phase-specific skills in
neighboring directories remain directly available.

## Route the request

Choose exactly one workflow unless the user explicitly asks for a sequence. Treat text following a
Claude-style command alias as that workflow's arguments.

| User intent or alias | Canonical workflow |
|---|---|
| set up a projects directory, `/drvr:setup` | `../../commands/setup.md` |
| start or scaffold a feature, `/drvr:feature` | `../../commands/feature.md` |
| gather focused Driver context, `/drvr:context` | `../../commands/context.md` |
| resume or report feature status, `/drvr:orchestrate` | `../../commands/orchestrate.md` |
| validate or dry-run a plan, `/drvr:dry-run-plan` | `../../commands/dry-run-plan.md` |
| curate tests, `/drvr:assess` | `../../commands/assess.md` |
| run standards review, `/drvr:review` | `../../commands/review.md` |
| generate handoff docs, `/drvr:docs-artifacts` | `../../commands/docs-artifacts.md` |
| open a pull request, `/drvr:open-pr` | `../../commands/open-pr.md` |
| run a retrospective, `/drvr:retro` | `../../commands/retro.md` |

After selecting a workflow:

1. Read the canonical workflow document completely.
2. Follow its body as instructions. Its Claude frontmatter documents capabilities; it does not
   restrict Codex tools.
3. Resolve all relative links from the canonical workflow document's directory.
4. Load any linked phase skill or agent instruction completely before using it.

## Codex translations

Apply these translations without changing the workflow's intent:

- `Read`, `Write`, `Edit`, `Glob`, `Grep`, and `Bash` mean the equivalent Codex filesystem and
  shell capabilities.
- `Agent` means Codex sub-agent delegation. When the canonical workflow explicitly calls for an
  agent, read the matching file under `../../agents/`, give the sub-agent those instructions and
  the concrete task context, and preserve the workflow's convergence step.
- `AskUserQuestion` means ask the user a concise question only when their answer is required.
- `$ARGUMENTS` means the text supplied after the alias or the arguments stated in natural language.
- "Activate `drvr:<skill>`" means use the matching installed skill under `../<skill>/SKILL.md`.
- A reference to another `/drvr:<command>` means route it through this skill on the next user
  request; do not pretend Codex has registered Claude slash commands.
- Prefer `AGENTS.md` as Codex's native repository-instruction file. Also honor `CLAUDE.md` when it
  exists so shared projects work in both clients. More deeply nested instruction files take
  precedence within their subtree.

## Setup behavior in Codex

When following `setup.md` in Codex:

- Treat either `.codex-plugin/plugin.json` or `.claude-plugin/plugin.json` as evidence that the user
  is currently inside the plugin repository.
- Create or audit `AGENTS.md` using `../../templates/AGENTS.md.template`. If the projects repository
  also supports Claude Code, preserve or create `CLAUDE.md` as requested by the user; never
  overwrite one platform's customized instructions with the other platform's template.
- Report both instruction files independently when either exists.
- Tell Codex users to invoke workflows with `@drvr` or natural language, for example
  "Use drvr to start feature billing-export." Claude slash-command examples in generated artifacts
  may remain as cross-client aliases, but they are not native Codex commands.

## Platform-specific workflows

`driverize` and `un-driverize` install and remove Claude Code settings, shadow agents, and hooks.
Only follow `../../commands/driverize.md` or `../../commands/un-driverize.md` when the user explicitly
asks to manage those Claude Code artifacts. Do not apply them as Codex configuration.

The plugin's existing `hooks/hooks.json` also uses Claude Code's hook schema and environment
variables. It is intentionally not registered by the Codex manifest. Do not claim that artifact
auto-commit, friction tracking, or laziness-detection hooks run automatically in Codex.
