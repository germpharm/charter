"""Role-Based Access Control, Dual Signoff, and Layer 0 Invariants.

Layer 0 defines truly immutable invariants that are hardcoded in Python.
No CLI command, MCP tool, configuration change, or dual signoff process
can modify them. They are the structural foundation beneath Layer A.

Governance Roles (operator, reviewer, auditor, observer) control who can
propose new rules, sign off on proposals, assign roles, and view the
audit trail. All role assignments and rule proposals are logged to the
team's hash chain for tamper-evident accountability.

Dual Signoff requires two authorized signatures (approvals) before any
proposed rule change takes effect. A single rejection from any signer
immediately rejects the proposal. This prevents unilateral rule changes
while keeping the governance process lightweight.

Storage:
    ~/.charter/teams/<team_hash>/roles.jsonl     — role assignment log
    ~/.charter/teams/<team_hash>/proposals.jsonl  — rule proposals
    ~/.charter/teams/<team_hash>/signatures.jsonl — signoff records

Usage:
    charter roles assign <team> <member> <role>
    charter roles propose <team> --rule "..." --layer a
    charter roles sign <team> <proposal_id> --approve/--reject
    charter roles status <team>
    charter roles invariants
"""

import hashlib
import json
import os
import re
import time


# ---------------------------------------------------------------------------
# Layer 0 — Truly Immutable Invariants
# ---------------------------------------------------------------------------
# These are hardcoded. They cannot be modified by any mechanism: no CLI,
# no MCP tool, no config file, no dual signoff. They are the bedrock.

LAYER_0_INVARIANTS = [
    "Audit trail cannot be disabled",
    "Kill triggers cannot be removed",
    "Layer 0 invariants cannot be modified",
    "Identity signing key cannot be exported without dual signoff",
    "Chain integrity verification cannot be bypassed",
]

# Keyword patterns used by enforce_layer_0 to detect violations.
# Each tuple is (compiled_regex, invariant_index, exception_pattern_or_None).
_LAYER_0_PATTERNS = [
    (re.compile(r"(disable|remove|delete)\s+audit", re.IGNORECASE), 0, None),
    (re.compile(r"(remove|disable|delete)\s+kill", re.IGNORECASE), 1, None),
    (re.compile(r"(modify|change)\s+layer\s*0", re.IGNORECASE), 2, None),
    (re.compile(r"edit\s+invariant", re.IGNORECASE), 2, None),
    (re.compile(r"export.*key", re.IGNORECASE), 3, re.compile(r"dual\s+signoff", re.IGNORECASE)),
    (re.compile(r"extract.*seed", re.IGNORECASE), 3, re.compile(r"dual\s+signoff", re.IGNORECASE)),
    (re.compile(r"bypass.*verification", re.IGNORECASE), 4, None),
    (re.compile(r"skip.*integrity", re.IGNORECASE), 4, None),
]


# ---------------------------------------------------------------------------
# Roles — Permission Model
# ---------------------------------------------------------------------------

VALID_ROLES = ("operator", "reviewer", "auditor", "observer")

# Permission matrix: role -> set of capabilities
_PERMISSIONS = {
    "operator": {"propose_rules", "sign_vote", "assign_roles", "view_audit"},
    "reviewer": {"propose_rules", "sign_vote", "view_audit"},
    "auditor":  {"view_audit"},
    "observer": {"view_audit_readonly"},
}


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _load_identity():
    """Load the current user's Charter identity."""
    from charter.identity import load_identity
    return load_identity()


def _append_to_chain(event, data):
    """Append an event to the global hash chain."""
    from charter.identity import append_to_chain
    return append_to_chain(event, data)


def _sign_data(data, private_seed):
    """Sign data with HMAC-SHA256 using the private seed."""
    from charter.identity import sign_data
    return sign_data(data, private_seed)


