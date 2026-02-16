"""Tests for the AI tool detection module."""

import time
from unittest.mock import patch

from charter.daemon.detector import (
    AI_TOOLS,
    detect_ai_tools,
    detect_processes,
    get_summary,
)


class TestAIToolsRegistry:
    """Tests for the AI_TOOLS configuration."""

    def test_known_tools_exist(self):
        assert "claude_code" in AI_TOOLS
        assert "chatgpt_desktop" in AI_TOOLS
        assert "vscode" in AI_TOOLS
        assert "cursor" in AI_TOOLS
        assert "windsurf" in AI_TOOLS

    def test_all_tools_have_required_fields(self):
        for tool_id, info in AI_TOOLS.items():
            assert "name" in info, f"{tool_id} missing name"
            assert "vendor" in info, f"{tool_id} missing vendor"
            assert "signatures" in info, f"{tool_id} missing signatures"
            assert "governable" in info, f"{tool_id} missing governable"
            assert "method" in info, f"{tool_id} missing method"

    def test_claude_code_is_governable(self):
        assert AI_TOOLS["claude_code"]["governable"] is True
        assert AI_TOOLS["claude_code"]["method"] == "claude_md"

    def test_chatgpt_is_not_governable(self):
        assert AI_TOOLS["chatgpt_desktop"]["governable"] is False


class TestDetectProcesses:
    """Tests for process detection."""

    def test_returns_list(self):
        result = detect_processes()
        assert isinstance(result, list)

    def test_processes_have_required_keys(self):
        result = detect_processes()
        if result:
            proc = result[0]
            assert "pid" in proc
            assert "name" in proc
            assert "cmdline" in proc


class TestDetectAITools:
    """Tests for AI tool detection with mocked processes."""

    def test_detects_claude_code(self):
        mock_procs = [
            {"pid": 1234, "name": "claude", "cmdline": "claude --help"},
        ]
        with patch("charter.daemon.detector.detect_processes", return_value=mock_procs):
            tools = detect_ai_tools()
            assert len(tools) == 1
            assert tools[0]["tool_id"] == "claude_code"
            assert tools[0]["name"] == "Claude Code"
            assert tools[0]["governable"] is True

    def test_detects_chatgpt(self):
        mock_procs = [
            {"pid": 5678, "name": "ChatGPT", "cmdline": "ChatGPT"},
        ]
        with patch("charter.daemon.detector.detect_processes", return_value=mock_procs):
            tools = detect_ai_tools()
            assert len(tools) == 1
            assert tools[0]["tool_id"] == "chatgpt_desktop"
            assert tools[0]["governable"] is False

    def test_detects_vscode(self):
        mock_procs = [
            {"pid": 9999, "name": "Code Helper", "cmdline": "Code Helper (Renderer)"},
        ]
        with patch("charter.daemon.detector.detect_processes", return_value=mock_procs):
            tools = detect_ai_tools()
            assert len(tools) == 1
            assert tools[0]["tool_id"] == "vscode"

    def test_detects_multiple_tools(self):
        mock_procs = [
            {"pid": 1, "name": "claude", "cmdline": "claude"},
            {"pid": 2, "name": "ChatGPT", "cmdline": "ChatGPT"},
            {"pid": 3, "name": "Code Helper", "cmdline": "Code Helper"},
        ]
        with patch("charter.daemon.detector.detect_processes", return_value=mock_procs):
            tools = detect_ai_tools()
            assert len(tools) == 3
            tool_ids = {t["tool_id"] for t in tools}
            assert "claude_code" in tool_ids
            assert "chatgpt_desktop" in tool_ids
            assert "vscode" in tool_ids

    def test_no_duplicates(self):
        mock_procs = [
            {"pid": 1, "name": "claude", "cmdline": "claude"},
            {"pid": 2, "name": "claude", "cmdline": "claude --version"},
        ]
        with patch("charter.daemon.detector.detect_processes", return_value=mock_procs):
            tools = detect_ai_tools()
            assert len(tools) == 1

    def test_no_false_positives(self):
        mock_procs = [
            {"pid": 1, "name": "python3", "cmdline": "python3 script.py"},
            {"pid": 2, "name": "bash", "cmdline": "bash"},
            {"pid": 3, "name": "Safari", "cmdline": "Safari"},
        ]
        with patch("charter.daemon.detector.detect_processes", return_value=mock_procs):
            tools = detect_ai_tools()
            assert len(tools) == 0

    def test_detection_has_timestamp(self):
        mock_procs = [
            {"pid": 1, "name": "claude", "cmdline": "claude"},
        ]
        with patch("charter.daemon.detector.detect_processes", return_value=mock_procs):
            tools = detect_ai_tools()
            assert "detected_at" in tools[0]
            assert "T" in tools[0]["detected_at"]


class TestGetSummary:
    """Tests for the summary function."""

    def test_summary_structure(self):
        mock_procs = [
            {"pid": 1, "name": "claude", "cmdline": "claude"},
            {"pid": 2, "name": "ChatGPT", "cmdline": "ChatGPT"},
        ]
        with patch("charter.daemon.detector.detect_processes", return_value=mock_procs):
            summary = get_summary()
            assert summary["total"] == 2
            assert summary["governed"] == 1
            assert summary["ungoverned"] == 1
            assert "scanned_at" in summary
            assert len(summary["tools"]) == 2

    def test_empty_summary(self):
        with patch("charter.daemon.detector.detect_processes", return_value=[]):
            summary = get_summary()
            assert summary["total"] == 0
            assert summary["governed"] == 0
            assert summary["ungoverned"] == 0
