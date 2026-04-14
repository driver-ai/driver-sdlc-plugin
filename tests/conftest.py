"""Shared helpers for driver-sdlc-plugin tests.

All stdlib Python — no external dependencies.
"""

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Path constants
# ---------------------------------------------------------------------------

PLUGIN_ROOT: Path = Path(__file__).resolve().parent.parent
PLUGIN_CONFIG_DIR: Path = PLUGIN_ROOT / ".claude-plugin"


def discover_feature_projects(search_path=None):
    """Find feature project directories containing FEATURE_LOG.md.
    Uses FEATURE_PROJECTS_PATH env var, or falls back to sibling directory."""
    if search_path is None:
        search_path = os.environ.get("FEATURE_PROJECTS_PATH",
            str(PLUGIN_ROOT.parent / "driver-sdlc-projects" / "features"))
    search = Path(search_path)
    if not search.is_dir():
        return []
    return [p.parent for p in search.rglob("FEATURE_LOG.md")]

# ---------------------------------------------------------------------------
# Frontmatter / Markdown helpers
# ---------------------------------------------------------------------------


def parse_frontmatter(path: Path) -> dict:
    """Parse YAML frontmatter (between ``---`` fences) from a markdown file.

    Handles:
    * Simple ``key: value`` pairs
    * Block scalars (``|`` / ``>``) followed by indented continuation lines
    * Quoted values that span multiple lines (``"...\\n  ..."``)
    * ``allowed-tools`` as a YAML list (``  - item``) — returned as a Python
      list with ``allowed-tools-format`` set to ``"list"``
    * ``allowed-tools`` as a comma-separated string — returned as a Python
      list (split on ``,`` + strip) with ``allowed-tools-format`` set to
      ``"string"``
    """

    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    # Locate the two ``---`` fences.
    fence_indices: list[int] = []
    for idx, line in enumerate(lines):
        if line.strip() == "---":
            fence_indices.append(idx)
            if len(fence_indices) == 2:
                break

    if len(fence_indices) < 2:
        return {}

    fm_lines = lines[fence_indices[0] + 1 : fence_indices[1]]

    result: dict = {}
    i = 0
    while i < len(fm_lines):
        line = fm_lines[i]

        # Skip blank / comment lines
        if not line.strip() or line.strip().startswith("#"):
            i += 1
            continue

        # Must be a top-level key (no leading whitespace, contains ':')
        if line[0] == " " or line[0] == "\t" or ":" not in line:
            i += 1
            continue

        colon_pos = line.index(":")
        key = line[:colon_pos].strip()
        raw_value = line[colon_pos + 1 :].strip()

        # --- Block scalar (| or >) ---
        if raw_value in ("|", ">"):
            collected: list[str] = []
            i += 1
            while i < len(fm_lines) and fm_lines[i] and (fm_lines[i][0] == " " or fm_lines[i][0] == "\t"):
                collected.append(fm_lines[i].strip())
                i += 1
            result[key] = "\n".join(collected)
            continue

        # --- Quoted multiline value ---
        if raw_value.startswith('"') and not raw_value.endswith('"'):
            collected_parts: list[str] = [raw_value[1:]]  # strip opening quote
            i += 1
            while i < len(fm_lines):
                cont = fm_lines[i]
                stripped = cont.strip()
                if stripped.endswith('"'):
                    collected_parts.append(stripped[:-1])  # strip closing quote
                    i += 1
                    break
                collected_parts.append(stripped)
                i += 1
            result[key] = " ".join(collected_parts)
            continue

        # --- Strip surrounding quotes from simple values ---
        if raw_value.startswith('"') and raw_value.endswith('"'):
            raw_value = raw_value[1:-1]

        # --- YAML list (allowed-tools or any list key) ---
        if raw_value == "":
            # Could be a YAML list — peek ahead
            list_items: list[str] = []
            j = i + 1
            while j < len(fm_lines) and fm_lines[j].startswith("  - "):
                list_items.append(fm_lines[j].strip().lstrip("- ").strip())
                j += 1
            if list_items:
                result[key] = list_items
                if key == "allowed-tools":
                    result["allowed-tools-format"] = "list"
                i = j
                continue

        # --- Comma-separated allowed-tools ---
        if key == "allowed-tools" and raw_value and "," in raw_value:
            result[key] = [item.strip() for item in raw_value.split(",")]
            result["allowed-tools-format"] = "string"
            i += 1
            continue

        # --- Plain value ---
        result[key] = raw_value
        i += 1

    return result


def get_md_body(path: Path) -> str:
    """Return the markdown content after the YAML frontmatter fences.

    Only strips frontmatter when the first non-blank line is ``---``
    (real YAML frontmatter). Horizontal-rule ``---`` dividers inside
    the body are left untouched.
    """

    text = path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)

    # Check that the first non-blank line is a ``---`` fence.
    first_content_is_fence = False
    for line in lines:
        if not line.strip():
            continue
        first_content_is_fence = line.strip() == "---"
        break

    if not first_content_is_fence:
        return text

    fence_count = 0
    body_start = 0
    for idx, line in enumerate(lines):
        if line.strip() == "---":
            fence_count += 1
            if fence_count == 2:
                body_start = idx + 1
                break

    if fence_count < 2:
        # No closing fence — entire file is the body
        return text

    return "".join(lines[body_start:]).lstrip("\n")


def get_md_sections(path: Path) -> list[str]:
    """Return a list of H2 heading strings (``## Heading``) from a markdown file."""

    body = get_md_body(path)
    sections: list[str] = []
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            sections.append(stripped[3:].strip())
    return sections
