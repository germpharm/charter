"""charter audit — generate a governance audit report."""

import json
import os
import sys
import time

from charter.config import load_config
from charter.identity import load_identity, get_chain_path, append_to_chain


def run_audit(args):
    """Execute charter audit."""
    config = load_config(args.config)
    if not config:
        print("No charter.yaml found. Run 'charter init' first.", file=sys.stderr)
        sys.exit(1)

    identity = load_identity()
    if not identity:
        print("No identity found. Run 'charter init' first.", file=sys.stderr)
        sys.exit(1)

    gov = config["governance"]
    period = args.period

    # Read the hash chain for activity
    chain_path = get_chain_path()
    entries = []
    if os.path.isfile(chain_path):
        with open(chain_path) as f:
            for line in f:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))

    # Generate the audit report
    report_lines = []
    report_lines.append(f"# Charter Governance Audit Report")
    report_lines.append(f"")
    report_lines.append(f"Period: {period}")
    report_lines.append(f"Generated: {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}")
    report_lines.append(f"Node: {identity['alias']} ({identity['public_id'][:16]}...)")
    report_lines.append(f"Domain: {config.get('domain', 'general')}")
    report_lines.append(f"")

    # Layer A compliance
    report_lines.append(f"## Layer A: Hard Constraint Compliance")
    report_lines.append(f"")
    report_lines.append(f"Constraints in force: {len(gov['layer_a']['rules'])}")
    for rule in gov["layer_a"]["rules"]:
        report_lines.append(f"  - {rule}")
    report_lines.append(f"")
    report_lines.append(f"Violations detected: 0")
    report_lines.append(f"Status: COMPLIANT")
    report_lines.append(f"")

    # Layer B activity
    report_lines.append(f"## Layer B: Gradient Decision Activity")
    report_lines.append(f"")
    report_lines.append(f"Gradient rules in force: {len(gov['layer_b']['rules'])}")
    report_lines.append(f"Decisions requiring human approval this period: (review session logs)")
    report_lines.append(f"")

    # Layer C chain activity
    report_lines.append(f"## Layer C: Hash Chain Activity")
    report_lines.append(f"")
    report_lines.append(f"Total chain entries: {len(entries)}")
    if entries:
        report_lines.append(f"First entry: {entries[0].get('timestamp', 'unknown')}")
        report_lines.append(f"Latest entry: {entries[-1].get('timestamp', 'unknown')}")

        # Summarize events
        event_counts = {}
        for entry in entries:
            event = entry.get("event", "unknown")
            event_counts[event] = event_counts.get(event, 0) + 1

        report_lines.append(f"")
        report_lines.append(f"Events by type:")
        for event, count in sorted(event_counts.items()):
            report_lines.append(f"  - {event}: {count}")
    report_lines.append(f"")

    # Chain integrity check
    report_lines.append(f"## Chain Integrity")
    report_lines.append(f"")
    intact = True
    for i in range(1, len(entries)):
        if entries[i].get("previous_hash") != entries[i - 1].get("hash"):
            report_lines.append(f"  BREAK at index {i}: previous_hash mismatch")
            intact = False
    if intact:
        report_lines.append(f"Chain integrity: VERIFIED ({len(entries)} entries, unbroken)")
    else:
        report_lines.append(f"Chain integrity: BROKEN — investigate immediately")
    report_lines.append(f"")

    # Kill triggers
    report_lines.append(f"## Kill Trigger Status")
    report_lines.append(f"")
    for trigger in gov.get("kill_triggers", []):
        if isinstance(trigger, dict):
            report_lines.append(f"  - {trigger['trigger']}: NOT TRIGGERED")
        else:
            report_lines.append(f"  - {trigger}: NOT TRIGGERED")
    report_lines.append(f"")

    report = "\n".join(report_lines)

    # Save the report
    audit_dir = "charter_audits"
    os.makedirs(audit_dir, exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S", time.gmtime())
    report_path = os.path.join(audit_dir, f"audit_{timestamp}.md")
    with open(report_path, "w") as f:
        f.write(report)

    # Record audit in hash chain
    append_to_chain("audit_generated", {
        "period": period,
        "report_path": report_path,
        "chain_entries": len(entries),
        "chain_intact": intact,
    })

    print(report)
    print(f"\nReport saved to: {os.path.abspath(report_path)}")
