"""Cross-project reference resolution for Charter.

v3.1.1 Phase 3: References between projects use chain hashes,
not file paths. File paths change. Hashes don't.

A cross-reference has the format: project_hash:entry_hash
This uniquely identifies any chain entry across all projects.

Usage:
    from charter.cross_ref import resolve_ref, create_ref, search_across_projects

    ref = create_ref("abc123", "def456")  # project_hash:entry_hash
    entry = resolve_ref(ref)               # returns the chain entry
    results = search_across_projects(actor="human", since="2026-03-22")
"""

import json
import os

from charter.identity import (
    get_identity_dir,
    get_chain_path,
    get_project_chain_path,
    list_project_chains,
    append_to_chain,
)


def create_ref(project_hash, entry_hash):
    """Create a cross-project reference string.

    Format: project_hash:entry_hash
    Both can be full hashes or prefixes (minimum 8 chars).
    """
    return f"{project_hash}:{entry_hash}"


def parse_ref(ref_string):
    """Parse a cross-project reference into components.

    Args:
        ref_string: "project_hash:entry_hash" format

    Returns:
        tuple: (project_hash, entry_hash) or (None, None) if invalid
    """
    if ":" not in ref_string:
        return None, None
    parts = ref_string.split(":", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return None, None
    return parts[0], parts[1]


def _load_chain_file(chain_path):
    """Load all entries from a chain file."""
    if not os.path.isfile(chain_path):
        return []
    entries = []
    with open(chain_path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return entries


def resolve_ref(ref_string):
    """Resolve a cross-project reference to a chain entry.

    Args:
        ref_string: "project_hash:entry_hash" format

    Returns:
        dict: The chain entry, or None if not found
    """
    project_hash, entry_hash = parse_ref(ref_string)
    if not project_hash or not entry_hash:
        return None

    # Find the project chain
    chains_dir = os.path.join(get_identity_dir(), "chains")
    chain_path = None

    # Try exact match first, then prefix
    candidate = os.path.join(chains_dir, f"{project_hash}.jsonl")
    if os.path.isfile(candidate):
        chain_path = candidate
    else:
        # Prefix match
        if os.path.isdir(chains_dir):
            for filename in os.listdir(chains_dir):
                if filename.startswith(project_hash) and filename.endswith(".jsonl"):
                    chain_path = os.path.join(chains_dir, filename)
                    break

    # Also check global chain
    if chain_path is None:
        chain_path = get_chain_path()

    entries = _load_chain_file(chain_path)
    for entry in entries:
        h = entry.get("hash", "")
        if h == entry_hash or h.startswith(entry_hash):
            return entry

    return None


def search_across_projects(actor=None, event_type=None, since=None,
                           until=None, keyword=None, limit=50):
    """Search across all project chains and the global chain.

    Args:
        actor: Filter by actor type ("human", "ai", "collaborative")
        event_type: Filter by event type
        since: ISO 8601 start date (inclusive)
        until: ISO 8601 end date (inclusive)
        keyword: Search in event type and data description fields
        limit: Maximum results to return

    Returns:
        list of dicts, each with the entry plus a _source field
        indicating which project chain it came from.
    """
    results = []

    # Collect all chain paths: global + all projects
    chain_sources = [("global", get_chain_path())]
    for project in list_project_chains():
        chain_sources.append((
            project.get("project_name") or project["project_hash"][:12],
            project["chain_path"],
        ))

    for source_name, chain_path in chain_sources:
        entries = _load_chain_file(chain_path)

        for entry in entries:
            # Apply filters
            if actor and entry.get("actor") != actor:
                continue
            if event_type and entry.get("event") != event_type:
                continue
            ts = entry.get("timestamp", "")
            if since and ts < since:
                continue
            if until and ts > until:
                continue
            if keyword:
                # Search in event type and data fields
                match = False
                if keyword.lower() in entry.get("event", "").lower():
                    match = True
                data = entry.get("data", {})
                for val in data.values():
                    if isinstance(val, str) and keyword.lower() in val.lower():
                        match = True
                        break
                if not match:
                    continue

            # Add source info
            enriched = dict(entry)
            enriched["_source"] = source_name
            enriched["_chain_path"] = chain_path
            results.append(enriched)

            if len(results) >= limit:
                break

        if len(results) >= limit:
            break

    # Sort by timestamp descending (most recent first)
    results.sort(key=lambda e: e.get("timestamp", ""), reverse=True)
    return results[:limit]


def anchor_project_to_global(project_path):
    """Anchor a project chain's latest Merkle root to the global chain.

    This creates a cross-reference from the global chain to the project
    chain's current state, providing a cryptographic link between them.

    Args:
        project_path: Path to the project directory

    Returns:
        dict: The anchor entry, or None if failed
    """
    from charter.identity import get_project_hash
    from charter.merkle import load_batch_index

    project_hash = get_project_hash(project_path)
    project_chain = get_project_chain_path(project_path)

    if not os.path.isfile(project_chain):
        return None

    # Count entries in project chain
    entry_count = 0
    last_hash = None
    with open(project_chain) as f:
        for line in f:
            line = line.strip()
            if line:
                entry_count += 1
                try:
                    last_hash = json.loads(line).get("hash")
                except json.JSONDecodeError:
                    pass

    if not last_hash:
        return None

    # Record anchor in global chain
    return append_to_chain(
        "project_anchor",
        {
            "project_hash": project_hash,
            "project_path": os.path.abspath(project_path),
            "entry_count": entry_count,
            "latest_hash": last_hash,
            "cross_ref": create_ref(project_hash, last_hash),
        },
        actor="ai",
    )


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------

def run_cross_ref(args):
    """CLI entry point for cross-project operations."""
    action = getattr(args, "action", "search")

    if action == "resolve":
        ref = getattr(args, "ref", None)
        if not ref:
            print("Usage: charter xref resolve <project_hash:entry_hash>")
            return
        entry = resolve_ref(ref)
        if entry:
            print(json.dumps(entry, indent=2))
        else:
            print(f"Reference not found: {ref}")

    elif action == "search":
        actor = getattr(args, "actor", None)
        since = getattr(args, "since", None)
        keyword = getattr(args, "keyword", None)

        results = search_across_projects(
            actor=actor, since=since, keyword=keyword,
        )

        if not results:
            print("No entries found.")
            return

        print(f"Cross-project search: {len(results)} entries")
        print()
        for entry in results:
            source = entry.get("_source", "?")
            actor_sym = {"human": "H", "ai": "A", "collaborative": "H+A"}.get(
                entry.get("actor"), "?",
            )
            print(f"  [{actor_sym}] [{source}] {entry.get('timestamp', '')[:19]} {entry.get('event')}")
            data = entry.get("data", {})
            desc = data.get("description", data.get("message", ""))
            if desc:
                print(f"         {desc[:70]}")

    elif action == "projects":
        projects = list_project_chains()
        if not projects:
            print("No project chains found.")
            print("Use 'charter project register <path>' to register a project.")
            return

        print(f"Project Chains ({len(projects)}):")
        for p in projects:
            name = p.get("project_name") or "unnamed"
            print(f"  {name}")
            print(f"    Hash:    {p['project_hash'][:24]}...")
            print(f"    Entries: {p['entry_count']}")
            print(f"    Path:    {p['chain_path']}")

    elif action == "anchor":
        project_path = getattr(args, "path", None) or "."
        result = anchor_project_to_global(project_path)
        if result:
            print(f"Project anchored to global chain.")
            print(f"  Entry hash: {result['hash'][:24]}...")
            ref = result.get("data", {}).get("cross_ref", "")
            print(f"  Cross-ref:  {ref}")
        else:
            print("Failed to anchor. Is this a registered project?")

    else:
        print(f"Unknown action: {action}")
        print("Valid: resolve, search, projects, anchor")
