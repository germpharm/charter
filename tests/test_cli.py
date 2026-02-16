"""Tests for charter.cli — argument parsing and command dispatch."""

import subprocess
import sys


class TestCLI:
    def test_version(self):
        result = subprocess.run(
            [sys.executable, "-m", "charter", "--version"],
            capture_output=True, text=True,
            cwd="/tmp",
        )
        assert result.returncode == 0
        assert "charter" in result.stdout

    def test_help(self):
        result = subprocess.run(
            [sys.executable, "-m", "charter", "--help"],
            capture_output=True, text=True,
            cwd="/tmp",
        )
        assert result.returncode == 0
        assert "governance" in result.stdout.lower()

    def test_no_args_shows_help(self):
        result = subprocess.run(
            [sys.executable, "-m", "charter"],
            capture_output=True, text=True,
            cwd="/tmp",
        )
        assert result.returncode == 0

    def test_init_help(self):
        result = subprocess.run(
            [sys.executable, "-m", "charter", "init", "--help"],
            capture_output=True, text=True,
            cwd="/tmp",
        )
        assert result.returncode == 0
        assert "domain" in result.stdout.lower()

    def test_generate_help(self):
        result = subprocess.run(
            [sys.executable, "-m", "charter", "generate", "--help"],
            capture_output=True, text=True,
            cwd="/tmp",
        )
        assert result.returncode == 0
        assert "format" in result.stdout.lower()
