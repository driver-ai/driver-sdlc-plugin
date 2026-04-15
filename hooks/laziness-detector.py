#!/usr/bin/env python3
"""
Agent Laziness Detector - PreToolUse hook for Claude Code

Blocks writes/edits that contain lazy patterns like TODO, FIXME,
NotImplementedError, empty function bodies, etc.

Part of the SDLC plugin for Claude Code.
"""

import json
import os
import re
import sys
from typing import List, Tuple

# =============================================================================
# CONFIGURATION
# =============================================================================

# High-confidence patterns that should always block
# Each tuple: (regex_pattern, error_message)
# Use {match} in message to include the matched text
PATTERNS: List[Tuple[str, str]] = [
    # ===================
    # Universal (all languages)
    # ===================
    (r'\b(TODO|FIXME|XXX|HACK|STUB)\b',
     'Found {match} comment - implement the actual code'),
    (r'(implement|add|do|fix)\s+(this\s+)?later',
     'Found "implement later" comment - implement now'),

    # ===================
    # Python
    # ===================
    (r'raise\s+NotImplementedError',
     'Found NotImplementedError - implement the actual code'),
    (r':\s*\n\s*pass\s*$',
     'Found empty function body with pass - implement the actual code'),
    (r':\s*\n\s*\.\.\.\s*$',
     'Found ellipsis (...) as implementation - implement the actual code'),
    (r'return\s+None\s*#.*placeholder',
     'Found placeholder return - implement the actual code'),

    # ===================
    # TypeScript/JavaScript
    # ===================
    (r'throw\s+new\s+Error\s*\(\s*["\']([Nn]ot\s+[Ii]mplemented|TODO)',
     'Found "not implemented" error - implement the actual code'),
    (r'\)\s*=>\s*\{\s*\}',
     'Found empty arrow function - implement the actual code'),
    (r'function\s+\w+\s*\([^)]*\)\s*\{\s*\}',
     'Found empty function body - implement the actual code'),
    (r'return\s+(null|undefined)\s*[;]?\s*//.*placeholder',
     'Found placeholder return - implement the actual code'),

    # ===================
    # Swift
    # ===================
    (r'fatalError\s*\(\s*["\']([Nn]ot\s+[Ii]mplemented|TODO)',
     'Found fatalError stub - implement the actual code'),
    (r'preconditionFailure\s*\(\s*["\']([Nn]ot\s+[Ii]mplemented|TODO)',
     'Found preconditionFailure stub - implement the actual code'),

    # ===================
    # Go
    # ===================
    (r'panic\s*\(\s*["\']not\s+implemented',
     'Found panic stub - implement the actual code'),

    # ===================
    # Java/C#
    # ===================
    (r'throw\s+new\s+(UnsupportedOperationException|NotImplementedException)',
     'Found not-implemented exception - implement the actual code'),
]

# File extensions to check (skip binary, config, etc.)
CODE_EXTENSIONS = {
    # Python
    '.py', '.pyi',
    # TypeScript/JavaScript
    '.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs',
    # Swift
    '.swift',
    # Other (for future use)
    '.go', '.rs', '.java', '.rb', '.cs', '.c', '.cpp', '.h', '.hpp',
}

# Files to always skip (even if extension matches)
SKIP_PATTERNS = [
    r'__pycache__',
    r'node_modules',
    r'\.git/',
    r'\.test\.',
    r'\.spec\.',
    r'_test\.py$',
    r'test_.*\.py$',
]

# =============================================================================
# FUNCTIONS
# =============================================================================

def get_content(tool_input: dict, tool_name: str) -> str:
    """Extract content being written/edited."""
    if tool_name == "Write":
        return tool_input.get("content", "")
    elif tool_name == "Edit":
        return tool_input.get("new_string", "")
    return ""


def should_check_file(file_path: str) -> bool:
    """Determine if file should be checked based on extension and path."""
    # Check extension
    ext = os.path.splitext(file_path)[1].lower()
    if ext not in CODE_EXTENSIONS:
        return False

    # Check skip patterns
    for pattern in SKIP_PATTERNS:
        if re.search(pattern, file_path):
            return False

    return True