def _now():
    """Current UTC timestamp in ISO 8601 format."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _append_jsonl(path, record):
    """Append a JSON record to a JSONL file, creating it if needed."""
    parent = os.path.dirname(path)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(record) + "\n")


def _read_jsonl(path):
    """Read all records from a JSONL file. Returns [] if missing."""
    if not os.path.isfile(path):
        return []
    records = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _has_permission(role, permission):
    """Check whether a role has a specific permission."""
    if role not in _PERMISSIONS:
        return False
    return permission in _PERMISSIONS[role]


# ---------------------------------------------------------------------------
# Directory helpers
# ---------------------------------------------------------------------------

def get_teams_dir():
    """Get the path to the Charter teams directory.

    Returns:
        str: Absolute path to ~/.charter/teams
    """
    return os.path.join(os.path.expanduser("~"), ".charter", "teams")


def get_team_dir(team_hash):
    """Get the directory for a specific team.

    Args:
        team_hash: SHA-256 hash identifying the team.

    Returns:
        str: Absolute path to ~/.charter/teams/<team_hash>
    """
    return os.path.join(get_teams_dir(), team_hash)


def _roles_path(team_hash):
    """Path to a team's roles.jsonl."""
    return os.path.join(get_team_dir(team_hash), "roles.jsonl")


def _proposals_path(team_hash):
    """Path to a team's proposals.jsonl."""
    return os.path.join(get_team_dir(team_hash), "proposals.jsonl")


def _signatures_path(team_hash):
    """Path to a team's signatures.jsonl."""
    return os.path.join(get_team_dir(team_hash), "signatures.jsonl")


# ---------------------------------------------------------------------------
# Layer 0 enforcement
# ---------------------------------------------------------------------------

def enforce_layer_0(action_description):
    """Check whether an action would violate a Layer 0 invariant.

    Layer 0 invariants are hardcoded and cannot be overridden by any
    mechanism. This function performs keyword-based matching against the
    action description to detect violations.

    Args:
        action_description: A human-readable string describing the
            intended action (e.g. "disable audit trail logging").

    Returns:
        dict: ``{"allowed": True}`` if the action is safe, or
        ``{"allowed": False, "invariant": "..."}`` if the action would
        violate a Layer 0 invariant.
    """
    if not action_description or not isinstance(action_description, str):
        return {"allowed": True}

    for pattern, invariant_idx, exception_pattern in _LAYER_0_PATTERNS:
        if pattern.search(action_description):
            # Some invariants have exception conditions
            if exception_pattern and exception_pattern.search(action_description):
                continue
            return {
                "allowed": False,
                "invariant": LAYER_0_INVARIANTS[invariant_idx],
            }

    return {"allowed": True}


# ---------------------------------------------------------------------------
# Layer A validation
# ---------------------------------------------------------------------------

def validate_layer_a_modification(current_rules, proposed_rules):
    """Validate a proposed modification to Layer A (hard constraint) rules.

    Layer A modifications are additive only. Existing rules cannot be
    removed or weakened — only new rules can be appended. This function
    verifies that every rule in ``current_rules`` is still present in
    ``proposed_rules``.

    Args:
        current_rules: List of current rule strings.
        proposed_rules: List of proposed rule strings.

    Returns:
        dict: ``{"valid": True, "errors": []}`` if the modification is
        acceptable, or ``{"valid": False, "errors": [...]}`` listing
        every current rule that would be removed.
    """
    if not isinstance(current_rules, list) or not isinstance(proposed_rules, list):
        return {
            "valid": False,
            "errors": ["current_rules and proposed_rules must both be lists"],
        }

    errors = []
    proposed_set = set(proposed_rules)

    for rule in current_rules:
        if rule not in proposed_set:
            errors.append("Rule would be removed: {}".format(rule))

    return {
        "valid": len(errors) == 0,
        "errors": errors,
    }


# ---------------------------------------------------------------------------
# Role assignment
# ---------------------------------------------------------------------------

