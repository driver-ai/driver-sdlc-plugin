"""Shared helpers for driver-sdlc-plugin tests.

All stdlib Python — no external dependencies.
"""

from pathlib import Path

# ---------------------------------------------------------------------------
# Path constants
# ---------------------------------------------------------------------------

PLUGIN_ROOT: Path = Path(__file__).resolve().parent.parent
PLUGIN_CONFIG_DIR: Path = PLUGIN_ROOT / ".claude-plugin"

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
    """Return the markdown content after the YAML frontmatter fences."""

    text = path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)

    fence_count = 0
    body_start = 0
    for idx, line in enumerate(lines):
        if line.strip() == "---":
            fence_count += 1
            if fence_count == 2:
                body_start = idx + 1
                break

    if fence_count < 2:
        # No frontmatter — entire file is the body
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
