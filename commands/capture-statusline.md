---
description: Install (or remove) the capture-awareness statusline badge in ~/.claude/settings.json
argument-hint: "[remove]"
allowed-tools: Bash, Read, Write, Edit, AskUserQuestion
---

# /drvr:capture-statusline

Install (or remove) the capture-awareness statusline badge — a "capturing" indicator
rendered by a plugin-shipped, local-only script. The `statusLine` slot in
`~/.claude/settings.json` is user-owned configuration: this command never force-installs.
It backs up first, composes with any existing statusline instead of replacing it, and shows
you the exact change for approval before anything is written.

Install flow (no argument):
1. Read ~/.claude/settings.json (missing → treat as {}). If it exists but does not parse as
   JSON: STOP and report — never overwrite a file you cannot parse.
2. If `_drvr_capture_statusline` provenance key present → already installed: REFRESH the
   installed copies (re-copy capture-statusline.sh and capture_config_core.py from the current
   plugin; if ~/.claude/drvr/statusline-wrapper.sh exists, re-instantiate it from the current
   template using the provenance previous_command), leave settings.json untouched, report
   "refreshed" and stop. This is the documented post-plugin-update path.
3. mkdir -p ~/.claude/drvr; copy from "${CLAUDE_PLUGIN_ROOT}/scripts/capture/":
   capture-statusline.sh and capture_config_core.py.
4. Back up settings.json to settings.json.pre-drvr-statusline ONLY if that backup does not
   already exist.
5. Compose: if settings has an existing statusLine.command, first VALIDATE it: must be
   single-line shell text with no unquoted `#` (a newline or comment char breaks template
   instantiation — verified by execution) — otherwise STOP and report; no settings change, and
   clean up per the decline branch below. Then instantiate ~/.claude/drvr/statusline-wrapper.sh
   from "${CLAUDE_PLUGIN_ROOT}/scripts/capture/statusline-wrapper-template.sh" by replacing the
   {{ORIGINAL_COMMAND}} placeholder (exactly one occurrence, on the ORIG= line) with the
   original command string (the tested template pipes the stdin payload to the original, runs
   the badge with stdin closed, and appends the badge to the FINAL line of the original's
   output); new statusLine = the EXISTING statusLine object with only .command replaced by
   sh <abs>/drvr/statusline-wrapper.sh — sibling keys (padding, refreshInterval, …) preserved.
   If no existing statusLine: statusLine = {"type": "command",
   "command": "sh <abs>/drvr/capture-statusline.sh"}.
6. AskUserQuestion showing the exact settings.json change BEFORE writing. On approval, write
   settings.json (2-space indent) adding statusLine and
   "_drvr_capture_statusline": {"version": "1", "installed_at": <ISO8601>,
   "previous_command": <original command or null>}. On decline (or a step-5 validation stop):
   delete the files copied in step 3 and any instantiated wrapper, delete the step-4 backup
   ONLY if this run created it, report "nothing changed".

Remove flow ("remove"):
provenance present → restore statusLine.command to previous_command preserving sibling keys
(or delete the whole statusLine key when previous_command is null — we created it),
delete the provenance key, delete the named files capture-statusline.sh,
capture_config_core.py, statusline-wrapper.sh from ~/.claude/drvr/ (rmdir ~/.claude/drvr only
if empty — other drvr artifacts may live there later), report. Backup file is left in place as
a safety net. No provenance → nothing installed; report.

## Notes

- **Installed-copy drift.** The copies under `~/.claude/drvr/` do not update when the plugin
  updates — they drift until refreshed. After a plugin update, re-run
  `/drvr:capture-statusline` to refresh the installed copies (the provenance `version` field
  supports detecting a stale install).
- The badge reads `~/.driver/config.json` locally on each render and prints nothing when
  rolling capture is off — no network access, and a badge failure never breaks the statusline.