def assign_role(team_hash, member_id, role, assigner_id):
    """Assign a governance role to a team member.

    Only members with the ``operator`` role can assign roles. The
    assignment is appended to ``roles.jsonl`` and logged to the global
    hash chain.

    Args:
        team_hash: SHA-256 hash identifying the team.
        member_id: Public ID of the member receiving the role.
        role: One of ``operator``, ``reviewer``, ``auditor``, ``observer``.
        assigner_id: Public ID of the member performing the assignment.

    Returns:
        dict: The role entry that was recorded, or None if the operation
        failed (invalid role, insufficient permissions, or missing team).
    """
    if role not in VALID_ROLES:
        return None

    # Verify the team directory exists
    team_dir = get_team_dir(team_hash)
    if not os.path.isdir(team_dir):
        return None

    # Verify the assigner has operator permissions.
    # The first assignment in a team (no roles.jsonl yet) is allowed if
    # the assigner is the team creator (bootstrap case).
    assigner_role = get_member_role(team_hash, assigner_id)
    if assigner_role is not None and not _has_permission(assigner_role, "assign_roles"):
        return None
    # If assigner_role is None, allow it only if no roles have been
    # assigned yet (bootstrap: team creator makes the first assignments).
    if assigner_role is None:
        existing = _read_jsonl(_roles_path(team_hash))
        if len(existing) > 0:
            # Roles exist but assigner has none — not authorized
            return None

    timestamp = _now()
    entry = {
        "event": "role_assigned",
        "team_hash": team_hash,
        "member_id": member_id,
        "role": role,
        "assigned_by": assigner_id,
        "assigned_at": timestamp,
    }

    _append_jsonl(_roles_path(team_hash), entry)

    # Log to global chain
    _append_to_chain("role_assigned", {
        "team_hash": team_hash,
        "member_id": member_id,
        "role": role,
        "assigned_by": assigner_id,
    })

    return entry


def get_member_role(team_hash, member_id):
    """Get the current governance role for a team member.

    Reads ``roles.jsonl`` and returns the most recently assigned role
    for the given member. Returns None if the member has no role.

    Args:
        team_hash: SHA-256 hash identifying the team.
        member_id: Public ID of the member.

    Returns:
        str | None: The member's current role, or None.
    """
    records = _read_jsonl(_roles_path(team_hash))
    latest_role = None
    for record in records:
        if record.get("member_id") == member_id and record.get("event") == "role_assigned":
            latest_role = record.get("role")
    return latest_role


# ---------------------------------------------------------------------------
# Rule proposals
# ---------------------------------------------------------------------------

def propose_rule(team_hash, rule_text, layer, proposer_id):
    """Create a proposal for a new governance rule.

    Only members with ``operator`` or ``reviewer`` roles can propose
    rules. The proposal is appended to ``proposals.jsonl`` and logged
    to the global hash chain. It requires dual signoff (two approving
    signatures) before taking effect.

    Args:
        team_hash: SHA-256 hash identifying the team.
        rule_text: The text of the proposed rule.
        layer: ``"a"`` for Layer A (hard constraint) or ``"b"`` for
            Layer B (gradient decision).
        proposer_id: Public ID of the member creating the proposal.

    Returns:
        dict: The proposal record, or None if the operation failed
        (invalid layer, insufficient permissions, or missing team).
    """
    if layer not in ("a", "b"):
        return None

    # Verify team exists
    team_dir = get_team_dir(team_hash)
    if not os.path.isdir(team_dir):
        return None

    # Verify proposer permissions
    proposer_role = get_member_role(team_hash, proposer_id)
    if proposer_role is None or not _has_permission(proposer_role, "propose_rules"):
        return None

    # Layer 0 check: make sure the proposed rule text itself does not
    # attempt to weaken Layer 0 invariants.
    l0_check = enforce_layer_0(rule_text)
    if not l0_check["allowed"]:
        return None

    timestamp = _now()
    proposal_id = hashlib.sha256(
        "{}{}".format(rule_text, time.time_ns()).encode()
    ).hexdigest()[:16]

    proposal = {
        "proposal_id": proposal_id,
        "rule_text": rule_text,
        "layer": layer,
        "proposed_by": proposer_id,
        "proposed_at": timestamp,
        "status": "open",
        "required_signatures": 2,
    }

    _append_jsonl(_proposals_path(team_hash), proposal)

    # Log to global chain
    _append_to_chain("rule_proposed", {
        "team_hash": team_hash,
        "proposal_id": proposal_id,
        "rule_text": rule_text,
        "layer": layer,
        "proposed_by": proposer_id,
    })

    return proposal


