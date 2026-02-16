"""Context management — separate work/personal knowledge boundaries.

A context is a governed space where knowledge lives. Each context has:
- Its own governance rules (org sets work rules, you set personal rules)
- Its own data boundary (what's visible, what's not)
- Its own hash chain entries (work stays at work, personal stays personal)

The same person can have multiple contexts. Knowledge does NOT flow
between contexts by default. This is the security boundary.

Future: governed bridging allows controlled knowledge transfer
between contexts when both parties (person + org) consent.
"""

import hashlib
import json
import os
import time

from charter.config import load_config, save_config
from charter.identity import load_identity, append_to_chain


CONTEXTS_DIR = ".charter/contexts"


def get_contexts_dir():
    home = os.path.expanduser("~")
    return os.path.join(home, CONTEXTS_DIR)


def list_contexts():
    """List all contexts for the current identity."""
    ctx_dir = get_contexts_dir()
    if not os.path.isdir(ctx_dir):
        return []
    contexts = []
    for name in sorted(os.listdir(ctx_dir)):
        meta_path = os.path.join(ctx_dir, name, "context.json")
        if os.path.isfile(meta_path):
            with open(meta_path) as f:
                meta = json.load(f)
            meta["name"] = name
            contexts.append(meta)
    return contexts


def create_context(name, context_type="personal", org_name=None, work_email=None):
    """Create a new context.

    context_type: 'personal' or 'work'
    For work contexts, org_name and work_email establish the org link.
    The work email is the initial crosswalk — it connects the person
    to everything in that organization's systems.
    """
    identity = load_identity()
    if not identity:
        raise RuntimeError("No identity found. Run init first.")

    ctx_dir = os.path.join(get_contexts_dir(), name)
    os.makedirs(ctx_dir, exist_ok=True)

    meta = {
        "name": name,
        "type": context_type,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "identity": identity["public_id"],
        "org_name": org_name,
        "work_email": work_email,
        "verified": False,  # True after ID.me or org HR verification
        "bridging": {
            "enabled": False,  # No cross-context knowledge flow by default
            "policy": "isolated",  # isolated | read-only | bidirectional
            "requires_approval": True,
        },
        "governance_config": None,  # Path to context-specific charter.yaml
    }

    meta_path = os.path.join(ctx_dir, "context.json")
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)

    # Create context-specific hash chain
    chain_path = os.path.join(ctx_dir, "chain.jsonl")
    genesis = {
        "index": 0,
        "timestamp": meta["created_at"],
        "event": "context_created",
        "data": {
            "name": name,
            "type": context_type,
            "org_name": org_name,
        },
        "previous_hash": "0" * 64,
    }
    import hashlib
    content = json.dumps(
        {k: v for k, v in genesis.items() if k != "hash"},
        sort_keys=True, separators=(",", ":"),
    )
    genesis["hash"] = hashlib.sha256(content.encode()).hexdigest()

    with open(chain_path, "w") as f:
        f.write(json.dumps(genesis) + "\n")

    # Record in main identity chain
    append_to_chain("context_created", {
        "context": name,
        "type": context_type,
        "org_name": org_name,
    })

    return meta


def get_context(name):
    """Load a specific context."""
    meta_path = os.path.join(get_contexts_dir(), name, "context.json")
    if not os.path.isfile(meta_path):
        return None
    with open(meta_path) as f:
        return json.load(f)


def set_active_context(name):
    """Set the active context for the current session."""
    ctx = get_context(name)
    if not ctx:
        raise RuntimeError(f"Context '{name}' not found.")

    active_path = os.path.join(get_contexts_dir(), ".active")
    with open(active_path, "w") as f:
        f.write(name)

    return ctx


def get_active_context():
    """Get the currently active context name."""
    active_path = os.path.join(get_contexts_dir(), ".active")
    if not os.path.isfile(active_path):
        return None
    with open(active_path) as f:
        return f.read().strip()


