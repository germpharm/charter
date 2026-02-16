"""charter generate — convert governance config into AI-enforceable instructions."""

import os
import sys
import time

from charter.config import load_config
from charter.identity import append_to_chain


def render_claude_md(config):
    """Render governance config as a CLAUDE.md file."""
    gov = config["governance"]
    domain = config.get("domain", "general")
    identity = config.get("identity", {})

    lines = []
    lines.append(f"# Governance Layer — Charter v{config.get('version', '1.0')}")
    lines.append(f"")
    lines.append(f"Domain: {domain}")
    lines.append(f"Generated: {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}")
    if identity.get("alias"):
        lines.append(f"Node: {identity['alias']}")
    lines.append(f"")
    lines.append(f"This file defines the governance rules for AI agents in this project.")
    lines.append(f"These rules are mandatory. Follow them exactly as written.")
    lines.append(f"")

    # Layer A
    lines.append(f"## Layer A: Hard Constraints")
    lines.append(f"")
    lines.append(f"{gov['layer_a']['description']}")
    lines.append(f"You MUST comply with every rule below. No exceptions.")
    lines.append(f"")

    # Universal floor (accountability constraints, always present)
    universal = gov["layer_a"].get("universal", [])
    if universal:
        lines.append(f"### Universal (accountability floor)")
        lines.append(f"These constraints are structural. They cannot be removed.")
        lines.append(f"")
        for rule in universal:
            lines.append(f"- {rule}")
        lines.append(f"")

    # Domain rules (user-defined, the freedom layer)
    if gov["layer_a"].get("rules"):
        lines.append(f"### Domain Rules")
        lines.append(f"")
        for rule in gov["layer_a"]["rules"]:
            lines.append(f"- {rule}")
        lines.append(f"")

    # Layer B
    lines.append(f"## Layer B: Gradient Decisions")
    lines.append(f"")
    lines.append(f"{gov['layer_b']['description']}")
    lines.append(f"Before taking any of these actions, check the threshold and get approval if required.")
    lines.append(f"")
    for rule in gov["layer_b"]["rules"]:
        if isinstance(rule, dict):
            action = rule.get("action", "unknown")
            threshold = rule.get("threshold", rule.get("threshold_dollars", "N/A"))
            requires = rule.get("requires", "human_review")
            desc = rule.get("description", "")
            if "threshold_dollars" in rule:
                lines.append(f"- **{action}**: Transactions over ${threshold} require {requires}. {desc}")
            else:
                lines.append(f"- **{action}**: Threshold: {threshold}. Requires: {requires}. {desc}")
        else:
            lines.append(f"- {rule}")
    lines.append(f"")

    # Layer C
    lines.append(f"## Layer C: Self-Audit")
    lines.append(f"")
    lines.append(f"{gov['layer_c']['description']}")
    freq = gov["layer_c"]["frequency"]
    lines.append(f"Audit frequency: {freq}")
    lines.append(f"")
    lines.append(f"At the end of each {freq}, generate an audit report that includes:")
    for item in gov["layer_c"]["report_includes"]:
        lines.append(f"- {item.replace('_', ' ').title()}")
    lines.append(f"")
    lines.append(f"The audit report must be honest. If rules were bent or gray areas were navigated,")
    lines.append(f"report them transparently. The purpose of the audit is accountability, not perfection.")
    lines.append(f"")

    # Kill triggers
    if gov.get("kill_triggers"):
        lines.append(f"## Kill Triggers")
        lines.append(f"")
        lines.append(f"Immediately stop all work and alert the human operator if any of these occur:")
        lines.append(f"")
        for trigger in gov["kill_triggers"]:
            if isinstance(trigger, dict):
                lines.append(f"- **{trigger['trigger']}**: {trigger['description']}")
            else:
                lines.append(f"- {trigger}")
        lines.append(f"")

    return "\n".join(lines)


def render_system_prompt(config):
    """Render governance config as a system prompt for any AI."""
    gov = config["governance"]
    domain = config.get("domain", "general")

    lines = []
    lines.append(f"You are operating under a governance framework (Charter). Domain: {domain}.")
    lines.append(f"")
    lines.append(f"HARD CONSTRAINTS (never violate):")
    lines.append(f"")
    universal = gov["layer_a"].get("universal", [])
    if universal:
        lines.append(f"Universal (accountability floor):")
        for rule in universal:
            lines.append(f"- {rule}")
        lines.append(f"")
    if gov["layer_a"].get("rules"):
        lines.append(f"Domain rules:")
        for rule in gov["layer_a"]["rules"]:
            lines.append(f"- {rule}")
    lines.append(f"")

    lines.append(f"APPROVAL REQUIRED (check before acting):")
    for rule in gov["layer_b"]["rules"]:
        if isinstance(rule, dict):
            action = rule.get("action", "")
            desc = rule.get("description", "")
            lines.append(f"- {action}: {desc}")
        else:
            lines.append(f"- {rule}")
    lines.append(f"")

    lines.append(f"SELF-AUDIT: At the end of each {gov['layer_c']['frequency']}, report what you did and why.")
    lines.append(f"Be transparent about gray areas. Accountability, not perfection.")
    lines.append(f"")

    if gov.get("kill_triggers"):
        lines.append(f"KILL TRIGGERS (stop immediately and alert human):")
        for trigger in gov["kill_triggers"]:
            if isinstance(trigger, dict):
                lines.append(f"- {trigger['trigger']}: {trigger['description']}")
            else:
                lines.append(f"- {trigger}")

    return "\n".join(lines)


def render_raw(config):
    """Render governance rules as plain text."""
    import yaml
    return yaml.dump(config["governance"], default_flow_style=False, sort_keys=False)


def run_generate(args):
    """Execute charter generate."""
    config = load_config(args.config)
    if not config:
        print(f"No charter.yaml found. Run 'charter init' first.", file=sys.stderr)
        sys.exit(1)

    if args.format == "claude-md":
        content = render_claude_md(config)
        output_path = args.output or "CLAUDE.md"
        with open(output_path, "w") as f:
            f.write(content)
        print(f"Generated: {os.path.abspath(output_path)}")

        # Record in hash chain
        append_to_chain("governance_generated", {
            "format": "claude-md",
            "output": output_path,
            "domain": config.get("domain", "general"),
        })

    elif args.format == "system-prompt":
        content = render_system_prompt(config)
        if args.output:
            with open(args.output, "w") as f:
                f.write(content)
            print(f"Generated: {os.path.abspath(args.output)}")
        else:
            print(content)

        append_to_chain("governance_generated", {
            "format": "system-prompt",
            "domain": config.get("domain", "general"),
        })

    elif args.format == "raw":
        content = render_raw(config)
        if args.output:
            with open(args.output, "w") as f:
                f.write(content)
            print(f"Generated: {os.path.abspath(args.output)}")
        else:
            print(content)
