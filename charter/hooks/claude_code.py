"""Claude Code hooks for Charter — auto-hash every AI agent action.

Generates Claude Code settings.json hook configurations that fire
`charter log` on tool calls, edits, and session events.

v3.1.1 Phase 2.5: Hooks auto-link caused_by edges. When an AI action
follows a human input (requirement_stated, decision_made), the hook
reads the latest human entry from the chain and links to it. This
creates the causal chain: Matt said X → Claude built Y because of X.

Claude Code hooks are defined in ~/.claude/settings.json under the
"hooks" key. Charter provides pre-built hook definitions that log
agent actions to the hash chain.

Usage:
    charter hooks claude-code install   # Add hooks to Claude Code settings
    charter hooks claude-code status    # Show hook status
    charter hooks claude-code remove    # Remove Charter hooks
"""

import json
import os


CLAUDE_SETTINGS_PATH = os.path.expanduser("~/.claude/settings.json")

# The hook commands use a helper script that:
# 1. Logs the action to the chain
# 2. Reads the latest human entry and auto-links caused_by
CAUSED_BY_SCRIPT = os.path.join(
    os.path.dirname(__file__), "auto_link.sh"
)

# Hook definitions for Claude Code
CHARTER_HOOKS = {
    "PostToolUse": [
        {
            "matcher": "Edit|Write|NotebookEdit",
            "hooks": [
                {
                    "type": "command",
                    "command": (
                        "charter log agent_edit --actor ai "
                        '--data-json \'{"tool": "edit", '
                        '"description": "AI edited file"}\' '
                        "--edge caused_by:$(charter _last-human-hash 2>/dev/null || echo skip)"
                    ),
                }
            ],
        },
    ],
    "PreToolUse": [
        {
            "matcher": "Bash",
            "hooks": [
                {
                    "type": "command",
                    "command": (
                        "charter log agent_action --actor ai "
                        '--data-json \'{"tool": "Bash", '
                        '"description": "AI executing shell command"}\' '
                        "--edge caused_by:$(charter _last-human-hash 2>/dev/null || echo skip)"
                    ),
                }
            ],
        },
    ],
    "Notification": [
        {
            "matcher": "",
            "hooks": [
                {
                    "type": "command",
                    "command": (
                        'charter log agent_notification --actor ai '
                        '--data-json \'{"description": "Agent notification"}\''
                    ),
                }
            ],
        },
    ],
    "Stop": [
        {
            "matcher": "",
            "hooks": [
                {
                    "type": "command",
                    "command": (
                        'charter log session_ended --actor collaborative '
                        '--data-json \'{"description": "Claude Code session ended"}\''
                    ),
                }
            ],
        },
    ],
}

CHARTER_HOOK_MARKER = "charter log"


def load_claude_settings():
    """Load Claude Code settings, creating if needed."""
    if os.path.isfile(CLAUDE_SETTINGS_PATH):
        with open(CLAUDE_SETTINGS_PATH) as f:
            return json.load(f)
    return {}


def save_claude_settings(settings):
    """Save Claude Code settings."""
    os.makedirs(os.path.dirname(CLAUDE_SETTINGS_PATH), exist_ok=True)
    with open(CLAUDE_SETTINGS_PATH, "w") as f:
        json.dump(settings, f, indent=2)


def install_claude_hooks():
    """Install Charter hooks into Claude Code settings.

    Returns:
        dict: {"installed": list of hook types, "errors": list}
    """
    settings = load_claude_settings()

    if "hooks" not in settings:
        settings["hooks"] = {}

    installed = []

    for hook_type, hook_defs in CHARTER_HOOKS.items():
        if hook_type not in settings["hooks"]:
            settings["hooks"][hook_type] = []

        # Check if Charter hooks already exist
        existing = settings["hooks"][hook_type]
        charter_exists = False
        for entry in existing:
            hooks = entry.get("hooks", [])
            for h in hooks:
                if isinstance(h.get("command", ""), str) and CHARTER_HOOK_MARKER in h["command"]:
                    charter_exists = True
                    break

        if not charter_exists:
            settings["hooks"][hook_type].extend(hook_defs)
            installed.append(hook_type)

    save_claude_settings(settings)
    return {"installed": installed, "errors": []}


def remove_claude_hooks():
    """Remove Charter hooks from Claude Code settings."""
    settings = load_claude_settings()

    if "hooks" not in settings:
        return {"removed": [], "errors": []}

    removed = []

    for hook_type in list(settings["hooks"].keys()):
        entries = settings["hooks"][hook_type]
        filtered = []
        had_charter = False
        for entry in entries:
            hooks = entry.get("hooks", [])
            is_charter = any(
                isinstance(h.get("command", ""), str) and CHARTER_HOOK_MARKER in h["command"]
                for h in hooks
            )
            if is_charter:
                had_charter = True
            else:
                filtered.append(entry)

        if had_charter:
            removed.append(hook_type)
            settings["hooks"][hook_type] = filtered

    save_claude_settings(settings)
    return {"removed": removed, "errors": []}


def claude_hooks_status():
    """Check Charter hook installation status in Claude Code."""
    settings = load_claude_settings()
    hooks = settings.get("hooks", {})

    status = {}
    for hook_type in CHARTER_HOOKS:
        entries = hooks.get(hook_type, [])
        installed = any(
            isinstance(h.get("command", ""), str) and CHARTER_HOOK_MARKER in h["command"]
            for entry in entries
            for h in entry.get("hooks", [])
        )
        status[hook_type] = installed

    return status
