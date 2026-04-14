#!/usr/bin/env bash
set -euo pipefail

# Run the plugin test suite from the repository root.
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

python3 -m unittest discover -s tests -v
