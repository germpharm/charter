"""Governance injection into AI tools.

Writes governance rules into tool-specific configuration files.
For Claude Code and similar tools, this means CLAUDE.md.
Uses markers to update governance sections without touching
user-authored content in the same file.
"""

import os
import time

from charter.config import load_config
from charter.generate import render_claude_md


MARKER_START = "<!-- charter:governance:start -->"
MARKER_END = "<!-- charter:governance:end -->"


def inject_claude_md(project_path, config=None, config_path=None):
    """Write or update CLAUDE.md with governance rules.

    If a CLAUDE.md already exists:
      - With markers: update the governed section only
      - Without markers: prepend governance above existing content

    If no CLAUDE.md exists, create one with governance rules.

    Returns the path to the written file, or None on failure.
    """
    if config is None:
        config = load_config(config_path)
    if not config:
        return None

    content = render_claude_md(config)
    governed_block = f"{MARKER_START}\n{content}\n{MARKER_END}"

    claude_md = os.path.join(project_path, "CLAUDE.md")

    if os.path.exists(claude_md):
        with open(claude_md) as f:
            existing = f.read()

        if MARKER_START in existing and MARKER_END in existing:
            start = existing.index(MARKER_START)
            end = existing.index(MARKER_END) + len(MARKER_END)
            result = existing[:start] + governed_block + existing[end:]
        else:
            result = governed_block + "\n\n" + existing
    else:
        result = governed_block

    with open(claude_md, "w") as f:
        f.write(result)

    return claude_md


def check_governance(project_path):
    """Check if a project directory has governance configured.

    Returns dict with governance status for the project.
    """
    claude_md = os.path.join(project_path, "CLAUDE.md")
    charter_yaml = os.path.join(project_path, "charter.yaml")

    has_claude_md = os.path.exists(claude_md)
    has_charter = os.path.exists(charter_yaml)
    has_markers = False

    if has_claude_md:
        with open(claude_md) as f:
            content = f.read()
        has_markers = MARKER_START in content

    return {
        "path": project_path,
        "has_claude_md": has_claude_md,
        "has_charter_yaml": has_charter,
        "governed": has_markers,
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def scan_projects(search_paths=None):
    """Find project directories and check their governance status.

    Looks for directories with .git, package.json, pyproject.toml, etc.
    Returns list of governance status dicts.
    """
    from pathlib import Path

    if search_paths is None:
        home = Path.home()
        search_paths = [
            home / "Documents",
            home / "Projects",
            home / "Code",
            home / "repos",
            home / "src",
            home / "Development",
        ]

    indicators = [
        ".git", "package.json", "pyproject.toml",
        "Cargo.toml", "go.mod", "Makefile",
    ]

    results = []
    for search_path in search_paths:
        search_path = Path(search_path)
        if not search_path.exists():
            continue

        try:
            for item in search_path.iterdir():
                if item.is_dir() and not item.name.startswith("."):
                    for indicator in indicators:
                        if (item / indicator).exists():
                            results.append(check_governance(str(item)))
                            break
        except PermissionError:
            continue

    return results
