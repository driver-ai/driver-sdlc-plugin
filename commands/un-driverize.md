---
description: Remove Driver enforcement stack — restore backups and remove driverize artifacts
argument-hint: ""
allowed-tools: Read, Write, Edit, Bash, Glob, Grep
---

# Un-Driverize — Remove Driver Enforcement Stack

This command cleanly reverses all changes made by `/drvr:driverize`. It uses provenance markers to identify Driverize-created artifacts, restores pre-Driverize backups where available, and performs surgical removal where backups don't exist.

**You are running from the repo root.** This prompt works standalone — no plugins required.

Follow these 6 phases in order.

---

## Phase 1: Detect

Scan for Driverize artifacts using provenance markers. Check each of the following:

### 1.1: Settings Metadata

Read `.claude/settings.json`. Look for the `_driverize` key at the top level. If found, extract:
- `version` — the installed Driverize version
- `installed_at` — when Driverize was installed

Store the detected version for reporting.

### 1.2: CLAUDE.md Block

Read `CLAUDE.md`. Search for the `<!-- driverize:v` opening marker and `<!-- /driverize -->` closing marker. If found, note the version from the opening marker tag (e.g., `<!-- driverize:v1.0 -->`).

### 1.3: Hook Scripts

Scan `.claude/hooks/` for shell scripts with provenance markers. Look for files containing:
- `# Driverize v` — version stamp in hook scripts

Check specifically for:
- `.claude/hooks/driver-first.sh`
- `.claude/hooks/inject-driver-policy.sh`
- `.claude/hooks/route-to-driver.sh`

### 1.4: Shadow Agents and Skills

Scan `.claude/agents/*.md` for files containing `<!-- driverize:v` provenance markers. Check specifically:
- `.claude/agents/Explore.md`
- `.claude/agents/Plan.md`
- `.claude/agents/general-purpose.md`

Scan `.claude/skills/**/*.md` for files containing `<!-- driverize:v` provenance markers. Check specifically:
- `.claude/skills/explore-codebase/SKILL.md`

### 1.5: Backups

Check for `.pre-driver` backup files:
- `CLAUDE.md.pre-driver`
- `.claude/settings.json.pre-driver`

### 1.6: Report Findings

Present a summary of what was found:

```
Driverize Installation Detected:
  Version: <version or "unknown (pre-versioning install)">
  Installed: <timestamp or "unknown">

Artifacts found:
  - [x/n] .claude/settings.json (_driverize metadata)
  - [x/n] CLAUDE.md (driverize block)
  - [x/n] .claude/hooks/driver-first.sh
  - [x/n] .claude/hooks/inject-driver-policy.sh
  - [x/n] .claude/hooks/route-to-driver.sh
  - [x/n] .claude/agents/Explore.md
  - [x/n] .claude/agents/Plan.md
  - [x/n] .claude/agents/general-purpose.md
  - [x/n] .claude/skills/explore-codebase/SKILL.md

Backups found:
  - [x/n] CLAUDE.md.pre-driver
  - [x/n] .claude/settings.json.pre-driver
```

If no Driverize artifacts are found at all, stop and tell the user:
> "No Driverize installation detected. Nothing to remove."

---

## Phase 2: Plan

Build a removal plan based on what was detected in Phase 1.

### 2.1: Build Removal Plan

For each detected artifact, determine the action:

| Artifact | Backup Exists? | Action |
|----------|---------------|--------|
| `CLAUDE.md` | Yes (`CLAUDE.md.pre-driver`) | Restore from backup |
| `CLAUDE.md` | No | Surgical removal of `<!-- driverize:v...-->...<!-- /driverize -->` block |
| `.claude/settings.json` | Yes (`.claude/settings.json.pre-driver`) | Restore from backup |
| `.claude/settings.json` | No | Surgical removal of Driverize entries (preserve customer additions) |
| Hook scripts | n/a | Delete (only if provenance marker found) |
| Shadow agents | n/a | Delete (only if provenance marker found) |
| Skills | n/a | Delete (only if provenance marker found) |

### 2.2: Pre-Versioning Install Handling

If no provenance markers were found (no `driverize:v` in any file, no `_driverize` key in settings.json), this is a pre-versioning installation. In this case:

- Fall back to the hardcoded file list (the files listed in Phase 1)
- **Require explicit user confirmation for EACH file** — never silently delete files that might be customer-created
- For each file, show the user its first few lines and ask: "This file matches the expected Driverize artifact location. Does it look like a Driverize-generated file? Remove it? (y/n)"

