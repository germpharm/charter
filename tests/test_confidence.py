"""Tests for charter.confidence — confidence tagging and revision linkage."""

import json
import os

from charter.identity import create_identity, append_to_chain
from charter.confidence import (
    CONFIDENCE_LEVELS,
    validate_confidence,
    tag_confidence,
    link_revision,
    find_revisions,
    get_revision_chain,
    _load_chain,
    _find_entry_by_hash,
)


class TestValidateConfidence:
    def test_verified_is_valid(self):
        assert validate_confidence("verified") is True

    def test_inferred_is_valid(self):
        assert validate_confidence("inferred") is True

    def test_exploratory_is_valid(self):
        assert validate_confidence("exploratory") is True

    def test_invalid_string_rejected(self):
        assert validate_confidence("guessed") is False

    def test_empty_string_rejected(self):
        assert validate_confidence("") is False

    def test_none_rejected(self):
        assert validate_confidence(None) is False


class TestTagConfidence:
    def test_valid_tagging(self):
        data = {"action": "approve", "amount": 100}
        result = tag_confidence(data, "verified", "Lab report #42")
        assert result["_confidence"] == "verified"
        assert result["_evidence_basis"] == "Lab report #42"
        assert result["_constraint_assumptions"] == []
        assert result["action"] == "approve"
        assert result["amount"] == 100

    def test_original_data_not_mutated(self):
        data = {"key": "value"}
        result = tag_confidence(data, "inferred", "pattern match")
        assert "_confidence" not in data
        assert "_confidence" in result

    def test_invalid_confidence_returns_none(self):
        data = {"key": "value"}
        result = tag_confidence(data, "guessed", "gut feeling")
        assert result is None

    def test_default_constraint_assumptions(self):
        result = tag_confidence({}, "exploratory", "early hypothesis")
        assert result["_constraint_assumptions"] == []

    def test_explicit_constraint_assumptions(self):
        assumptions = ["Supply chain stable", "Pricing unchanged"]
        result = tag_confidence({}, "inferred", "trend data", assumptions)
        assert result["_constraint_assumptions"] == assumptions


class TestLinkRevision:
    def test_valid_linking(self):
        data = {"action": "update_policy"}
        result = link_revision(data, "abc123hash", "New regulation published")
        assert result["_revision_of"] == "abc123hash"
        assert result["_revision_reason"] == "New regulation published"
        assert result["action"] == "update_policy"

    def test_original_data_not_mutated(self):
        data = {"key": "value"}
        link_revision(data, "abc123", "reason")
        assert "_revision_of" not in data

    def test_empty_revision_of_returns_none(self):
        assert link_revision({}, "", "some reason") is None

    def test_none_revision_of_returns_none(self):
        assert link_revision({}, None, "some reason") is None

    def test_empty_reason_returns_none(self):
        assert link_revision({}, "abc123", "") is None

    def test_none_reason_returns_none(self):
        assert link_revision({}, "abc123", None) is None


class TestFindRevisions:
    def test_finds_matching_entries(self, charter_home):
        create_identity()
        entry_a = append_to_chain("decision", {"detail": "original"})
        # Create a revision pointing back to entry_a
        revision_data = link_revision(
            {"detail": "updated"}, entry_a["hash"], "Corrected calculation"
        )
        append_to_chain("revision", revision_data)

        chain_path = str(charter_home / "chain.jsonl")
        revisions = find_revisions(chain_path, entry_a["hash"])
        assert len(revisions) == 1
        assert revisions[0]["data"]["_revision_of"] == entry_a["hash"]
        assert revisions[0]["data"]["_revision_reason"] == "Corrected calculation"

    def test_returns_empty_for_no_matches(self, charter_home):
        create_identity()
        append_to_chain("event", {"detail": "standalone"})
        chain_path = str(charter_home / "chain.jsonl")
        revisions = find_revisions(chain_path, "nonexistent_hash")
        assert revisions == []

    def test_returns_empty_for_missing_file(self, tmp_path):
        chain_path = str(tmp_path / "missing.jsonl")
        assert find_revisions(chain_path, "anyhash") == []


