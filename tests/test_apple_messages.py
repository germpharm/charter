"""Unit tests for the Apple Messages connector.

The most common bug in chat.db tooling is botching the Apple
Mac Absolute Time epoch conversion. These tests pin it down so
the next person to touch the connector can't drift.
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "charter"))

from charter.connectors.apple_messages import (  # noqa: E402
    apple_ns_to_iso,
    iso_to_apple_ns,
    _normalize_handle,
    _decode_attributed_body,
)


class AppleEpochTests(unittest.TestCase):
    """Round-trip and known-value checks for Apple Mac Absolute Time."""

    def test_zero_returns_empty(self):
        self.assertEqual(apple_ns_to_iso(0), "")
        self.assertEqual(apple_ns_to_iso(None), "")

    def test_known_nanosecond_value(self):
        # 2026-04-01 00:00:00 UTC
        # unix = 1775001600 (calendar.timegm)
        # apple = unix - 978307200 = 796694400
        apple_ns = 796694400 * 1_000_000_000
        self.assertEqual(apple_ns_to_iso(apple_ns), "2026-04-01T00:00:00Z")

    def test_legacy_seconds_value(self):
        # Older chat.db rows store seconds, not nanoseconds. Heuristic
        # treats anything below 1e15 as seconds.
        apple_seconds = 796694400  # 2026-04-01 UTC
        self.assertEqual(apple_ns_to_iso(apple_seconds), "2026-04-01T00:00:00Z")

    def test_iso_to_apple_ns_round_trip(self):
        iso = "2026-04-11T15:30:00Z"
        ns = iso_to_apple_ns(iso)
        self.assertIsNotNone(ns)
        self.assertEqual(apple_ns_to_iso(ns), iso)

    def test_iso_date_only(self):
        ns = iso_to_apple_ns("2026-04-01")
        self.assertEqual(apple_ns_to_iso(ns), "2026-04-01T00:00:00Z")

    def test_iso_unparseable(self):
        self.assertIsNone(iso_to_apple_ns("not a date"))
        self.assertIsNone(iso_to_apple_ns(""))


class HandleNormalizationTests(unittest.TestCase):

    def test_phone_with_country_code(self):
        kind, norm, display = _normalize_handle("+18017258742")
        self.assertEqual(kind, "phone")
        self.assertEqual(norm, "18017258742")
        self.assertEqual(display, "+18017258742")

    def test_phone_with_formatting(self):
        kind, norm, _ = _normalize_handle("(801) 725-8742")
        self.assertEqual(kind, "phone")
        self.assertEqual(norm, "8017258742")

    def test_email(self):
        kind, norm, _ = _normalize_handle("Lea@MySuperOil.com")
        self.assertEqual(kind, "email")
        self.assertEqual(norm, "lea@mysuperoil.com")

    def test_unknown(self):
        kind, _, _ = _normalize_handle("")
        self.assertEqual(kind, "unknown")


class AttributedBodyTests(unittest.TestCase):

    def test_empty_input(self):
        self.assertEqual(_decode_attributed_body(None), "")
        self.assertEqual(_decode_attributed_body(b""), "")

    def test_no_marker_returns_empty(self):
        self.assertEqual(_decode_attributed_body(b"\x00\x01\x02"), "")

    def test_heuristic_extracts_after_marker(self):
        # Simulate a tiny NSKeyedArchiver-like blob with an NSString
        # marker followed by length byte and ASCII text.
        payload = b"\x00\x00NSString\x01+Hello from Apple Messages\x86"
        out = _decode_attributed_body(payload)
        self.assertIn("Hello from Apple Messages", out)


if __name__ == "__main__":
    unittest.main()
