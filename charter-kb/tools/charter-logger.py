#!/usr/bin/env python3
"""Charter KB Logger — logs every KB operation to the immutable Charter hash chain."""

import json
import hashlib
import datetime
from pathlib import Path

CHAIN = Path.home() / ".charter" / "chain.jsonl"
CHAIN.parent.mkdir(parents=True, exist_ok=True)


def log_to_charter(action: str, wiki: str, summary: str = "", details: dict = None):
    """Log a KB operation to the Charter hash chain.

    Args:
        action: The operation type (e.g., 'index', 'compile', 'lint', 'ingest')
        wiki: The wiki/project name (e.g., 'germpharm', 'charter-governance')
        summary: Human-readable description of what happened
        details: Optional dict with additional structured data
    """
    if details is None:
        details = {}
    event = {
        "timestamp": datetime.datetime.now().isoformat(),
        "action": action,
        "wiki": wiki,
        "summary": summary,
        "details": details,
        "source": "charter-kb",
        "version": "v3.3",
    }
    event_str = json.dumps(event, sort_keys=True)
    event["hash"] = hashlib.sha256(event_str.encode()).hexdigest()
    with open(CHAIN, "a") as f:
        f.write(json.dumps(event) + "\n")
    print(f"Logged to Charter chain -> {action} | {wiki}")
    return event["hash"]


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print("Usage: charter-logger.py <action> <wiki> [summary]")
        sys.exit(1)
    action = sys.argv[1]
    wiki = sys.argv[2]
    summary = sys.argv[3] if len(sys.argv) > 3 else ""
    h = log_to_charter(action, wiki, summary)
    print(f"Hash: {h}")
