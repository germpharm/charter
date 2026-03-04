"""Tests for the daemon service module."""

import time
import threading
from unittest.mock import patch, MagicMock

from charter.daemon.service import (
    CharterDaemon,
    DEFAULT_PORT,
    SCAN_INTERVAL,
    AUDIT_CHECK_INTERVAL,
)


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

    def test_init_with_config(self):
        config = {
            "governance": {
                "layer_c": {"frequency": "daily"},
            },
            "alerting": {
                "webhooks": [{"url": "https://example.com/hook"}],
            },
        }
        daemon = CharterDaemon(config=config)
        assert daemon._audit_freq_label == "daily"
        assert daemon._audit_interval == 86400
        assert daemon._dispatcher is not None

    def test_init_defaults_to_weekly(self):
        daemon = CharterDaemon(config={})
        assert daemon._audit_freq_label == "weekly"
        assert daemon._audit_interval == 604800

    def test_get_status_includes_audit_frequency(self):
        daemon = CharterDaemon(config={})
        status = daemon.get_status()
        assert "audit_frequency" in status
        assert status["audit_frequency"] == "weekly"

    def test_detection_loop_dispatches_ungoverned_alert(self):
        config = {
            "alerting": {
                "webhooks": [{"url": "https://example.com/hook"}],
            },
        }
        daemon = CharterDaemon(scan_interval=0.1, config=config)
        daemon.running = True

        mock_tools = [
            {
                "tool_id": "unknown_ai",
                "name": "Unknown AI",
                "vendor": "Unknown",
                "pid": 5678,
                "process_name": "unknown",
                "governable": False,
                "method": "none",
                "detected_at": "2026-03-02T00:00:00Z",
            }
        ]

        dispatch_calls = []
        original_dispatch = daemon._dispatcher.dispatch
        def mock_dispatch(event_type, event_data):
            dispatch_calls.append(event_type)
            return {"sent": 0, "failed": 0, "channels": []}

        daemon._dispatcher.dispatch = mock_dispatch

        with patch("charter.daemon.service.detect_ai_tools", return_value=mock_tools):
            with patch("charter.daemon.service.append_to_chain"):
                thread = threading.Thread(target=daemon._detection_loop, daemon=True)
                thread.start()
                time.sleep(0.3)
                daemon.running = False
                thread.join(timeout=1)

        assert "ai_tool_ungoverned" in dispatch_calls

    def test_audit_loop_runs_when_overdue(self):
        config = {
            "governance": {
                "layer_c": {"frequency": "weekly"},
            },
        }
        daemon = CharterDaemon(config=config)
        daemon.running = True

        audit_called = []

        with patch("charter.daemon.service.is_audit_overdue", return_value=True):
            with patch("charter.daemon.service.generate_audit_report",
                       return_value={"report": "test", "chain_intact": True,
                                     "chain_entries": 5, "report_path": "/tmp/test.md"}) as mock_gen:
                with patch("charter.daemon.service.apply_retention_policy"):
                    with patch("charter.daemon.service.AUDIT_CHECK_INTERVAL", 0.1):
                        thread = threading.Thread(target=daemon._audit_loop, daemon=True)
                        thread.start()
                        time.sleep(0.3)
                        daemon.running = False
                        thread.join(timeout=1)

                assert mock_gen.called

    def test_audit_loop_skips_when_not_overdue(self):
        daemon = CharterDaemon(config={})
        daemon.running = True

        with patch("charter.daemon.service.is_audit_overdue", return_value=False):
            with patch("charter.daemon.service.generate_audit_report") as mock_gen:
                with patch("charter.daemon.service.AUDIT_CHECK_INTERVAL", 0.1):
                    thread = threading.Thread(target=daemon._audit_loop, daemon=True)
                    thread.start()
                    time.sleep(0.3)
                    daemon.running = False
                    thread.join(timeout=1)

            assert not mock_gen.called
