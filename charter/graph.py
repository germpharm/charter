"""Charter Graph — DAG query engine over the hash chain.

v3.1.1: Every chain entry can carry graph edges that link it to other
entries. These edges are included in the hash computation, making
relationships immutable once signed.

Edge types:
    caused_by   — this entry exists because of that entry
    revision_of — this supersedes a prior entry
    input_to    — this entry fed into that entry
    part_of     — this entry belongs to a larger unit of work
    approved_by — human approved this AI action
"""

import json
import os
import time

from charter.identity import get_chain_path, append_to_chain


VALID_EDGE_TYPES = ("caused_by", "revision_of", "input_to", "part_of", "approved_by")


def load_chain():
    """Load all chain entries from disk."""
    chain_path = get_chain_path()
    if not os.path.isfile(chain_path):
        return []
    with open(chain_path) as f:
        return [json.loads(line) for line in f if line.strip()]


def validate_edges(edges, chain_entries=None):
    """Validate edge list. Each edge must have type and hash.

    Args:
        edges: list of {"type": str, "hash": str}
        chain_entries: optional list of chain entries for hash existence check

    Returns:
        dict: {"valid": bool, "errors": list}
    """
    if not isinstance(edges, list):
        return {"valid": False, "errors": ["_edges must be a list"]}

    errors = []
    known_hashes = set()
    if chain_entries:
        known_hashes = {e.get("hash") for e in chain_entries if e.get("hash")}

    for i, edge in enumerate(edges):
        if not isinstance(edge, dict):
            errors.append(f"Edge {i}: must be a dict")
            continue
        if "type" not in edge:
            errors.append(f"Edge {i}: missing 'type'")
        elif edge["type"] not in VALID_EDGE_TYPES:
            errors.append(f"Edge {i}: invalid type '{edge['type']}'. Valid: {VALID_EDGE_TYPES}")
        if "hash" not in edge:
            errors.append(f"Edge {i}: missing 'hash'")
        elif chain_entries and edge["hash"] not in known_hashes:
            errors.append(f"Edge {i}: referenced hash '{edge['hash'][:16]}...' not found in chain")

    return {"valid": len(errors) == 0, "errors": errors}


def get_entry_by_hash(entries, target_hash):
    """Find a chain entry by its hash (supports prefix matching)."""
    for entry in entries:
        h = entry.get("hash", "")
        if h == target_hash or h.startswith(target_hash):
            return entry
    return None


def get_edges_from(entries, source_hash):
    """Get all outgoing edges from an entry."""
    entry = get_entry_by_hash(entries, source_hash)
    if not entry:
        return []
    return entry.get("data", {}).get("_edges", []) or entry.get("_edges", [])


def get_edges_to(entries, target_hash):
    """Get all incoming edges pointing to an entry."""
    results = []
    for entry in entries:
        edges = entry.get("data", {}).get("_edges", []) or entry.get("_edges", [])
        for edge in edges:
            if edge.get("hash", "").startswith(target_hash):
                results.append({
                    "from_hash": entry.get("hash"),
                    "from_event": entry.get("event"),
                    "from_actor": entry.get("actor"),
                    "edge_type": edge["type"],
                    "from_timestamp": entry.get("timestamp"),
                })
    return results


def query_by_actor(entries, actor, since=None, until=None):
    """Query chain entries by actor with optional date range.

    Args:
        entries: list of chain entries
        actor: "human", "ai", or "collaborative"
        since: ISO timestamp string (inclusive)
        until: ISO timestamp string (inclusive)
    """
    results = []
    for entry in entries:
        if entry.get("actor") != actor:
            continue
        ts = entry.get("timestamp", "")
        if since and ts < since:
            continue
        if until and ts > until:
            continue
        results.append(entry)
    return results


def query_by_file(entries, filepath):
    """Query chain entries that reference a specific file."""
    results = []
    for entry in entries:
        data = entry.get("data", {})
        # Check common data fields where file paths appear
        for key in ("file", "path", "file_path", "files", "description"):
            val = data.get(key, "")
            if isinstance(val, str) and filepath in val:
                results.append(entry)
                break
            elif isinstance(val, list):
                for item in val:
                    if isinstance(item, str) and filepath in item:
                        results.append(entry)
                        break
    return results


def query_by_event(entries, event_type, since=None):
    """Query chain entries by event type."""
    results = []
    for entry in entries:
        if entry.get("event") != event_type:
            continue
        if since and entry.get("timestamp", "") < since:
            continue
        results.append(entry)
    return results


def get_provenance(entries, target_hash, max_depth=20):
    """Trace the full provenance of an entry by following caused_by edges backward.

    Returns a list of entries from the target back to the root cause.
    """
    chain = []
    visited = set()
    current_hash = target_hash

    for _ in range(max_depth):
        if current_hash in visited:
            break
        visited.add(current_hash)

        entry = get_entry_by_hash(entries, current_hash)
        if not entry:
            break
        chain.append(entry)

        # Follow caused_by edges backward
        edges = entry.get("data", {}).get("_edges", []) or entry.get("_edges", [])
        caused_by = [e for e in edges if e.get("type") == "caused_by"]
        if not caused_by:
            break
        current_hash = caused_by[0]["hash"]

    return chain


