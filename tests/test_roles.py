"""Tests for charter.roles — RBAC, dual signoff, and Layer 0 invariants."""

import json
import os

import pytest

from charter.identity import create_identity
from charter.roles import (
    LAYER_0_INVARIANTS,
    VALID_ROLES,
    enforce_layer_0,
    validate_layer_a_modification,
    assign_role,
    get_member_role,
    propose_rule,
    sign_proposal,
    check_signoff_threshold,
    get_proposal,
    get_proposal_signatures,
    get_team_roles,
    get_open_proposals,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def team_setup(charter_home, tmp_path, monkeypatch):
    """Create a team directory with team.json and an operator identity for testing."""
    import charter.roles as roles_mod

    identity = create_identity(alias="test-operator")
    team_hash = "a" * 64
    team_dir = tmp_path / ".charter" / "teams" / team_hash
    team_dir.mkdir(parents=True)

    # Write a minimal team manifest
    with open(team_dir / "team.json", "w") as f:
        json.dump({"team_hash": team_hash, "name": "Test Team"}, f)

    # Redirect the roles module directory helpers to our temp directory
    monkeypatch.setattr(roles_mod, "get_teams_dir",
                        lambda: str(tmp_path / ".charter" / "teams"))
    monkeypatch.setattr(roles_mod, "get_team_dir",
                        lambda h: str(team_dir))

    return {
        "identity": identity,
        "team_hash": team_hash,
        "team_dir": team_dir,
    }


@pytest.fixture
def operator_setup(team_setup):
    """Bootstrap an operator on the team (first role assignment)."""
    identity = team_setup["identity"]
    team_hash = team_setup["team_hash"]

    # First assignment: creator bootstraps themselves as operator
    result = assign_role(
        team_hash,
        identity["public_id"],
        "operator",
        identity["public_id"],
    )
    assert result is not None

    return team_setup


@pytest.fixture
def second_identity(charter_home):
    """Create a second Charter identity (for dual signoff, etc.).

    Note: create_identity overwrites the identity file, but we only need
    the returned dict to get the public_id and private_seed.
    """
    return create_identity(alias="second-member")


# ---------------------------------------------------------------------------
# TestLayer0Invariants
# ---------------------------------------------------------------------------

class TestLayer0Invariants:
    """Test Layer 0 constants and enforce_layer_0() pattern matching."""

    def test_invariants_count(self):
        assert len(LAYER_0_INVARIANTS) == 5

    def test_invariants_are_strings(self):
        for inv in LAYER_0_INVARIANTS:
            assert isinstance(inv, str)
            assert len(inv) > 0

    def test_valid_roles_tuple(self):
        assert VALID_ROLES == ("operator", "reviewer", "auditor", "observer")

    # -- enforce_layer_0 blocking cases --

    def test_block_disable_audit_trail(self):
        result = enforce_layer_0("disable audit trail")
        assert result["allowed"] is False
        assert result["invariant"] == LAYER_0_INVARIANTS[0]

    def test_block_remove_audit(self):
        result = enforce_layer_0("remove audit logging")
        assert result["allowed"] is False
        assert result["invariant"] == LAYER_0_INVARIANTS[0]

    def test_block_delete_audit(self):
        result = enforce_layer_0("delete audit records")
        assert result["allowed"] is False
        assert result["invariant"] == LAYER_0_INVARIANTS[0]

    def test_block_remove_kill_triggers(self):
        result = enforce_layer_0("remove kill triggers")
        assert result["allowed"] is False
        assert result["invariant"] == LAYER_0_INVARIANTS[1]

    def test_block_disable_kill_triggers(self):
        result = enforce_layer_0("disable kill switch")
        assert result["allowed"] is False
        assert result["invariant"] == LAYER_0_INVARIANTS[1]

    def test_block_modify_layer_0(self):
        result = enforce_layer_0("modify layer 0")
        assert result["allowed"] is False
        assert result["invariant"] == LAYER_0_INVARIANTS[2]

    def test_block_change_layer0(self):
        result = enforce_layer_0("change layer0 rules")
        assert result["allowed"] is False
        assert result["invariant"] == LAYER_0_INVARIANTS[2]

    def test_block_edit_invariant(self):
        result = enforce_layer_0("edit invariant definitions")
        assert result["allowed"] is False
        assert result["invariant"] == LAYER_0_INVARIANTS[2]

    def test_block_export_signing_key(self):
        result = enforce_layer_0("export the signing key")
        assert result["allowed"] is False
        assert result["invariant"] == LAYER_0_INVARIANTS[3]

    def test_block_extract_seed(self):
        result = enforce_layer_0("extract the private seed")
        assert result["allowed"] is False
        assert result["invariant"] == LAYER_0_INVARIANTS[3]

    def test_allow_export_key_with_dual_signoff(self):
        result = enforce_layer_0("export the signing key with dual signoff")
        assert result["allowed"] is True

    def test_allow_extract_seed_with_dual_signoff(self):
        result = enforce_layer_0("extract seed via dual signoff procedure")
        assert result["allowed"] is True

    def test_block_bypass_verification(self):
        result = enforce_layer_0("bypass verification checks")
        assert result["allowed"] is False
        assert result["invariant"] == LAYER_0_INVARIANTS[4]

    def test_block_skip_integrity(self):
        result = enforce_layer_0("skip integrity check")
        assert result["allowed"] is False
        assert result["invariant"] == LAYER_0_INVARIANTS[4]

    # -- enforce_layer_0 allowed cases --

    def test_allow_add_new_rule(self):
        result = enforce_layer_0("add new rule to layer a")
        assert result["allowed"] is True

    def test_allow_benign_action(self):
        result = enforce_layer_0("update the team roster")
        assert result["allowed"] is True

    def test_allow_none_input(self):
        result = enforce_layer_0(None)
        assert result["allowed"] is True

    def test_allow_empty_string(self):
        result = enforce_layer_0("")
        assert result["allowed"] is True

    def test_allow_non_string_input(self):
        result = enforce_layer_0(42)
        assert result["allowed"] is True

    def test_case_insensitive_blocking(self):
        result = enforce_layer_0("DISABLE AUDIT trail")
        assert result["allowed"] is False
        assert result["invariant"] == LAYER_0_INVARIANTS[0]

    def test_case_insensitive_exception(self):
        result = enforce_layer_0("Export Key with DUAL SIGNOFF")
        assert result["allowed"] is True


# ---------------------------------------------------------------------------
# TestLayerAValidation
# ---------------------------------------------------------------------------

class TestLayerAValidation:
    """Test validate_layer_a_modification() — additive-only enforcement."""

    def test_same_rules_valid(self):
        rules = ["Never do X", "Never do Y"]
        result = validate_layer_a_modification(rules, list(rules))
        assert result["valid"] is True
        assert result["errors"] == []

    def test_superset_valid(self):
        current = ["Never do X"]
        proposed = ["Never do X", "Never do Y"]
        result = validate_layer_a_modification(current, proposed)
        assert result["valid"] is True
        assert result["errors"] == []

    def test_subset_invalid(self):
        current = ["Never do X", "Never do Y"]
        proposed = ["Never do X"]
        result = validate_layer_a_modification(current, proposed)
        assert result["valid"] is False
        assert len(result["errors"]) == 1
        assert "Never do Y" in result["errors"][0]

    def test_remove_all_rules_invalid(self):
        current = ["Rule A", "Rule B"]
        proposed = []
        result = validate_layer_a_modification(current, proposed)
        assert result["valid"] is False
        assert len(result["errors"]) == 2

    def test_empty_to_nonempty_valid(self):
        result = validate_layer_a_modification([], ["New rule"])
        assert result["valid"] is True
        assert result["errors"] == []

    def test_both_empty_valid(self):
        result = validate_layer_a_modification([], [])
        assert result["valid"] is True
        assert result["errors"] == []

    def test_non_list_current_rules_invalid(self):
        result = validate_layer_a_modification("not a list", ["rule"])
        assert result["valid"] is False
        assert len(result["errors"]) == 1

    def test_non_list_proposed_rules_invalid(self):
        result = validate_layer_a_modification(["rule"], "not a list")
        assert result["valid"] is False
        assert len(result["errors"]) == 1

    def test_both_non_list_invalid(self):
        result = validate_layer_a_modification(None, None)
        assert result["valid"] is False

    def test_multiple_deletions_reported(self):
        current = ["A", "B", "C"]
        proposed = ["B"]
        result = validate_layer_a_modification(current, proposed)
        assert result["valid"] is False
        assert len(result["errors"]) == 2
        error_text = " ".join(result["errors"])
        assert "A" in error_text
        assert "C" in error_text

    def test_reordered_rules_still_valid(self):
        current = ["Rule A", "Rule B"]
        proposed = ["Rule B", "Rule A"]
        result = validate_layer_a_modification(current, proposed)
        assert result["valid"] is True


# ---------------------------------------------------------------------------
# TestAssignRole
# ---------------------------------------------------------------------------

class TestAssignRole:
    """Test assign_role() — permission checks, bootstrap case, storage."""

    def test_bootstrap_first_assignment(self, team_setup):
        """First role assignment on a team is allowed (bootstrap)."""
        identity = team_setup["identity"]
        team_hash = team_setup["team_hash"]

        result = assign_role(
            team_hash,
            identity["public_id"],
            "operator",
            identity["public_id"],
        )
        assert result is not None
        assert result["event"] == "role_assigned"
        assert result["role"] == "operator"
        assert result["member_id"] == identity["public_id"]
        assert result["assigned_by"] == identity["public_id"]

    def test_operator_can_assign_reviewer(self, operator_setup, second_identity):
        """An operator can assign reviewer to another member."""
        team_hash = operator_setup["team_hash"]
        operator_id = operator_setup["identity"]["public_id"]

        result = assign_role(
            team_hash,
            second_identity["public_id"],
            "reviewer",
            operator_id,
        )
        assert result is not None
        assert result["role"] == "reviewer"
        assert result["member_id"] == second_identity["public_id"]

    def test_operator_can_assign_all_valid_roles(self, operator_setup, second_identity):
        """Operator can assign any of the four valid roles."""
        team_hash = operator_setup["team_hash"]
        operator_id = operator_setup["identity"]["public_id"]

        for role in VALID_ROLES:
            result = assign_role(
                team_hash,
                second_identity["public_id"],
                role,
                operator_id,
            )
            assert result is not None
            assert result["role"] == role

    def test_invalid_role_returns_none(self, operator_setup):
        team_hash = operator_setup["team_hash"]
        operator_id = operator_setup["identity"]["public_id"]

        result = assign_role(team_hash, "member-x", "superadmin", operator_id)
        assert result is None

    def test_non_operator_cannot_assign(self, operator_setup, second_identity):
        """A reviewer cannot assign roles."""
        team_hash = operator_setup["team_hash"]
        operator_id = operator_setup["identity"]["public_id"]

        # First make second_identity a reviewer
        assign_role(
            team_hash,
            second_identity["public_id"],
            "reviewer",
            operator_id,
        )

        # Now reviewer tries to assign a role — should fail
        result = assign_role(
            team_hash,
            "member-z",
            "observer",
            second_identity["public_id"],
        )
        assert result is None

    def test_auditor_cannot_assign(self, operator_setup, second_identity):
        """An auditor cannot assign roles."""
        team_hash = operator_setup["team_hash"]
        operator_id = operator_setup["identity"]["public_id"]

        assign_role(team_hash, second_identity["public_id"], "auditor", operator_id)

        result = assign_role(
            team_hash, "m3", "observer", second_identity["public_id"]
        )
        assert result is None

    def test_observer_cannot_assign(self, operator_setup, second_identity):
        """An observer cannot assign roles."""
        team_hash = operator_setup["team_hash"]
        operator_id = operator_setup["identity"]["public_id"]

        assign_role(team_hash, second_identity["public_id"], "observer", operator_id)

        result = assign_role(
            team_hash, "m3", "reviewer", second_identity["public_id"]
        )
        assert result is None

    def test_unknown_assigner_after_bootstrap_returns_none(self, operator_setup):
        """An unknown member cannot assign roles once roles exist."""
        team_hash = operator_setup["team_hash"]
        result = assign_role(team_hash, "member-x", "observer", "unknown-id")
        assert result is None

    def test_missing_team_returns_none(self, team_setup, monkeypatch):
        """Returns None when team directory does not exist."""
        import charter.roles as roles_mod
        monkeypatch.setattr(roles_mod, "get_team_dir", lambda h: "/nonexistent/path")

        result = assign_role("b" * 64, "member-x", "operator", "assigner-x")
        assert result is None

    def test_role_persisted_to_jsonl(self, team_setup):
        """The role assignment is written to roles.jsonl."""
        identity = team_setup["identity"]
        team_hash = team_setup["team_hash"]
        team_dir = team_setup["team_dir"]

        assign_role(team_hash, identity["public_id"], "operator", identity["public_id"])

        roles_path = os.path.join(str(team_dir), "roles.jsonl")
        assert os.path.isfile(roles_path)

        with open(roles_path) as f:
            lines = [line.strip() for line in f if line.strip()]
        assert len(lines) == 1

        record = json.loads(lines[0])
        assert record["event"] == "role_assigned"
        assert record["role"] == "operator"

    def test_role_reassignment_overwrites(self, operator_setup, second_identity):
        """When a role is reassigned the latest record wins."""
        team_hash = operator_setup["team_hash"]
        operator_id = operator_setup["identity"]["public_id"]

        assign_role(team_hash, second_identity["public_id"], "reviewer", operator_id)
        assign_role(team_hash, second_identity["public_id"], "auditor", operator_id)

        role = get_member_role(team_hash, second_identity["public_id"])
        assert role == "auditor"


# ---------------------------------------------------------------------------
# TestGetMemberRole
# ---------------------------------------------------------------------------

class TestGetMemberRole:
    """Test get_member_role() — replay of roles.jsonl."""

    def test_returns_role_for_known_member(self, operator_setup):
        identity = operator_setup["identity"]
        team_hash = operator_setup["team_hash"]
        role = get_member_role(team_hash, identity["public_id"])
        assert role == "operator"

    def test_returns_none_for_unknown_member(self, operator_setup):
        team_hash = operator_setup["team_hash"]
        role = get_member_role(team_hash, "nonexistent-member-id")
        assert role is None

    def test_returns_latest_role(self, operator_setup, second_identity):
        """If a member is re-assigned, the latest role is returned."""
        team_hash = operator_setup["team_hash"]
        operator_id = operator_setup["identity"]["public_id"]

        assign_role(team_hash, second_identity["public_id"], "reviewer", operator_id)
        assert get_member_role(team_hash, second_identity["public_id"]) == "reviewer"

        assign_role(team_hash, second_identity["public_id"], "observer", operator_id)
        assert get_member_role(team_hash, second_identity["public_id"]) == "observer"

    def test_returns_none_when_no_roles_file(self, team_setup):
        """When roles.jsonl does not exist, returns None."""
        team_hash = team_setup["team_hash"]
        role = get_member_role(team_hash, "any-id")
        assert role is None


# ---------------------------------------------------------------------------
# TestProposeRule
# ---------------------------------------------------------------------------

class TestProposeRule:
    """Test propose_rule() — permissions, layer validation, Layer 0 check."""

    def test_operator_proposes_layer_a_rule(self, operator_setup):
        team_hash = operator_setup["team_hash"]
        operator_id = operator_setup["identity"]["public_id"]

        result = propose_rule(team_hash, "Never leak data", "a", operator_id)
        assert result is not None
        assert result["rule_text"] == "Never leak data"
        assert result["layer"] == "a"
        assert result["status"] == "open"
        assert result["required_signatures"] == 2
        assert len(result["proposal_id"]) == 16

    def test_operator_proposes_layer_b_rule(self, operator_setup):
        team_hash = operator_setup["team_hash"]
        operator_id = operator_setup["identity"]["public_id"]

        result = propose_rule(team_hash, "Require approval for deploys", "b", operator_id)
        assert result is not None
        assert result["layer"] == "b"

    def test_reviewer_can_propose(self, operator_setup, second_identity):
        """Reviewers have propose_rules permission."""
        team_hash = operator_setup["team_hash"]
        operator_id = operator_setup["identity"]["public_id"]

        assign_role(team_hash, second_identity["public_id"], "reviewer", operator_id)

        result = propose_rule(
            team_hash,
            "Require MFA for admin access",
            "a",
            second_identity["public_id"],
        )
        assert result is not None

    def test_auditor_cannot_propose(self, operator_setup, second_identity):
        """Auditors lack propose_rules permission."""
        team_hash = operator_setup["team_hash"]
        operator_id = operator_setup["identity"]["public_id"]

        assign_role(team_hash, second_identity["public_id"], "auditor", operator_id)

        result = propose_rule(
            team_hash,
            "Some rule",
            "a",
            second_identity["public_id"],
        )
        assert result is None

    def test_observer_cannot_propose(self, operator_setup, second_identity):
        """Observers lack propose_rules permission."""
        team_hash = operator_setup["team_hash"]
        operator_id = operator_setup["identity"]["public_id"]

        assign_role(team_hash, second_identity["public_id"], "observer", operator_id)

        result = propose_rule(
            team_hash,
            "Some rule",
            "b",
            second_identity["public_id"],
        )
        assert result is None

    def test_unknown_member_cannot_propose(self, operator_setup):
        team_hash = operator_setup["team_hash"]
        result = propose_rule(team_hash, "Some rule", "a", "unknown-id")
        assert result is None

    def test_invalid_layer_returns_none(self, operator_setup):
        team_hash = operator_setup["team_hash"]
        operator_id = operator_setup["identity"]["public_id"]

        assert propose_rule(team_hash, "Rule", "c", operator_id) is None
        assert propose_rule(team_hash, "Rule", "0", operator_id) is None
        assert propose_rule(team_hash, "Rule", "", operator_id) is None

    def test_layer_0_violation_blocked(self, operator_setup):
        """A rule that would weaken Layer 0 is rejected."""
        team_hash = operator_setup["team_hash"]
        operator_id = operator_setup["identity"]["public_id"]

        result = propose_rule(
            team_hash,
            "disable audit trail for performance",
            "a",
            operator_id,
        )
        assert result is None

    def test_layer_0_bypass_verification_blocked(self, operator_setup):
        team_hash = operator_setup["team_hash"]
        operator_id = operator_setup["identity"]["public_id"]

        result = propose_rule(
            team_hash,
            "bypass verification in staging",
            "b",
            operator_id,
        )
        assert result is None

    def test_missing_team_returns_none(self, team_setup, monkeypatch):
        import charter.roles as roles_mod
        monkeypatch.setattr(roles_mod, "get_team_dir", lambda h: "/nonexistent")
        result = propose_rule("x" * 64, "Rule text", "a", "proposer-id")
        assert result is None

    def test_proposal_persisted_to_jsonl(self, operator_setup):
        team_hash = operator_setup["team_hash"]
        operator_id = operator_setup["identity"]["public_id"]
        team_dir = operator_setup["team_dir"]

        propose_rule(team_hash, "Test rule", "a", operator_id)

        proposals_path = os.path.join(str(team_dir), "proposals.jsonl")
        assert os.path.isfile(proposals_path)

        with open(proposals_path) as f:
            lines = [line.strip() for line in f if line.strip()]
        assert len(lines) == 1

        record = json.loads(lines[0])
        assert record["rule_text"] == "Test rule"
        assert record["status"] == "open"


# ---------------------------------------------------------------------------
# TestSignProposal
# ---------------------------------------------------------------------------

class TestSignProposal:
    """Test sign_proposal() — approve, reject, duplicate prevention, dual signoff."""

    def _make_proposal(self, operator_setup):
        """Helper: create a proposal and return (team_hash, proposal_id, operator_identity)."""
        team_hash = operator_setup["team_hash"]
        operator_id = operator_setup["identity"]["public_id"]
        proposal = propose_rule(team_hash, "Require TLS everywhere", "a", operator_id)
        return team_hash, proposal["proposal_id"], operator_setup["identity"]

    def test_approve_signature(self, operator_setup):
        team_hash, proposal_id, identity = self._make_proposal(operator_setup)

        sig = sign_proposal(
            team_hash,
            proposal_id,
            identity["public_id"],
            identity["private_seed"],
            approve=True,
        )
        assert sig is not None
        assert sig["approve"] is True
        assert sig["proposal_id"] == proposal_id
        assert sig["signer_id"] == identity["public_id"]
        assert len(sig["signature"]) == 64  # HMAC-SHA256 hex digest

    def test_reject_immediately_rejects_proposal(self, operator_setup):
        """A single rejection immediately marks the proposal as rejected."""
        team_hash, proposal_id, identity = self._make_proposal(operator_setup)

        sig = sign_proposal(
            team_hash,
            proposal_id,
            identity["public_id"],
            identity["private_seed"],
            approve=False,
        )
        assert sig is not None
        assert sig["approve"] is False

        # Proposal should now be rejected
        proposal = get_proposal(team_hash, proposal_id)
        assert proposal["status"] == "rejected"

    def test_duplicate_signature_prevented(self, operator_setup):
        """Same signer cannot sign the same proposal twice."""
        team_hash, proposal_id, identity = self._make_proposal(operator_setup)

        first = sign_proposal(
            team_hash,
            proposal_id,
            identity["public_id"],
            identity["private_seed"],
            approve=True,
        )
        assert first is not None

        duplicate = sign_proposal(
            team_hash,
            proposal_id,
            identity["public_id"],
            identity["private_seed"],
            approve=True,
        )
        assert duplicate is None

    def test_dual_signoff_approves_proposal(self, operator_setup, second_identity):
        """Two approving signatures meet the threshold and approve the proposal."""
        team_hash = operator_setup["team_hash"]
        operator = operator_setup["identity"]
        operator_id = operator["public_id"]

        # Add second_identity as reviewer so they can sign
        assign_role(team_hash, second_identity["public_id"], "reviewer", operator_id)

        # Create proposal
        proposal = propose_rule(team_hash, "Require code review", "a", operator_id)
        proposal_id = proposal["proposal_id"]

        # First signature
        sig1 = sign_proposal(
            team_hash, proposal_id, operator_id, operator["private_seed"], approve=True
        )
        assert sig1 is not None

        # Proposal still open after one signature
        p = get_proposal(team_hash, proposal_id)
        assert p["status"] == "open"

        # Second signature
        sig2 = sign_proposal(
            team_hash,
            proposal_id,
            second_identity["public_id"],
            second_identity["private_seed"],
            approve=True,
        )
        assert sig2 is not None

        # Proposal should now be approved
        p = get_proposal(team_hash, proposal_id)
        assert p["status"] == "approved"

    def test_rejection_after_approval_still_rejects(self, operator_setup, second_identity):
        """One approval then one rejection results in rejection."""
        team_hash = operator_setup["team_hash"]
        operator = operator_setup["identity"]
        operator_id = operator["public_id"]

        assign_role(team_hash, second_identity["public_id"], "reviewer", operator_id)

        proposal = propose_rule(team_hash, "Require encryption", "a", operator_id)
        proposal_id = proposal["proposal_id"]

        # First: approve
        sign_proposal(
            team_hash, proposal_id, operator_id, operator["private_seed"], approve=True
        )

        # Second: reject
        sign_proposal(
            team_hash,
            proposal_id,
            second_identity["public_id"],
            second_identity["private_seed"],
            approve=False,
        )

        p = get_proposal(team_hash, proposal_id)
        assert p["status"] == "rejected"

    def test_cannot_sign_nonexistent_proposal(self, operator_setup):
        team_hash = operator_setup["team_hash"]
        identity = operator_setup["identity"]

        result = sign_proposal(
            team_hash,
            "nonexistent1234ab",
            identity["public_id"],
            identity["private_seed"],
            approve=True,
        )
        assert result is None

    def test_cannot_sign_already_approved_proposal(self, operator_setup, second_identity):
        """Once approved, no more signatures are accepted."""
        team_hash = operator_setup["team_hash"]
        operator = operator_setup["identity"]
        operator_id = operator["public_id"]

        assign_role(team_hash, second_identity["public_id"], "reviewer", operator_id)

        proposal = propose_rule(team_hash, "Rule X", "b", operator_id)
        proposal_id = proposal["proposal_id"]

        # Two approvals to finalize
        sign_proposal(team_hash, proposal_id, operator_id, operator["private_seed"], True)
        sign_proposal(
            team_hash, proposal_id,
            second_identity["public_id"], second_identity["private_seed"], True,
        )

        # Create a third identity for the late signer
        third = create_identity(alias="third-member")
        assign_role(team_hash, third["public_id"], "reviewer", operator_id)

        result = sign_proposal(
            team_hash, proposal_id, third["public_id"], third["private_seed"], True
        )
        assert result is None

    def test_cannot_sign_already_rejected_proposal(self, operator_setup, second_identity):
        """Once rejected, no more signatures are accepted."""
        team_hash = operator_setup["team_hash"]
        operator = operator_setup["identity"]
        operator_id = operator["public_id"]

        assign_role(team_hash, second_identity["public_id"], "reviewer", operator_id)

        proposal = propose_rule(team_hash, "Rule Y", "a", operator_id)
        proposal_id = proposal["proposal_id"]

        # Reject
        sign_proposal(team_hash, proposal_id, operator_id, operator["private_seed"], False)

        result = sign_proposal(
            team_hash, proposal_id,
            second_identity["public_id"], second_identity["private_seed"], True,
        )
        assert result is None

    def test_auditor_cannot_sign(self, operator_setup, second_identity):
        """Auditors lack sign_vote permission."""
        team_hash = operator_setup["team_hash"]
        operator = operator_setup["identity"]
        operator_id = operator["public_id"]

        assign_role(team_hash, second_identity["public_id"], "auditor", operator_id)

        proposal = propose_rule(team_hash, "Rule Z", "a", operator_id)
        proposal_id = proposal["proposal_id"]

        result = sign_proposal(
            team_hash, proposal_id,
            second_identity["public_id"], second_identity["private_seed"], True,
        )
        assert result is None

    def test_observer_cannot_sign(self, operator_setup, second_identity):
        """Observers lack sign_vote permission."""
        team_hash = operator_setup["team_hash"]
        operator = operator_setup["identity"]
        operator_id = operator["public_id"]

        assign_role(team_hash, second_identity["public_id"], "observer", operator_id)

        proposal = propose_rule(team_hash, "Rule W", "b", operator_id)
        proposal_id = proposal["proposal_id"]

        result = sign_proposal(
            team_hash, proposal_id,
            second_identity["public_id"], second_identity["private_seed"], True,
        )
        assert result is None

    def test_signature_persisted_to_jsonl(self, operator_setup):
        team_hash, proposal_id, identity = self._make_proposal(operator_setup)
        team_dir = operator_setup["team_dir"]

        sign_proposal(
            team_hash, proposal_id,
            identity["public_id"], identity["private_seed"], True,
        )

        sig_path = os.path.join(str(team_dir), "signatures.jsonl")
        assert os.path.isfile(sig_path)

        with open(sig_path) as f:
            lines = [line.strip() for line in f if line.strip()]
        assert len(lines) == 1

        record = json.loads(lines[0])
        assert record["proposal_id"] == proposal_id
        assert record["approve"] is True


# ---------------------------------------------------------------------------
# TestSignoffThreshold
# ---------------------------------------------------------------------------

class TestSignoffThreshold:
    """Test check_signoff_threshold() — counts and met/not-met logic."""

    def test_no_signatures_not_met(self, operator_setup):
        team_hash = operator_setup["team_hash"]
        operator_id = operator_setup["identity"]["public_id"]

        proposal = propose_rule(team_hash, "Some rule", "a", operator_id)
        result = check_signoff_threshold(team_hash, proposal["proposal_id"])

        assert result["met"] is False
        assert result["approvals"] == 0
        assert result["rejections"] == 0
        assert result["required"] == 2

    def test_one_approval_not_met(self, operator_setup):
        team_hash = operator_setup["team_hash"]
        operator = operator_setup["identity"]

        proposal = propose_rule(team_hash, "Some rule", "a", operator["public_id"])
        sign_proposal(
            team_hash, proposal["proposal_id"],
            operator["public_id"], operator["private_seed"], True,
        )

        result = check_signoff_threshold(team_hash, proposal["proposal_id"])
        assert result["met"] is False
        assert result["approvals"] == 1
        assert result["rejections"] == 0

    def test_two_approvals_met(self, operator_setup, second_identity):
        team_hash = operator_setup["team_hash"]
        operator = operator_setup["identity"]
        operator_id = operator["public_id"]

        assign_role(team_hash, second_identity["public_id"], "reviewer", operator_id)

        proposal = propose_rule(team_hash, "Rule ABC", "a", operator_id)
        pid = proposal["proposal_id"]

        sign_proposal(team_hash, pid, operator_id, operator["private_seed"], True)
        sign_proposal(
            team_hash, pid,
            second_identity["public_id"], second_identity["private_seed"], True,
        )

        result = check_signoff_threshold(team_hash, pid)
        assert result["met"] is True
        assert result["approvals"] == 2
        assert result["rejections"] == 0

    def test_one_rejection_counted(self, operator_setup):
        team_hash = operator_setup["team_hash"]
        operator = operator_setup["identity"]

        proposal = propose_rule(team_hash, "Rule DEF", "b", operator["public_id"])
        sign_proposal(
            team_hash, proposal["proposal_id"],
            operator["public_id"], operator["private_seed"], False,
        )

        result = check_signoff_threshold(team_hash, proposal["proposal_id"])
        assert result["rejections"] == 1
        assert result["approvals"] == 0
        assert result["met"] is False

    def test_nonexistent_proposal_defaults(self, operator_setup):
        team_hash = operator_setup["team_hash"]
        result = check_signoff_threshold(team_hash, "does_not_exist_")
        assert result["met"] is False
        assert result["approvals"] == 0
        assert result["rejections"] == 0
        assert result["required"] == 2


# ---------------------------------------------------------------------------
# TestQueryHelpers
# ---------------------------------------------------------------------------

class TestQueryHelpers:
    """Test get_proposal, get_proposal_signatures, get_team_roles, get_open_proposals."""

    # -- get_proposal --

    def test_get_proposal_found(self, operator_setup):
        team_hash = operator_setup["team_hash"]
        operator_id = operator_setup["identity"]["public_id"]

        created = propose_rule(team_hash, "Rule P", "a", operator_id)
        fetched = get_proposal(team_hash, created["proposal_id"])

        assert fetched is not None
        assert fetched["proposal_id"] == created["proposal_id"]
        assert fetched["rule_text"] == "Rule P"

    def test_get_proposal_not_found(self, operator_setup):
        team_hash = operator_setup["team_hash"]
        assert get_proposal(team_hash, "nonexistent_pid_") is None

    def test_get_proposal_returns_latest_state(self, operator_setup):
        """After rejection, get_proposal returns the rejected record."""
        team_hash = operator_setup["team_hash"]
        operator = operator_setup["identity"]

        proposal = propose_rule(team_hash, "Rule Q", "b", operator["public_id"])
        pid = proposal["proposal_id"]

        sign_proposal(team_hash, pid, operator["public_id"], operator["private_seed"], False)

        latest = get_proposal(team_hash, pid)
        assert latest["status"] == "rejected"

    # -- get_proposal_signatures --

    def test_get_proposal_signatures_returns_list(self, operator_setup):
        team_hash = operator_setup["team_hash"]
        operator = operator_setup["identity"]

        proposal = propose_rule(team_hash, "Rule S", "a", operator["public_id"])
        pid = proposal["proposal_id"]

        sign_proposal(team_hash, pid, operator["public_id"], operator["private_seed"], True)

        sigs = get_proposal_signatures(team_hash, pid)
        assert isinstance(sigs, list)
        assert len(sigs) == 1
        assert sigs[0]["signer_id"] == operator["public_id"]

    def test_get_proposal_signatures_empty(self, operator_setup):
        team_hash = operator_setup["team_hash"]
        operator_id = operator_setup["identity"]["public_id"]

        proposal = propose_rule(team_hash, "Rule T", "b", operator_id)
        sigs = get_proposal_signatures(team_hash, proposal["proposal_id"])
        assert sigs == []

    def test_get_proposal_signatures_filters_by_proposal(self, operator_setup):
        """Signatures for other proposals are not returned."""
        team_hash = operator_setup["team_hash"]
        operator = operator_setup["identity"]

        p1 = propose_rule(team_hash, "Rule U", "a", operator["public_id"])
        p2 = propose_rule(team_hash, "Rule V", "a", operator["public_id"])

        sign_proposal(
            team_hash, p1["proposal_id"],
            operator["public_id"], operator["private_seed"], True,
        )

        sigs_p1 = get_proposal_signatures(team_hash, p1["proposal_id"])
        sigs_p2 = get_proposal_signatures(team_hash, p2["proposal_id"])

        assert len(sigs_p1) == 1
        assert len(sigs_p2) == 0

    # -- get_team_roles --

    def test_get_team_roles_empty(self, team_setup):
        team_hash = team_setup["team_hash"]
        roles = get_team_roles(team_hash)
        assert roles == {}

    def test_get_team_roles_single_member(self, operator_setup):
        team_hash = operator_setup["team_hash"]
        operator_id = operator_setup["identity"]["public_id"]

        roles = get_team_roles(team_hash)
        assert roles == {operator_id: "operator"}

    def test_get_team_roles_multiple_members(self, operator_setup, second_identity):
        team_hash = operator_setup["team_hash"]
        operator_id = operator_setup["identity"]["public_id"]

        assign_role(team_hash, second_identity["public_id"], "reviewer", operator_id)

        roles = get_team_roles(team_hash)
        assert len(roles) == 2
        assert roles[operator_id] == "operator"
        assert roles[second_identity["public_id"]] == "reviewer"

    def test_get_team_roles_reflects_reassignment(self, operator_setup, second_identity):
        """If a member is reassigned, only the latest role appears."""
        team_hash = operator_setup["team_hash"]
        operator_id = operator_setup["identity"]["public_id"]

        assign_role(team_hash, second_identity["public_id"], "reviewer", operator_id)
        assign_role(team_hash, second_identity["public_id"], "auditor", operator_id)

        roles = get_team_roles(team_hash)
        assert roles[second_identity["public_id"]] == "auditor"

    # -- get_open_proposals --

    def test_get_open_proposals_empty(self, operator_setup):
        team_hash = operator_setup["team_hash"]
        assert get_open_proposals(team_hash) == []

    def test_get_open_proposals_returns_open_only(self, operator_setup, second_identity):
        team_hash = operator_setup["team_hash"]
        operator = operator_setup["identity"]
        operator_id = operator["public_id"]

        assign_role(team_hash, second_identity["public_id"], "reviewer", operator_id)

        # Create three proposals
        p1 = propose_rule(team_hash, "Open rule 1", "a", operator_id)
        p2 = propose_rule(team_hash, "Will be rejected", "b", operator_id)
        p3 = propose_rule(team_hash, "Will be approved", "a", operator_id)

        # Reject p2
        sign_proposal(
            team_hash, p2["proposal_id"],
            operator_id, operator["private_seed"], False,
        )

        # Approve p3 with dual signoff
        sign_proposal(
            team_hash, p3["proposal_id"],
            operator_id, operator["private_seed"], True,
        )
        sign_proposal(
            team_hash, p3["proposal_id"],
            second_identity["public_id"], second_identity["private_seed"], True,
        )

        open_proposals = get_open_proposals(team_hash)
        open_ids = [p["proposal_id"] for p in open_proposals]

        assert len(open_proposals) == 1
        assert p1["proposal_id"] in open_ids
        assert p2["proposal_id"] not in open_ids
        assert p3["proposal_id"] not in open_ids

    def test_get_open_proposals_with_no_proposals_file(self, team_setup):
        """Returns empty list when proposals.jsonl does not exist."""
        team_hash = team_setup["team_hash"]
        assert get_open_proposals(team_hash) == []
