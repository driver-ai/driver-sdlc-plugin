#!/bin/sh
# PreToolUse hook for Skill tool — tracks which skills are loaded in the session.
# Appends skill name to a session-scoped temp file for the status line to read.
# Also tracks phase transitions and optionally logs friction events.
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

# Session-scoped file (backward compatible)
SKILLS_FILE="/tmp/driver-skills-${SESSION_ID}.txt"
echo "$SKILL_NAME" >> "$SKILLS_FILE"

# ---------------------------------------------------------------------------
# Phase tracking
# ---------------------------------------------------------------------------

PHASE=""
case "$SKILL_NAME" in
    research-guidance)    PHASE="Research" ;;
    planning-guidance)    PHASE="Planning" ;;
    implementation-guidance) PHASE="Implementation" ;;
    sdlc-orchestration)   PHASE="Orchestration" ;;
    *)                    PHASE="" ;;
esac

if [ -n "$PHASE" ]; then
    PHASE_FILE="/tmp/driver-phase-${SESSION_ID}.txt"
    printf '%s\n' "$PHASE" > "$PHASE_FILE"
fi

# ---------------------------------------------------------------------------
# Friction logging (optional — requires config.local.json)
# ---------------------------------------------------------------------------

FRICTION_ENABLED=false
CONFIG_FILE="$HOME/.driver/config.json"

if [ -f "$CONFIG_FILE" ]; then
    FRICTION_VAL=$(jq -r '.friction_tracking // false' "$CONFIG_FILE" 2>/dev/null)
    if [ "$FRICTION_VAL" = "true" ]; then
        FRICTION_ENABLED=true
    fi
fi

if [ "$FRICTION_ENABLED" = "true" ] && [ -n "$PHASE" ]; then
    FRICTION_LOG="/tmp/driver-friction-${SESSION_ID}.log"
    TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    printf '{"ts":"%s","type":"skill_invoked","cost":0,"detail":"%s loaded in %s phase"}\n' \
        "$TS" "$SKILL_NAME" "$PHASE" >> "$FRICTION_LOG"
fi

exit 0
