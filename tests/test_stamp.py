"""Tests for the attribution stamp module."""

import json
import os
import tempfile
from unittest.mock import patch, MagicMock

from charter.stamp import (
    STAMP_VERSION,
    hash_charter,
    create_stamp,
    create_attestation,
    verify_stamp,
    accept_work_product,
    stamp_to_trailer,
    stamp_to_header,
    stamp_to_json,
)


# Sample data for tests

SAMPLE_CONFIG = {
    "domain": "healthcare",
    "governance": {
        "layer_a": {
            "universal": ["Never fabricate data"],
            "rules": ["Never disclose patient info"],
        },
        "layer_b": {
            "rules": [{"action": "external_communication", "requires": "human_approval"}],
        },
        "layer_c": {
            "frequency": "weekly",
            "report_includes": ["decisions_made"],
        },
    },
}

GOVERNED_TOOLS = [
    {
        "tool_id": "claude_code",
        "name": "Claude Code",
        "vendor": "Anthropic",
        "governable": True,
        "method": "claude_md",
        "pid": 1234,
        "process_name": "claude",
        "detected_at": "2026-02-16T00:00:00Z",
    },
]

UNGOVERNED_TOOLS = [
    {
        "tool_id": "browser_chatgpt",
        "name": "ChatGPT",
        "vendor": "OpenAI",
        "governable": False,
        "method": None,
        "pid": 0,
        "process_name": "browser",
        "detected_at": "2026-02-16T00:00:00Z",
    },
]

MIXED_TOOLS = GOVERNED_TOOLS + UNGOVERNED_TOOLS

SAMPLE_IDENTITY = {
    "version": "1.0",
    "public_id": "a" * 64,
    "private_seed": "b" * 64,
    "alias": "test-node",
    "created_at": "2026-02-16T00:00:00Z",
    "real_identity": None,
    "contributions": 5,
}

SAMPLE_CHAIN_ENTRY = {
    "index": 6,
    "timestamp": "2026-02-16T00:00:00Z",
    "event": "work_product_stamped",
    "data": {},
    "previous_hash": "c" * 64,
    "hash": "d" * 64,
    "signature": "e" * 64,
}


class TestHashCharter:
    """Tests for charter hashing."""

    def test_produces_hex_string(self):
        h = hash_charter(SAMPLE_CONFIG)
        assert isinstance(h, str)
        assert len(h) == 64

    def test_same_config_same_hash(self):
        h1 = hash_charter(SAMPLE_CONFIG)
        h2 = hash_charter(SAMPLE_CONFIG)
        assert h1 == h2

    def test_different_config_different_hash(self):
        config2 = {
            "governance": {
                "layer_a": {"rules": ["different rule"]},
            },
        }
        h1 = hash_charter(SAMPLE_CONFIG)
        h2 = hash_charter(config2)
        assert h1 != h2

    def test_empty_config(self):
        h = hash_charter({})
        assert isinstance(h, str)
        assert len(h) == 64


