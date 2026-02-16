"""Tests for charter.context — work/personal knowledge boundaries."""

import json
import os

import pytest

from charter.identity import create_identity
from charter.context import (
    create_context,
    get_context,
    list_contexts,
    set_active_context,
    get_active_context,
    propose_bridge,
    approve_bridge,
    revoke_bridge,
    list_bridges,
)


class TestCreateContext:
    def test_creates_personal_context(self, charter_home_with_context):
        create_identity()
        meta = create_context("personal")
        assert meta["type"] == "personal"
        assert meta["bridging"]["enabled"] is False
        assert meta["bridging"]["policy"] == "isolated"

    def test_creates_work_context(self, charter_home_with_context):
        create_identity()
        meta = create_context("work", context_type="work",
                              org_name="Acme Corp", work_email="user@acme.com")
        assert meta["type"] == "work"
        assert meta["org_name"] == "Acme Corp"
        assert meta["work_email"] == "user@acme.com"

    def test_creates_context_chain(self, charter_home_with_context):
        create_identity()
        create_context("test-ctx")
        ctx_dir = os.path.join(str(charter_home_with_context / "contexts"), "test-ctx")
        chain_path = os.path.join(ctx_dir, "chain.jsonl")
        assert os.path.isfile(chain_path)

        with open(chain_path) as f:
            genesis = json.loads(f.readline())
        assert genesis["event"] == "context_created"

    def test_requires_identity(self, charter_home_with_context):
        with pytest.raises(RuntimeError, match="No identity"):
            create_context("no-id")


class TestContextRetrieval:
    def test_get_context(self, charter_home_with_context):
        create_identity()
        create_context("myctx")
        ctx = get_context("myctx")
        assert ctx is not None
        assert ctx["type"] == "personal"

    def test_get_nonexistent(self, charter_home_with_context):
        assert get_context("nope") is None

    def test_list_contexts(self, charter_home_with_context):
        create_identity()
        create_context("alpha")
        create_context("beta")
        contexts = list_contexts()
        names = [c["name"] for c in contexts]
        assert "alpha" in names
        assert "beta" in names

    def test_list_empty(self, charter_home_with_context):
        assert list_contexts() == []


class TestActiveContext:
    def test_set_and_get(self, charter_home_with_context):
        create_identity()
        create_context("active-test")
        set_active_context("active-test")
        assert get_active_context() == "active-test"

    def test_no_active_returns_none(self, charter_home_with_context):
        assert get_active_context() is None

    def test_set_nonexistent_raises(self, charter_home_with_context):
        with pytest.raises(RuntimeError, match="not found"):
            set_active_context("ghost")


class TestBridging:
    def test_propose_bridge(self, charter_home_with_context):
        create_identity()
        create_context("personal")
        create_context("work", context_type="work")
        bridge = propose_bridge("personal", "work", policy="read-only")
        assert bridge["status"] == "pending"
        assert bridge["source"] == "personal"
        assert bridge["target"] == "work"
        assert bridge["policy"] == "read-only"
        assert len(bridge["bridge_id"]) == 16

    def test_approve_bridge(self, charter_home_with_context):
        create_identity()
        create_context("personal")
        create_context("work", context_type="work")
        bridge = propose_bridge("personal", "work")
        approved = approve_bridge(bridge["bridge_id"], "work")
        assert approved["status"] == "approved"
        assert approved["approved_by"] == "work"

        # Both contexts should have bridging enabled
        src = get_context("personal")
        tgt = get_context("work")
        assert src["bridging"]["enabled"] is True
        assert tgt["bridging"]["enabled"] is True

    def test_revoke_bridge(self, charter_home_with_context):
        create_identity()
        create_context("personal")
        create_context("work", context_type="work")
        bridge = propose_bridge("personal", "work")
        approve_bridge(bridge["bridge_id"], "work")
        revoked = revoke_bridge(bridge["bridge_id"], "personal")
        assert revoked["status"] == "revoked"
        assert revoked["revoked_by"] == "personal"

        # Both contexts should be isolated again
        src = get_context("personal")
        tgt = get_context("work")
        assert src["bridging"]["enabled"] is False
        assert tgt["bridging"]["enabled"] is False
        assert src["bridging"]["policy"] == "isolated"

    def test_list_bridges(self, charter_home_with_context):
        create_identity()
        create_context("a")
        create_context("b")
        propose_bridge("a", "b")
        bridges = list_bridges()
        assert len(bridges) == 1

    def test_cannot_approve_non_pending(self, charter_home_with_context):
        create_identity()
        create_context("a")
        create_context("b")
        bridge = propose_bridge("a", "b")
        approve_bridge(bridge["bridge_id"], "b")
        with pytest.raises(RuntimeError, match="already"):
            approve_bridge(bridge["bridge_id"], "b")

    def test_bridge_nonexistent_context_raises(self, charter_home_with_context):
        create_identity()
        create_context("real")
        with pytest.raises(RuntimeError, match="not found"):
            propose_bridge("real", "ghost")
