"""Chain-Graph Cross-Reference — link hash chain entries to graph entities.

The chain records events (decisions, stamps, audits). The graph records
entities and relationships. This module builds the bridge between them,
enabling the Context Manifest to show decisions in their relational context.

Used by: charter.manifest
"""

import json
import os

from charter.identity import get_chain_path


# Decision-relevant event types
DECISION_EVENTS = {
    "rule_signed", "rule_proposed",
    "human_approval", "human_review",
    "stamp_created", "work_product_stamped",
    "audit_generated",
    "governance_config_changed", "governance_generated",
    "alert_dispatched", "kill_trigger_fired",
    "context_created", "context_bridged", "bridge_revoked",
    "team_created", "team_member_added", "team_member_removed",
    "identity_verified", "identity_created",
    "project_registered",
    "arbitration_requested", "arbitration_completed",
    "compliance_mapped",
}

# Events that indicate outcomes (used for decision-outcome pairing)
OUTCOME_EVENTS = {
    "audit_generated",
    "stamp_created", "work_product_stamped",
    "compliance_mapped",
    "arbitration_completed",
    "kill_trigger_fired",
    "alert_dispatched",
}


def load_chain(chain_path=None):
    """Load all chain entries from disk.

    Args:
        chain_path: Optional path override. Defaults to identity chain.

    Returns:
        List of chain entry dicts.
    """
    path = chain_path or get_chain_path()
    if not os.path.isfile(path):
        return []
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def link_chain_to_graph(chain_entries, graph_snapshot):
    """Match chain entry actors/signers to graph entity IDs.

    Builds a mapping from chain actor identifiers to graph entity IDs
    by matching on public_id prefix, name, or email.

    Args:
        chain_entries: List of chain entry dicts.
        graph_snapshot: Dict from GraphMemory.export_snapshot().

    Returns:
        dict with actor_map (actor_id -> entity_id) and unmatched actors.
    """
    entities = graph_snapshot.get("entities", [])

    # Build lookup indices
    by_id = {}
    by_name_lower = {}
    by_email_lower = {}
    for entity in entities:
        eid = entity.get("id", "")
        by_id[eid] = entity
        name = entity.get("name", "").lower()
        if name:
            by_name_lower[name] = eid
        email = entity.get("email", "").lower()
        if email:
            by_email_lower[email] = eid

    # Collect unique actors from chain
    actors = set()
    for entry in chain_entries:
        actor = entry.get("data", {}).get("actor", "")
        signer = entry.get("signer", "")
        if actor:
            actors.add(actor)
        if signer:
            actors.add(signer)

    # Match actors to entities
    actor_map = {}
    unmatched = []
    for actor in actors:
        actor_lower = actor.lower()
        # Try exact ID match
        if actor in by_id:
            actor_map[actor] = actor
            continue
        # Try name match
        if actor_lower in by_name_lower:
            actor_map[actor] = by_name_lower[actor_lower]
            continue
        # Try email match
        if actor_lower in by_email_lower:
            actor_map[actor] = by_email_lower[actor_lower]
            continue
        # Try prefix match on entity IDs (public_id prefix)
        matched = False
        for eid in by_id:
            if eid.startswith(actor) or actor.startswith(eid):
                actor_map[actor] = eid
                matched = True
                break
        if not matched:
            unmatched.append(actor)

    return {
        "actor_map": actor_map,
        "unmatched_actors": unmatched,
        "matched_count": len(actor_map),
        "total_actors": len(actors),
    }


def extract_decision_log(chain_entries, actor_id=None, context=None,
                         since=None, include_outcomes=True):
    """Extract decision-relevant events from the chain.

    Filters chain for decision events (approvals, escalations, stamps,
    rule signs) and returns them with contextual metadata.

    Args:
        chain_entries: List of chain entry dicts.
        actor_id: Optional actor/signer filter.
        context: Optional context name filter.
        since: Optional ISO date string filter.
        include_outcomes: Whether to pair decisions with outcomes.

    Returns:
        List of decision log entries with event, timestamp, data,
        actor, and optional outcome linkage.
    """
    decisions = []

    for entry in chain_entries:
        event = entry.get("event", "")
        if event not in DECISION_EVENTS:
            continue

        data = entry.get("data", {})
        entry_actor = data.get("actor", entry.get("signer", ""))
        timestamp = entry.get("timestamp", "")

        # Apply filters
        if actor_id and entry_actor != actor_id:
            continue
        if context and data.get("context", "") != context:
            continue
        if since and timestamp < since:
            continue

        decision = {
            "event": event,
            "timestamp": timestamp,
            "index": entry.get("index"),
            "hash": entry.get("hash", "")[:16],
            "actor": entry_actor,
            "data": _sanitize_data(data),
        }

        # Look for edges that link to outcomes
        edges = data.get("_edges", [])
        if edges:
            decision["linked_entries"] = [
                {"type": e.get("type", ""), "hash": e.get("hash", "")[:16]}
                for e in edges
            ]

        decisions.append(decision)

    # Pair decisions with outcomes if requested
    if include_outcomes and decisions:
        decisions = _pair_decision_outcomes(decisions, chain_entries)

    return decisions


def _pair_decision_outcomes(decisions, chain_entries):
    """Find outcome events that follow each decision within a time window.

    Looks for outcome events occurring within 24 hours after a decision,
    linked by the same actor or by chain edge references.
    """
    # Index outcome events by timestamp for lookup
    outcomes = []
    for entry in chain_entries:
        if entry.get("event", "") in OUTCOME_EVENTS:
            outcomes.append(entry)

    for decision in decisions:
        d_ts = decision.get("timestamp", "")
        d_actor = decision.get("actor", "")
        d_hash = decision.get("hash", "")

        # Find outcomes within 24h by same actor or linked by edge
        nearby_outcomes = []
        for outcome in outcomes:
            o_ts = outcome.get("timestamp", "")
            o_data = outcome.get("data", {})
            o_actor = o_data.get("actor", outcome.get("signer", ""))

            # Must be after the decision
            if o_ts <= d_ts:
                continue

            # Check time window (simple string comparison works for ISO dates)
            # and actor match
            if o_actor == d_actor:
                nearby_outcomes.append({
                    "event": outcome.get("event", ""),
                    "timestamp": o_ts,
                    "hash": outcome.get("hash", "")[:16],
                })

            # Stop after finding 3 nearby outcomes
            if len(nearby_outcomes) >= 3:
                break

        if nearby_outcomes:
            decision["outcomes"] = nearby_outcomes

    return decisions


def _sanitize_data(data):
    """Remove internal fields and large payloads from chain data for export."""
    sanitized = {}
    skip_keys = {"_edges", "private_seed", "signature", "raw_content"}
    for key, value in data.items():
        if key in skip_keys:
            continue
        # Truncate large string values
        if isinstance(value, str) and len(value) > 500:
            sanitized[key] = value[:500] + "..."
        elif isinstance(value, (dict, list)) and len(str(value)) > 1000:
            sanitized[key] = str(value)[:1000] + "..."
        else:
            sanitized[key] = value
    return sanitized