class TestCreateStamp:
    """Tests for stamp creation."""

    def _mock_deps(self, identity=None, config=None, chain_entry=None):
        """Patch identity, config, and chain for isolated tests."""
        id_patch = patch(
            "charter.stamp.load_identity",
            return_value=identity or SAMPLE_IDENTITY,
        )
        config_patch = patch(
            "charter.stamp.load_config",
            return_value=config or SAMPLE_CONFIG,
        )
        chain_patch = patch(
            "charter.stamp.append_to_chain",
            return_value=chain_entry or SAMPLE_CHAIN_ENTRY,
        )
        return id_patch, config_patch, chain_patch

    def test_creates_stamp_with_governed_tools(self):
        id_p, cfg_p, chain_p = self._mock_deps()
        with id_p, cfg_p, chain_p:
            stamp = create_stamp(tools=GOVERNED_TOOLS, description="test output")
            assert stamp is not None
            assert stamp["governed"] is True
            assert stamp["version"] == STAMP_VERSION
            assert stamp["node"] == "a" * 64
            assert stamp["alias"] == "test-node"
            assert len(stamp["tools"]) == 1
            assert stamp["tools"][0]["governed"] is True
            assert stamp["signature"]
            assert stamp["chain_index"] == 6
            assert stamp["charter_hash"]

    def test_creates_stamp_with_ungoverned_tools(self):
        id_p, cfg_p, chain_p = self._mock_deps()
        with id_p, cfg_p, chain_p:
            stamp = create_stamp(tools=UNGOVERNED_TOOLS)
            assert stamp["governed"] is False
            assert stamp["tools"][0]["governed"] is False

    def test_mixed_tools_not_governed(self):
        id_p, cfg_p, chain_p = self._mock_deps()
        with id_p, cfg_p, chain_p:
            stamp = create_stamp(tools=MIXED_TOOLS)
            assert stamp["governed"] is False
            assert len(stamp["tools"]) == 2

    def test_no_tools_not_governed(self):
        id_p, cfg_p, chain_p = self._mock_deps()
        with id_p, cfg_p, chain_p:
            stamp = create_stamp(tools=[])
            assert stamp["governed"] is False
            assert len(stamp["tools"]) == 0

    def test_returns_none_without_identity(self):
        with patch("charter.stamp.load_identity", return_value=None):
            stamp = create_stamp(tools=GOVERNED_TOOLS)
            assert stamp is None

    def test_stamp_has_description(self):
        id_p, cfg_p, chain_p = self._mock_deps()
        with id_p, cfg_p, chain_p:
            stamp = create_stamp(tools=GOVERNED_TOOLS, description="feature X")
            assert stamp["description"] == "feature X"

    def test_stamp_records_domain(self):
        id_p, cfg_p, chain_p = self._mock_deps()
        with id_p, cfg_p, chain_p:
            stamp = create_stamp(tools=GOVERNED_TOOLS)
            assert stamp["domain"] == "healthcare"


class TestVerifyStamp:
    """Tests for stamp verification."""

    def _make_stamp(self, governed=True, tools="default", charter_hash="abc123"):
        if tools == "default":
            tools = [{"tool_id": "claude_code", "name": "Claude Code", "vendor": "Anthropic", "governed": governed}]
        return {
            "version": STAMP_VERSION,
            "node": "a" * 64,
            "alias": "test-node",
            "timestamp": "2026-02-16T00:00:00Z",
            "charter_hash": charter_hash,
            "tools": tools,
            "governed": governed,
            "signature": "sig123",
        }

    def test_valid_governed_stamp(self):
        result = verify_stamp(self._make_stamp(governed=True))
        assert result["verified"] is True
        assert result["governed"] is True
        assert len(result["reasons"]) == 0

    def test_ungoverned_stamp(self):
        result = verify_stamp(self._make_stamp(governed=False))
        assert result["governed"] is False
        assert any("ungoverned" in r for r in result["reasons"])

    def test_missing_fields(self):
        result = verify_stamp({"version": "1.0"})
        assert result["verified"] is False
        assert any("missing field" in r for r in result["reasons"])

    def test_no_charter_hash(self):
        result = verify_stamp(self._make_stamp(charter_hash=None))
        assert any("charter" in r.lower() for r in result["reasons"])

    def test_no_tools(self):
        stamp = self._make_stamp(governed=False, tools=[])
        result = verify_stamp(stamp)
        assert result["governed"] is False
        assert any("no AI tools" in r for r in result["reasons"])


class TestAcceptWorkProduct:
    """Tests for the ingestion gate."""

    def _make_stamp(self, governed=True, charter_hash="abc"):
        return {
            "version": STAMP_VERSION,
            "node": "a" * 64,
            "timestamp": "2026-02-16T00:00:00Z",
            "charter_hash": charter_hash,
            "tools": [{"tool_id": "claude_code", "name": "Claude Code", "vendor": "Anthropic", "governed": governed}],
            "governed": governed,
            "signature": "sig",
        }

    def test_accepts_governed(self):
        accepted, reason = accept_work_product(self._make_stamp(governed=True))
        assert accepted is True
        assert "valid" in reason

    def test_accepts_human_only_none(self):
        accepted, reason = accept_work_product(None)
        assert accepted is True
        assert "human-only" in reason

    def test_accepts_human_only_string(self):
        accepted, reason = accept_work_product("human_only")
        assert accepted is True
        assert "human-only" in reason

    def test_rejects_ungoverned(self):
        accepted, reason = accept_work_product(self._make_stamp(governed=False))
        assert accepted is False
        assert "ungoverned" in reason

    def test_rejects_no_charter(self):
        accepted, reason = accept_work_product(self._make_stamp(charter_hash=None))
        assert accepted is False
        assert "charter" in reason.lower()

    def test_rejects_empty_stamp(self):
        accepted, reason = accept_work_product({})
        assert accepted is False