def propose_bridge(source_name, target_name, policy="read-only", items=None):
    """Propose a governed bridge between two contexts.

    A bridge allows controlled knowledge flow between contexts.
    Both parties must consent. The bridge request is recorded
    in both context chains.

    Policies:
        isolated:      No knowledge flows (default, bridge disabled)
        read-only:     Target can read from source, not write
        bidirectional: Both contexts can read from each other
        items-only:    Only specific named items can cross

    This is the security boundary. The org can't see your personal
    knowledge unless you propose a bridge AND the org approves it.
    You can't see org data unless the org proposes and you approve.
    """
    source = get_context(source_name)
    target = get_context(target_name)
    if not source:
        raise RuntimeError(f"Source context '{source_name}' not found.")
    if not target:
        raise RuntimeError(f"Target context '{target_name}' not found.")

    bridge_request = {
        "bridge_id": hashlib.sha256(
            f"{source_name}:{target_name}:{time.time_ns()}".encode()
        ).hexdigest()[:16],
        "source": source_name,
        "target": target_name,
        "policy": policy,
        "items": items,  # None = all (subject to policy), or list of specific items
        "proposed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "proposed_by": source_name,
        "status": "pending",  # pending | approved | denied | revoked
        "approved_at": None,
        "approved_by": None,
    }

    # Save the bridge request
    bridges_dir = os.path.join(get_contexts_dir(), ".bridges")
    os.makedirs(bridges_dir, exist_ok=True)
    bridge_path = os.path.join(bridges_dir, f"{bridge_request['bridge_id']}.json")
    with open(bridge_path, "w") as f:
        json.dump(bridge_request, f, indent=2)

    # Record in main chain
    append_to_chain("bridge_proposed", {
        "bridge_id": bridge_request["bridge_id"],
        "source": source_name,
        "target": target_name,
        "policy": policy,
    })

    return bridge_request


