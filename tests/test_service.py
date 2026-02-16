"""Tests for the daemon service module."""

import time
import threading
from unittest.mock import patch, MagicMock

from charter.daemon.service import CharterDaemon, DEFAULT_PORT, SCAN_INTERVAL


class TestCharterDaemon:
    """Tests for the CharterDaemon class."""

    def test_init_defaults(self):
        daemon = CharterDaemon()
        assert daemon.port == DEFAULT_PORT
        assert daemon.scan_interval == SCAN_INTERVAL
        assert daemon.running is False

    def test_init_custom(self):
        daemon = CharterDaemon(port=9999, scan_interval=30)
        assert daemon.port == 9999
        assert daemon.scan_interval == 30

    def test_get_status_initial(self):
        daemon = CharterDaemon()
        status = daemon.get_status()
        assert status["running"] is False
        assert status["last_scan"] is None
        assert status["detection_log"] == []
        assert status["total_detected"] == 0

    def test_stop(self):
        daemon = CharterDaemon()
        daemon.running = True
        daemon.stop()
        assert daemon.running is False

    def test_detection_loop_updates_state(self):
        daemon = CharterDaemon(scan_interval=0.1)
        daemon.running = True

        mock_tools = [
            {
                "tool_id": "claude_code",
                "name": "Claude Code",
                "vendor": "Anthropic",
                "pid": 1234,
                "process_name": "claude",
                "governable": True,
                "method": "claude_md",
                "detected_at": "2026-02-16T00:00:00Z",
            }
        ]

        with patch("charter.daemon.service.detect_ai_tools", return_value=mock_tools):
            with patch("charter.daemon.service.append_to_chain"):
                thread = threading.Thread(target=daemon._detection_loop, daemon=True)
                thread.start()
                time.sleep(0.3)
                daemon.running = False
                thread.join(timeout=1)

        status = daemon.get_status()
        assert status["last_scan"] is not None
        assert len(status["last_scan"]["tools"]) == 1
        assert status["total_detected"] == 1

    def test_detection_loop_no_duplicates(self):
        daemon = CharterDaemon(scan_interval=0.1)
        daemon.running = True

        mock_tools = [
            {
                "tool_id": "claude_code",
                "name": "Claude Code",
                "vendor": "Anthropic",
                "pid": 1234,
                "process_name": "claude",
                "governable": True,
                "method": "claude_md",
                "detected_at": "2026-02-16T00:00:00Z",
            }
        ]

        with patch("charter.daemon.service.detect_ai_tools", return_value=mock_tools):
            with patch("charter.daemon.service.append_to_chain") as mock_chain:
                thread = threading.Thread(target=daemon._detection_loop, daemon=True)
                thread.start()
                time.sleep(0.4)
                daemon.running = False
                thread.join(timeout=1)

        # Should only log to chain once despite multiple scans
        assert mock_chain.call_count == 1

    def test_detection_loop_handles_errors(self):
        daemon = CharterDaemon(scan_interval=0.1)
        daemon.running = True

        with patch("charter.daemon.service.detect_ai_tools", side_effect=RuntimeError("fail")):
            thread = threading.Thread(target=daemon._detection_loop, daemon=True)
            thread.start()
            time.sleep(0.3)
            daemon.running = False
            thread.join(timeout=1)

        # Should not crash
        assert daemon.get_status()["last_scan"] is None
