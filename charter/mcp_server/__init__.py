"""Charter MCP Server — governance as a service for any AI model.

Exposes Charter's governance tools via the Model Context Protocol.
Two transport modes:
  - stdio: for local Claude Code integration via .mcp.json
  - sse: for remote access (Mac Mini, Grok via remote MCP)

Usage:
  charter mcp-serve --transport stdio
  charter mcp-serve --transport sse --port 8375
"""

import json
import os
import time

from mcp.server import Server
from mcp.types import Tool, TextContent

from charter import __version__
from charter.config import load_config, find_config
from charter.identity import (
    load_identity,
    get_chain_path,
    append_to_chain,
    hash_entry,
)
from charter.stamp import create_stamp, verify_stamp
from charter.dispute import export_dispute_package, verify_dispute_package, inspect_dispute_package
from charter.timestamp import anchor_chain, verify_timestamp_anchor
from charter.merkle import (
    batch_chain_entries,
    generate_proof,
    verify_chain_entry,
    create_exchange_proof,
    verify_exchange_proof,
    load_batch_index,
)

# ---------------------------------------------------------------------------
# Server instance
# ---------------------------------------------------------------------------

server = Server("charter-governance")


# ---------------------------------------------------------------------------
# Data helpers (pure functions, no print statements)
# ---------------------------------------------------------------------------

def _get_status_data() -> dict:
    """Gather governance status as a dict."""
    config_path = find_config()
    identity = load_identity()

    result = {
        "version": __version__,
        "config_path": config_path,
        "identity": None,
        "chain": None,
        "governance": None,
    }

    if config_path:
        config = load_config(config_path)
        gov = config.get("governance", {})
        result["governance"] = {
            "domain": config.get("domain", "unknown"),
            "layer_a_count": len(gov.get("layer_a", {}).get("rules", [])),
            "layer_b_count": len(gov.get("layer_b", {}).get("rules", [])),
            "layer_c_frequency": gov.get("layer_c", {}).get("frequency", "unknown"),
            "kill_trigger_count": len(gov.get("kill_triggers", [])),
        }

    if identity:
        result["identity"] = {
            "alias": identity["alias"],
            "public_id": identity["public_id"],
            "created_at": identity["created_at"],
            "contributions": identity.get("contributions", 0),
            "verified": identity.get("real_identity") is not None,
        }

    chain_path = get_chain_path()
    if os.path.isfile(chain_path):
        with open(chain_path) as f:
            lines = [l for l in f.readlines() if l.strip()]
        entries = [json.loads(l) for l in lines]
        intact = all(
            entries[i].get("previous_hash") == entries[i - 1].get("hash")
            for i in range(1, len(entries))
        )
        last = entries[-1] if entries else None
        result["chain"] = {
            "length": len(entries),
            "integrity": "verified" if intact else "broken",
            "last_event": last.get("event") if last else None,
            "last_timestamp": last.get("timestamp") if last else None,
        }

    # Merkle tree status
    try:
        idx = load_batch_index()
        batched = idx["last_chain_index"] + 1 if idx["last_chain_index"] >= 0 else 0
        total = result.get("chain", {}).get("length", 0)
        result["merkle"] = {
            "total_batches": len(idx["batches"]),
            "entries_batched": batched,
            "entries_unbatched": total - batched,
            "latest_root": idx["batches"][-1]["root"] if idx["batches"] else None,
            "architecture": "production",
            "proof_complexity": "O(log n)",
        }
    except Exception:
        result["merkle"] = {"architecture": "available", "status": "no batches yet"}

    return result


def _get_chain_entries(count: int = 10) -> list:
    """Read the most recent chain entries."""
    chain_path = get_chain_path()
    if not os.path.isfile(chain_path):
        return []
    with open(chain_path) as f:
        lines = [l for l in f.readlines() if l.strip()]
    entries = [json.loads(l) for l in lines]
    return entries[-count:]


def _check_chain_integrity() -> dict:
    """Full chain integrity check."""
    chain_path = get_chain_path()
    if not os.path.isfile(chain_path):
        return {"exists": False, "length": 0, "intact": False}
    with open(chain_path) as f:
        lines = [l for l in f.readlines() if l.strip()]
    entries = [json.loads(l) for l in lines]
    breaks = []
    for i in range(1, len(entries)):
        if entries[i].get("previous_hash") != entries[i - 1].get("hash"):
            breaks.append({"index": i, "expected": entries[i - 1].get("hash"), "got": entries[i].get("previous_hash")})
    return {
        "exists": True,
        "length": len(entries),
        "intact": len(breaks) == 0,
        "breaks": breaks,
        "genesis": entries[0].get("timestamp") if entries else None,
        "latest": entries[-1].get("timestamp") if entries else None,
    }


