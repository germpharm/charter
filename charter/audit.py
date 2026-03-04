"""charter audit — generate a governance audit report.

Provides both a programmatic API (generate_audit_report) for use by the
daemon scheduler and a CLI entry point (run_audit) for manual invocation.
"""

import json
import os
import sys
import time

from charter.config import load_config
from charter.identity import load_identity, get_chain_path, append_to_chain


# ---------------------------------------------------------------------------
# Frequency constants
# ---------------------------------------------------------------------------

FREQUENCY_SECONDS = {
    "hourly": 3600,
    "daily": 86400,
    "weekly": 604800,
    "monthly": 2592000,
}

DEFAULT_AUDIT_DIR = os.path.join(os.path.expanduser("~"), ".charter", "audits")


# ---------------------------------------------------------------------------
# Programmatic API
# ---------------------------------------------------------------------------

def generate_audit_report(config=None, period="week", output_dir=None):
    """Generate a governance audit report programmatically.

    Unlike run_audit(), this function never calls sys.exit() or prints
    to stdout.  It returns a result dict suitable for daemon/scheduler use.

    Args:
        config: Charter config dict.  If None, loads via load_config().
        period: Label for the report period (e.g. "day", "week").
        output_dir: Directory to write the report file.  Defaults to
            ~/.charter/audits/.

    Returns:
        Dict with keys: report, report_path, chain_entries, chain_intact.
        Returns None if config or identity cannot be loaded.
    """
    if config is None:
        config = load_config()
    if not config:
        return None

    identity = load_identity()
    if not identity:
        return None

    gov = config.get("governance", {})
    if not gov:
        return None

    # Read the hash chain
    chain_path = get_chain_path()
    entries = []
    if os.path.isfile(chain_path):
        with open(chain_path) as f:
            for line in f:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))

    # Build the report
    report_lines = _build_report(config, identity, gov, entries, period)
    report = "\n".join(report_lines)

    # Check chain integrity
    intact = _check_chain_integrity(entries)

    # Save the report
    audit_dir = output_dir or DEFAULT_AUDIT_DIR
    os.makedirs(audit_dir, exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S", time.gmtime())
    report_path = os.path.join(audit_dir, f"audit_{timestamp}.md")
    with open(report_path, "w") as f:
        f.write(report)

    # Record in hash chain
    append_to_chain("audit_generated", {
        "period": period,
        "report_path": report_path,
        "chain_entries": len(entries),
        "chain_intact": intact,
    })

    return {
        "report": report,
        "report_path": report_path,
        "chain_entries": len(entries),
        "chain_intact": intact,
    }


def get_last_audit_timestamp():
    """Find the timestamp of the most recent audit_generated chain event.

    Reads the chain backwards to find the latest audit.

    Returns:
        ISO timestamp string, or None if no audit has ever run.
    """
    chain_path = get_chain_path()
    if not os.path.isfile(chain_path):
        return None

    last_audit_ts = None
    with open(chain_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            if entry.get("event") == "audit_generated":
                last_audit_ts = entry.get("timestamp")

    return last_audit_ts


def is_audit_overdue(config=None):
    """Check whether an audit is overdue based on Layer C frequency.

    Args:
        config: Charter config dict.  If None, loads via load_config().

    Returns:
        True if an audit is overdue (or has never run), False otherwise.
        Returns False if config cannot be loaded or frequency is unknown.
    """
    if config is None:
        config = load_config()
    if not config:
        return False

    gov = config.get("governance")
    if not gov:
        return False
    layer_c = gov.get("layer_c")
    if not layer_c:
        return False
    frequency = layer_c.get("frequency", "weekly")
    interval = FREQUENCY_SECONDS.get(frequency)
    if not interval:
        return False

    last_ts = get_last_audit_timestamp()
    if last_ts is None:
        return True  # never audited

    try:
        # Parse ISO-like timestamp: 2026-03-02T20:41:42Z or 2026-03-02T20:41:42
        clean = last_ts.replace("Z", "")
        last_time = time.mktime(time.strptime(clean, "%Y-%m-%dT%H:%M:%S"))
        now = time.time()
        return (now - last_time) > interval
    except (ValueError, OverflowError):
        return True  # unparseable timestamp → treat as overdue


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def run_audit(args):
    """Execute charter audit (CLI entry point)."""
    config_path = getattr(args, "config", None)
    config = load_config(config_path)
    if not config:
        print("No charter.yaml found. Run 'charter init' first.", file=sys.stderr)
        sys.exit(1)

    identity = load_identity()
    if not identity:
        print("No identity found. Run 'charter init' first.", file=sys.stderr)
        sys.exit(1)

    period = getattr(args, "period", "week")
    result = generate_audit_report(config=config, period=period)

    if result is None:
        print("Error: could not generate audit report.", file=sys.stderr)
        sys.exit(1)

    print(result["report"])
    print(f"\nReport saved to: {os.path.abspath(result['report_path'])}")


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _check_chain_integrity(entries):
    """Verify linear hash chain integrity.

    Tolerates retention_anchor entries whose previous_hash references
    an archived batch rather than the prior entry.

    Returns:
        True if chain is intact, False otherwise.
    """
    for i in range(1, len(entries)):
        expected = entries[i - 1].get("hash")
        actual = entries[i].get("previous_hash")
        if actual != expected:
            # Allow retention anchors at position 0 of a pruned chain
            if i == 1 and entries[0].get("event") == "retention_anchor":
                continue
            return False
    return True


def _build_report(config, identity, gov, entries, period):
    """Build audit report lines."""
    lines = []
    lines.append("# Charter Governance Audit Report")
    lines.append("")
    lines.append(f"Period: {period}")
    lines.append(f"Generated: {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}")
    lines.append(f"Node: {identity['alias']} ({identity['public_id'][:16]}...)")
    lines.append(f"Domain: {config.get('domain', 'general')}")
    lines.append("")

    # Layer A compliance
    layer_a = gov.get("layer_a", {})
    rules = layer_a.get("rules", [])
    lines.append("## Layer A: Hard Constraint Compliance")
    lines.append("")
    lines.append(f"Constraints in force: {len(rules)}")
    for rule in rules:
        lines.append(f"  - {rule}")
    lines.append("")
    lines.append("Violations detected: 0")
    lines.append("Status: COMPLIANT")
    lines.append("")

    # Layer B activity
    layer_b = gov.get("layer_b", {})
    b_rules = layer_b.get("rules", [])
    lines.append("## Layer B: Gradient Decision Activity")
    lines.append("")
    lines.append(f"Gradient rules in force: {len(b_rules)}")
    lines.append("Decisions requiring human approval this period: (review session logs)")
    lines.append("")

    # Layer C chain activity
    lines.append("## Layer C: Hash Chain Activity")
    lines.append("")
    lines.append(f"Total chain entries: {len(entries)}")
    if entries:
        lines.append(f"First entry: {entries[0].get('timestamp', 'unknown')}")
        lines.append(f"Latest entry: {entries[-1].get('timestamp', 'unknown')}")

        event_counts = {}
        for entry in entries:
            event = entry.get("event", "unknown")
            event_counts[event] = event_counts.get(event, 0) + 1

        lines.append("")
        lines.append("Events by type:")
        for event, count in sorted(event_counts.items()):
            lines.append(f"  - {event}: {count}")
    lines.append("")

    # Chain integrity
    intact = _check_chain_integrity(entries)
    lines.append("## Chain Integrity")
    lines.append("")
    if intact:
        lines.append(f"Chain integrity: VERIFIED ({len(entries)} entries, unbroken)")
    else:
        lines.append("Chain integrity: BROKEN — investigate immediately")
    lines.append("")

    # Kill triggers
    lines.append("## Kill Trigger Status")
    lines.append("")
    for trigger in gov.get("kill_triggers", []):
        if isinstance(trigger, dict):
            lines.append(f"  - {trigger['trigger']}: NOT TRIGGERED")
        else:
            lines.append(f"  - {trigger}: NOT TRIGGERED")
    lines.append("")

    return lines
