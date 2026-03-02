"""Tests for charter.alerting — alert dispatch, webhook signing, chain logging."""

import hashlib
import hmac
import json
import urllib.request

from charter.alerting import (
    AlertDispatcher,
    configure_webhook,
    load_alerting_config,
    _sign_payload,
    KNOWN_EVENTS,
)
from charter.identity import create_identity


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------

class MockResponse:
    """Minimal stand-in for an HTTP response returned by urlopen."""
    status = 200
    def read(self):
        return b"ok"
    def __enter__(self):
        return self
    def __exit__(self, *a):
        pass


class MockSMTP:
    """Minimal stand-in for smtplib.SMTP used during email dispatch tests."""
    def __init__(self, *a, **kw):
        self.calls = []
    def ehlo(self):
        self.calls.append("ehlo")
    def starttls(self):
        self.calls.append("starttls")
    def login(self, user, pw):
        self.calls.append(("login", user, pw))
    def sendmail(self, from_addr, to_addrs, msg):
        self.calls.append(("sendmail", from_addr, to_addrs, msg))
    def quit(self):
        self.calls.append("quit")


# ---------------------------------------------------------------------------
# _matches_event
# ---------------------------------------------------------------------------

class TestMatchesEvent:
    def test_matches_when_event_in_list(self):
        wh = {"url": "https://example.com/hook", "events": ["kill_trigger_fired"]}
        assert AlertDispatcher._matches_event(wh, "kill_trigger_fired") is True

    def test_matches_when_events_list_empty(self):
        wh = {"url": "https://example.com/hook", "events": []}
        assert AlertDispatcher._matches_event(wh, "kill_trigger_fired") is True

    def test_matches_when_events_key_missing(self):
        wh = {"url": "https://example.com/hook"}
        assert AlertDispatcher._matches_event(wh, "anything") is True

    def test_no_match_when_event_not_in_list(self):
        wh = {"url": "https://example.com/hook", "events": ["audit_overdue"]}
        assert AlertDispatcher._matches_event(wh, "kill_trigger_fired") is False

    def test_no_match_multiple_events(self):
        wh = {
            "url": "https://example.com/hook",
            "events": ["audit_overdue", "chain_integrity_failure"],
        }
        assert AlertDispatcher._matches_event(wh, "kill_trigger_fired") is False
        assert AlertDispatcher._matches_event(wh, "audit_overdue") is True
        assert AlertDispatcher._matches_event(wh, "chain_integrity_failure") is True


# ---------------------------------------------------------------------------
# configure_webhook
# ---------------------------------------------------------------------------

class TestConfigureWebhook:
    def test_creates_with_all_params(self):
        cfg = configure_webhook(
            url="https://example.com/hook",
            events=["kill_trigger_fired", "audit_overdue"],
            secret="my-secret",
        )
        assert cfg["url"] == "https://example.com/hook"
        assert cfg["events"] == ["kill_trigger_fired", "audit_overdue"]
        assert cfg["secret"] == "my-secret"

    def test_creates_with_defaults(self):
        cfg = configure_webhook(url="https://example.com/hook")
        assert cfg["url"] == "https://example.com/hook"
        assert "events" not in cfg
        assert "secret" not in cfg

    def test_events_converted_to_list(self):
        cfg = configure_webhook(
            url="https://example.com/hook",
            events=("kill_trigger_fired",),
        )
        assert isinstance(cfg["events"], list)
        assert cfg["events"] == ["kill_trigger_fired"]


# ---------------------------------------------------------------------------
# load_alerting_config
# ---------------------------------------------------------------------------

class TestLoadAlertingConfig:
    def test_returns_empty_when_no_config(self):
        result = load_alerting_config(config={})
        assert result == {}

    def test_returns_empty_when_config_none_key(self):
        result = load_alerting_config(config={"domain": "general"})
        assert result == {}

    def test_returns_alerting_section(self):
        cfg = {
            "domain": "general",
            "alerting": {
                "webhooks": [{"url": "https://example.com/hook"}],
            },
        }
        result = load_alerting_config(config=cfg)
        assert "webhooks" in result
        assert result["webhooks"][0]["url"] == "https://example.com/hook"


