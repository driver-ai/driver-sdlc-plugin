#!/bin/sh
# SessionEnd hook: commit uncommitted SDLC artifacts as safety net.
# Follows fail-open pattern — always exits 0. No set -e.

# Consume stdin (required by hook protocol)
cat > /dev/null 2>&1

# Must be in a git repo
git rev-parse --git-dir > /dev/null 2>&1 || exit 0

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0

# Find feature directories by scanning for FEATURE_LOG.md
FEATURE_DIRS=""
if [ -d "$REPO_ROOT/features" ]; then
  FEATURE_DIRS="$(find "$REPO_ROOT/features" -maxdepth 2 -name FEATURE_LOG.md -exec dirname {} \; 2>/dev/null)" || true
fi

# Also check cwd and parents (covers non-standard layouts)
check_dir="$(pwd)"
for _ in 1 2 3 4 5; do
  if [ -f "$check_dir/FEATURE_LOG.md" ]; then
    FEATURE_DIRS="$FEATURE_DIRS
$check_dir"
    break
  fi
  parent="$(dirname "$check_dir")"
  [ "$parent" = "$check_dir" ] && break
  check_dir="$parent"
done

# Run all git operations from repo root for consistent path resolution
cd "$REPO_ROOT" 2>/dev/null || exit 0

# Deduplicate and process each feature directory
echo "$FEATURE_DIRS" | sort -u | while IFS= read -r feature_dir; do
  [ -z "$feature_dir" ] && continue
  [ -d "$feature_dir" ] || continue

  # Make path relative to repo root for git commands
  rel_dir="$(echo "$feature_dir" | sed "s|^$REPO_ROOT/||")"

  # Collect uncommitted .md files in artifact directories
  files_to_add=""
  for dir in research plans implementation assessment driver-docs dry-runs tests; do
    if [ -d "$feature_dir/$dir" ]; then
      changed="$(git ls-files --others --modified --exclude-standard -- "$rel_dir/$dir/" 2>/dev/null)" || true
      [ -n "$changed" ] && files_to_add="$files_to_add $changed"
    fi
  done

  # Check root-level artifacts
  for f in FEATURE_LOG.md DECISIONS.md; do
    if [ -f "$feature_dir/$f" ]; then
      git diff --quiet -- "$rel_dir/$f" 2>/dev/null || files_to_add="$files_to_add $rel_dir/$f"
    fi
  done

  # Trim whitespace
  files_to_add="$(echo "$files_to_add" | sed 's/^ *//;s/ *$//')"
  [ -z "$files_to_add" ] && continue

  # Stage and commit
  git add $files_to_add 2>/dev/null || continue
  feature_name="$(basename "$feature_dir")"
  git commit -m "chore: Auto-commit SDLC artifacts — $feature_name (session end)" 2>/dev/null || continue
done

exit 0
