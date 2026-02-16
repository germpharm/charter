"""Charter web dashboard.

Flask application that provides a governance dashboard for
enterprise users. Reads state from ~/.charter/ filesystem.
Can run standalone or as part of the daemon service.
"""

import json
import os
import time

try:
    from flask import Flask, render_template, jsonify, request
except ImportError:
    Flask = None

from charter import __version__
from charter.identity import load_identity, get_chain_path, get_identity_dir
from charter.config import load_config
from charter.daemon.detector import detect_ai_tools, get_summary


def create_app(daemon=None):
    """Create and configure the Flask application.

    Args:
        daemon: Optional CharterDaemon instance for live status.
                If None, runs in standalone dashboard mode.
    """
    if Flask is None:
        raise ImportError(
            "Flask required for web dashboard. "
            "Install with: pip install charter-governance[daemon]"
        )

    app = Flask(
        __name__,
        template_folder=os.path.join(os.path.dirname(__file__), "templates"),
        static_folder=os.path.join(os.path.dirname(__file__), "static"),
    )
    app.config["daemon"] = daemon

    @app.context_processor
    def inject_globals():
        """Make common variables available to all templates."""
        identity = load_identity()
        return {
            "version": __version__,
            "daemon_running": daemon is not None and daemon.running,
            "current_identity": identity,
        }

    @app.route("/")
    def dashboard():
        identity = load_identity()
        chain = _read_chain()

        if daemon:
            status = daemon.get_status()
            scan = status.get("last_scan")
            tools = scan["tools"] if scan else detect_ai_tools()
        else:
            tools = detect_ai_tools()

        config = load_config()

        return render_template(
            "dashboard.html",
            active="dashboard",
            identity=identity,
            chain_length=len(chain),
            chain_intact=_check_integrity(chain),
            tools=tools,
            recent_events=chain[-10:][::-1],
            config=config,
        )

    @app.route("/identity")
    def identity_page():
        identity = load_identity()
        chain = _read_chain()

        return render_template(
            "identity.html",
            active="identity",
            identity=identity,
            chain_length=len(chain),
            chain_intact=_check_integrity(chain),
        )

    @app.route("/audit")
    def audit_page():
        chain = _read_chain()

        event_counts = {}
        for entry in chain:
            event = entry.get("event", "unknown")
            event_counts[event] = event_counts.get(event, 0) + 1

        return render_template(
            "audit.html",
            active="audit",
            entries=chain[::-1],
            chain_length=len(chain),
            chain_intact=_check_integrity(chain),
            event_counts=sorted(event_counts.items()),
        )

    @app.route("/governance")
    def governance_page():
        config = load_config()

        return render_template(
            "governance.html",
            active="governance",
            config=config,
        )

    @app.route("/network")
    def network_page():
        node = _load_node()
        connections = _load_jsonl("network", "connections.jsonl")
        contributions = _load_jsonl("network", "contributions.jsonl")

        return render_template(
            "network.html",
            active="network",
            node=node,
            connections=connections,
            contributions=contributions,
        )

    # --- API endpoints ---

    @app.route("/api/status")
    def api_status():
        identity = load_identity()
        chain = _read_chain()
        daemon_status = daemon.get_status() if daemon else None

        return jsonify({
            "identity": {
                "alias": identity["alias"] if identity else None,
                "public_id": identity["public_id"][:16] if identity else None,
                "verified": (
                    identity.get("real_identity") is not None
                    if identity else False
                ),
            },
            "chain": {
                "length": len(chain),
                "intact": _check_integrity(chain),
            },
            "daemon": daemon_status,
        })

    @app.route("/api/detect")
    def api_detect():
        return jsonify(get_summary())

    @app.route("/api/chain")
    def api_chain():
        chain = _read_chain()
        limit = request.args.get("limit", 50, type=int)
        offset = request.args.get("offset", 0, type=int)

        return jsonify({
            "total": len(chain),
            "entries": chain[offset:offset + limit],
        })

    return app


# --- Helper functions ---

def _read_chain():
    """Read and parse the hash chain."""
    chain_path = get_chain_path()
    entries = []
    if os.path.isfile(chain_path):
        with open(chain_path) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    return entries


def _check_integrity(entries):
    """Verify hash chain integrity."""
    for i in range(1, len(entries)):
        if entries[i].get("previous_hash") != entries[i - 1].get("hash"):
            return False
    return True


def _load_node():
    """Load network node manifest."""
    node_path = os.path.join(get_identity_dir(), "network", "node.json")
    if os.path.isfile(node_path):
        with open(node_path) as f:
            return json.load(f)
    return None


def _load_jsonl(subdir, filename):
    """Load a JSONL file from the identity directory."""
    path = os.path.join(get_identity_dir(), subdir, filename)
    items = []
    if os.path.isfile(path):
        with open(path) as f:
            for line in f:
                if line.strip():
                    try:
                        items.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    return items
