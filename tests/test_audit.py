"""Tests for charter.audit — governance audit report generation."""

import os
import sys
from io import StringIO
from unittest.mock import patch

import yaml

from charter.identity import create_identity, append_to_chain
from charter.audit import run_audit


class TestRunAudit:
    def _make_args(self, config_path, period="week"):
        """Create a mock args object."""
        class Args:
            pass
        args = Args()
        args.config = config_path
        args.period = period
        return args

    def test_generates_report(self, charter_home, tmp_path, sample_config):
        create_identity()

        # Write config
        config_path = str(tmp_path / "charter.yaml")
        with open(config_path, "w") as f:
            yaml.dump(sample_config, f)

        # Run audit from tmp_path so audit dir is created there
        old_cwd = os.getcwd()
        os.chdir(str(tmp_path))
        try:
            captured = StringIO()
            with patch("sys.stdout", captured):
                run_audit(self._make_args(config_path))

            output = captured.getvalue()
            assert "Charter Governance Audit Report" in output
            assert "Layer A" in output
            assert "Chain Integrity" in output

            # Check audit file was saved
            audit_dir = tmp_path / "charter_audits"
            assert audit_dir.is_dir()
            audit_files = list(audit_dir.glob("audit_*.md"))
            assert len(audit_files) == 1
        finally:
            os.chdir(old_cwd)

    def test_reports_chain_activity(self, charter_home, tmp_path, sample_config):
        create_identity()
        append_to_chain("test_event", {"x": 1})
        append_to_chain("test_event", {"x": 2})

        config_path = str(tmp_path / "charter.yaml")
        with open(config_path, "w") as f:
            yaml.dump(sample_config, f)

        old_cwd = os.getcwd()
        os.chdir(str(tmp_path))
        try:
            captured = StringIO()
            with patch("sys.stdout", captured):
                run_audit(self._make_args(config_path))

            output = captured.getvalue()
            assert "Total chain entries: 3" in output  # genesis + 2
            assert "test_event: 2" in output
        finally:
            os.chdir(old_cwd)

    def test_verifies_chain_integrity(self, charter_home, tmp_path, sample_config):
        create_identity()

        config_path = str(tmp_path / "charter.yaml")
        with open(config_path, "w") as f:
            yaml.dump(sample_config, f)

        old_cwd = os.getcwd()
        os.chdir(str(tmp_path))
        try:
            captured = StringIO()
            with patch("sys.stdout", captured):
                run_audit(self._make_args(config_path))

            output = captured.getvalue()
            assert "VERIFIED" in output
        finally:
            os.chdir(old_cwd)