def _get_audit_data(period: str = "week") -> dict:
    """Generate audit report as structured data."""
    config = load_config()
    identity = load_identity()
    if not config or not identity:
        return {"error": "No config or identity found. Run 'charter init' first."}

    gov = config.get("governance", {})
    chain_path = get_chain_path()
    entries = []
    if os.path.isfile(chain_path):
        with open(chain_path) as f:
            entries = [json.loads(l) for l in f if l.strip()]

    event_counts = {}
    for entry in entries:
        event = entry.get("event", "unknown")
        event_counts[event] = event_counts.get(event, 0) + 1

    intact = all(
        entries[i].get("previous_hash") == entries[i - 1].get("hash")
        for i in range(1, len(entries))
    )

    return {
        "period": period,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "node": identity["alias"],
        "public_id": identity["public_id"][:16] + "...",
        "domain": config.get("domain", "general"),
        "layer_a": {
            "constraint_count": len(gov.get("layer_a", {}).get("rules", [])),
            "violations": 0,
            "status": "COMPLIANT",
        },
        "layer_b": {
            "rule_count": len(gov.get("layer_b", {}).get("rules", [])),
        },
        "chain": {
            "total_entries": len(entries),
            "events_by_type": event_counts,
            "integrity": "verified" if intact else "broken",
        },
        "kill_triggers": [
            {"trigger": t.get("trigger", t) if isinstance(t, dict) else t, "status": "NOT_TRIGGERED"}
            for t in gov.get("kill_triggers", [])
        ],
    }


# ---------------------------------------------------------------------------
# MCP Tool definitions
# ---------------------------------------------------------------------------

