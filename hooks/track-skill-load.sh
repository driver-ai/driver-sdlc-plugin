#!/bin/sh
# PreToolUse hook for Skill tool — tracks which skills are loaded in the session.
# Appends skill name to a session-scoped temp file for the status line to read.
# Must exit 0 always — never block a skill invocation.

# Check for jq
if ! command -v jq >/dev/null 2>&1; then
    exit 0
fi

# Read stdin, extract skill name and session ID
INPUT=$(cat)
SKILL_NAME=$(echo "$INPUT" | jq -r '.tool_input.skill // empty' 2>/dev/null)
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // empty' 2>/dev/null)

# Need both to proceed
if [ -z "$SKILL_NAME" ] || [ -z "$SESSION_ID" ]; then
    exit 0
fi

# Session-scoped file
SKILLS_FILE="/tmp/driver-skills-${SESSION_ID}.txt"
echo "$SKILL_NAME" >> "$SKILLS_FILE"

exit 0
