"""charter init — create a governance config for your project."""

import os
import sys
import yaml

from charter.config import save_config, CONFIG_NAME
from charter.identity import create_identity, load_identity


DOMAINS = ["healthcare", "finance", "education", "general"]


def load_template(domain):
    """Load a domain template from the templates directory."""
    templates_dir = os.path.join(os.path.dirname(__file__), "templates")
    path = os.path.join(templates_dir, f"{domain}.yaml")
    if not os.path.isfile(path):
        path = os.path.join(templates_dir, "default.yaml")
    with open(path) as f:
        return yaml.safe_load(f)


def prompt_domain():
    """Ask the user what domain they work in."""
    print("\nWhat domain does this project serve?\n")
    for i, d in enumerate(DOMAINS, 1):
        print(f"  {i}. {d}")
    print()

    while True:
        choice = input("Enter number (1-4): ").strip()
        if choice in ("1", "2", "3", "4"):
            return DOMAINS[int(choice) - 1]
        print("Please enter 1, 2, 3, or 4.")


def prompt_customize(config):
    """Let user review and customize the governance rules."""
    print("\n--- Layer A: Hard Constraints ---")

    # Show universal floor (not editable)
    universal = config["governance"]["layer_a"].get("universal", [])
    if universal:
        print("\nUniversal (accountability floor — cannot be removed):\n")
        for i, rule in enumerate(universal, 1):
            print(f"  {i}. {rule}")

    # Show domain rules (editable)
    print("\nDomain rules (your constraints):\n")
    for i, rule in enumerate(config["governance"]["layer_a"]["rules"], 1):
        print(f"  {i}. {rule}")

    print()
    edit = input("Add a constraint? (enter text, or press Enter to continue): ").strip()
    while edit:
        config["governance"]["layer_a"]["rules"].append(edit)
        print(f"  Added: {edit}")
        edit = input("Add another? (enter text, or press Enter to continue): ").strip()

    print("\n--- Layer B: Gradient Decisions ---")
    print("Actions that require human judgment:\n")
    for rule in config["governance"]["layer_b"]["rules"]:
        desc = rule.get("description", rule.get("action", ""))
        print(f"  - {desc}")

    print()
    print("--- Layer C: Self-Audit ---")
    freq = config["governance"]["layer_c"]["frequency"]
    print(f"  Audit frequency: {freq}")

    change = input(f"\nChange audit frequency? (daily/weekly/monthly, or Enter for {freq}): ").strip()
    if change in ("daily", "weekly", "monthly"):
        config["governance"]["layer_c"]["frequency"] = change

    return config


def prompt_alias():
    """Ask for a node alias."""
    alias = input("\nChoose an alias for this node (or press Enter for auto): ").strip()
    return alias if alias else None


def run_init(args):
    """Execute charter init."""
    # Check if config already exists
    if os.path.isfile(CONFIG_NAME):
        overwrite = input(f"{CONFIG_NAME} already exists. Overwrite? (y/N): ").strip().lower()
        if overwrite != "y":
            print("Aborted.")
            return

    print("Charter — AI Governance Layer")
    print("=" * 40)

    # Domain selection
    if args.domain:
        domain = args.domain
    elif args.non_interactive:
        domain = "general"
    else:
        domain = prompt_domain()

    # Load template
    config = load_template(domain)
    config["version"] = "1.0"

    # Customize if interactive
    if not args.non_interactive:
        config = prompt_customize(config)

    # Identity
    identity = load_identity()
    if identity:
        print(f"\nExisting identity found: {identity['alias']} ({identity['public_id'][:16]}...)")
        config["identity"] = {
            "public_id": identity["public_id"],
            "alias": identity["alias"],
        }
    else:
        alias = None if args.non_interactive else prompt_alias()
        identity = create_identity(alias=alias)
        print(f"\nIdentity created: {identity['alias']} ({identity['public_id'][:16]}...)")
        config["identity"] = {
            "public_id": identity["public_id"],
            "alias": identity["alias"],
        }

    # Save config
    path = save_config(config)
    print(f"\nGovernance config saved to: {path}")
    print(f"\nNext steps:")
    print(f"  charter generate          Generate a CLAUDE.md with your governance rules")
    print(f"  charter generate --format system-prompt   Generate a system prompt for any AI")
    print(f"  charter audit             Run a governance audit")
    print(f"  charter identity          View your identity")
