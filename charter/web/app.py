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

    @app.route("/federation")
    def federation_page():
        from charter.federation import Federation

        fed = Federation()
        status = fed.get_all_status()
        events = fed.get_event_stream(limit=50)

        return render_template(
            "federation.html",
            active="federation",
            nodes=status.get("nodes", []),
            summary=status.get("summary", {}),
            events=events,
        )

    @app.route("/api/federation/status")
    def api_federation_status():
        from charter.federation import Federation

        fed = Federation()
        return jsonify(fed.get_all_status())

    @app.route("/api/federation/events")
    def api_federation_events():
        from charter.federation import Federation

        limit = request.args.get("limit", 50, type=int)
        fed = Federation()
        return jsonify({"events": fed.get_event_stream(limit=limit)})

    # --- Account & Licensing ---

    @app.route("/account")
    def account_page():
        from charter.licensing import get_license_status, get_upgrade_info
        from charter.onboard import _load_onboard_state, ONBOARD_STEPS

        license_status = get_license_status()
        upgrade_info = get_upgrade_info()
        onboard_state = _load_onboard_state()
        identity = load_identity()
        chain = _read_chain()

        return render_template(
            "account.html",
            active="account",
            license=license_status,
            upgrade_options=upgrade_info.get("options", []),
            onboard_state=onboard_state,
            onboard_steps=ONBOARD_STEPS,
            identity=identity,
            chain_length=len(chain),
            chain_intact=_check_integrity(chain),
        )

    @app.route("/webhook/stripe", methods=["POST"])
    def stripe_webhook():
        """Handle Stripe webhook events for license management.

        Events handled:
          - checkout.session.completed: activate license
          - customer.subscription.updated: update tier/seats
          - customer.subscription.deleted: deactivate license
        """
        import hashlib
        import hmac as _hmac

        payload = request.get_data(as_text=True)
        sig_header = request.headers.get("Stripe-Signature", "")

        # Verify webhook signature if secret is configured
        webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET")
        if webhook_secret:
            # Stripe signature format: t=timestamp,v1=signature
            parts = {}
            for item in sig_header.split(","):
                if "=" in item:
                    k, v = item.split("=", 1)
                    parts[k] = v

            timestamp = parts.get("t", "")
            expected_sig = parts.get("v1", "")

            signed_payload = f"{timestamp}.{payload}"
            computed = _hmac.new(
                webhook_secret.encode(),
                signed_payload.encode(),
                hashlib.sha256,
            ).hexdigest()

            if not _hmac.compare_digest(computed, expected_sig):
                return jsonify({"error": "Invalid signature"}), 400

        try:
            event = json.loads(payload)
        except json.JSONDecodeError:
            return jsonify({"error": "Invalid JSON"}), 400

        event_type = event.get("type", "")
        data = event.get("data", {}).get("object", {})

        if event_type == "checkout.session.completed":
            _handle_checkout_completed(data)
        elif event_type == "customer.subscription.updated":
            _handle_subscription_updated(data)
        elif event_type == "customer.subscription.deleted":
            _handle_subscription_deleted(data)

        return jsonify({"received": True})

    def _handle_checkout_completed(session):
        """Process a completed checkout — activate license."""
        from charter.licensing import generate_license_key, activate_license

        customer_id = session.get("customer", "")
        # Determine tier from metadata or line items
        metadata = session.get("metadata", {})
        tier = metadata.get("tier", "pro")

        key = generate_license_key(tier, identifier=customer_id)
        seats = int(metadata.get("seats", 1))

        activate_license(
            key,
            seats=seats,
            stripe_customer_id=customer_id,
        )

    def _handle_subscription_updated(subscription):
        """Process a subscription update — adjust tier/seats."""
        from charter.licensing import get_license, activate_license

        lic = get_license()
        if not lic:
            return

        # Update seats from subscription quantity
        items = subscription.get("items", {}).get("data", [])
        if items:
            seats = items[0].get("quantity", 1)
            lic["seats"] = seats
            # Re-activate with updated data
            activate_license(
                lic["key"],
                seats=seats,
                team_hash=lic.get("team_hash"),
                stripe_customer_id=lic.get("stripe_customer_id"),
                expires_at=lic.get("expires_at"),
            )

    def _handle_subscription_deleted(subscription):
        """Process a subscription cancellation — deactivate license."""
        from charter.licensing import deactivate_license
        deactivate_license()

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
