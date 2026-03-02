"""Federated Governance — Italian cooperative model for Charter v3.0.0.

Each Charter node operates independently with its own hash chain, identity,
and governance rules. This module implements federated reads across multiple
Charter nodes via their MCP SSE endpoints.

The design follows the Italian cooperative model:
  - Each node is sovereign. It owns its data, its chain, its rules.
  - The federation is a read-only aggregation layer.
  - No data centralization: we query nodes, we don't store their data.
  - Enterprise visibility without enterprise data lakes.
  - Any node can join or leave the federation at any time.

A Federation queries remote Charter nodes at their MCP SSE base URLs
(e.g., http://host:8375) to aggregate governance state, verify chain
integrity across the network, and merge event streams for unified
operational awareness.

Config lives at ~/.charter/federation.yaml. Each node entry contains a
node_id (SHA-256 public identity), an SSE URL, and an optional alias.

Usage:
    charter federation status      — aggregated governance view
    charter federation add         — register a remote node
    charter federation remove      — deregister a node
    charter federation events      — merged event stream across all nodes
"""

import json
import os
import time
import urllib.request
import urllib.error

import yaml

from charter.identity import append_to_chain


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CHARTER_DIR = ".charter"
FEDERATION_FILE = "federation.yaml"
DEFAULT_TIMEOUT = 10  # seconds for HTTP requests


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _default_config_path():
    """Return the default federation config path: ~/.charter/federation.yaml."""
    home = os.path.expanduser("~")
    return os.path.join(home, CHARTER_DIR, FEDERATION_FILE)


def _base_url_from_sse(sse_url):
    """Derive the base URL from an SSE URL by stripping the /sse suffix.

    Example:
        http://100.95.120.54:8375/sse  ->  http://100.95.120.54:8375
        http://localhost:8375/sse       ->  http://localhost:8375
        http://host:8375               ->  http://host:8375  (unchanged)
    """
    if sse_url.endswith("/sse"):
        return sse_url[:-4]
    return sse_url.rstrip("/")


def _http_get_json(url, timeout=DEFAULT_TIMEOUT):
    """Perform an HTTP GET and parse the response as JSON.

    Returns the parsed dict on success, None on any failure.
    All network errors are caught — federation must be resilient
    to nodes being unreachable.
    """
    try:
        req = urllib.request.Request(url, method="GET")
        req.add_header("Accept", "application/json")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body)
    except (urllib.error.URLError, urllib.error.HTTPError,
            json.JSONDecodeError, OSError, ValueError):
        return None


def _timestamp_now():
    """Return an ISO 8601 UTC timestamp string."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ---------------------------------------------------------------------------
# FederationNode
# ---------------------------------------------------------------------------

class FederationNode:
    """Represents a remote Charter node in the federation.

    Each node has a public identity (node_id), an SSE URL where its
    MCP server is reachable, and an optional human-readable alias.
    The node object tracks reachability and caches the last known status.
    """

    def __init__(self, node_id, sse_url, alias=None):
        self.node_id = node_id
        self.sse_url = sse_url
        self.alias = alias or f"node-{node_id[:8]}"
        self.last_status = None
        self.last_checked = None
        self.reachable = False

    def _base_url(self):
        """Get the base URL for this node's HTTP endpoints."""
        return _base_url_from_sse(self.sse_url)

    def check_health(self):
        """Check if the node is reachable via its health endpoint.

        GET <base_url>/health

        Updates self.reachable, self.last_checked, and self.last_status.
        Returns True if the node responded, False otherwise.
        """
        self.last_checked = _timestamp_now()
        url = f"{self._base_url()}/health"
        result = _http_get_json(url)

        if result is not None:
            self.reachable = True
            self.last_status = result
            return True

        self.reachable = False
        self.last_status = None
        return False

    def get_status(self):
        """Get the governance status from this node.

        Calls the health endpoint and returns the parsed status dict.
        Returns None if the node is unreachable.
        """
        self.check_health()
        if not self.reachable or self.last_status is None:
            return None

        # The health endpoint returns {"status": "ok", "charter": {...}}.
        # The governance data is under the "charter" key.
        # Fall back to the top-level response if "charter" isn't present.
        if "charter" in self.last_status and isinstance(self.last_status["charter"], dict):
            return self.last_status["charter"]
        return self.last_status

    def get_chain_summary(self):
        """Get a summary of recent chain entries from this node.

        GET <base_url>/api/chain?limit=5

        Returns a dict with chain info, or None if unreachable.
        """
        url = f"{self._base_url()}/api/chain?limit=5"
        result = _http_get_json(url)
        if result is None:
            return None

        # Normalize the response into a consistent shape
        summary = {
            "node_id": self.node_id,
            "alias": self.alias,
            "entries": result.get("entries", []),
            "total": result.get("total", 0),
            "intact": result.get("intact", None),
        }
        return summary

    def to_dict(self):
        """Serialize this node for config storage."""
        d = {
            "node_id": self.node_id,
            "sse_url": self.sse_url,
        }
        if self.alias and self.alias != f"node-{self.node_id[:8]}":
            d["alias"] = self.alias
        return d

    def __repr__(self):
        status = "reachable" if self.reachable else "unreachable"
        return f"<FederationNode {self.alias} ({status})>"