### 2.3: User Confirmation

Present the full removal plan to the user for confirmation:

> **The following changes will be made:**
>
> **Restore from backup:**
> - `CLAUDE.md.pre-driver` → `CLAUDE.md`
> - `.claude/settings.json.pre-driver` → `.claude/settings.json`
>
> **Surgical removal (no backup):**
> - Remove driverize block from `CLAUDE.md`
> - Remove Driverize entries from `.claude/settings.json`
>
> **Delete files:**
> - `.claude/hooks/driver-first.sh`
> - `.claude/hooks/inject-driver-policy.sh`
> - `.claude/hooks/route-to-driver.sh`
> - `.claude/agents/Explore.md`
> - `.claude/agents/Plan.md`
> - `.claude/agents/general-purpose.md`
> - `.claude/skills/explore-codebase/SKILL.md`
>
> **Clean up:**
> - Remove session artifacts (`/tmp/driver-context-loaded-*`, `/tmp/driver-unavailable-*`)
>
> **Proceed? (y/n)**

Only list items that were actually detected. If the user declines, stop immediately — do not make any changes.

### 2.4: Modified File Detection

Before proceeding, for files that will be deleted (hooks, agents, skills), check if they have been modified after Driverize installed them:

- If the file has a `_driverize.installed_at` timestamp in settings.json, compare the file's modification time against it
- If the file appears modified, show the user a diff or the current content and ask: "This file appears to have been modified after Driverize installed it. Remove anyway? (y/n)"

---

## Phase 3: Restore

Restore `.pre-driver` backups where they exist.

### 3.1: Restore CLAUDE.md

**If `CLAUDE.md.pre-driver` exists:**
- Copy `CLAUDE.md.pre-driver` → `CLAUDE.md` (overwrite)
- Delete `CLAUDE.md.pre-driver`

**If no backup exists — surgical removal:**
- Read `CLAUDE.md`
- Find the `<!-- driverize:v` opening marker line
- Find the `<!-- /driverize -->` closing marker line
- Remove everything from the opening marker line through the closing marker line (inclusive)
- Write the modified content back to `CLAUDE.md`
- WARN the user: "No CLAUDE.md backup found. Removed the driverize block surgically. Review the result."

### 3.2: Restore settings.json

**If `.claude/settings.json.pre-driver` exists:**
- Copy `.claude/settings.json.pre-driver` → `.claude/settings.json` (overwrite)
- Delete `.claude/settings.json.pre-driver`

**If no backup exists — surgical removal:**

Read `.claude/settings.json` and parse it as JSON. Perform these removals (hardcoded for v1.0):

1. **Remove the `_driverize` metadata key** from the top level

2. **From `permissions.deny` array**, remove these exact entries:
   - `Bash(grep:*)`
   - `Bash(rg:*)`
   - `Bash(find:*)`
   - `Bash(ag:*)`
   - `Bash(ack:*)`
   - `Bash(fd:*)`
   - `Bash(tree:*)`
   - `Bash(env grep:*)`
   - `Bash(command grep:*)`
   - `Bash(env rg:*)`
   - `Bash(command rg:*)`
   - `Bash(env find:*)`
   - `Bash(command find:*)`
   - `Bash(touch /tmp/driver:*)`
   - `Bash(rm /tmp/driver:*)`

3. **From `permissions.ask` array**, remove these exact entries:
   - `Edit(.claude/**)`
   - `Write(.claude/**)`

4. **From `hooks` object**, remove hook entries whose `command` path contains any of:
   - `driver-first.sh`
   - `inject-driver-policy.sh`
   - `route-to-driver.sh`

   For each hook type (`PreToolUse`, `PostToolUse`, `UserPromptSubmit`, `SessionStart`, etc.), iterate the array and remove entries matching the above. If the array becomes empty after removal, remove the hook type key entirely.

5. **Preserve all other entries** in each array and object — customer additions must remain intact.

6. Write the modified JSON back to `.claude/settings.json` with proper formatting (2-space indent).

7. WARN the user: "No settings.json backup found. Removed Driverize entries surgically. Review the result."

---

## Phase 4: Remove

Delete Driverize-created files. **Only delete files that have provenance markers** (or were confirmed by the user in the pre-versioning flow).

### 4.1: Delete Hook Scripts

Delete these files if they exist and contain the `# Driverize v` provenance marker:
- `.claude/hooks/driver-first.sh`
- `.claude/hooks/inject-driver-policy.sh`
- `.claude/hooks/route-to-driver.sh`

