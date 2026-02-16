"""charter status — show current governance status."""

import json
import os
import sys

from charter.config import load_config, find_config
from charter.identity import load_identity, get_chain_path


def run_status(args):
    """Execute charter status."""
    config_path = find_config()
    identity = load_identity()

    print("Charter Governance Status")
    print("=" * 40)

    # Config
    if config_path:
        config = load_config(config_path)
        domain = config.get("domain", "unknown")
        gov = config.get("governance", {})
        layer_a_count = len(gov.get("layer_a", {}).get("rules", []))
        layer_b_count = len(gov.get("layer_b", {}).get("rules", []))
        frequency = gov.get("layer_c", {}).get("frequency", "unknown")
        triggers = len(gov.get("kill_triggers", []))

        print(f"  Config:      {config_path}")
        print(f"  Domain:      {domain}")
        print(f"  Layer A:     {layer_a_count} hard constraints")
        print(f"  Layer B:     {layer_b_count} gradient rules")
        print(f"  Layer C:     {frequency} audit")
        print(f"  Kill triggers: {triggers}")
    else:
        print(f"  Config:      not found (run 'charter init')")

    print()

    # Identity
    if identity:
        print(f"  Identity:    {identity['alias']}")
        print(f"  Public ID:   {identity['public_id'][:24]}...")
        print(f"  Created:     {identity['created_at']}")
        print(f"  Contributions: {identity.get('contributions', 0)}")
    else:
        print(f"  Identity:    not created (run 'charter init')")

    print()

    # Chain
    chain_path = get_chain_path()
    if os.path.isfile(chain_path):
        with open(chain_path) as f:
            lines = [l for l in f.readlines() if l.strip()]
        print(f"  Chain:       {len(lines)} entries")
        if lines:
            last = json.loads(lines[-1])
            print(f"  Last entry:  {last.get('event', 'unknown')} at {last.get('timestamp', 'unknown')}")

            # Verify integrity
            entries = [json.loads(l) for l in lines]
            intact = all(
                entries[i].get("previous_hash") == entries[i - 1].get("hash")
                for i in range(1, len(entries))
            )
            print(f"  Integrity:   {'VERIFIED' if intact else 'BROKEN'}")
    else:
        print(f"  Chain:       not initialized")