def get_sprint_graph(entries, sprint_hash=None, since=None):
    """Get all entries belonging to a sprint/work session.

    If sprint_hash provided, follows part_of edges.
    If since provided, returns all entries after that timestamp.
    """
    if sprint_hash:
        results = []
        for entry in entries:
            edges = entry.get("data", {}).get("_edges", []) or entry.get("_edges", [])
            for edge in edges:
                if edge.get("type") == "part_of" and edge.get("hash", "").startswith(sprint_hash):
                    results.append(entry)
                    break
        return results
    elif since:
        return [e for e in entries if e.get("timestamp", "") >= since]
    return entries


def attribution_summary(entries, since=None, until=None):
    """Generate an attribution summary: what % was human, ai, collaborative.

    Returns:
        dict with counts and percentages per actor type.
    """
    filtered = entries
    if since:
        filtered = [e for e in filtered if e.get("timestamp", "") >= since]
    if until:
        filtered = [e for e in filtered if e.get("timestamp", "") <= until]

    total = len(filtered)
    if total == 0:
        return {"total": 0, "human": 0, "ai": 0, "collaborative": 0}

    counts = {"human": 0, "ai": 0, "collaborative": 0}
    for entry in filtered:
        actor = entry.get("actor", "collaborative")
        if actor in counts:
            counts[actor] += 1

    return {
        "total": total,
        "human": counts["human"],
        "ai": counts["ai"],
        "collaborative": counts["collaborative"],
        "human_pct": round(counts["human"] / total * 100, 1),
        "ai_pct": round(counts["ai"] / total * 100, 1),
        "collaborative_pct": round(counts["collaborative"] / total * 100, 1),
    }


def to_mermaid(entries, max_entries=50):
    """Generate a Mermaid diagram from chain entries with edges.

    Returns a string containing a Mermaid flowchart.
    """
    if len(entries) > max_entries:
        entries = entries[-max_entries:]

    lines = ["graph TD"]

    # Build node map using short hash as ID
    for entry in entries:
        h = entry.get("hash", "")[:8]
        event = entry.get("event", "unknown")
        actor = entry.get("actor", "?")
        label = f"{event}\\n({actor})"

        # Style by actor
        if actor == "human":
            lines.append(f'    {h}["{label}"]:::human')
        elif actor == "ai":
            lines.append(f'    {h}["{label}"]:::ai')
        else:
            lines.append(f'    {h}["{label}"]:::collab')

    # Build edges
    for entry in entries:
        h = entry.get("hash", "")[:8]
        edges = entry.get("data", {}).get("_edges", []) or entry.get("_edges", [])
        for edge in edges:
            target_short = edge.get("hash", "")[:8]
            edge_type = edge.get("type", "")
            # Only draw if target is in our entry set
            target_hashes = {e.get("hash", "")[:8] for e in entries}
            if target_short in target_hashes:
                lines.append(f'    {h} -->|{edge_type}| {target_short}')

    # Style definitions
    lines.append('    classDef human fill:#4CAF50,stroke:#333,color:#fff')
    lines.append('    classDef ai fill:#2196F3,stroke:#333,color:#fff')
    lines.append('    classDef collab fill:#FF9800,stroke:#333,color:#fff')

    return "\n".join(lines)