# ---------------------------------------------------------------------------
# Federation
# ---------------------------------------------------------------------------

class Federation:
    """Manage a collection of federated Charter nodes.

    The federation is a read-only aggregation layer. It queries remote
    nodes, merges their governance state, and presents a unified view.
    No remote data is persisted locally beyond the node registry.

    Config format (~/.charter/federation.yaml):

        federation:
          name: "My Organization"
          nodes:
            - node_id: "abc123..."
              alias: "production-1"
              sse_url: "http://100.95.120.54:8375/sse"
            - node_id: "def456..."
              alias: "staging"
              sse_url: "http://localhost:8375/sse"
    """

    def __init__(self, config_path=None):
        self.config_path = config_path or _default_config_path()
        self.name = "Charter Federation"
        self.nodes = []
        self._load_config()

    def _load_config(self):
        """Load federation config from YAML file.

        If the config file doesn't exist, start with an empty node list.
        Malformed entries are silently skipped.
        """
        if not os.path.isfile(self.config_path):
            self.nodes = []
            return

        try:
            with open(self.config_path) as f:
                data = yaml.safe_load(f) or {}
        except (yaml.YAMLError, OSError):
            self.nodes = []
            return

        fed_config = data.get("federation", {})
        self.name = fed_config.get("name", self.name)

        self.nodes = []
        for entry in fed_config.get("nodes", []):
            node_id = entry.get("node_id")
            sse_url = entry.get("sse_url")
            if not node_id or not sse_url:
                continue  # skip malformed entries
            alias = entry.get("alias")
            self.nodes.append(FederationNode(node_id, sse_url, alias))

    def _save_config(self):
        """Save the current node list back to federation.yaml.

        Creates the parent directory if it doesn't exist.
        """
        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)

        data = {
            "federation": {
                "name": self.name,
                "nodes": [node.to_dict() for node in self.nodes],
            }
        }

        with open(self.config_path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    def add_node(self, node_id, sse_url, alias=None):
        """Add a remote Charter node to the federation.

        Prevents duplicate node_ids. Logs `federation_node_added` to
        the local hash chain for audit.

        Returns the newly created FederationNode.
        """
        # Check for duplicates
        for existing in self.nodes:
            if existing.node_id == node_id:
                raise ValueError(
                    f"Node {node_id[:16]}... already in federation "
                    f"as '{existing.alias}'"
                )

        node = FederationNode(node_id, sse_url, alias)
        self.nodes.append(node)
        self._save_config()

        # Log to local chain
        append_to_chain("federation_node_added", {
            "node_id": node_id,
            "alias": node.alias,
            "sse_url": sse_url,
        })

        return node

    def remove_node(self, node_id):
        """Remove a node from the federation by node_id.

        Logs `federation_node_removed` to the local hash chain.
        Returns True if the node was found and removed, False otherwise.
        """
        original_count = len(self.nodes)
        self.nodes = [n for n in self.nodes if n.node_id != node_id]

        if len(self.nodes) == original_count:
            return False  # node_id not found

        self._save_config()

        # Log to local chain
        append_to_chain("federation_node_removed", {
            "node_id": node_id,
        })

        return True

    def get_node(self, node_id):
        """Look up a single node by its node_id. Returns None if not found."""
        for node in self.nodes:
            if node.node_id == node_id:
                return node
        return None

    def get_all_status(self):
        """Query all nodes and return an aggregated governance status.

        This is the core federation read: hit every node in parallel-ish
        (sequential for simplicity, async can come later), collect their
        governance state, and merge it into a single view.

        Logs `federation_status_checked` to the local chain.

        Returns a dict with:
          - timestamp: when this query ran
          - total_nodes: how many nodes are registered
          - nodes_reachable / nodes_unreachable: counts
          - nodes: per-node detail list
          - aggregate: cross-node summary
        """
        timestamp = _timestamp_now()
        node_details = []
        reachable_count = 0
        unreachable_count = 0

        # Aggregate accumulators
        total_chain_entries = 0
        all_chains_intact = True
        domains = set()
        versions = set()

        for node in self.nodes:
            status = node.get_status()
            chain_summary = node.get_chain_summary()

            detail = {
                "node_id": node.node_id,
                "alias": node.alias,
                "sse_url": node.sse_url,
                "reachable": node.reachable,
                "last_checked": node.last_checked,
                "version": None,
                "chain_length": None,
                "chain_intact": None,
                "domain": None,
            }

            if node.reachable:
                reachable_count += 1

                # Extract fields from status (structure depends on MCP server)
                if status:
                    detail["version"] = status.get("version")
                    detail["domain"] = status.get("domain")
                    detail["chain_length"] = status.get("chain_length",
                                                        status.get("chain_entries"))
                    detail["chain_intact"] = status.get("chain_intact",
                                                        status.get("integrity"))

                    if detail["version"]:
                        versions.add(detail["version"])
                    if detail["domain"]:
                        domains.add(detail["domain"])

                # Overlay chain summary data if available
                if chain_summary:
                    if detail["chain_length"] is None:
                        detail["chain_length"] = chain_summary.get("total")
                    if chain_summary.get("intact") is not None:
                        detail["chain_intact"] = chain_summary["intact"]

                # Accumulate
                if detail["chain_length"] is not None:
                    total_chain_entries += detail["chain_length"]
                if detail["chain_intact"] is False:
                    all_chains_intact = False
            else:
                unreachable_count += 1
                # Unknown integrity for unreachable nodes
                all_chains_intact = False

            node_details.append(detail)

        result = {
            "timestamp": timestamp,
            "total_nodes": len(self.nodes),
            "nodes_reachable": reachable_count,
            "nodes_unreachable": unreachable_count,
            "nodes": node_details,
            "aggregate": {
                "total_chain_entries": total_chain_entries,
                "all_chains_intact": all_chains_intact,
                "domains": sorted(domains),
                "versions": sorted(versions),
            },
        }

        # Log the check to local chain
        append_to_chain("federation_status_checked", {
            "total_nodes": len(self.nodes),
            "reachable": reachable_count,
            "unreachable": unreachable_count,
        })

        return result

    def get_event_stream(self, limit=50):
        """Query recent events from all nodes, merge and sort by timestamp.

        Queries each node's chain endpoint for recent entries, tags each
        event with the originating node_id and node_alias, then merges
        all events into a single list sorted by timestamp (newest first).

        Returns a list of event dicts.
        """
        all_events = []

        for node in self.nodes:
            chain_summary = node.get_chain_summary()
            if chain_summary is None:
                continue

            for entry in chain_summary.get("entries", []):
                event = dict(entry)
                event["node_id"] = node.node_id
                event["node_alias"] = node.alias
                all_events.append(event)

        # Sort by timestamp descending (newest first)
        # Handle missing timestamps gracefully
        all_events.sort(
            key=lambda e: e.get("timestamp", ""),
            reverse=True,
        )

        return all_events[:limit]


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def run_federation(args):
    """Dispatch federation subcommands.

    Actions:
        status  — aggregated governance view across all federated nodes
        add     — register a new remote Charter node
        remove  — deregister a node from the federation
        events  — merged event stream from all nodes
    """
    action = getattr(args, "action", None)

    if action == "status":
        _cmd_status(args)
    elif action == "add":
        _cmd_add(args)
    elif action == "remove":
        _cmd_remove(args)
    elif action == "events":
        _cmd_events(args)
    else:
        print("Usage: charter federation {status|add|remove|events}")
        print()
        print("  status   Aggregated governance view across all nodes")
        print("  add      Register a remote Charter node")
        print("  remove   Deregister a node from the federation")
        print("  events   Merged event stream from all nodes")


def _cmd_status(args):
    """Display aggregated federation status."""
    fed = Federation()
    result = fed.get_all_status()

    print(f"Charter Federation — {fed.name}")
    print("=" * 56)
    print(f"  Queried at:  {result['timestamp']}")
    print(f"  Total nodes: {result['total_nodes']}")
    print(f"  Reachable:   {result['nodes_reachable']}")
    print(f"  Unreachable: {result['nodes_unreachable']}")
    print()

    if not result["nodes"]:
        print("  No nodes registered. Add one with:")
        print("    charter federation add --url <sse_url> --alias <name>")
        return

    # Per-node table
    print("  Nodes:")
    print("  {:<16} {:<12} {:<10} {:<8} {}".format(
        "Alias", "Version", "Chain", "Intact", "Domain"
    ))
    print("  " + "-" * 54)

    for nd in result["nodes"]:
        alias = nd["alias"][:15]
        if nd["reachable"]:
            version = nd.get("version") or "?"
            chain = str(nd.get("chain_length") or "?")
            intact = "yes" if nd.get("chain_intact") else "NO"
            domain = nd.get("domain") or "?"
        else:
            version = "-"
            chain = "-"
            intact = "-"
            domain = "-"
            alias = f"{alias} (down)"

        print("  {:<16} {:<12} {:<10} {:<8} {}".format(
            alias, version, chain, intact, domain
        ))

    # Aggregate
    agg = result["aggregate"]
    print()
    print("  Aggregate:")
    print(f"    Total chain entries: {agg['total_chain_entries']}")
    intact_str = "YES" if agg["all_chains_intact"] else "NO"
    print(f"    All chains intact:  {intact_str}")
    if agg["domains"]:
        print(f"    Domains:            {', '.join(agg['domains'])}")
    if agg["versions"]:
        print(f"    Versions:           {', '.join(agg['versions'])}")


def _cmd_add(args):
    """Add a new node to the federation."""
    sse_url = getattr(args, "url", None) or getattr(args, "sse_url", None)
    alias = getattr(args, "alias", None)
    node_id = getattr(args, "node_id", None)

    if not sse_url:
        print("Error: --url is required")
        print("Usage: charter federation add --url <sse_url> [--alias <name>] [--node-id <id>]")
        return

    # If no node_id provided, try to discover it from the remote node
    if not node_id:
        node_id = _discover_node_id(sse_url)
        if not node_id:
            print(f"Error: Could not discover node identity from {sse_url}")
            print("Provide --node-id manually, or ensure the node is running.")
            return

    fed = Federation()

    try:
        node = fed.add_node(node_id, sse_url, alias)
    except ValueError as e:
        print(f"Error: {e}")
        return

    print(f"Node added to federation:")
    print(f"  Alias:   {node.alias}")
    print(f"  Node ID: {node.node_id[:24]}...")
    print(f"  URL:     {node.sse_url}")

    # Quick health check
    if node.check_health():
        print(f"  Status:  reachable")
    else:
        print(f"  Status:  unreachable (will retry on next status check)")


def _discover_node_id(sse_url):
    """Try to discover a node's public ID from its health endpoint.

    Returns the node_id string or None if discovery fails.
    """
    base_url = _base_url_from_sse(sse_url)
    result = _http_get_json(f"{base_url}/health")
    if result is None:
        return None

    # The health endpoint may include identity info at various levels
    node_id = (
        result.get("node_id")
        or result.get("public_id")
        or result.get("identity", {}).get("public_id")
    )

    # Check under "charter" key (standard health response shape)
    if not node_id and "charter" in result and isinstance(result["charter"], dict):
        charter_data = result["charter"]
        node_id = (
            charter_data.get("node_id")
            or charter_data.get("public_id")
            or charter_data.get("identity", {}).get("public_id")
        )

    return node_id


def _cmd_remove(args):
    """Remove a node from the federation."""
    node_id = getattr(args, "node_id", None)

    if not node_id:
        print("Error: --node-id is required")
        print("Usage: charter federation remove --node-id <id>")
        print()
        # Show available nodes to help the user
        fed = Federation()
        if fed.nodes:
            print("Current nodes:")
            for node in fed.nodes:
                print(f"  {node.alias}: {node.node_id[:24]}...")
        return

    fed = Federation()
    removed = fed.remove_node(node_id)

    if removed:
        print(f"Node removed: {node_id[:24]}...")
    else:
        print(f"Node not found: {node_id[:24]}...")
        if fed.nodes:
            print()
            print("Current nodes:")
            for node in fed.nodes:
                print(f"  {node.alias}: {node.node_id[:24]}...")


def _cmd_events(args):
    """Display merged event stream from all federated nodes."""
    limit = getattr(args, "limit", 50) or 50
    fed = Federation()

    if not fed.nodes:
        print("No nodes in federation. Add one with:")
        print("  charter federation add --url <sse_url> --alias <name>")
        return

    events = fed.get_event_stream(limit=limit)

    print(f"Charter Federation — Event Stream")
    print(f"Nodes queried: {len(fed.nodes)}")
    print("=" * 64)

    if not events:
        print("  No events retrieved. Nodes may be unreachable.")
        return

    for event in events:
        ts = event.get("timestamp", "?")
        evt_type = event.get("event", "?")
        node_alias = event.get("node_alias", "?")
        index = event.get("index", "?")

        print(f"  [{ts}] {node_alias} #{index}: {evt_type}")

        # Show event data summary if present
        data = event.get("data")
        if data and isinstance(data, dict):
            for key, val in data.items():
                val_str = str(val)
                if len(val_str) > 48:
                    val_str = val_str[:48] + "..."
                print(f"    {key}: {val_str}")