# ---------------------------------------------------------------------------
# AlertDispatcher — construction and basic dispatch
# ---------------------------------------------------------------------------

class TestAlertDispatcher:
    def test_construction_with_config(self):
        config = {
            "webhooks": [{"url": "https://example.com/hook"}],
            "email": {"smtp_host": "smtp.example.com"},
            "slack": {"webhook_url": "https://hooks.slack.com/services/T/B/x"},
        }
        d = AlertDispatcher(config)
        assert len(d._webhooks) == 1
        assert d._email is not None
        assert d._slack is not None

    def test_construction_with_none(self):
        d = AlertDispatcher(None)
        assert d._webhooks == []
        assert d._email is None
        assert d._slack is None

    def test_dispatch_no_channels(self, charter_home):
        """With no channels configured, dispatch returns zeros and empty list."""
        create_identity(alias="alerting-test")
        d = AlertDispatcher(None)
        result = d.dispatch("kill_trigger_fired", {"detail": "test"})
        assert result["sent"] == 0
        assert result["failed"] == 0
        assert result["channels"] == []

    def test_dispatch_routes_to_matching_webhook(self, charter_home, monkeypatch):
        """A webhook whose events list matches the event type should be called."""
        create_identity(alias="alerting-route")

        sent_requests = []

        def mock_urlopen(req, **kw):
            sent_requests.append(req)
            return MockResponse()

        monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)

        config = {
            "webhooks": [
                {
                    "url": "https://example.com/hook",
                    "events": ["kill_trigger_fired"],
                },
            ],
        }
        d = AlertDispatcher(config)
        result = d.dispatch("kill_trigger_fired", {"trigger": "ethics_decline"})

        assert result["sent"] == 1
        assert result["failed"] == 0
        assert len(result["channels"]) == 1
        assert "webhook:https://example.com/hook" in result["channels"]
        assert len(sent_requests) == 1

    def test_dispatch_skips_non_matching_webhook(self, charter_home, monkeypatch):
        """A webhook whose events list does NOT match should not be called."""
        create_identity(alias="alerting-skip")

        sent_requests = []

        def mock_urlopen(req, **kw):
            sent_requests.append(req)
            return MockResponse()

        monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)

        config = {
            "webhooks": [
                {
                    "url": "https://example.com/hook",
                    "events": ["audit_overdue"],
                },
            ],
        }
        d = AlertDispatcher(config)
        result = d.dispatch("kill_trigger_fired", {"trigger": "ethics_decline"})

        assert result["sent"] == 0
        assert result["failed"] == 0
        assert len(sent_requests) == 0

    def test_dispatch_counts_failed_webhook(self, charter_home, monkeypatch):
        """When urlopen raises, the webhook should count as failed."""
        create_identity(alias="alerting-fail")

        def mock_urlopen(req, **kw):
            raise urllib.error.URLError("connection refused")

        monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)

        config = {
            "webhooks": [{"url": "https://example.com/hook"}],
        }
        d = AlertDispatcher(config)
        result = d.dispatch("kill_trigger_fired", {"detail": "boom"})

        assert result["sent"] == 0
        assert result["failed"] == 1


# ---------------------------------------------------------------------------
# Webhook signing (HMAC-SHA256)
# ---------------------------------------------------------------------------