def get_proposal(team_hash, proposal_id):
    """Find and return a proposal by its ID.

    Reads ``proposals.jsonl`` and returns the matching proposal record.
    If the proposal has been updated (approved/rejected), the latest
    state is returned.

    Args:
        team_hash: SHA-256 hash identifying the team.
        proposal_id: The 16-character hex proposal identifier.

    Returns:
        dict | None: The proposal record, or None if not found.
    """
    records = _read_jsonl(_proposals_path(team_hash))
    latest = None
    for record in records:
        if record.get("proposal_id") == proposal_id:
            latest = record
    return latest


def _update_proposal_status(team_hash, proposal_id, new_status):
    """Write an updated proposal record to proposals.jsonl.

    Rather than modifying the original record in place (which would
    break the append-only model), this appends a new record with the
    same proposal_id and the updated status. get_proposal() returns
    the latest record for any given proposal_id.
    """
    proposal = get_proposal(team_hash, proposal_id)
    if not proposal:
        return None
    updated = dict(proposal)
    updated["status"] = new_status
    updated["status_changed_at"] = _now()
    _append_jsonl(_proposals_path(team_hash), updated)
    return updated


# ---------------------------------------------------------------------------
# Signatures / Dual Signoff
# ---------------------------------------------------------------------------

def sign_proposal(team_hash, proposal_id, signer_id, signer_seed, approve=True):
    """Sign (approve or reject) a governance proposal.

    Only members with the ``sign_vote`` permission (operators and
    reviewers) can sign proposals. The signature is HMAC-SHA256 of the
    proposal_id using the signer's private seed.

    After each signature, the signoff threshold is checked:
    - If enough approving signatures are collected, the proposal is
      marked ``approved`` and ``rule_applied`` is logged to the chain.
    - If any signature rejects, the proposal is immediately marked
      ``rejected`` and ``rule_rejected`` is logged.

    Args:
        team_hash: SHA-256 hash identifying the team.
        proposal_id: The 16-character hex proposal identifier.
        signer_id: Public ID of the signer.
        signer_seed: Private seed (hex string) for HMAC signing.
        approve: True to approve, False to reject.

    Returns:
        dict: The signature record, or None if the operation failed
        (proposal not found, already resolved, insufficient permissions,
        or duplicate signature).
    """
    # Verify proposal exists and is open
    proposal = get_proposal(team_hash, proposal_id)
    if not proposal:
        return None
    if proposal.get("status") != "open":
        return None

    # Verify signer permissions
    signer_role = get_member_role(team_hash, signer_id)
    if signer_role is None or not _has_permission(signer_role, "sign_vote"):
        return None

    # Prevent duplicate signatures from the same signer
    existing_sigs = get_proposal_signatures(team_hash, proposal_id)
    for sig in existing_sigs:
        if sig.get("signer_id") == signer_id:
            return None

    # Create HMAC signature of the proposal_id
    import hmac
    hmac_sig = hmac.new(
        bytes.fromhex(signer_seed),
        proposal_id.encode(),
        hashlib.sha256,
    ).hexdigest()

    timestamp = _now()
    signature = {
        "proposal_id": proposal_id,
        "signer_id": signer_id,
        "approve": approve,
        "signature": hmac_sig,
        "signed_at": timestamp,
    }

    _append_jsonl(_signatures_path(team_hash), signature)

    # Log to global chain
    _append_to_chain("rule_signed", {
        "team_hash": team_hash,
        "proposal_id": proposal_id,
        "signer_id": signer_id,
        "approve": approve,
    })

    # Check if threshold has been met after this signature
    threshold = check_signoff_threshold(team_hash, proposal_id)

    if not approve:
        # Any rejection immediately rejects the proposal
        _update_proposal_status(team_hash, proposal_id, "rejected")
        _append_to_chain("rule_rejected", {
            "team_hash": team_hash,
            "proposal_id": proposal_id,
            "rule_text": proposal.get("rule_text"),
            "layer": proposal.get("layer"),
            "rejected_by": signer_id,
        })
    elif threshold["met"]:
        # Enough approvals — mark approved
        _update_proposal_status(team_hash, proposal_id, "approved")
        _append_to_chain("rule_applied", {
            "team_hash": team_hash,
            "proposal_id": proposal_id,
            "rule_text": proposal.get("rule_text"),
            "layer": proposal.get("layer"),
            "approvals": threshold["approvals"],
        })

    return signature