def approve_bridge(bridge_id, approver_context):
    """Approve a pending bridge request.

    The approver is the TARGET context — the one receiving knowledge.
    Both parties must consent for knowledge to flow.
    """
    bridges_dir = os.path.join(get_contexts_dir(), ".bridges")
    bridge_path = os.path.join(bridges_dir, f"{bridge_id}.json")

    if not os.path.isfile(bridge_path):
        raise RuntimeError(f"Bridge '{bridge_id}' not found.")

    with open(bridge_path) as f:
        bridge = json.load(f)

    if bridge["status"] != "pending":
        raise RuntimeError(f"Bridge is already {bridge['status']}.")

    bridge["status"] = "approved"
    bridge["approved_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    bridge["approved_by"] = approver_context

    with open(bridge_path, "w") as f:
        json.dump(bridge, f, indent=2)

    # Update both context metadata
    source = get_context(bridge["source"])
    target = get_context(bridge["target"])

    if source:
        source["bridging"]["enabled"] = True
        source["bridging"]["policy"] = bridge["policy"]
        source_path = os.path.join(get_contexts_dir(), bridge["source"], "context.json")
        with open(source_path, "w") as f:
            json.dump(source, f, indent=2)

    if target:
        target["bridging"]["enabled"] = True
        target["bridging"]["policy"] = bridge["policy"]
        target_path = os.path.join(get_contexts_dir(), bridge["target"], "context.json")
        with open(target_path, "w") as f:
            json.dump(target, f, indent=2)

    # Record approval in chain
    append_to_chain("bridge_approved", {
        "bridge_id": bridge_id,
        "source": bridge["source"],
        "target": bridge["target"],
        "policy": bridge["policy"],
        "approved_by": approver_context,
    })

    return bridge


def revoke_bridge(bridge_id, revoker_context):
    """Revoke an active bridge. Either party can revoke at any time."""
    bridges_dir = os.path.join(get_contexts_dir(), ".bridges")
    bridge_path = os.path.join(bridges_dir, f"{bridge_id}.json")

    if not os.path.isfile(bridge_path):
        raise RuntimeError(f"Bridge '{bridge_id}' not found.")

    with open(bridge_path) as f:
        bridge = json.load(f)

    bridge["status"] = "revoked"
    bridge["revoked_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    bridge["revoked_by"] = revoker_context

    with open(bridge_path, "w") as f:
        json.dump(bridge, f, indent=2)

    # Reset both contexts to isolated
    for ctx_name in [bridge["source"], bridge["target"]]:
        ctx = get_context(ctx_name)
        if ctx:
            ctx["bridging"]["enabled"] = False
            ctx["bridging"]["policy"] = "isolated"
            ctx_path = os.path.join(get_contexts_dir(), ctx_name, "context.json")
            with open(ctx_path, "w") as f:
                json.dump(ctx, f, indent=2)

    append_to_chain("bridge_revoked", {
        "bridge_id": bridge_id,
        "revoked_by": revoker_context,
    })

    return bridge


def list_bridges():
    """List all bridge requests."""
    bridges_dir = os.path.join(get_contexts_dir(), ".bridges")
    if not os.path.isdir(bridges_dir):
        return []
    bridges = []
    for f in sorted(os.listdir(bridges_dir)):
        if f.endswith(".json"):
            with open(os.path.join(bridges_dir, f)) as fh:
                bridges.append(json.load(fh))
    return bridges


def run_context(args):
    """CLI entry point for context management."""
    if args.action == "list":
        contexts = list_contexts()
        if not contexts:
            print("No contexts created. Use 'charter context create <name>' to start.")
            return
        active = get_active_context()
        print("Contexts:\n")
        for ctx in contexts:
            marker = " *" if ctx["name"] == active else "  "
            ctx_type = ctx.get("type", "personal")
            org = f" ({ctx.get('org_name', '')})" if ctx.get("org_name") else ""
            verified = " [verified]" if ctx.get("verified") else ""
            bridging = ctx.get("bridging", {}).get("policy", "isolated")
            print(f"{marker} {ctx['name']} — {ctx_type}{org}{verified} [bridging: {bridging}]")
        print()
        if active:
            print(f"Active context: {active}")

    elif args.action == "create":
        if not args.name:
            print("Usage: charter context create <name> [--type work] [--org 'Org Name'] [--email you@work.com]")
            return
        ctx_type = args.type or "personal"
        meta = create_context(
            name=args.name,
            context_type=ctx_type,
            org_name=args.org,
            work_email=args.email,
        )
        print(f"Context created: {meta['name']} ({meta['type']})")
        if meta.get("org_name"):
            print(f"  Organization: {meta['org_name']}")
        if meta.get("work_email"):
            print(f"  Work email: {meta['work_email']}")
        print(f"\n  Bridging: DISABLED (isolated by default)")
        print(f"  Verified: No")
        print(f"\n  Knowledge in this context stays in this context.")
        print(f"  Use 'charter context switch {args.name}' to activate.")

    elif args.action == "switch":
        if not args.name:
            print("Usage: charter context switch <name>")
            return
        ctx = set_active_context(args.name)
        print(f"Switched to context: {args.name} ({ctx.get('type', 'personal')})")

    elif args.action == "show":
        name = args.name or get_active_context()
        if not name:
            print("No active context. Use 'charter context list' to see available contexts.")
            return
        ctx = get_context(name)
        if not ctx:
            print(f"Context '{name}' not found.")
            return
        print(f"Context: {ctx.get('name', name)}")
        print(f"  Type:         {ctx.get('type', 'personal')}")
        print(f"  Organization: {ctx.get('org_name', 'none')}")
        print(f"  Work email:   {ctx.get('work_email', 'none')}")
        print(f"  Verified:     {ctx.get('verified', False)}")
        print(f"  Created:      {ctx.get('created_at', 'unknown')}")
        bridging = ctx.get("bridging", {})
        print(f"  Bridging:     {bridging.get('policy', 'isolated')}")
        if bridging.get("enabled"):
            print(f"  Bridge approval required: {bridging.get('requires_approval', True)}")

    elif args.action == "bridge":
        if not args.name:
            # Show all bridges
            bridges = list_bridges()
            if not bridges:
                print("No bridges. Use 'charter context bridge <source> --target <target>' to propose one.")
                return
            print("Bridges:\n")
            for b in bridges:
                status_icon = {
                    "pending": "?",
                    "approved": "+",
                    "denied": "x",
                    "revoked": "-",
                }.get(b["status"], "?")
                print(f"  [{status_icon}] {b['bridge_id']}: {b['source']} -> {b['target']} ({b['policy']}) [{b['status']}]")
            return

        source = args.name
        target = getattr(args, "target", None)

        if not target:
            print("Usage: charter context bridge <source> --target <target> [--policy read-only]")
            print("  Policies: read-only, bidirectional, items-only")
            return

        policy = getattr(args, "policy", None) or "read-only"
        bridge = propose_bridge(source, target, policy=policy)
        print(f"Bridge proposed: {bridge['bridge_id']}")
        print(f"  {bridge['source']} -> {bridge['target']}")
        print(f"  Policy: {bridge['policy']}")
        print(f"  Status: PENDING")
        print(f"\n  The target context must approve this bridge.")
        print(f"  Use 'charter context approve {bridge['bridge_id']}' to approve.")

    elif args.action == "approve":
        if not args.name:
            print("Usage: charter context approve <bridge_id>")
            return
        active = get_active_context()
        if not active:
            print("No active context. Switch to the approving context first.")
            return
        bridge = approve_bridge(args.name, active)
        print(f"Bridge approved: {bridge['bridge_id']}")
        print(f"  {bridge['source']} -> {bridge['target']}")
        print(f"  Policy: {bridge['policy']}")
        print(f"  Approved by: {active}")
        print(f"\n  Knowledge can now flow according to the {bridge['policy']} policy.")
        print(f"  Either party can revoke at any time with 'charter context revoke {bridge['bridge_id']}'")

    elif args.action == "revoke":
        if not args.name:
            print("Usage: charter context revoke <bridge_id>")
            return
        active = get_active_context()
        if not active:
            print("No active context.")
            return
        bridge = revoke_bridge(args.name, active)
        print(f"Bridge revoked: {bridge['bridge_id']}")
        print(f"  {bridge['source']} -> {bridge['target']}")
        print(f"  Revoked by: {active}")
        print(f"  Both contexts are now isolated.")
