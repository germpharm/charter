"""charter update — check for and install newer versions."""

import json
import subprocess
import sys
import urllib.request
import urllib.error

from charter import __version__


PYPI_URL = "https://pypi.org/pypi/charter-governance/json"


def check_latest_version():
    """Check PyPI for the latest version. Returns (latest, current) or (None, current)."""
    try:
        req = urllib.request.Request(PYPI_URL, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            latest = data.get("info", {}).get("version")
            return latest, __version__
    except (urllib.error.URLError, json.JSONDecodeError, OSError):
        return None, __version__


def version_tuple(v):
    """Convert version string to tuple for comparison."""
    try:
        return tuple(int(x) for x in v.split("."))
    except (ValueError, AttributeError):
        return (0, 0, 0)


def is_update_available():
    """Returns True if a newer version exists on PyPI."""
    latest, current = check_latest_version()
    if latest is None:
        return False
    return version_tuple(latest) > version_tuple(current)


def format_update_notice():
    """Returns a string with update info, or empty string if current."""
    latest, current = check_latest_version()
    if latest is None:
        return ""
    if version_tuple(latest) > version_tuple(current):
        return (
            f"  Update available: v{current} -> v{latest}\n"
            f"  Run 'charter update' to upgrade"
        )
    return ""


def run_update(args):
    """Execute charter update."""
    latest, current = check_latest_version()

    if latest is None:
        print("Could not check for updates. Check your internet connection.")
        return

    if version_tuple(latest) <= version_tuple(current):
        print(f"Charter v{current} is up to date.")
        return

    print(f"Update available: v{current} -> v{latest}")
    print()

    # Ask for confirmation
    try:
        answer = input("Install update? [Y/n] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\nUpdate cancelled.")
        return

    if answer and answer != "y":
        print("Update cancelled.")
        return

    print(f"\nUpgrading charter-governance to v{latest}...")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--upgrade", "charter-governance"],
        capture_output=True,
        text=True,
    )

    if result.returncode == 0:
        print(f"\nCharter updated to v{latest}.")
    else:
        print(f"\nUpdate failed:")
        print(result.stderr)
