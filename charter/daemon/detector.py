"""AI tool detection on the local machine.

Scans running processes and browser tabs to identify AI tools
and reports their governance status. Works cross-platform
(macOS, Windows, Linux). Browser tab detection uses AppleScript
on macOS.

Uses psutil if available, falls back to ps/tasklist.
"""

import os
import platform
import subprocess
import time


# Known AI domains in browser tabs
BROWSER_AI_DOMAINS = {
    "chatgpt": {
        "name": "ChatGPT",
        "vendor": "OpenAI",
        "domains": ["chat.openai.com", "chatgpt.com"],
        "governable": False,
        "method": None,
    },
    "grok": {
        "name": "Grok",
        "vendor": "xAI",
        "domains": ["grok.com", "grok.x.ai", "x.com/i/grok"],
        "governable": False,
        "method": None,
    },
    "claude_web": {
        "name": "Claude (web)",
        "vendor": "Anthropic",
        "domains": ["claude.ai"],
        "governable": False,
        "method": None,
    },
    "gemini": {
        "name": "Gemini",
        "vendor": "Google",
        "domains": ["gemini.google.com"],
        "governable": False,
        "method": None,
    },
    "copilot_web": {
        "name": "Microsoft Copilot",
        "vendor": "Microsoft",
        "domains": ["copilot.microsoft.com"],
        "governable": False,
        "method": None,
    },
    "perplexity": {
        "name": "Perplexity",
        "vendor": "Perplexity AI",
        "domains": ["perplexity.ai"],
        "governable": False,
        "method": None,
    },
    "poe": {
        "name": "Poe",
        "vendor": "Quora",
        "domains": ["poe.com"],
        "governable": False,
        "method": None,
    },
    "deepseek": {
        "name": "DeepSeek",
        "vendor": "DeepSeek",
        "domains": ["chat.deepseek.com"],
        "governable": False,
        "method": None,
    },
}


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


def detect_browser_ai():
    """Detect AI tools open in browser tabs (macOS only).

    Uses AppleScript to query Safari and Chrome for open tab URLs.
    Matches URLs against known AI domains.
    Returns list of detected browser AI tools.
    """
    if platform.system() != "Darwin":
        return []

    urls = []

    # Query Safari
    try:
        result = subprocess.run(
            ["osascript", "-e",
             'tell application "System Events" to get name of every process whose name is "Safari"'],
            capture_output=True, text=True, timeout=3,
        )
        if "Safari" in result.stdout:
            result = subprocess.run(
                ["osascript", "-e",
                 'tell application "Safari" to get URL of every tab of every window'],
            capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                urls.extend(result.stdout.strip().split(", "))
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    # Query Chrome
    try:
        result = subprocess.run(
            ["osascript", "-e",
             'tell application "System Events" to get name of every process whose name is "Google Chrome"'],
            capture_output=True, text=True, timeout=3,
        )
        if "Google Chrome" in result.stdout:
            result = subprocess.run(
                ["osascript", "-e",
                 'tell application "Google Chrome" to get URL of every tab of every window'],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                urls.extend(result.stdout.strip().split(", "))
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    detected = []
    seen = set()
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    for url in urls:
        url_lower = url.lower().strip()
        for tool_id, info in BROWSER_AI_DOMAINS.items():
            if tool_id in seen:
                continue
            for domain in info["domains"]:
                if domain in url_lower:
                    detected.append({
                        "tool_id": f"browser_{tool_id}",
                        "name": info["name"],
                        "vendor": info["vendor"],
                        "pid": 0,
                        "process_name": "browser",
                        "governable": info["governable"],
                        "method": info["method"],
                        "detected_at": now,
                        "source": "browser_tab",
                        "url_match": domain,
                    })
                    seen.add(tool_id)
                    break

    return detected


def detect_ai_tools():
    """Scan running processes and browser tabs for AI tools.

    Returns list of detected tools with governance status.
    Each tool appears at most once regardless of how many
    matching processes or tabs are found.
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

    # Also check browser tabs
    browser_tools = detect_browser_ai()
    for tool in browser_tools:
        if tool["tool_id"] not in seen:
            detected.append(tool)
            seen.add(tool["tool_id"])

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
