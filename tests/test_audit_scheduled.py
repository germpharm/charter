"""Tests for audit scheduling API: generate_audit_report, get_last_audit_timestamp, is_audit_overdue."""

import json
import os
import time
from unittest.mock import patch

import yaml

from charter.identity import create_identity, append_to_chain, get_chain_path
from charter.audit import (
    generate_audit_report,
    get_last_audit_timestamp,
    is_audit_overdue,
    _check_chain_integrity,
    FREQUENCY_SECONDS,
)


class TestGenerateAuditReport:
    """Tests for generate_audit_report() programmatic API."""

    def test_returns_none_without_config(self, charter_home):
        create_identity()
        result = generate_audit_report(config={})
        assert result is None

    def test_returns_none_without_identity(self, charter_home, sample_config, monkeypatch):
        # Don't create identity — load_identity should return None
        monkeypatch.setattr("charter.audit.load_identity", lambda: None)
        result = generate_audit_report(config=sample_config)
        assert result is None

    def test_returns_dict_with_report(self, charter_home, tmp_path, sample_config):
        create_identity()
        audit_dir = str(tmp_path / "audit_out")
        result = generate_audit_report(
            config=sample_config, period="week", output_dir=audit_dir,
        )
        assert result is not None
        assert "report" in result
        assert "report_path" in result
        assert "chain_entries" in result
        assert "chain_intact" in result
        assert "Charter Governance Audit Report" in result["report"]

    def test_saves_report_file(self, charter_home, tmp_path, sample_config):
        create_identity()
        audit_dir = str(tmp_path / "audit_out")
        result = generate_audit_report(
            config=sample_config, output_dir=audit_dir,
        )
        assert os.path.isfile(result["report_path"])
        with open(result["report_path"]) as f:
            content = f.read()
        assert "Charter Governance Audit Report" in content

    def test_logs_to_chain(self, charter_home, tmp_path, sample_config):
        create_identity()
        audit_dir = str(tmp_path / "audit_out")
        generate_audit_report(config=sample_config, output_dir=audit_dir)

        chain_path = get_chain_path()
        with open(chain_path) as f:
            entries = [json.loads(line) for line in f if line.strip()]
        audit_events = [e for e in entries if e.get("event") == "audit_generated"]
        assert len(audit_events) == 1
        assert audit_events[0]["data"]["chain_intact"] is True

    def test_reports_chain_entries_count(self, charter_home, tmp_path, sample_config):
        create_identity()
        append_to_chain("test_event", {"x": 1})
        append_to_chain("test_event", {"x": 2})
        audit_dir = str(tmp_path / "audit_out")
        result = generate_audit_report(config=sample_config, output_dir=audit_dir)
        # genesis + 2 test events = 3 (audit_generated appended after count)
        assert result["chain_entries"] == 3

    def test_default_audit_dir(self, charter_home, sample_config, monkeypatch):
        create_identity()
        # Patch DEFAULT_AUDIT_DIR to temp
        fake_dir = str(charter_home / "audits")
        monkeypatch.setattr("charter.audit.DEFAULT_AUDIT_DIR", fake_dir)
        result = generate_audit_report(config=sample_config)
        assert fake_dir in result["report_path"]


class TestGetLastAuditTimestamp:
    """Tests for get_last_audit_timestamp()."""

    def test_returns_none_when_no_chain(self, charter_home):
        assert get_last_audit_timestamp() is None

    def test_returns_none_when_no_audit_events(self, charter_home):
        create_identity()
        append_to_chain("some_event", {"x": 1})
        assert get_last_audit_timestamp() is None

    def test_returns_timestamp_of_latest_audit(self, charter_home, tmp_path, sample_config):
        create_identity()
        audit_dir = str(tmp_path / "audit_out")
        generate_audit_report(config=sample_config, output_dir=audit_dir)
        ts = get_last_audit_timestamp()
        assert ts is not None
        # Should be a valid ISO-like timestamp
        assert "T" in ts
        assert ":" in ts

    def test_returns_most_recent_audit(self, charter_home, tmp_path, sample_config):
        create_identity()
        audit_dir = str(tmp_path / "audit_out")
        generate_audit_report(config=sample_config, period="first", output_dir=audit_dir)
        generate_audit_report(config=sample_config, period="second", output_dir=audit_dir)
        ts = get_last_audit_timestamp()
        assert ts is not None


class TestIsAuditOverdue:
    """Tests for is_audit_overdue()."""

    def test_overdue_when_never_audited(self, charter_home, sample_config):
        create_identity()
        assert is_audit_overdue(sample_config) is True

    def test_not_overdue_right_after_audit(self, charter_home, tmp_path, sample_config):
        create_identity()
        audit_dir = str(tmp_path / "audit_out")
        generate_audit_report(config=sample_config, output_dir=audit_dir)
        assert is_audit_overdue(sample_config) is False

    def test_returns_false_without_config(self):
        assert is_audit_overdue(config={}) is False

    def test_returns_false_without_governance(self, charter_home):
        create_identity()
        assert is_audit_overdue(config={"domain": "general"}) is False

    def test_uses_frequency_from_config(self, charter_home, sample_config):
        create_identity()
        # Confirm the config has weekly frequency
        freq = sample_config["governance"]["layer_c"]["frequency"]
        assert freq == "weekly"
        assert FREQUENCY_SECONDS[freq] == 604800


class TestCheckChainIntegrity:
    """Tests for _check_chain_integrity()."""

    def test_empty_chain_is_intact(self):
        assert _check_chain_integrity([]) is True

    def test_single_entry_is_intact(self):
        assert _check_chain_integrity([{"hash": "abc"}]) is True

    def test_intact_chain(self):
        entries = [
            {"hash": "aaa", "previous_hash": ""},
            {"hash": "bbb", "previous_hash": "aaa"},
            {"hash": "ccc", "previous_hash": "bbb"},
        ]
        assert _check_chain_integrity(entries) is True

    def test_broken_chain(self):
        entries = [
            {"hash": "aaa", "previous_hash": ""},
            {"hash": "bbb", "previous_hash": "WRONG"},
        ]
        assert _check_chain_integrity(entries) is False

    def test_retention_anchor_tolerated(self):
        entries = [
            {"hash": "anchor_hash", "previous_hash": "archived_hash", "event": "retention_anchor"},
            {"hash": "bbb", "previous_hash": "anchor_hash"},
        ]
        assert _check_chain_integrity(entries) is True
