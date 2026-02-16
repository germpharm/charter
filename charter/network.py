"""Network layer — connect nodes, register expertise, discover connections.

A node is anything that generates observable data and can receive
economic units. The network is how nodes find each other.

Phase 2 starts local: your node exists on your machine.
The registry is a local manifest that can be shared or published
when you're ready to connect.

The goal: get from "you just told me this exists" to
"I can see my data has connections" with minimal friction.
"""

import json
import os
import time

from charter.identity import load_identity, append_to_chain


NETWORK_DIR = ".charter/network"


def get_network_dir():
    home = os.path.expanduser("~")
    return os.path.join(home, NETWORK_DIR)


def get_node_manifest_path():
    return os.path.join(get_network_dir(), "node.json")


def get_connections_path():
    return os.path.join(get_network_dir(), "connections.jsonl")


def get_contributions_path():
    return os.path.join(get_network_dir(), "contributions.jsonl")


def create_node(expertise=None, data_sources=None):
    """Create a network node for this identity.

    A node is the network representation of your identity.
    It declares what expertise you bring and what data sources
    you can connect.
    """
    identity = load_identity()
    if not identity:
        raise RuntimeError("No identity found. Run 'charter init' first.")

    net_dir = get_network_dir()
    os.makedirs(net_dir, exist_ok=True)

    node = {
        "version": "1.0",
        "public_id": identity["public_id"],
        "alias": identity["alias"],
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "expertise": expertise or [],
        "data_sources": data_sources or [],
        "connections": 0,
        "contributions": 0,
        "formation_contributors": [],
    }

    with open(get_node_manifest_path(), "w") as f:
        json.dump(node, f, indent=2)

    # Initialize connections file
    if not os.path.isfile(get_connections_path()):
        with open(get_connections_path(), "w") as f:
            pass  # Empty file

    # Initialize contributions file
    if not os.path.isfile(get_contributions_path()):
        with open(get_contributions_path(), "w") as f:
            pass  # Empty file

    append_to_chain("node_created", {
        "expertise": expertise or [],
        "data_sources": data_sources or [],
    })

    return node


def load_node():
    """Load the current node manifest."""
    path = get_node_manifest_path()
    if not os.path.isfile(path):
        return None
    with open(path) as f:
        return json.load(f)


