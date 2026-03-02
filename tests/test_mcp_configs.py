"""Tests for MCP config generation in charter bootstrap."""

import json
import os
import pytest

from charter.bootstrap import (
    generate_mcp_configs,
    _merge_mcp_config,
    _mcp_server_entry,
    _find_charter_command,
)


class TestFindCharterCommand:
    def test_returns_command_and_args(self):
        cmd_path, args = _find_charter_command()
        assert isinstance(cmd_path, str)
        assert isinstance(args, list)
        assert len(args) >= 2

    def test_command_exists(self):
        cmd_path, args = _find_charter_command()
        # The command should be an actual file
        assert os.path.isfile(args[0]) or args[0] in ("charter",)

    def test_args_include_mcp_serve_or_module(self):
        cmd_path, args = _find_charter_command()
        # Should either be charter mcp-serve --transport stdio
        # or python -m charter.mcp_server
        joined = " ".join(args)
        assert "mcp" in joined.lower()


class TestMcpServerEntry:
    def test_returns_dict_with_command_and_args(self):
        entry = _mcp_server_entry()
        assert "command" in entry
        assert "args" in entry
        assert isinstance(entry["args"], list)


class TestMergeMcpConfig:
    def test_creates_new_file(self, tmp_path):
        filepath = str(tmp_path / "test.mcp.json")
        server = {"command": "charter", "args": ["mcp-serve"]}
        _merge_mcp_config(filepath, "charter-governance", server)

        assert os.path.isfile(filepath)
        with open(filepath) as f:
            data = json.load(f)
        assert "mcpServers" in data
        assert "charter-governance" in data["mcpServers"]
        assert data["mcpServers"]["charter-governance"]["command"] == "charter"

    def test_preserves_existing_servers(self, tmp_path):
        filepath = str(tmp_path / "test.mcp.json")
        # Write an existing config with another server
        existing = {
            "mcpServers": {
                "other-server": {
                    "command": "other",
                    "args": ["--flag"]
                }
            }
        }
        with open(filepath, "w") as f:
            json.dump(existing, f)

        # Merge charter server
        server = {"command": "charter", "args": ["mcp-serve"]}
        _merge_mcp_config(filepath, "charter-governance", server)

        with open(filepath) as f:
            data = json.load(f)
        assert "other-server" in data["mcpServers"]
        assert "charter-governance" in data["mcpServers"]

    def test_updates_existing_charter_entry(self, tmp_path):
        filepath = str(tmp_path / "test.mcp.json")
        # Write old charter config
        existing = {
            "mcpServers": {
                "charter-governance": {
                    "command": "old-charter",
                    "args": ["old-args"]
                }
            }
        }
        with open(filepath, "w") as f:
            json.dump(existing, f)

        # Merge new config
        server = {"command": "charter", "args": ["mcp-serve", "--transport", "stdio"]}
        _merge_mcp_config(filepath, "charter-governance", server)

        with open(filepath) as f:
            data = json.load(f)
        assert data["mcpServers"]["charter-governance"]["command"] == "charter"
        assert "stdio" in data["mcpServers"]["charter-governance"]["args"]

    def test_handles_corrupt_file(self, tmp_path):
        filepath = str(tmp_path / "test.mcp.json")
        with open(filepath, "w") as f:
            f.write("{corrupt json")

        server = {"command": "charter", "args": ["mcp-serve"]}
        _merge_mcp_config(filepath, "charter-governance", server)

        with open(filepath) as f:
            data = json.load(f)
        assert "charter-governance" in data["mcpServers"]

    def test_handles_missing_mcpServers_key(self, tmp_path):
        filepath = str(tmp_path / "test.mcp.json")
        with open(filepath, "w") as f:
            json.dump({"other_key": "value"}, f)

        server = {"command": "charter", "args": ["mcp-serve"]}
        _merge_mcp_config(filepath, "charter-governance", server)

        with open(filepath) as f:
            data = json.load(f)
        assert "mcpServers" in data
        assert "charter-governance" in data["mcpServers"]

    def test_file_ends_with_newline(self, tmp_path):
        filepath = str(tmp_path / "test.mcp.json")
        server = {"command": "charter", "args": ["mcp-serve"]}
        _merge_mcp_config(filepath, "charter-governance", server)

        with open(filepath) as f:
            content = f.read()
        assert content.endswith("\n")


class TestGenerateMcpConfigs:
    def test_creates_claude_code_config(self, tmp_path):
        files = generate_mcp_configs(str(tmp_path))
        assert ".mcp.json" in files

        mcp_path = tmp_path / ".mcp.json"
        assert mcp_path.exists()

        with open(mcp_path) as f:
            data = json.load(f)
        assert "charter-governance" in data["mcpServers"]

    def test_creates_cursor_config(self, tmp_path):
        files = generate_mcp_configs(str(tmp_path))
        assert ".cursor/mcp.json" in files

        cursor_path = tmp_path / ".cursor" / "mcp.json"
        assert cursor_path.exists()

        with open(cursor_path) as f:
            data = json.load(f)
        assert "charter-governance" in data["mcpServers"]

    def test_creates_cursor_directory(self, tmp_path):
        # .cursor dir should not exist before
        cursor_dir = tmp_path / ".cursor"
        assert not cursor_dir.exists()

        generate_mcp_configs(str(tmp_path))
        assert cursor_dir.exists()

    def test_returns_two_files(self, tmp_path):
        files = generate_mcp_configs(str(tmp_path))
        assert len(files) == 2

    def test_both_configs_have_same_server_entry(self, tmp_path):
        generate_mcp_configs(str(tmp_path))

        with open(tmp_path / ".mcp.json") as f:
            claude_data = json.load(f)
        with open(tmp_path / ".cursor" / "mcp.json") as f:
            cursor_data = json.load(f)

        claude_server = claude_data["mcpServers"]["charter-governance"]
        cursor_server = cursor_data["mcpServers"]["charter-governance"]
        assert claude_server == cursor_server

    def test_preserves_existing_claude_config(self, tmp_path):
        # Pre-populate with another server
        mcp_path = tmp_path / ".mcp.json"
        with open(mcp_path, "w") as f:
            json.dump({"mcpServers": {"my-server": {"command": "my-cmd"}}}, f)

        generate_mcp_configs(str(tmp_path))

        with open(mcp_path) as f:
            data = json.load(f)
        assert "my-server" in data["mcpServers"]
        assert "charter-governance" in data["mcpServers"]

    def test_idempotent(self, tmp_path):
        generate_mcp_configs(str(tmp_path))
        generate_mcp_configs(str(tmp_path))

        with open(tmp_path / ".mcp.json") as f:
            data = json.load(f)
        # Should still have exactly one charter-governance entry
        assert len([k for k in data["mcpServers"] if k == "charter-governance"]) == 1