class TestStampFormats:
    """Tests for stamp output formats."""

    STAMP = {
        "version": "1.0",
        "node": "93921f61d71e951713aa2b6259857bf6b804509d5c2268cca5f0950c6d62ef0a",
        "alias": "node-93921f61",
        "timestamp": "2026-02-16T22:00:00Z",
        "charter_hash": "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2",
        "tools": [
            {"tool_id": "claude_code", "name": "Claude Code", "vendor": "Anthropic", "governed": True},
        ],
        "governed": True,
        "signature": "abc123",
    }

    def test_trailer_format(self):
        trailer = stamp_to_trailer(self.STAMP)
        assert trailer.startswith("Charter-Stamp: v1.0:")
        assert "93921f61" in trailer
        assert "claude_code" in trailer
        assert "governed" in trailer

    def test_trailer_none(self):
        assert stamp_to_trailer(None) == ""

    def test_header_python(self):
        header = stamp_to_header(self.STAMP, language="python")
        assert header.startswith("# ")
        assert "GOVERNED" in header
        assert "Claude Code" in header
        assert "Charter-Stamp:" in header

    def test_header_javascript(self):
        header = stamp_to_header(self.STAMP, language="javascript")
        assert "// " in header
        assert "GOVERNED" in header

    def test_header_html(self):
        header = stamp_to_header(self.STAMP, language="html")
        assert "<!--" in header
        assert "GOVERNED" in header

    def test_json_format(self):
        j = stamp_to_json(self.STAMP)
        parsed = json.loads(j)
        assert parsed["version"] == "1.0"
        assert parsed["governed"] is True

    def test_json_none(self):
        assert stamp_to_json(None) == "{}"

    def test_ungoverned_trailer(self):
        stamp = dict(self.STAMP)
        stamp["governed"] = False
        trailer = stamp_to_trailer(stamp)
        assert "ungoverned" in trailer


class TestAttestation:
    """Tests for human attestation of ungoverned work products."""

    def test_gate_accepts_attestation(self):
        attestation = {
            "version": "1.0",
            "type": "attestation",
            "node": "a" * 64,
            "reviewer": "Matt Maughan",
            "governed": True,
            "signature": "sig123",
            "file_hash": "b" * 64,
            "reason": "Reviewed, logic is sound",
        }
        accepted, reason = accept_work_product(attestation)
        assert accepted is True
        assert "Matt Maughan" in reason
        assert "attested" in reason

    def test_gate_rejects_incomplete_attestation(self):
        attestation = {
            "version": "1.0",
            "type": "attestation",
            "governed": True,
            # missing reviewer and signature
        }
        accepted, reason = accept_work_product(attestation)
        assert accepted is False
        assert "incomplete" in reason

    def test_create_attestation_with_mocked_deps(self):
        import tempfile
        import os
        # Create a temp file to attest
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("print('hello world')\n")
            tmp_path = f.name

        try:
            with patch("charter.stamp.load_identity", return_value=SAMPLE_IDENTITY):
                with patch("charter.stamp.append_to_chain", return_value=SAMPLE_CHAIN_ENTRY):
                    att = create_attestation(
                        tmp_path,
                        reason="Code reviewed, no issues",
                        reviewer_name="Test Reviewer",
                    )
                    assert att is not None
                    assert att["type"] == "attestation"
                    assert att["reviewer"] == "Test Reviewer"
                    assert att["governed"] is True
                    assert att["file_hash"]
                    assert att["signature"]
                    assert att["reason"] == "Code reviewed, no issues"
        finally:
            os.unlink(tmp_path)

    def test_create_attestation_no_identity(self):
        with patch("charter.stamp.load_identity", return_value=None):
            att = create_attestation("/tmp/fake.py", reason="test")
            assert att is None

    def test_create_attestation_file_not_found(self):
        with patch("charter.stamp.load_identity", return_value=SAMPLE_IDENTITY):
            att = create_attestation(
                "/nonexistent/path/fake.py",
                reason="test",
            )
            assert att is None