def get_proposal_signatures(team_hash, proposal_id):
    """Return all signatures for a given proposal.

    Args:
        team_hash: SHA-256 hash identifying the team.
        proposal_id: The 16-character hex proposal identifier.

    Returns:
        list[dict]: All signature records for the proposal.
    """
    records = _read_jsonl(_signatures_path(team_hash))
    return [r for r in records if r.get("proposal_id") == proposal_id]


def check_signoff_threshold(team_hash, proposal_id):
    """Check whether a proposal has met its dual-signoff threshold.

    Args:
        team_hash: SHA-256 hash identifying the team.
        proposal_id: The 16-character hex proposal identifier.

    Returns:
        dict: ``{"met": bool, "approvals": int, "rejections": int,
        "required": int}``
    """
    proposal = get_proposal(team_hash, proposal_id)
    required = proposal.get("required_signatures", 2) if proposal else 2

    sigs = get_proposal_signatures(team_hash, proposal_id)
    approvals = sum(1 for s in sigs if s.get("approve") is True)
    rejections = sum(1 for s in sigs if s.get("approve") is False)

    return {
        "met": approvals >= required,
        "approvals": approvals,
        "rejections": rejections,
        "required": required,
    }


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def get_team_roles(team_hash):
    """Get the current role for every member who has been assigned one.

    Replays ``roles.jsonl`` to compute the latest role per member.

    Args:
        team_hash: SHA-256 hash identifying the team.

    Returns:
        dict: Mapping of member_id -> role string.
    """
    records = _read_jsonl(_roles_path(team_hash))
    roles = {}
    for record in records:
        if record.get("event") == "role_assigned":
            mid = record.get("member_id")
            if mid:
                roles[mid] = record.get("role")
    return roles


def get_open_proposals(team_hash):
    """Get all open (unresolved) proposals for a team.

    Args:
        team_hash: SHA-256 hash identifying the team.

    Returns:
        list[dict]: Open proposal records.
    """
    records = _read_jsonl(_proposals_path(team_hash))
    # Build the latest state per proposal_id
    latest = {}
    for record in records:
        pid = record.get("proposal_id")
        if pid:
            latest[pid] = record
    return [p for p in latest.values() if p.get("status") == "open"]


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def run_roles(args):
    """CLI entry point for ``charter roles``.

    Dispatches based on ``args.action``:
        assign     — Assign a governance role to a team member.
        propose    — Propose a new Layer A or Layer B rule.
        sign       — Approve or reject a proposal.
        status     — Show team roles and open proposals.
        invariants — Print Layer 0 invariants.
    """
    action = getattr(args, "action", None)

    if action == "invariants":
        _cli_invariants()
        return

    if action == "assign":
        _cli_assign(args)
    elif action == "propose":
        _cli_propose(args)
    elif action == "sign":
        _cli_sign(args)
    elif action == "status":
        _cli_status(args)
    else:
        print("Unknown action: {}".format(action))
        print("Valid actions: assign, propose, sign, status, invariants")