def find_laziness(content: str, file_path: str) -> List[str]:
    """Find all laziness patterns in content."""
    issues = []

    for pattern, message in PATTERNS:
        try:
            match = re.search(pattern, content, re.IGNORECASE | re.MULTILINE)
            if match:
                match_str = match.group(1) if match.lastindex else match.group(0)
                issues.append(message.format(match=match_str))
        except re.error:
            # Skip invalid patterns
            continue

    return issues


def block_write(reason: str) -> None:
    """Output JSON to block the write operation."""
    result = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason
        }
    }
    print(json.dumps(result))


def log_friction_event(session_id, event_type, cost, detail):
    """Append a JSONL friction event to the session friction log."""
    try:
        if not session_id:
            return
        log_path = f"/tmp/driver-friction-{session_id}.log"
        event = json.dumps({
            "ts": __import__('datetime').datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
            "type": event_type,
            "cost": cost,
            "detail": detail,
        })
        with open(log_path, 'a') as f:
            f.write(event + '\n')
    except Exception:
        return  # fail open — never block on friction logging errors


def main():
    try:
        # Read input from stdin
        input_data = json.load(sys.stdin)

        # Friction tracking config — fail open on any error
        # Resolution order: installed_plugins.json installPath, then CLAUDE_PLUGIN_ROOT, then local/, then dirname
        friction_enabled = False
        try:
            config_path = None
            # Check installed_plugins.json for marketplace install path
            installed_path = os.path.expanduser('~/.claude/plugins/installed_plugins.json')
            if os.path.exists(installed_path):
                with open(installed_path) as f:
                    installed = json.load(f)
                for key, entries in installed.get('plugins', {}).items():
                    if 'driver-sdlc-plugin' in key and entries:
                        ip = os.path.join(entries[0].get('installPath', ''), 'config.local.json')
                        if os.path.exists(ip):
                            config_path = ip
                        break
            # Fallback: CLAUDE_PLUGIN_ROOT
            if not config_path:
                plugin_dir = os.environ.get('CLAUDE_PLUGIN_ROOT')
                if plugin_dir:
                    candidate = os.path.join(plugin_dir, 'config.local.json')
                    if os.path.exists(candidate):
                        config_path = candidate
            # Fallback: local dir
            if not config_path:
                local_config = os.path.expanduser('~/.claude/plugins/local/driver-sdlc-plugin/config.local.json')
                if os.path.exists(local_config):
                    config_path = local_config
            # Fallback: dirname
            if not config_path:
                plugin_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                config_path = os.path.join(plugin_dir, 'config.local.json')

            with open(config_path) as f:
                config = json.load(f)
            friction_enabled = config.get('friction_tracking', False)
        except Exception:
            friction_enabled = False

        tool_name = input_data.get("tool_name", "")
        tool_input = input_data.get("tool_input", {})
        file_path = tool_input.get("file_path", "")
        session_id = input_data.get("session_id", "")

        # Friction: detect Edit on non-existent file
        if friction_enabled and tool_name == "Edit" and file_path and not os.path.exists(file_path):
            log_friction_event(session_id, "wrong_path", 2, f"Edit on non-existent file: {file_path}")

        # Skip non-code files
        if not should_check_file(file_path):
            sys.exit(0)

        # Get content being written
        content = get_content(tool_input, tool_name)
        if not content:
            sys.exit(0)

        # Check for laziness
        issues = find_laziness(content, file_path)

        if issues:
            # Block the write with detailed reason
            reason = "Laziness detected! Please fix before continuing:\n\n"
            reason += "\n".join(f"  • {issue}" for issue in issues)
            reason += "\n\nRewrite the code with actual implementations instead of stubs/placeholders."
            block_write(reason)
            if friction_enabled:
                log_friction_event(session_id, "silent_failure", 3, f"Laziness blocked: {file_path}")
            sys.exit(0)

        # No issues - allow the write
        sys.exit(0)

    except json.JSONDecodeError as e:
        # Invalid JSON input - fail open
        print(f"Laziness detector: Invalid JSON input - {e}", file=sys.stderr)
        sys.exit(0)
    except Exception as e:
        # On any error, allow the write (fail open)
        print(f"Laziness detector error: {e}", file=sys.stderr)
        sys.exit(0)


if __name__ == "__main__":
    main()