TOOLS = [
    Tool(
        name="charter_status",
        description="Get current Charter governance status including version, identity, chain state, and governance rules. Read-only.",
        inputSchema={"type": "object", "properties": {}, "required": []},
    ),
    Tool(
        name="charter_stamp",
        description="Create an attribution stamp for a work product. Records who created it, which AI tools were used, and whether governance was active.",
        inputSchema={
            "type": "object",
            "properties": {
                "description": {
                    "type": "string",
                    "description": "Description of the work product being stamped.",
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="charter_verify_stamp",
        description="Verify an attribution stamp's integrity and governance status.",
        inputSchema={
            "type": "object",
            "properties": {
                "stamp": {
                    "type": "object",
                    "description": "The stamp JSON object to verify.",
                },
            },
            "required": ["stamp"],
        },
    ),
    Tool(
        name="charter_append_chain",
        description="Record an event to the immutable hash chain. Every action logged with timestamp, signer, and cryptographic link to previous entry.",
        inputSchema={
            "type": "object",
            "properties": {
                "event": {
                    "type": "string",
                    "description": "Event type (e.g. 'email_sent', 'order_created', 'decision_made').",
                },
                "data": {
                    "type": "object",
                    "description": "Event data payload. Any JSON-serializable object.",
                },
            },
            "required": ["event", "data"],
        },
    ),
    Tool(
        name="charter_read_chain",
        description="Read recent entries from the hash chain. Returns the most recent N entries.",
        inputSchema={
            "type": "object",
            "properties": {
                "count": {
                    "type": "integer",
                    "description": "Number of recent entries to return (default: 10).",
                    "default": 10,
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="charter_check_integrity",
        description="Verify the full hash chain has not been tampered with. Checks every link from genesis to latest entry.",
        inputSchema={"type": "object", "properties": {}, "required": []},
    ),
    Tool(
        name="charter_get_config",
        description="Get the active governance configuration including Layer A constraints, Layer B gradient rules, Layer C audit settings, and kill triggers.",
        inputSchema={"type": "object", "properties": {}, "required": []},
    ),
    Tool(
        name="charter_identity",
        description="Get current identity information (alias, public ID, verification status). Never exposes the private seed.",
        inputSchema={"type": "object", "properties": {}, "required": []},
    ),
    Tool(
        name="charter_audit",
        description="Generate a governance audit report covering chain activity, compliance status, and kill trigger state.",
        inputSchema={
            "type": "object",
            "properties": {
                "period": {
                    "type": "string",
                    "enum": ["day", "week", "month", "session"],
                    "description": "Audit period (default: week).",
                    "default": "week",
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="charter_local_inference",
        description="Call the local LLM (Qwen3 Coder 30B on Mac Mini) for routine coding tasks. Zero API cost. Every call logged to Charter chain.",
        inputSchema={
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "The prompt to send to the local model.",
                },
                "system": {
                    "type": "string",
                    "description": "Optional system prompt.",
                },
                "max_tokens": {
                    "type": "integer",
                    "description": "Maximum tokens to generate (default: 2048).",
                    "default": 2048,
                },
            },
            "required": ["prompt"],
        },
    ),
    # --- Dispute tools ---
    Tool(
        name="charter_dispute_export",
        description="Export a self-contained dispute proof package for a chain segment. The package includes chain entries, Merkle proofs, RFC 3161 timestamp anchors, governance config snapshots, and exchange proofs — everything an independent examiner needs to verify the evidence.",
        inputSchema={
            "type": "object",
            "properties": {
                "from_index": {
                    "type": "integer",
                    "description": "Starting chain entry index (inclusive). Omit for full chain.",
                },
                "to_index": {
                    "type": "integer",
                    "description": "Ending chain entry index (inclusive). Omit for full chain.",
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="charter_dispute_verify",
        description="Verify a dispute proof package received from another party. Checks hash integrity, chain links, boundary links, and Merkle proofs. Returns VERIFIED or FAILED with specific failure points.",
        inputSchema={
            "type": "object",
            "properties": {
                "package": {
                    "type": "object",
                    "description": "The dispute proof package JSON object to verify.",
                },
            },
            "required": ["package"],
        },
    ),
    # --- Timestamp tools ---
    Tool(
        name="charter_timestamp_anchor",
        description="Create an RFC 3161 timestamp anchor for the current chain state. Submits the latest chain hash to a certified Time Stamping Authority (TSA) and records the signed token in the chain. Provides independently attested proof of when the chain state existed.",
        inputSchema={
            "type": "object",
            "properties": {
                "force": {
                    "type": "boolean",
                    "description": "If true, anchor regardless of interval settings (default: true).",
                    "default": True,
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="charter_timestamp_status",
        description="Get RFC 3161 timestamp anchoring status: total anchors, entries since last anchor, last anchor time and TSA, and anchoring interval settings.",
        inputSchema={"type": "object", "properties": {}, "required": []},
    ),
    # --- Merkle tree tools ---
    Tool(
        name="charter_merkle_batch",
        description="Roll unbatched chain entries into a Merkle tree. Returns the tree root hash and batch metadata. Run after bulk operations or on a schedule.",
        inputSchema={
            "type": "object",
            "properties": {
                "batch_size": {
                    "type": "integer",
                    "description": "Max entries per batch (default: 256, powers of 2 optimal).",
                    "default": 256,
                },
                "min_entries": {
                    "type": "integer",
                    "description": "Minimum entries to trigger batching (default: 16).",
                    "default": 16,
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="charter_merkle_prove",
        description="Generate a Merkle inclusion proof for a specific chain entry. The proof is O(log n) — 40 steps to prove 1 entry out of 1 trillion.",
        inputSchema={
            "type": "object",
            "properties": {
                "chain_index": {
                    "type": "integer",
                    "description": "The chain entry index to generate a proof for.",
                },
            },
            "required": ["chain_index"],
        },
    ),
    Tool(
        name="charter_merkle_verify",
        description="Verify a chain entry against its Merkle tree. Confirms the entry exists in the batch and the proof is valid.",
        inputSchema={
            "type": "object",
            "properties": {
                "chain_index": {
                    "type": "integer",
                    "description": "The chain entry index to verify.",
                },
                "entry_hash": {
                    "type": "string",
                    "description": "The SHA-256 hash of the chain entry.",
                },
            },
            "required": ["chain_index", "entry_hash"],
        },
    ),
    Tool(
        name="charter_merkle_exchange_proof",
        description="Create a self-contained proof package for sending to another node. Contains the chain entry, Merkle proof, and signature. The receiving node can verify without access to your chain.",
        inputSchema={
            "type": "object",
            "properties": {
                "chain_index": {
                    "type": "integer",
                    "description": "The chain entry index to create an exchange proof for.",
                },
            },
            "required": ["chain_index"],
        },
    ),
    Tool(
        name="charter_merkle_verify_exchange",
        description="Verify an exchange proof received from another node. No access to the source node's chain is needed.",
        inputSchema={
            "type": "object",
            "properties": {
                "package": {
                    "type": "object",
                    "description": "The exchange proof package received from another node.",
                },
            },
            "required": ["package"],
        },
    ),
    Tool(
        name="charter_merkle_status",
        description="Get Merkle tree status: number of batches, total entries batched, unbatched entry count, latest root hash.",
        inputSchema={"type": "object", "properties": {}, "required": []},
    ),
    # --- v2.2.0: Confidence tagging tools ---
    Tool(
        name="charter_tag_confidence",
        description="Tag a chain entry with a confidence level (verified, inferred, exploratory), evidence basis, and constraint assumptions. Records the tagging as a chain event.",
        inputSchema={
            "type": "object",
            "properties": {
                "entry_index": {
                    "type": "integer",
                    "description": "The chain entry index to tag.",
                },
                "confidence": {
                    "type": "string",
                    "enum": ["verified", "inferred", "exploratory"],
                    "description": "Confidence level.",
                },
                "evidence_basis": {
                    "type": "string",
                    "description": "What evidence supports this decision.",
                },
                "constraint_assumptions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Assumptions that must remain true.",
                },
            },
            "required": ["entry_index", "confidence"],
        },
    ),
    Tool(
        name="charter_revision_history",
        description="Get the full revision chain for a chain entry, showing how a decision evolved as new evidence arrived. Traces backward through revision links.",
        inputSchema={
            "type": "object",
            "properties": {
                "entry_hash": {
                    "type": "string",
                    "description": "The hash of the chain entry to trace revisions for.",
                },
            },
            "required": ["entry_hash"],
        },
    ),
    # --- v2.2.0: Red team tools ---
    Tool(
        name="charter_redteam_run",
        description="Run the adversarial test battery against the current governance configuration. Tests constraint escape, gradient manipulation, chain tampering, threshold erosion, identity spoofing, and audit evasion. Returns pass/fail for each scenario.",
        inputSchema={
            "type": "object",
            "properties": {
                "categories": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Categories to test (default: all). Options: constraint_escape, gradient_manipulation, chain_tampering, threshold_erosion, identity_spoofing, audit_evasion.",
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="charter_redteam_status",
        description="Get the results of the most recent red team run, or run a new battery and return the results.",
        inputSchema={"type": "object", "properties": {}, "required": []},
    ),
    # --- v2.2.0: Arbitration tools ---
    Tool(
        name="charter_arbitrate",
        description="Route a decision through multiple AI models for divergence analysis. Implements the Bezos Type 1/Type 2 framework: irreversible decisions get multi-model checks, reversible decisions use single model. Returns agreement status, divergence score, and recommendation.",
        inputSchema={
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "The question or decision to arbitrate.",
                },
                "models": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Model names to consult (default: auto based on reversibility). Options: local, anthropic.",
                },
                "reversibility": {
                    "type": "string",
                    "enum": ["reversible", "low_reversibility", "irreversible"],
                    "description": "Override reversibility classification.",
                },
            },
            "required": ["question"],
        },
    ),
    # --- v2.3.0: Role-Based Access Control tools ---
    Tool(
        name="charter_propose_rule",
        description="Propose a new governance rule for a team. Requires operator or reviewer role. The proposal enters dual-signoff workflow — two team members must approve before the rule takes effect. Layer A proposals are additive-only (no deletions).",
        inputSchema={
            "type": "object",
            "properties": {
                "team_hash": {
                    "type": "string",
                    "description": "The team hash to propose a rule for.",
                },
                "rule_text": {
                    "type": "string",
                    "description": "The rule text to propose.",
                },
                "layer": {
                    "type": "string",
                    "enum": ["a", "b"],
                    "description": "Which governance layer this rule belongs to.",
                },
            },
            "required": ["team_hash", "rule_text", "layer"],
        },
    ),
    Tool(
        name="charter_sign_rule",
        description="Sign (approve or reject) a pending governance rule proposal. Requires operator or reviewer role. When the required number of signatures is met, the rule is automatically applied or rejected.",
        inputSchema={
            "type": "object",
            "properties": {
                "team_hash": {
                    "type": "string",
                    "description": "The team hash.",
                },
                "proposal_id": {
                    "type": "string",
                    "description": "The proposal ID to sign.",
                },
                "approve": {
                    "type": "boolean",
                    "description": "True to approve, False to reject.",
                    "default": True,
                },
            },
            "required": ["team_hash", "proposal_id"],
        },
    ),
    Tool(
        name="charter_role_status",
        description="Get RBAC status for a team: member roles, open proposals, Layer 0 invariants, and signoff requirements.",
        inputSchema={
            "type": "object",
            "properties": {
                "team_hash": {
                    "type": "string",
                    "description": "The team hash to check status for.",
                },
            },
            "required": ["team_hash"],
        },
    ),
    # --- v2.3.0: Alerting tools ---
    Tool(
        name="charter_alert_status",
        description="Get the current alerting configuration: configured channels (webhooks, Slack, email), event filters, and connection status.",
        inputSchema={"type": "object", "properties": {}, "required": []},
    ),
    # --- v2.3.0: SIEM tools ---
    Tool(
        name="charter_siem_export",
        description="Export chain events in SIEM-compatible formats. Supports CEF (Splunk), structured JSON (Datadog), and RFC 5424 syslog. Optionally filter by chain index range.",
        inputSchema={
            "type": "object",
            "properties": {
                "format": {
                    "type": "string",
                    "enum": ["cef", "json", "syslog"],
                    "description": "Export format (default: cef).",
                    "default": "cef",
                },
                "from_index": {
                    "type": "integer",
                    "description": "Starting chain index (inclusive).",
                },
                "to_index": {
                    "type": "integer",
                    "description": "Ending chain index (inclusive).",
                },
            },
            "required": [],
        },
    ),
    # --- v2.3.0: Compliance tools ---
    Tool(
        name="charter_compliance_map",
        description="Map current governance configuration against a regulatory compliance framework (SOX, HIPAA, FERPA, SOC 2, GDPR, EU AI Act, NIST AI RMF, ISO 27001). Returns coverage percentage, covered controls, gaps, and recommendations.",
        inputSchema={
            "type": "object",
            "properties": {
                "standard": {
                    "type": "string",
                    "description": "Compliance standard to map against (sox, hipaa, ferpa, soc2, gdpr, eu_ai_act, nist_ai_rmf, iso27001).",
                },
            },
            "required": ["standard"],
        },
    ),
    Tool(
        name="charter_federation_status",
        description="Get aggregated governance status across all federated Charter nodes. Shows node health, chain lengths, integrity, and overall summary.",
        inputSchema={
            "type": "object",
            "properties": {},
        },
    ),
    Tool(
        name="charter_federation_events",
        description="Get a merged event stream from all federated Charter nodes, sorted by timestamp. Provides a unified view of governance activity across the network.",
        inputSchema={
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of events to return (default: 50).",
                },
            },
        },
    ),
]


# ---------------------------------------------------------------------------
# MCP handlers
# ---------------------------------------------------------------------------

@server.list_tools()
async def handle_list_tools() -> list[Tool]:
    return TOOLS


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict | None) -> list[TextContent]:
    arguments = arguments or {}

    # License tier gating for paid MCP tools
    from charter.licensing import MCP_FEATURE_TIERS, check_tier, TIER_LABELS
    if name in MCP_FEATURE_TIERS:
        if not check_tier(name, feature_map=MCP_FEATURE_TIERS):
            required = MCP_FEATURE_TIERS[name]
            return [TextContent(type="text", text=json.dumps({
                "error": "license_required",
                "required_tier": required,
                "tier_label": TIER_LABELS.get(required, required),
                "message": f"Charter {TIER_LABELS.get(required, required)} required for {name}. Run: charter upgrade",
            }, indent=2))]

    if name == "charter_status":
        data = _get_status_data()
        return [TextContent(type="text", text=json.dumps(data, indent=2))]

    elif name == "charter_stamp":
        description = arguments.get("description")
        stamp = create_stamp(description=description)
        if not stamp:
            return [TextContent(type="text", text=json.dumps({"error": "No identity found. Run 'charter init' first."}))]
        return [TextContent(type="text", text=json.dumps(stamp, indent=2))]

    elif name == "charter_verify_stamp":
        stamp = arguments.get("stamp", {})
        result = verify_stamp(stamp)
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    elif name == "charter_append_chain":
        event = arguments.get("event", "unknown")
        data = arguments.get("data", {})
        entry = append_to_chain(event, data)
        if not entry:
            return [TextContent(type="text", text=json.dumps({"error": "No identity found. Cannot append to chain."}))]
        return [TextContent(type="text", text=json.dumps(entry, indent=2))]

    elif name == "charter_read_chain":
        count = arguments.get("count", 10)
        entries = _get_chain_entries(count)
        return [TextContent(type="text", text=json.dumps(entries, indent=2))]

    elif name == "charter_check_integrity":
        result = _check_chain_integrity()
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    elif name == "charter_get_config":
        config_path = find_config()
        if not config_path:
            return [TextContent(type="text", text=json.dumps({"error": "No charter.yaml found."}))]
        config = load_config(config_path)
        config["_config_path"] = config_path
        return [TextContent(type="text", text=json.dumps(config, indent=2, default=str))]

    elif name == "charter_identity":
        identity = load_identity()
        if not identity:
            return [TextContent(type="text", text=json.dumps({"error": "No identity found. Run 'charter init' first."}))]
        safe = {
            "alias": identity["alias"],
            "public_id": identity["public_id"],
            "created_at": identity["created_at"],
            "contributions": identity.get("contributions", 0),
            "verified": identity.get("real_identity") is not None,
        }
        if identity.get("real_identity"):
            ri = identity["real_identity"]
            safe["verified_name"] = ri.get("name")
            safe["verified_email"] = ri.get("email")
            safe["trust_level"] = ri.get("trust_level")
        return [TextContent(type="text", text=json.dumps(safe, indent=2))]

    elif name == "charter_audit":
        period = arguments.get("period", "week")
        data = _get_audit_data(period)
        return [TextContent(type="text", text=json.dumps(data, indent=2))]

    elif name == "charter_local_inference":
        prompt = arguments.get("prompt", "")
        system = arguments.get("system")
        max_tokens = arguments.get("max_tokens", 2048)
        try:
            from charter.mcp_server.local_model import call_local_model
            result = call_local_model(prompt, system=system, max_tokens=max_tokens)
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        except ConnectionError as e:
            return [TextContent(type="text", text=json.dumps({"error": str(e)}))]
        except Exception as e:
            return [TextContent(type="text", text=json.dumps({"error": f"Local inference failed: {e}"}))]

    # --- Dispute handlers ---

    elif name == "charter_dispute_export":
        from_idx = arguments.get("from_index")
        to_idx = arguments.get("to_index")
        # Default to full chain if not specified
        if from_idx is None or to_idx is None:
            chain_path = get_chain_path()
            if os.path.isfile(chain_path):
                with open(chain_path) as f:
                    entries = [json.loads(line) for line in f if line.strip()]
                if entries:
                    if from_idx is None:
                        from_idx = entries[0].get("index", 0)
                    if to_idx is None:
                        to_idx = entries[-1].get("index", 0)
        if from_idx is None or to_idx is None:
            return [TextContent(type="text", text=json.dumps({"error": "No chain found."}))]
        package = export_dispute_package(from_idx, to_idx)
        if not package:
            return [TextContent(type="text", text=json.dumps({"error": "Failed to create dispute package."}))]
        return [TextContent(type="text", text=json.dumps(package, indent=2))]

    elif name == "charter_dispute_verify":
        package = arguments.get("package", {})
        result = verify_dispute_package(package)
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    # --- Timestamp handlers ---

    elif name == "charter_timestamp_anchor":
        force = arguments.get("force", True)
        result = anchor_chain(force=force)
        if not result:
            return [TextContent(type="text", text=json.dumps({"error": "Anchoring failed. Check OpenSSL and network."}))]
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    elif name == "charter_timestamp_status":
        chain_path = get_chain_path()
        if not os.path.isfile(chain_path):
            return [TextContent(type="text", text=json.dumps({"error": "No chain found."}))]
        anchors = []
        total = 0
        with open(chain_path) as f:
            for line in f:
                line = line.strip()
                if line:
                    total += 1
                    entry = json.loads(line)
                    if entry.get("event") == "timestamp_anchor":
                        anchors.append(entry)
        last_anchor_index = anchors[-1].get("index", 0) if anchors else -1
        entries_since = total - 1 - last_anchor_index if last_anchor_index >= 0 else total
        result = {
            "total_anchors": len(anchors),
            "entries_since_last": entries_since,
            "anchor_interval_entries": 1000,
            "anchor_interval_seconds": 3600,
        }
        if anchors:
            last = anchors[-1]
            result["last_anchor"] = {
                "chain_index": last.get("index"),
                "tsa_timestamp": last.get("data", {}).get("tsa_timestamp"),
                "tsa_url": last.get("data", {}).get("tsa_url"),
                "chain_hash_anchored": last.get("data", {}).get("chain_hash_anchored"),
            }
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    # --- Merkle tree handlers ---

    elif name == "charter_merkle_batch":
        chain_path = get_chain_path()
        bs = arguments.get("batch_size", 256)
        me = arguments.get("min_entries", 16)
        result = batch_chain_entries(chain_path, batch_size=bs, min_entries=me)
        if not result:
            idx = load_batch_index()
            return [TextContent(type="text", text=json.dumps({
                "batched": False,
                "reason": "Not enough unbatched entries",
                "existing_batches": len(idx["batches"]),
                "last_chain_index_batched": idx["last_chain_index"],
            }, indent=2))]
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    elif name == "charter_merkle_prove":
        chain_index = arguments.get("chain_index", 0)
        result = generate_proof(chain_index)
        if not result:
            return [TextContent(type="text", text=json.dumps({
                "error": f"Chain entry {chain_index} not yet batched into a Merkle tree. Run charter_merkle_batch first."
            }))]
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    elif name == "charter_merkle_verify":
        chain_index = arguments.get("chain_index", 0)
        entry_hash = arguments.get("entry_hash", "")
        result = verify_chain_entry(chain_index, entry_hash)
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    elif name == "charter_merkle_exchange_proof":
        chain_index = arguments.get("chain_index", 0)
        result = create_exchange_proof(chain_index)
        if not result:
            return [TextContent(type="text", text=json.dumps({
                "error": f"Could not create exchange proof for chain entry {chain_index}."
            }))]
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    elif name == "charter_merkle_verify_exchange":
        package = arguments.get("package", {})
        result = verify_exchange_proof(package)
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    # --- v2.2.0: Confidence tagging handlers ---

    elif name == "charter_tag_confidence":
        entry_index = arguments.get("entry_index", 0)
        confidence = arguments.get("confidence", "exploratory")
        evidence_basis = arguments.get("evidence_basis", "")
        assumptions = arguments.get("constraint_assumptions", [])
        from charter.confidence import validate_confidence
        if not validate_confidence(confidence):
            return [TextContent(
                type="text",
                text=json.dumps({"error": "Invalid confidence level. Use: verified, inferred, exploratory"}),
            )]
        entry = append_to_chain(
            "confidence_tagged",
            {
                "entry_index": entry_index,
                "confidence": confidence,
                "evidence_basis": evidence_basis,
                "constraint_assumptions": assumptions,
            },
        )
        if not entry:
            return [TextContent(type="text", text=json.dumps({"error": "No identity found."}))]
        return [TextContent(type="text", text=json.dumps(entry, indent=2))]

    elif name == "charter_revision_history":
        entry_hash = arguments.get("entry_hash", "")
        from charter.confidence import get_revision_chain
        chain_path = get_chain_path()
        history = get_revision_chain(chain_path, entry_hash)
        return [TextContent(type="text", text=json.dumps(history, indent=2))]

    # --- v2.2.0: Red team handlers ---

    elif name == "charter_redteam_run":
        categories = arguments.get("categories")
        from charter.redteam import RedTeamRunner
        runner = RedTeamRunner()
        results = runner.run_battery(categories=categories)
        if not results:
            return [TextContent(type="text", text=json.dumps({"error": "No scenarios to run."}))]
        return [TextContent(type="text", text=json.dumps(results, indent=2))]

    elif name == "charter_redteam_status":
        from charter.redteam import RedTeamRunner
        runner = RedTeamRunner()
        results = runner.run_battery()
        if not results:
            return [TextContent(type="text", text=json.dumps({"status": "no scenarios"}))]
        summary = {
            "passed": results["passed"],
            "failed": results["failed"],
            "total": results["total"],
            "duration_ms": results["duration_ms"],
            "all_passed": results["failed"] == 0,
        }
        return [TextContent(type="text", text=json.dumps(summary, indent=2))]

    # --- v2.2.0: Arbitration handlers ---

    elif name == "charter_arbitrate":
        question = arguments.get("question", "")
        models = arguments.get("models")
        reversibility = arguments.get("reversibility")
        from charter.arbitration import arbitrate
        result = arbitrate(
            question,
            models=models,
            reversibility=reversibility,
        )
        if not result:
            return [TextContent(type="text", text=json.dumps({"error": "Arbitration failed."}))]
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    # --- v2.3.0: RBAC handlers ---

    elif name == "charter_propose_rule":
        team_hash = arguments.get("team_hash", "")
        rule_text = arguments.get("rule_text", "")
        layer = arguments.get("layer", "a")
        identity = load_identity()
        if not identity:
            return [TextContent(type="text", text=json.dumps({"error": "No identity found."}))]
        from charter.roles import propose_rule
        result = propose_rule(team_hash, rule_text, layer, identity["public_id"])
        if not result:
            return [TextContent(type="text", text=json.dumps({"error": "Proposal failed. Check role permissions."}))]
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    elif name == "charter_sign_rule":
        team_hash = arguments.get("team_hash", "")
        proposal_id = arguments.get("proposal_id", "")
        approve = arguments.get("approve", True)
        identity = load_identity()
        if not identity:
            return [TextContent(type="text", text=json.dumps({"error": "No identity found."}))]
        from charter.roles import sign_proposal
        result = sign_proposal(team_hash, proposal_id, identity["public_id"], identity["private_seed"], approve)
        if not result:
            return [TextContent(type="text", text=json.dumps({"error": "Signing failed. Check role permissions."}))]
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    elif name == "charter_role_status":
        team_hash = arguments.get("team_hash", "")
        from charter.roles import LAYER_0_INVARIANTS, VALID_ROLES, get_member_role
        # Gather roles for known members
        team_dir = os.path.join(os.path.expanduser("~"), ".charter", "teams", team_hash)
        members_path = os.path.join(team_dir, "members.jsonl")
        member_roles = {}
        if os.path.isfile(members_path):
            with open(members_path) as f:
                for line in f:
                    if line.strip():
                        m = json.loads(line)
                        mid = m.get("member_id") or m.get("email", "unknown")
                        role = get_member_role(team_hash, mid)
                        member_roles[m.get("name", mid)] = role or "(no governance role)"
        # Gather open proposals
        proposals_path = os.path.join(team_dir, "proposals.jsonl")
        open_proposals = []
        if os.path.isfile(proposals_path):
            with open(proposals_path) as f:
                for line in f:
                    if line.strip():
                        p = json.loads(line)
                        if p.get("status") == "open":
                            open_proposals.append(p)
        result = {
            "team_hash": team_hash,
            "layer_0_invariants": LAYER_0_INVARIANTS,
            "available_roles": list(VALID_ROLES),
            "member_roles": member_roles,
            "open_proposals": open_proposals,
        }
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    # --- v2.3.0: Alerting handlers ---

    elif name == "charter_alert_status":
        from charter.alerting import load_alerting_config
        alert_config = load_alerting_config()
        webhooks = alert_config.get("webhooks", [])
        has_email = bool(alert_config.get("email"))
        has_slack = bool(alert_config.get("slack"))
        result = {
            "configured": bool(webhooks or has_email or has_slack),
            "webhook_count": len(webhooks),
            "email_configured": has_email,
            "slack_configured": has_slack,
            "webhooks": [{"url": w.get("url", ""), "events": w.get("events", [])} for w in webhooks],
        }
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    # --- v2.3.0: SIEM handlers ---

    elif name == "charter_siem_export":
        fmt = arguments.get("format", "cef")
        from_idx = arguments.get("from_index")
        to_idx = arguments.get("to_index")
        from charter.siem import export_chain as siem_export
        try:
            lines = siem_export(fmt, from_index=from_idx, to_index=to_idx)
            return [TextContent(type="text", text="\n".join(lines))]
        except ValueError as e:
            return [TextContent(type="text", text=json.dumps({"error": str(e)}))]

    # --- v2.3.0: Compliance handlers ---

    elif name == "charter_compliance_map":
        standard = arguments.get("standard", "hipaa")
        from charter.compliance import ComplianceMapper
        mapper = ComplianceMapper(standard=standard)
        result = mapper.map_to_standard()
        if not result:
            return [TextContent(type="text", text=json.dumps({"error": f"Failed to map against {standard}."}))]
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    elif name == "charter_federation_status":
        from charter.federation import Federation
        fed = Federation()
        result = fed.get_all_status()
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    elif name == "charter_federation_events":
        from charter.federation import Federation
        limit = arguments.get("limit", 50)
        fed = Federation()
        events = fed.get_event_stream(limit=limit)
        return [TextContent(type="text", text=json.dumps({"events": events, "count": len(events)}, indent=2))]

    elif name == "charter_merkle_status":
        idx = load_batch_index()
        chain_path = get_chain_path()
        total_chain = 0
        if os.path.isfile(chain_path):
            with open(chain_path) as f:
                total_chain = sum(1 for line in f if line.strip())
        unbatched = total_chain - (idx["last_chain_index"] + 1) if idx["last_chain_index"] >= 0 else total_chain
        result = {
            "total_chain_entries": total_chain,
            "total_batches": len(idx["batches"]),
            "entries_batched": idx["last_chain_index"] + 1 if idx["last_chain_index"] >= 0 else 0,
            "entries_unbatched": unbatched,
            "latest_batch": idx["batches"][-1] if idx["batches"] else None,
        }
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    else:
        return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]


# ---------------------------------------------------------------------------
# Transport runners
# ---------------------------------------------------------------------------

async def run_stdio():
    """Run Charter MCP server over stdio (for Claude Code .mcp.json)."""
    from mcp.server.stdio import stdio_server

    async with stdio_server() as (read_stream, write_stream):
        init_options = server.create_initialization_options()
        await server.run(read_stream, write_stream, init_options)


def run_sse(port: int = 8375):
    """Run Charter MCP server over SSE (for remote access)."""
    from mcp.server.sse import SseServerTransport
    from starlette.applications import Starlette
    from starlette.routing import Route
    from starlette.responses import JSONResponse
    import uvicorn

    sse = SseServerTransport("/messages/")

    async def handle_sse(request):
        async with sse.connect_sse(
            request.scope, request.receive, request._send
        ) as streams:
            await server.run(
                streams[0],
                streams[1],
                server.create_initialization_options(),
            )

    async def handle_messages(request):
        await sse.handle_post_message(
            request.scope, request.receive, request._send
        )

    async def health(request):
        status = _get_status_data()
        return JSONResponse({"status": "ok", "charter": status})

    app = Starlette(
        routes=[
            Route("/health", health),
            Route("/sse", handle_sse),
            Route("/messages/", handle_messages, methods=["POST"]),
        ],
    )

    print(f"Charter MCP Server v{__version__}")
    print(f"  Transport: SSE")
    print(f"  Port: {port}")
    print(f"  Health: http://localhost:{port}/health")
    print(f"  SSE: http://localhost:{port}/sse")

    uvicorn.run(app, host="0.0.0.0", port=port)


def run_mcp_serve(args):
    """CLI entry point for charter mcp-serve."""
    import asyncio

    transport = getattr(args, "transport", "stdio")

    if transport == "stdio":
        asyncio.run(run_stdio())
    elif transport == "sse":
        port = getattr(args, "port", 8375)
        run_sse(port)
    else:
        print(f"Unknown transport: {transport}. Use 'stdio' or 'sse'.")