def _cli_invariants():
    """Print Layer 0 invariants."""
    print("Layer 0 — Immutable Invariants")
    print("=" * 50)
    print()
    print("These invariants are hardcoded. No CLI command, MCP tool,")
    print("configuration change, or dual signoff can modify them.")
    print()
    for i, invariant in enumerate(LAYER_0_INVARIANTS):
        print("  {}. {}".format(i, invariant))
    print()


def _cli_assign(args):
    """Handle ``charter roles assign``."""
    identity = _load_identity()
    if not identity:
        print("No Charter identity found. Run 'charter init' first.")
        return

    team_hash = getattr(args, "team", None)
    member_id = getattr(args, "member", None)
    role = getattr(args, "role", None)

    if not team_hash or not member_id or not role:
        print("Usage: charter roles assign --team <hash> --member <id> --role <role>")
        return

    if role not in VALID_ROLES:
        print("Invalid role: {}".format(role))
        print("Valid roles: {}".format(", ".join(VALID_ROLES)))
        return

    result = assign_role(team_hash, member_id, role, identity["public_id"])
    if result:
        print("Role assigned.")
        print("  Team:    {}".format(team_hash[:16])
              + "...")
        print("  Member:  {}".format(member_id[:16])
              + "...")
        print("  Role:    {}".format(role))
        print("  By:      {}".format(identity["public_id"][:16])
              + "...")
    else:
        print("Failed to assign role.")
        print("Possible reasons:")
        print("  - You do not have the 'operator' role on this team")
        print("  - The team does not exist")
        print("  - The role is invalid")


def _cli_propose(args):
    """Handle ``charter roles propose``."""
    identity = _load_identity()
    if not identity:
        print("No Charter identity found. Run 'charter init' first.")
        return

    team_hash = getattr(args, "team", None)
    rule_text = getattr(args, "rule", None)
    layer = getattr(args, "layer", None)

    if not team_hash or not rule_text or not layer:
        print("Usage: charter roles propose --team <hash> --rule \"...\" --layer a|b")
        return

    if layer not in ("a", "b"):
        print("Invalid layer: {}. Must be 'a' or 'b'.".format(layer))
        return

    # Layer 0 pre-check for user feedback
    l0_check = enforce_layer_0(rule_text)
    if not l0_check["allowed"]:
        print("BLOCKED by Layer 0 invariant:")
        print("  {}".format(l0_check["invariant"]))
        print()
        print("This invariant is hardcoded and cannot be overridden.")
        return

    result = propose_rule(team_hash, rule_text, layer, identity["public_id"])
    if result:
        print("Proposal created.")
        print("  ID:       {}".format(result["proposal_id"]))
        print("  Layer:    {}".format(result["layer"].upper()))
        print("  Rule:     {}".format(result["rule_text"]))
        print("  Status:   {}".format(result["status"]))
        print("  Required: {} signatures".format(result["required_signatures"]))
        print()
        print("Share the proposal ID with team members for signoff:")
        print("  charter roles sign --team {} --proposal {}".format(
            team_hash[:16] + "...", result["proposal_id"]
        ))
    else:
        print("Failed to create proposal.")
        print("Possible reasons:")
        print("  - You do not have 'operator' or 'reviewer' role")
        print("  - The team does not exist")
        print("  - The rule conflicts with Layer 0 invariants")