def to_dot(entries, max_entries=50):
    """Generate a Graphviz DOT diagram from chain entries with edges.

    Returns a string containing DOT notation.
    """
    if len(entries) > max_entries:
        entries = entries[-max_entries:]

    lines = ['digraph charter {', '    rankdir=TB;', '    node [shape=box, style=filled];']

    actor_colors = {
        "human": "#4CAF50",
        "ai": "#2196F3",
        "collaborative": "#FF9800",
    }

    for entry in entries:
        h = entry.get("hash", "")[:8]
        event = entry.get("event", "unknown")
        actor = entry.get("actor", "?")
        color = actor_colors.get(actor, "#999999")
        label = f"{event}\\n({actor})"
        lines.append(f'    "{h}" [label="{label}", fillcolor="{color}", fontcolor="white"];')

    for entry in entries:
        h = entry.get("hash", "")[:8]
        edges = entry.get("data", {}).get("_edges", []) or entry.get("_edges", [])
        for edge in edges:
            target_short = edge.get("hash", "")[:8]
            edge_type = edge.get("type", "")
            target_hashes = {e.get("hash", "")[:8] for e in entries}
            if target_short in target_hashes:
                lines.append(f'    "{h}" -> "{target_short}" [label="{edge_type}"];')

    lines.append('}')
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def run_graph(args):
    """CLI entry point for charter graph."""
    entries = load_chain()

    if not entries:
        print("No chain entries found. Run 'charter init' first.")
        return

    action = getattr(args, "action", "summary")

    if action == "show":
        target = getattr(args, "target", None)
        if not target:
            print("Usage: charter graph show <hash>")
            return
        entry = get_entry_by_hash(entries, target)
        if not entry:
            print(f"Entry not found: {target}")
            return

        print(f"Chain Entry: {entry.get('hash', '')[:24]}...")
        print(f"  Event:     {entry.get('event')}")
        print(f"  Actor:     {entry.get('actor')}")
        print(f"  Time:      {entry.get('timestamp')}")
        print(f"  Index:     {entry.get('index')}")
        print()

        # Show outgoing edges
        out_edges = entry.get("data", {}).get("_edges", []) or entry.get("_edges", [])
        if out_edges:
            print(f"  Outgoing edges ({len(out_edges)}):")
            for edge in out_edges:
                ref = get_entry_by_hash(entries, edge["hash"])
                ref_desc = f"{ref['event']} ({ref['actor']})" if ref else "unknown"
                print(f"    {edge['type']} -> {edge['hash'][:16]}... [{ref_desc}]")

        # Show incoming edges
        incoming = get_edges_to(entries, entry.get("hash", ""))
        if incoming:
            print(f"  Incoming edges ({len(incoming)}):")
            for inc in incoming:
                print(f"    {inc['edge_type']} <- {inc['from_hash'][:16]}... [{inc['from_event']} ({inc['from_actor']})]")

    elif action == "actor":
        actor = getattr(args, "target", None)
        since = getattr(args, "since", None)
        if not actor or actor not in ("human", "ai", "collaborative"):
            print("Usage: charter graph actor <human|ai|collaborative> [--since YYYY-MM-DD]")
            return

        results = query_by_actor(entries, actor, since=since)
        print(f"Entries by '{actor}': {len(results)}")
        print()
        for entry in results[-20:]:  # Show last 20
            print(f"  [{entry.get('timestamp')}] {entry.get('event')} — {entry.get('hash', '')[:12]}...")
            data = entry.get("data", {})
            desc = data.get("description", data.get("file", data.get("message", "")))
            if desc:
                print(f"    {desc[:80]}")

    elif action == "file":
        filepath = getattr(args, "target", None)
        if not filepath:
            print("Usage: charter graph file <filepath>")
            return
        results = query_by_file(entries, filepath)
        print(f"Entries referencing '{filepath}': {len(results)}")
        print()
        for entry in results:
            print(f"  [{entry.get('timestamp')}] {entry.get('event')} ({entry.get('actor')}) — {entry.get('hash', '')[:12]}...")

    elif action == "provenance":
        target = getattr(args, "target", None)
        if not target:
            print("Usage: charter graph provenance <hash>")
            return
        chain = get_provenance(entries, target)
        if not chain:
            print(f"No provenance found for: {target}")
            return
        print(f"Provenance chain ({len(chain)} entries):")
        print()
        for i, entry in enumerate(chain):
            prefix = "  " if i > 0 else "> "
            indent = "  " * i
            print(f"{indent}{prefix}[{entry.get('timestamp')}] {entry.get('event')} ({entry.get('actor')})")
            print(f"{indent}  {entry.get('hash', '')[:24]}...")

    elif action == "summary":
        since = getattr(args, "since", None)
        summary = attribution_summary(entries, since=since)

        print(f"Attribution Summary")
        print(f"=" * 40)
        if since:
            print(f"  Since: {since}")
        print(f"  Total entries: {summary['total']}")
        print()
        print(f"  Human:         {summary['human']:>4} ({summary.get('human_pct', 0)}%)")
        print(f"  AI:            {summary['ai']:>4} ({summary.get('ai_pct', 0)}%)")
        print(f"  Collaborative: {summary['collaborative']:>4} ({summary.get('collaborative_pct', 0)}%)")

        # Show recent activity breakdown
        print()
        print("Recent Activity (last 10):")
        for entry in entries[-10:]:
            actor_sym = {"human": "H", "ai": "A", "collaborative": "H+A"}.get(entry.get("actor"), "?")
            print(f"  [{actor_sym}] {entry.get('timestamp', '')[:19]} {entry.get('event')}")

    elif action == "mermaid":
        since = getattr(args, "since", None)
        filtered = entries
        if since:
            filtered = [e for e in entries if e.get("timestamp", "") >= since]
        diagram = to_mermaid(filtered)
        print(diagram)

    elif action == "dot":
        since = getattr(args, "since", None)
        filtered = entries
        if since:
            filtered = [e for e in entries if e.get("timestamp", "") >= since]
        diagram = to_dot(filtered)
        print(diagram)

    else:
        print(f"Unknown graph action: {action}")
        print("Valid actions: show, actor, file, provenance, summary, mermaid, dot")