class TestGetRevisionChain:
    def test_builds_backward_chain(self, charter_home):
        create_identity()
        original = append_to_chain("v1", {"version": 1})
        rev1_data = link_revision({"version": 2}, original["hash"], "Fix typo")
        rev1 = append_to_chain("v2", rev1_data)
        rev2_data = link_revision({"version": 3}, rev1["hash"], "Add section")
        rev2 = append_to_chain("v3", rev2_data)

        chain_path = str(charter_home / "chain.jsonl")
        history = get_revision_chain(chain_path, rev2["hash"])

        # Oldest to newest
        assert len(history) == 3
        assert history[0]["hash"] == original["hash"]
        assert history[1]["hash"] == rev1["hash"]
        assert history[2]["hash"] == rev2["hash"]

    def test_single_entry_no_revision(self, charter_home):
        create_identity()
        entry = append_to_chain("standalone", {"detail": "no links"})
        chain_path = str(charter_home / "chain.jsonl")
        history = get_revision_chain(chain_path, entry["hash"])
        assert len(history) == 1
        assert history[0]["hash"] == entry["hash"]

    def test_handles_missing_entry(self, charter_home):
        create_identity()
        chain_path = str(charter_home / "chain.jsonl")
        history = get_revision_chain(chain_path, "nonexistent_hash")
        assert history == []

    def test_handles_cycles(self, charter_home):
        """Cycle detection: manually write entries that loop back."""
        chain_path = str(charter_home / "chain.jsonl")
        # Write two entries that reference each other
        entry_a = {
            "index": 0, "event": "a", "hash": "hash_a",
            "previous_hash": "0" * 64,
            "data": {"_revision_of": "hash_b", "_revision_reason": "loop"},
        }
        entry_b = {
            "index": 1, "event": "b", "hash": "hash_b",
            "previous_hash": "hash_a",
            "data": {"_revision_of": "hash_a", "_revision_reason": "loop"},
        }
        with open(chain_path, "w") as f:
            f.write(json.dumps(entry_a) + "\n")
            f.write(json.dumps(entry_b) + "\n")

        history = get_revision_chain(chain_path, "hash_a")
        # Should terminate rather than loop forever; contains at most 2 entries
        assert len(history) <= 2

    def test_returns_empty_for_empty_file(self, tmp_path):
        chain_path = str(tmp_path / "empty.jsonl")
        with open(chain_path, "w") as f:
            f.write("")
        assert get_revision_chain(chain_path, "anyhash") == []


class TestIntegration:
    def test_confidence_enriched_in_chain(self, charter_home):
        """append_to_chain with confidence-tagged data stores metadata."""
        create_identity()
        data = tag_confidence(
            {"action": "approve_budget"},
            "verified",
            "Board minutes 2026-02-28",
            ["Q1 revenue on track"],
        )
        entry = append_to_chain("budget_decision", data)

        chain_path = str(charter_home / "chain.jsonl")
        with open(chain_path) as f:
            entries = [json.loads(line) for line in f if line.strip()]

        last = entries[-1]
        assert last["data"]["_confidence"] == "verified"
        assert last["data"]["_evidence_basis"] == "Board minutes 2026-02-28"
        assert last["data"]["_constraint_assumptions"] == ["Q1 revenue on track"]
        assert last["data"]["action"] == "approve_budget"

    def test_revision_linked_in_chain(self, charter_home):
        """append_to_chain with revision-linked data stores linkage."""
        create_identity()
        original = append_to_chain("policy_v1", {"rule": "old"})
        revised_data = link_revision(
            {"rule": "new"}, original["hash"], "Regulation changed"
        )
        append_to_chain("policy_v2", revised_data)

        chain_path = str(charter_home / "chain.jsonl")
        revisions = find_revisions(chain_path, original["hash"])
        assert len(revisions) == 1
        assert revisions[0]["data"]["rule"] == "new"
        assert revisions[0]["data"]["_revision_reason"] == "Regulation changed"