def _cli_sign(args):
    """Handle ``charter roles sign``."""
    identity = _load_identity()
    if not identity:
        print("No Charter identity found. Run 'charter init' first.")
        return

    team_hash = getattr(args, "team", None)
    proposal_id = getattr(args, "proposal", None)
    approve = getattr(args, "approve", True)

    if not team_hash or not proposal_id:
        print("Usage: charter roles sign --team <hash> --proposal <id> [--approve|--reject]")
        return

    # Show the proposal before signing
    proposal = get_proposal(team_hash, proposal_id)
    if not proposal:
        print("Proposal {} not found.".format(proposal_id))
        return

    if proposal.get("status") != "open":
        print("Proposal {} is already {}.".format(proposal_id, proposal.get("status")))
        return

    result = sign_proposal(
        team_hash,
        proposal_id,
        identity["public_id"],
        identity["private_seed"],
        approve,
    )

    if result:
        action_word = "Approved" if approve else "Rejected"
        print("{} proposal {}.".format(action_word, proposal_id))
        print("  Rule:  {}".format(proposal.get("rule_text")))
        print("  Layer: {}".format(proposal.get("layer", "").upper()))
        print()

        # Show current threshold status
        threshold = check_signoff_threshold(team_hash, proposal_id)
        updated = get_proposal(team_hash, proposal_id)
        status = updated.get("status", "open") if updated else "open"

        if status == "approved":
            print("  Status: APPROVED (dual signoff complete)")
            print("  The rule is now in effect.")
        elif status == "rejected":
            print("  Status: REJECTED")
            print("  The proposal has been rejected.")
        else:
            print("  Status: open ({}/{} approvals, {} rejections)".format(
                threshold["approvals"],
                threshold["required"],
                threshold["rejections"],
            ))
            print("  Waiting for more signatures.")
    else:
        print("Failed to sign proposal.")
        print("Possible reasons:")
        print("  - You do not have 'operator' or 'reviewer' role")
        print("  - You already signed this proposal")
        print("  - The proposal is no longer open")


def _cli_status(args):
    """Handle ``charter roles status``."""
    team_hash = getattr(args, "team", None)
    if not team_hash:
        print("Usage: charter roles status --team <hash>")
        return

    team_dir = get_team_dir(team_hash)
    if not os.path.isdir(team_dir):
        print("Team {} not found.".format(team_hash[:16]))
        return

    # Load team manifest for display
    manifest_path = os.path.join(team_dir, "team.json")
    team_name = team_hash[:16]
    if os.path.isfile(manifest_path):
        with open(manifest_path) as f:
            manifest = json.load(f)
        team_name = manifest.get("name", team_name)

    print("Governance Status: {}".format(team_name))
    print("=" * 50)

    # Roles
    roles = get_team_roles(team_hash)
    print()
    print("Roles ({} assigned):".format(len(roles)))
    if roles:
        for mid, role in sorted(roles.items(), key=lambda x: x[1]):
            print("  {}...  {}".format(mid[:16], role))
    else:
        print("  (no governance roles assigned yet)")

    # Open proposals
    open_proposals = get_open_proposals(team_hash)
    print()
    print("Open Proposals ({} pending):".format(len(open_proposals)))
    if open_proposals:
        for prop in open_proposals:
            threshold = check_signoff_threshold(team_hash, prop["proposal_id"])
            print("  [{}] Layer {} — {}".format(
                prop["proposal_id"],
                prop.get("layer", "?").upper(),
                prop.get("rule_text", ""),
            ))
            print("       Proposed by: {}...  ({})".format(
                prop.get("proposed_by", "?")[:16],
                prop.get("proposed_at", "?"),
            ))
            print("       Signatures: {}/{} approvals, {} rejections".format(
                threshold["approvals"],
                threshold["required"],
                threshold["rejections"],
            ))
    else:
        print("  (no open proposals)")

    # Layer 0 reminder
    print()
    print("Layer 0 Invariants: {} (immutable, hardcoded)".format(
        len(LAYER_0_INVARIANTS)
    ))
    print("  Run 'charter roles invariants' to view them.")
    print()