class TestWebhookSigning:
    def test_sign_payload_format(self):
        """_sign_payload returns 'sha256=<hex>' with correct HMAC."""
        payload = b'{"key":"value"}'
        secret = "test-secret"
        result = _sign_payload(payload, secret)

        assert result.startswith("sha256=")
        hex_part = result[len("sha256="):]
        assert len(hex_part) == 64  # SHA-256 produces 64 hex characters

    def test_sign_payload_correctness(self):
        """Verify the signature matches a manual HMAC-SHA256 computation."""
        payload = b'{"event":"kill_trigger_fired"}'
        secret = "my-webhook-secret"

        expected_hex = hmac.new(
            secret.encode(),
            payload,
            hashlib.sha256,
        ).hexdigest()

        result = _sign_payload(payload, secret)
        assert result == f"sha256={expected_hex}"

    def test_webhook_sends_signature_header(self, charter_home, monkeypatch):
        """When a webhook has a secret, the request includes X-Charter-Signature."""
        create_identity(alias="alerting-sig")

        captured_requests = []

        def mock_urlopen(req, **kw):
            captured_requests.append(req)
            return MockResponse()

        monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)

        config = {
            "webhooks": [
                {
                    "url": "https://example.com/hook",
                    "secret": "test-hmac-secret",
                },
            ],
        }
        d = AlertDispatcher(config)
        d.dispatch("kill_trigger_fired", {"detail": "test"})

        assert len(captured_requests) == 1
        req = captured_requests[0]
        sig_header = req.get_header("X-charter-signature")
        assert sig_header is not None
        assert sig_header.startswith("sha256=")

        # Verify the signature matches the actual payload
        payload_bytes = req.data
        expected = _sign_payload(payload_bytes, "test-hmac-secret")
        assert sig_header == expected

    def test_webhook_no_signature_without_secret(self, charter_home, monkeypatch):
        """When a webhook has no secret, X-Charter-Signature is absent."""
        create_identity(alias="alerting-nosig")

        captured_requests = []

        def mock_urlopen(req, **kw):
            captured_requests.append(req)
            return MockResponse()

        monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)

        config = {
            "webhooks": [{"url": "https://example.com/hook"}],
        }
        d = AlertDispatcher(config)
        d.dispatch("alert_test", {"detail": "test"})

        assert len(captured_requests) == 1
        req = captured_requests[0]
        sig_header = req.get_header("X-charter-signature")
        assert sig_header is None


# ---------------------------------------------------------------------------
# Chain logging on dispatch
# ---------------------------------------------------------------------------

class TestDispatchChainLogging:
    def test_dispatch_logs_to_chain(self, charter_home, monkeypatch):
        """After dispatch, an alert_dispatched entry should appear in chain.jsonl."""
        create_identity(alias="alerting-chain")

        # Mock urlopen so the webhook "succeeds"
        monkeypatch.setattr(
            urllib.request, "urlopen", lambda req, **kw: MockResponse()
        )

        config = {
            "webhooks": [{"url": "https://example.com/hook"}],
        }
        d = AlertDispatcher(config)
        d.dispatch("kill_trigger_fired", {"trigger": "ethics_decline"})

        chain_path = str(charter_home / "chain.jsonl")
        with open(chain_path) as f:
            lines = f.readlines()

        # Line 0 is the genesis entry from create_identity
        # Line 1 should be alert_dispatched
        assert len(lines) >= 2
        entry = json.loads(lines[-1])
        assert entry["event"] == "alert_dispatched"
        assert entry["data"]["event_type"] == "kill_trigger_fired"
        assert entry["data"]["sent"] == 1
        assert "webhook:https://example.com/hook" in entry["data"]["channels"]

    def test_dispatch_chain_logging_no_crash_on_failure(self, charter_home, monkeypatch):
        """If append_to_chain raises, dispatch still returns a result without crashing."""
        create_identity(alias="alerting-chain-fail")

        def broken_append(*a, **kw):
            raise RuntimeError("chain write failed")

        monkeypatch.setattr("charter.alerting.append_to_chain", broken_append)

        d = AlertDispatcher(None)
        result = d.dispatch("alert_test", {"detail": "test"})

        # Should return normally despite chain failure
        assert "sent" in result
        assert "failed" in result
        assert "channels" in result
