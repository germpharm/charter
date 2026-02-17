"""Tests for charter.config — config file management."""

import os
import yaml

from charter.config import find_config, load_config, save_config


class TestFindConfig:
    def test_finds_config_in_current_dir(self, tmp_path):
        config_path = tmp_path / "charter.yaml"
        config_path.write_text("domain: test\n")
        result = find_config(str(tmp_path))
        assert result == str(config_path)

    def test_finds_config_in_parent(self, tmp_path):
        config_path = tmp_path / "charter.yaml"
        config_path.write_text("domain: test\n")
        child = tmp_path / "subdir"
        child.mkdir()
        result = find_config(str(child))
        assert result == str(config_path)

    def test_returns_none_when_not_found(self, tmp_path):
        result = find_config(str(tmp_path))
        assert result is None


class TestLoadConfig:
    def test_loads_valid_config(self, config_file):
        config = load_config(config_file)
        assert config is not None
        assert config["domain"] == "general"
        assert "governance" in config

    def test_returns_none_for_missing(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = load_config(str(tmp_path / "nonexistent.yaml"))
        assert result is None


class TestSaveConfig:
    def test_saves_and_loads(self, tmp_path, sample_config):
        out_path = str(tmp_path / "charter.yaml")
        save_config(sample_config, out_path)

        with open(out_path) as f:
            loaded = yaml.safe_load(f)

        assert loaded["domain"] == "general"
        assert len(loaded["governance"]["layer_a"]["rules"]) == 2

    def test_returns_absolute_path(self, tmp_path, sample_config):
        out_path = str(tmp_path / "charter.yaml")
        result = save_config(sample_config, out_path)
        assert os.path.isabs(result)