### 4.2: Delete Shadow Agents

Delete these files if they exist and contain the `<!-- driverize:v` provenance marker:
- `.claude/agents/Explore.md`
- `.claude/agents/Plan.md`
- `.claude/agents/general-purpose.md`

### 4.3: Delete Skills

Delete these files if they exist and contain the `<!-- driverize:v` provenance marker:
- `.claude/skills/explore-codebase/SKILL.md`

### 4.4: Clean Up Empty Directories

After deleting files, check if any directories are now empty and remove them:
- `.claude/hooks/` — remove if empty
- `.claude/agents/` — remove if empty
- `.claude/skills/explore-codebase/` — remove if empty
- `.claude/skills/` — remove if empty (after subdirectory cleanup)

Do NOT remove `.claude/` itself — it may contain other configuration.

### 4.5: Remove Session Artifacts

Delete temporary session files:
```bash
rm -f /tmp/driver-context-loaded-*
rm -f /tmp/driver-unavailable-*
```

---

## Phase 5: Verify

Confirm the removal was successful.

### 5.1: Artifact Verification

Check that all marked artifacts have been removed:
- No `_driverize` key in `.claude/settings.json` (if file still exists)
- No `<!-- driverize:v` markers in `CLAUDE.md` (if file still exists)
- No `# Driverize v` markers in `.claude/hooks/*.sh`
- No `<!-- driverize:v` markers in `.claude/agents/*.md`
- No `<!-- driverize:v` markers in `.claude/skills/**/*.md`

### 5.2: Backup Verification

Confirm backups were restored or blocks were surgically removed:
- If backups existed: confirm `.pre-driver` files have been deleted (they were consumed during restore)
- If surgical removal was used: confirm the driverize blocks/entries are gone from the target files

### 5.3: JSON Validation

If `.claude/settings.json` was surgically modified (no backup restore), validate it is still valid JSON:
```bash
python3 -c "import json; json.load(open('.claude/settings.json'))"
```

If validation fails, this is a critical error. Warn the user and do NOT proceed with cleanup.

---

## Phase 6: Output

Present the final summary to the user.

### 6.1: Summary

```
Un-Driverize Complete
=====================

Restored:
  - CLAUDE.md (from backup / surgical removal)
  - .claude/settings.json (from backup / surgical removal)

Removed:
  - .claude/hooks/driver-first.sh
  - .claude/hooks/inject-driver-policy.sh
  - .claude/hooks/route-to-driver.sh
  - .claude/agents/Explore.md
  - .claude/agents/Plan.md
  - .claude/agents/general-purpose.md
  - .claude/skills/explore-codebase/SKILL.md

Cleaned up:
  - /tmp/driver-context-loaded-*
  - /tmp/driver-unavailable-*
  - Empty directories removed

Warnings:
  - <any warnings from surgical removal, modified files, etc.>
```

Only list items that were actually processed. Omit sections with no items.

### 6.2: Re-Installation Note

> To re-install the Driver enforcement stack, run `/drvr:driverize`.

---

## Edge Cases

### No `.pre-driver` Backups

If no `.pre-driver` backup files exist, perform surgical removal only. Warn the user that the original file content cannot be fully restored — only the Driverize additions will be removed.

### Files Modified After Driverize

If a Driverize-created file has been modified since installation (detected via modification timestamps or content differences), show the user the current content and let them decide whether to remove it.

### No Provenance Markers (Pre-Versioning Install)

If no `driverize:v` markers or `_driverize` metadata key are found, this is a pre-versioning installation (before version stamps were added). In this case:
- Fall back to the hardcoded file list
- Require explicit user confirmation for each file before deletion
- Never silently delete files that might be customer-created

### Clean-Repo Driverize (No Original Files)

If Driverize was installed on a repo that had no existing `CLAUDE.md` or `.claude/settings.json`:
- There will be no `.pre-driver` backups (nothing to back up)
- Simply delete the Driverize-created files
- No restoration needed — the files didn't exist before Driverize

---

## Reminders

- **User controls all decisions** — present the plan, get confirmation, then execute. Never silently delete or modify files.
- **Provenance markers are the source of truth** — only remove files that have `driverize:v` markers (or are confirmed by the user in pre-versioning flow).
- **Preserve customer additions** — when doing surgical removal from settings.json, only remove the specific Driverize entries. All other entries (customer-added permissions, hooks, etc.) must remain.
- **Verify after removal** — always run the verification phase to confirm clean removal.
