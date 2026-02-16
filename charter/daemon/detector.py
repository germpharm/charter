"""AI tool detection on the local machine.

Scans running processes to identify AI tools and reports their
governance status. Works cross-platform (macOS, Windows, Linux).

Uses psutil if available, falls back to ps/tasklist.
"""

import os
import platform
import subprocess
import time


# Known AI tools and their process signatures
AI_TOOLS = {
    "claude_code": {
        "name": "Claude Code",
        "vendor": "Anthropic",
        "signatures": ["claude"],
        "governable": True,
        "method": "claude_md",
    },
    "chatgpt_desktop": {
        "name": "ChatGPT",
        "vendor": "OpenAI",
        "signatures": ["ChatGPT"],
        "governable": False,
        "method": None,
    },
    "vscode": {
        "name": "VS Code",
        "vendor": "Microsoft",
        "signatures": ["Code Helper"],
        "governable": True,
        "method": "vscode_settings",
        "note": "May include GitHub Copilot",
    },
    "cursor": {
        "name": "Cursor",
        "vendor": "Cursor",
        "signatures": ["Cursor Helper"],
        "governable": True,
        "method": "claude_md",
    },
    "windsurf": {
        "name": "Windsurf",
        "vendor": "Codeium",
        "signatures": ["Windsurf"],
        "governable": True,
        "method": "claude_md",
    },
    "copilot_cli": {
        "name": "GitHub Copilot CLI",
        "vendor": "GitHub",
        "signatures": ["github-copilot"],
        "governable": False,
        "method": None,
    },
}


def detect_processes():
    """Get running processes.

    Returns list of dicts with pid, name, cmdline keys.
    Uses psutil if available, falls back to subprocess.
    """
    try:
        import psutil
        return _detect_psutil()
    except ImportError:
        return _detect_subprocess()


def _detect_psutil():
    """Process detection using psutil."""
    import psutil
    processes = []
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            info = proc.info
            processes.append({
                "pid": info["pid"],
                "name": info["name"] or "",
                "cmdline": " ".join(info["cmdline"] or []),
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return processes


def _detect_subprocess():
    """Process detection using subprocess (no external deps)."""
    system = platform.system()
    processes = []

    if system in ("Darwin", "Linux"):
        try:
            result = subprocess.run(
                ["ps", "-eo", "pid,comm"],
                capture_output=True, text=True, timeout=10,
            )
            for line in result.stdout.strip().splitlines()[1:]:
                parts = line.strip().split(None, 1)
                if len(parts) >= 2:
                    processes.append({
                        "pid": int(parts[0]),
                        "name": os.path.basename(parts[1]),
                        "cmdline": parts[1],
                    })
        except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
            pass

    elif system == "Windows":
        try:
            result = subprocess.run(
                ["tasklist", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=10,
            )
            for line in result.stdout.strip().splitlines():
                parts = line.strip('"').split('","')
                if len(parts) >= 2:
                    pid = 0
                    try:
                        pid = int(parts[1])
                    except (ValueError, IndexError):
                        pass
                    processes.append({
                        "pid": pid,
                        "name": parts[0],
                        "cmdline": parts[0],
                    })
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    return processes


def detect_ai_tools():
    """Scan running processes for known AI tools.

    Returns list of detected tools with governance status.
    Each tool appears at most once regardless of how many
    matching processes are found.
    """
    processes = detect_processes()
    detected = []
    seen = set()

    for proc in processes:
        name_lower = proc["name"].lower()
        cmd_lower = proc.get("cmdline", "").lower()

        for tool_id, info in AI_TOOLS.items():
            if tool_id in seen:
                continue
            for sig in info["signatures"]:
                if sig.lower() in name_lower or sig.lower() in cmd_lower:
                    detected.append({
                        "tool_id": tool_id,
                        "name": info["name"],
                        "vendor": info["vendor"],
                        "pid": proc["pid"],
                        "process_name": proc["name"],
                        "governable": info["governable"],
                        "method": info["method"],
                        "detected_at": time.strftime(
                            "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
                        ),
                    })
                    seen.add(tool_id)
                    break

    return detected


def get_summary():
    """Detection summary with counts and tool list."""
    tools = detect_ai_tools()
    governed = [t for t in tools if t["governable"]]
    ungoverned = [t for t in tools if not t["governable"]]

    return {
        "total": len(tools),
        "governed": len(governed),
        "ungoverned": len(ungoverned),
        "tools": tools,
        "scanned_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
