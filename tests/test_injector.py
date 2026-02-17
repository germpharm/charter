"""Tests for the governance injection module."""

import os
import yaml

from charter.daemon.injector import (
    MARKER_START,
    MARKER_END,
    inject_claude_md,
    check_governance,
)


class TestInjectClaudeMd:
    """Tests for CLAUDE.md injection."""

    def test_creates_claude_md(self, tmp_path, sample_config):
        result = inject_claude_md(str(tmp_path), config=sample_config)
        assert result is not None
        assert os.path.exists(result)
        with open(result) as f:
            content = f.read()
        assert MARKER_START in content
        assert MARKER_END in content

    def test_contains_governance_rules(self, tmp_path, sample_config):
        inject_claude_md(str(tmp_path), config=sample_config)
        with open(tmp_path / "CLAUDE.md") as f:
            content = f.read()
        assert "Never violate applicable law" in content
        assert "Never fabricate data" in content

    def test_updates_existing_claude_md_with_markers(self, tmp_path, sample_config):
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text(
            f"# My Project\n\n{MARKER_START}\nold governance\n{MARKER_END}\n\nUser content."
        )
        inject_claude_md(str(tmp_path), config=sample_config)
        content = claude_md.read_text()
        assert "old governance" not in content
        assert "Never violate applicable law" in content
        assert "User content." in content

    def test_prepends_to_existing_claude_md_without_markers(self, tmp_path, sample_config):
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text("# Existing Project Rules\n\nDo good things.")
        inject_claude_md(str(tmp_path), config=sample_config)
        content = claude_md.read_text()
        assert content.startswith(MARKER_START)
        assert "Existing Project Rules" in content
        assert "Do good things." in content

    def test_returns_none_without_config(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = inject_claude_md(str(tmp_path), config=None)
        assert result is None

    def test_idempotent_injection(self, tmp_path, sample_config):
        inject_claude_md(str(tmp_path), config=sample_config)
        first = (tmp_path / "CLAUDE.md").read_text()
        inject_claude_md(str(tmp_path), config=sample_config)
        second = (tmp_path / "CLAUDE.md").read_text()
        assert first.count(MARKER_START) == 1
        assert second.count(MARKER_START) == 1

    def test_loads_config_from_file(self, tmp_path, sample_config):
        config_path = tmp_path / "charter.yaml"
        with open(config_path, "w") as f:
            yaml.dump(sample_config, f)
        result = inject_claude_md(str(tmp_path), config_path=str(config_path))
        assert result is not None


class TestCheckGovernance:
    """Tests for governance status checking."""

    def test_ungoverned_project(self, tmp_path):
        result = check_governance(str(tmp_path))
        assert result["has_claude_md"] is False
        assert result["has_charter_yaml"] is False
        assert result["governed"] is False

    def test_governed_project(self, tmp_path, sample_config):
        inject_claude_md(str(tmp_path), config=sample_config)
        result = check_governance(str(tmp_path))
        assert result["has_claude_md"] is True
        assert result["governed"] is True

    def test_claude_md_without_markers(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text("# Manual rules")
        result = check_governance(str(tmp_path))
        assert result["has_claude_md"] is True
        assert result["governed"] is False

    def test_charter_yaml_detected(self, tmp_path, sample_config):
        config_path = tmp_path / "charter.yaml"
        with open(config_path, "w") as f:
            yaml.dump(sample_config, f)
        result = check_governance(str(tmp_path))
        assert result["has_charter_yaml"] is True