def add_expertise(domain, description=None):
    """Register domain expertise on your node."""
    node = load_node()
    if not node:
        raise RuntimeError("No node found. Run 'charter connect' first.")

    entry = {
        "domain": domain,
        "description": description,
        "added_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    node["expertise"].append(entry)

    with open(get_node_manifest_path(), "w") as f:
        json.dump(node, f, indent=2)

    append_to_chain("expertise_added", {"domain": domain, "description": description})
    return entry


def add_data_source(name, source_type, connection_info=None):
    """Register a data source on your node.

    source_type: shopify, stripe, email, csv, api, foundry, etc.
    connection_info: how to reach it (URL, path, etc.)
    """
    node = load_node()
    if not node:
        raise RuntimeError("No node found. Run 'charter connect' first.")

    entry = {
        "name": name,
        "type": source_type,
        "connection_info": connection_info,
        "added_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "status": "registered",  # registered | connected | syncing | active
    }
    node["data_sources"].append(entry)

    with open(get_node_manifest_path(), "w") as f:
        json.dump(node, f, indent=2)

    append_to_chain("data_source_added", {"name": name, "type": source_type})
    return entry


def add_connection(peer_public_id, peer_alias=None, relationship=None):
    """Connect to another node on the network."""
    node = load_node()
    if not node:
        raise RuntimeError("No node found. Run 'charter connect' first.")

    connection = {
        "peer_id": peer_public_id,
        "peer_alias": peer_alias,
        "relationship": relationship,
        "connected_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    with open(get_connections_path(), "a") as f:
        f.write(json.dumps(connection) + "\n")

    node["connections"] += 1
    with open(get_node_manifest_path(), "w") as f:
        json.dump(node, f, indent=2)

    append_to_chain("connection_added", {
        "peer_id": peer_public_id,
        "peer_alias": peer_alias,
        "relationship": relationship,
    })

    return connection


def add_formation_contributor(name, contribution_type, description=None):
    """Register a formation contributor — someone who shaped you.

    contribution_type: capital | belief | challenge | knowledge | time | love
    """
    node = load_node()
    if not node:
        raise RuntimeError("No node found. Run 'charter connect' first.")

    entry = {
        "name": name,
        "contribution_type": contribution_type,
        "description": description,
        "recognized_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    node["formation_contributors"].append(entry)

    with open(get_node_manifest_path(), "w") as f:
        json.dump(node, f, indent=2)

    append_to_chain("formation_contributor_added", {
        "name": name,
        "contribution_type": contribution_type,
        "description": description,
    })

    return entry


def record_contribution(title, contribution_type, value=None, context=None):
    """Record a contribution to the network.

    This is the 99/1 model entry point. When you create something
    of value — governance rules, domain knowledge, a connection,
    a breakthrough — it gets recorded here.
    """
    identity = load_identity()
    if not identity:
        raise RuntimeError("No identity found.")

    contribution = {
        "title": title,
        "type": contribution_type,  # governance | knowledge | data | connection | breakthrough
        "value": value,
        "context": context,
        "contributor": identity["public_id"],
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    with open(get_contributions_path(), "a") as f:
        f.write(json.dumps(contribution) + "\n")

    # Update node contribution count
    node = load_node()
    if node:
        node["contributions"] += 1
        with open(get_node_manifest_path(), "w") as f:
            json.dump(node, f, indent=2)

    append_to_chain("contribution_recorded", {
        "title": title,
        "type": contribution_type,
    })

    return contribution


def run_connect(args):
    """CLI entry point for charter connect."""
    node = load_node()

    if args.action == "init":
        if node:
            print(f"Node already exists: {node['alias']} ({node['public_id'][:16]}...)")
            print(f"  Expertise: {len(node.get('expertise', []))} domains")
            print(f"  Data sources: {len(node.get('data_sources', []))} registered")
            print(f"  Connections: {node.get('connections', 0)}")
            return

        print("Creating your network node...\n")
        expertise = []
        print("What domains do you have expertise in?")
        print("(Enter one per line, empty line to finish)\n")

        while True:
            domain = input("  Domain: ").strip()
            if not domain:
                break
            desc = input("  Brief description: ").strip()
            expertise.append({"domain": domain, "description": desc or None,
                            "added_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})

        node = create_node(expertise=expertise)
        print(f"\nNode created: {node['alias']}")
        print(f"  Expertise: {len(expertise)} domains registered")
        print(f"\nNext steps:")
        print(f"  charter connect source <name> <type>   Register a data source")
        print(f"  charter connect peer <public_id>       Connect to another node")
        print(f"  charter connect formation <name>       Recognize a formation contributor")

    elif args.action == "status":
        if not node:
            print("No node found. Run 'charter connect init' first.")
            return
        print(f"Network Node: {node['alias']}")
        print(f"  Public ID:     {node['public_id'][:24]}...")
        print(f"  Created:       {node['created_at']}")
        print(f"  Expertise:     {len(node.get('expertise', []))} domains")
        for exp in node.get("expertise", []):
            desc = f" — {exp['description']}" if exp.get('description') else ""
            print(f"    - {exp['domain']}{desc}")
        print(f"  Data sources:  {len(node.get('data_sources', []))} registered")
        for ds in node.get("data_sources", []):
            print(f"    - {ds['name']} ({ds['type']}) [{ds.get('status', 'registered')}]")
        print(f"  Connections:   {node.get('connections', 0)}")
        print(f"  Contributions: {node.get('contributions', 0)}")
        if node.get("formation_contributors"):
            print(f"  Formation:     {len(node['formation_contributors'])} contributors recognized")
            for fc in node["formation_contributors"]:
                print(f"    - {fc['name']} ({fc['contribution_type']})")

    elif args.action == "source":
        if not node:
            print("No node found. Run 'charter connect init' first.")
            return
        if not args.name:
            print("Usage: charter connect source <name> <type>")
            print("  Types: shopify, stripe, email, csv, api, foundry, quickbooks")
            return
        source_type = args.extra or "api"
        entry = add_data_source(args.name, source_type)
        print(f"Data source registered: {entry['name']} ({entry['type']})")

    elif args.action == "formation":
        if not node:
            print("No node found. Run 'charter connect init' first.")
            return
        if not args.name:
            print("Usage: charter connect formation <name>")
            print("  Recognizes someone who shaped you.")
            return
        print(f"\nHow did {args.name} contribute to your formation?")
        print("  Types: capital, belief, challenge, knowledge, time, love")
        contrib_type = input("  Type: ").strip() or "belief"
        desc = input("  Description (optional): ").strip() or None
        entry = add_formation_contributor(args.name, contrib_type, desc)
        print(f"\nFormation contributor recognized: {entry['name']} ({entry['contribution_type']})")

    elif args.action == "contribute":
        if not node:
            print("No node found. Run 'charter connect init' first.")
            return
        if not args.name:
            print("Usage: charter connect contribute <title>")
            print("  Types: governance, knowledge, data, connection, breakthrough")
            return
        contrib_type = args.extra or "knowledge"
        entry = record_contribution(args.name, contrib_type)
        print(f"Contribution recorded: {entry['title']} ({entry['type']})")
