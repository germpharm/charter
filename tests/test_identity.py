"""Tests for charter.identity — hash chain, signing, authorship transfer."""

import json
import os

from charter.identity import (
    create_identity,
    load_identity,
    hash_entry,
    sign_data,
    append_to_chain,
    verify_identity,
    generate_transfer_proof,
)


class TestCreateIdentity:
    def test_creates_identity_file(self, charter_home):
        identity = create_identity(alias="test-node")
        assert identity["alias"] == "test-node"
        assert len(identity["public_id"]) == 64
        assert len(identity["private_seed"]) == 64
        assert identity["real_identity"] is None
        assert identity["contributions"] == 0

    def test_creates_genesis_chain_entry(self, charter_home):
        identity = create_identity()
        chain_path = str(charter_home / "chain.jsonl")
        assert os.path.isfile(chain_path)

        with open(chain_path) as f:
            lines = f.readlines()
        assert len(lines) == 1

        genesis = json.loads(lines[0])
        assert genesis["index"] == 0
        assert genesis["event"] == "identity_created"
        assert genesis["previous_hash"] == "0" * 64
        assert genesis["data"]["public_id"] == identity["public_id"]

    def test_auto_alias_when_none(self, charter_home):
        identity = create_identity()
        assert identity["alias"].startswith("node-")

    def test_identity_persists(self, charter_home):
        create_identity(alias="persist-test")
        loaded = load_identity()
        assert loaded is not None
        assert loaded["alias"] == "persist-test"


class TestHashEntry:
    def test_deterministic(self):
        entry = {"index": 0, "event": "test", "data": {}}
        h1 = hash_entry(entry)
        h2 = hash_entry(entry)
        assert h1 == h2

    def test_excludes_hash_field(self):
        entry = {"index": 0, "event": "test", "data": {}}
        h1 = hash_entry(entry)
        entry["hash"] = "should_be_ignored"
        h2 = hash_entry(entry)
        assert h1 == h2

    def test_different_entries_different_hashes(self):
        e1 = {"index": 0, "event": "a", "data": {}}
        e2 = {"index": 0, "event": "b", "data": {}}
        assert hash_entry(e1) != hash_entry(e2)


class TestSignData:
    def test_returns_hex_string(self):
        sig = sign_data({"key": "value"}, "aa" * 32)
        assert len(sig) == 64
        int(sig, 16)  # Valid hex

    def test_deterministic(self):
        data = {"key": "value"}
        seed = "bb" * 32
        assert sign_data(data, seed) == sign_data(data, seed)

    def test_different_seeds_different_sigs(self):
        data = {"key": "value"}
        assert sign_data(data, "aa" * 32) != sign_data(data, "bb" * 32)


class TestAppendToChain:
    def test_appends_entry(self, charter_home):
        create_identity()
        entry = append_to_chain("test_event", {"detail": "testing"})
        assert entry is not None
        assert entry["event"] == "test_event"
        assert entry["index"] == 1

    def test_chain_links(self, charter_home):
        create_identity()
        append_to_chain("event_1", {})
        append_to_chain("event_2", {})

        chain_path = str(charter_home / "chain.jsonl")
        with open(chain_path) as f:
            entries = [json.loads(line) for line in f if line.strip()]

        assert len(entries) == 3  # genesis + 2
        for i in range(1, len(entries)):
            assert entries[i]["previous_hash"] == entries[i - 1]["hash"]

    def test_entries_are_signed(self, charter_home):
        create_identity()
        entry = append_to_chain("signed_event", {"x": 1})
        assert "signature" in entry
        assert len(entry["signature"]) == 64

    def test_returns_none_without_identity(self, charter_home):
        result = append_to_chain("no_identity", {})
        assert result is None

    def test_updates_contribution_count(self, charter_home):
        create_identity()
        append_to_chain("e1", {})
        append_to_chain("e2", {})
        identity = load_identity()
        assert identity["contributions"] == 2


class TestVerifyIdentity:
    def test_links_real_identity(self, charter_home):
        create_identity()
        verification, prior = verify_identity(
            "Test User", "test@example.com", method="manual"
        )
        assert verification["name"] == "Test User"
        assert verification["trust_level"] == "self_declared"
        assert prior == 1  # genesis entry

    def test_records_chain_event(self, charter_home):
        create_identity()
        verify_identity("Test User", "test@example.com")

        chain_path = str(charter_home / "chain.jsonl")
        with open(chain_path) as f:
            entries = [json.loads(line) for line in f if line.strip()]

        verified_entries = [e for e in entries if e["event"] == "identity_verified"]
        assert len(verified_entries) == 1
        assert verified_entries[0]["data"]["real_identity"]["name"] == "Test User"

    def test_prevents_double_verification(self, charter_home):
        create_identity()
        verify_identity("Test User", "test@example.com")

        import pytest
        with pytest.raises(RuntimeError, match="already verified"):
            verify_identity("Other User", "other@example.com")

    def test_trust_levels(self, charter_home):
        methods = {
            "id_me": "government",
            "org_hr": "organizational",
            "email": "basic",
            "manual": "self_declared",
        }
        for method, expected_trust in methods.items():
            # Reset identity for each test
            create_identity()
            verification, _ = verify_identity("User", "u@test.com", method=method)
            assert verification["trust_level"] == expected_trust

    def test_raises_without_identity(self, charter_home):
        import pytest
        with pytest.raises(RuntimeError, match="No identity found"):
            verify_identity("User", "u@test.com")


class TestGenerateTransferProof:
    def test_unverified_proof(self, charter_home):
        create_identity()
        proof = generate_transfer_proof()
        assert proof is not None
        assert proof["verified"] is False
        assert proof["chain_intact"] is True
        assert proof["chain_length"] == 1

    def test_verified_proof(self, charter_home):
        create_identity()
        append_to_chain("some_work", {"detail": "built something"})
        verify_identity("Test User", "test@example.com", method="email")

        proof = generate_transfer_proof()
        assert proof["verified"] is True
        assert proof["verification"]["name"] == "Test User"
        assert proof["verification"]["method"] == "email"
        assert proof["chain_intact"] is True

    def test_proof_is_signed(self, charter_home):
        create_identity()
        proof = generate_transfer_proof()
        assert "signature" in proof
        assert len(proof["signature"]) == 64

    def test_returns_none_without_identity(self, charter_home):
        proof = generate_transfer_proof()
        assert proof is None
